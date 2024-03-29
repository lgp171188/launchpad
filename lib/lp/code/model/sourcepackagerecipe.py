# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation of the `SourcePackageRecipe` content type."""

__all__ = [
    "SourcePackageRecipe",
]

import re
from datetime import datetime, timedelta, timezone
from operator import attrgetter

from lazr.delegates import delegate_to
from storm.expr import And, LeftJoin
from storm.locals import (
    Bool,
    DateTime,
    Desc,
    Int,
    Reference,
    ReferenceSet,
    Store,
    Unicode,
)
from zope.component import getUtility
from zope.interface import implementer, provider

from lp.buildmaster.enums import BuildStatus
from lp.code.errors import BuildAlreadyPending, BuildNotAllowedForDistro
from lp.code.interfaces.sourcepackagerecipe import (
    IRecipeBranchSource,
    ISourcePackageRecipe,
    ISourcePackageRecipeData,
    ISourcePackageRecipeSource,
)
from lp.code.interfaces.sourcepackagerecipebuild import (
    ISourcePackageRecipeBuildSource,
)
from lp.code.model.sourcepackagerecipebuild import SourcePackageRecipeBuild
from lp.code.model.sourcepackagerecipedata import SourcePackageRecipeData
from lp.code.vocabularies.sourcepackagerecipe import BuildableDistroSeries
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.distroseries import DistroSeries
from lp.services.database.bulk import load_referencing
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import Greatest, NullsLast
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.soyuz.model.archive import Archive


def recipe_modified(recipe, event):
    """Update the date_last_modified property when a recipe is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent` events
    on recipes.
    """
    recipe.date_last_modified = UTC_NOW


class NonPPABuildRequest(Exception):
    """A build was requested to a non-PPA and this is currently
    unsupported."""


class _SourcePackageRecipeDistroSeries(StormBase):
    """Link table for many-to-many relationship."""

    __storm_table__ = "SourcePackageRecipeDistroSeries"
    id = Int(primary=True)
    sourcepackagerecipe_id = Int(name="sourcepackagerecipe", allow_none=False)
    sourcepackage_recipe = Reference(
        sourcepackagerecipe_id, "SourcePackageRecipe.id"
    )
    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")


@implementer(ISourcePackageRecipe)
@provider(ISourcePackageRecipeSource)
@delegate_to(ISourcePackageRecipeData, context="_recipe_data")
class SourcePackageRecipe(StormBase):
    """See `ISourcePackageRecipe` and `ISourcePackageRecipeSource`."""

    __storm_table__ = "SourcePackageRecipe"

    def __str__(self):
        return "%s/%s" % (self.owner.name, self.name)

    id = Int(primary=True)

    daily_build_archive_id = Int(name="daily_build_archive", allow_none=True)
    daily_build_archive = Reference(daily_build_archive_id, "Archive.id")

    date_created = DateTime(allow_none=False, tzinfo=timezone.utc)
    date_last_modified = DateTime(allow_none=False, tzinfo=timezone.utc)

    owner_id = Int(name="owner", allow_none=True)
    owner = Reference(owner_id, "Person.id")

    registrant_id = Int(name="registrant", allow_none=True)
    registrant = Reference(registrant_id, "Person.id")

    distroseries = ReferenceSet(
        id,
        _SourcePackageRecipeDistroSeries.sourcepackagerecipe_id,
        _SourcePackageRecipeDistroSeries.distroseries_id,
        DistroSeries.id,
    )

    build_daily = Bool()

    is_stale = Bool()

    name = Unicode(allow_none=True)
    description = Unicode(allow_none=True)

    @cachedproperty
    def _recipe_data(self):
        return (
            Store.of(self)
            .find(
                SourcePackageRecipeData,
                SourcePackageRecipeData.sourcepackage_recipe == self,
            )
            .one()
        )

    @property
    def builder_recipe(self):
        """Accesses of the recipe go to the SourcePackageRecipeData."""
        return self._recipe_data.getRecipe()

    @property
    def base_branch(self):
        return self._recipe_data.base_branch

    @property
    def base_git_repository(self):
        return self._recipe_data.base_git_repository

    @property
    def base(self):
        if self.base_branch is not None:
            return self.base_branch
        else:
            assert self.base_git_repository is not None
            return self.base_git_repository

    @staticmethod
    def preLoadDataForSourcePackageRecipes(sourcepackagerecipes):
        # Load the referencing SourcePackageRecipeData.
        spr_datas = load_referencing(
            SourcePackageRecipeData,
            sourcepackagerecipes,
            ["sourcepackage_recipe_id"],
        )
        # Store the SourcePackageRecipeData in the sourcepackagerecipes
        # objects.
        for spr_data in spr_datas:
            cache = get_property_cache(spr_data.sourcepackage_recipe)
            cache._recipe_data = spr_data
        SourcePackageRecipeData.preLoadReferencedBranches(spr_datas)
        owner_ids = set(map(attrgetter("owner_id"), sourcepackagerecipes))
        list(
            getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                owner_ids, need_validity=True
            )
        )

    def setRecipeText(self, recipe_text):
        parsed, recipe_branch_type = getUtility(
            IRecipeBranchSource
        ).getParsedRecipe(recipe_text)
        self._recipe_data.setRecipe(parsed, recipe_branch_type)

    def getRecipeText(self, validate=False):
        """See `ISourcePackageRecipe`."""
        recipe_text = self.builder_recipe.get_recipe_text(validate=validate)
        # For git-based recipes, mangle the header line to say
        # "git-build-recipe" to reduce confusion; bzr-builder's recipe
        # parser will always round-trip this to "bzr-builder".
        if self.base_git_repository is not None:
            recipe_text = re.sub(
                r"^(#\s*)bzr-builder", r"\1git-build-recipe", recipe_text
            )
        return recipe_text

    @property
    def recipe_text(self):
        return self.getRecipeText()

    def updateSeries(self, distroseries):
        if distroseries != self.distroseries:
            self.distroseries.clear()
            for distroseries_item in distroseries:
                self.distroseries.add(distroseries_item)

    @staticmethod
    def new(
        registrant,
        owner,
        name,
        recipe,
        description,
        distroseries=None,
        daily_build_archive=None,
        build_daily=False,
        date_created=DEFAULT,
    ):
        """See `ISourcePackageRecipeSource.new`."""
        store = IPrimaryStore(SourcePackageRecipe)
        sprecipe = SourcePackageRecipe()
        builder_recipe, recipe_branch_type = getUtility(
            IRecipeBranchSource
        ).getParsedRecipe(recipe)
        SourcePackageRecipeData(builder_recipe, recipe_branch_type, sprecipe)
        sprecipe.registrant = registrant
        sprecipe.owner = owner
        sprecipe.name = name
        if distroseries is not None:
            for distroseries_item in distroseries:
                sprecipe.distroseries.add(distroseries_item)
        sprecipe.description = description
        sprecipe.daily_build_archive = daily_build_archive
        sprecipe.build_daily = build_daily
        sprecipe.date_created = date_created
        sprecipe.date_last_modified = date_created
        store.add(sprecipe)
        return sprecipe

    @staticmethod
    def findStaleDailyBuilds():
        one_day_ago = datetime.now(timezone.utc) - timedelta(
            hours=23, minutes=50
        )
        joins = (
            SourcePackageRecipe,
            LeftJoin(
                SourcePackageRecipeBuild,
                And(
                    SourcePackageRecipeBuild.recipe_id
                    == SourcePackageRecipe.id,
                    SourcePackageRecipeBuild.archive_id
                    == SourcePackageRecipe.daily_build_archive_id,
                    SourcePackageRecipeBuild.date_created > one_day_ago,
                ),
            ),
        )
        return (
            IStore(SourcePackageRecipe)
            .using(*joins)
            .find(
                SourcePackageRecipe,
                SourcePackageRecipe.is_stale == True,
                SourcePackageRecipe.build_daily == True,
                SourcePackageRecipeBuild.date_created == None,
            )
            .config(distinct=True)
        )

    @staticmethod
    def exists(owner, name):
        """See `ISourcePackageRecipeSource.new`."""
        store = IPrimaryStore(SourcePackageRecipe)
        recipe = store.find(
            SourcePackageRecipe,
            SourcePackageRecipe.owner == owner,
            SourcePackageRecipe.name == name,
        ).one()
        if recipe:
            return True
        else:
            return False

    def destroySelf(self):
        store = Store.of(self)
        self.distroseries.clear()
        self._recipe_data.instructions.find().remove()
        builds = store.find(
            SourcePackageRecipeBuild, SourcePackageRecipeBuild.recipe == self
        )
        builds.set(recipe_id=None)
        store.remove(self._recipe_data)
        store.remove(self)

    def containsUnbuildableSeries(self, archive):
        buildable_distros = set(
            BuildableDistroSeries.findSeries(archive.owner)
        )
        return len(set(self.distroseries).difference(buildable_distros)) >= 1

    def requestBuild(
        self,
        archive,
        requester,
        distroseries,
        pocket=PackagePublishingPocket.RELEASE,
        manual=False,
    ):
        """See `ISourcePackageRecipe`."""
        if not archive.is_ppa:
            raise NonPPABuildRequest

        buildable_distros = BuildableDistroSeries.findSeries(archive.owner)
        if distroseries not in buildable_distros:
            raise BuildNotAllowedForDistro(self, distroseries)

        reject_reason = archive.checkUpload(
            requester, distroseries, None, archive.default_component, pocket
        )
        if reject_reason is not None:
            raise reject_reason
        pending = IStore(self).find(
            SourcePackageRecipeBuild,
            SourcePackageRecipeBuild.recipe_id == self.id,
            SourcePackageRecipeBuild.distroseries_id == distroseries.id,
            SourcePackageRecipeBuild.archive_id == archive.id,
            SourcePackageRecipeBuild.status == BuildStatus.NEEDSBUILD,
        )
        if pending.any() is not None:
            raise BuildAlreadyPending(self, distroseries)

        build = getUtility(ISourcePackageRecipeBuildSource).new(
            distroseries, self, requester, archive
        )
        build.queueBuild()
        queue_record = build.buildqueue_record
        if manual:
            queue_record.manualScore(queue_record.lastscore + 100)
        return build

    def performDailyBuild(self):
        """See `ISourcePackageRecipe`."""
        builds = []
        self.is_stale = False
        buildable_distros = set(
            BuildableDistroSeries.findSeries(self.daily_build_archive.owner)
        )
        build_for = set(self.distroseries).intersection(buildable_distros)
        for distroseries in build_for:
            try:
                build = self.requestBuild(
                    self.daily_build_archive,
                    self.owner,
                    distroseries,
                    PackagePublishingPocket.RELEASE,
                )
                builds.append(build)
            except BuildAlreadyPending:
                continue
        return builds

    @property
    def builds(self):
        """See `ISourcePackageRecipe`."""
        order_by = (
            NullsLast(
                Desc(
                    Greatest(
                        SourcePackageRecipeBuild.date_started,
                        SourcePackageRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(SourcePackageRecipeBuild.date_created),
            Desc(SourcePackageRecipeBuild.id),
        )
        return self._getBuilds(None, order_by)

    @property
    def completed_builds(self):
        """See `ISourcePackageRecipe`."""
        filter_term = SourcePackageRecipeBuild.status != BuildStatus.NEEDSBUILD
        order_by = (
            NullsLast(
                Desc(
                    Greatest(
                        SourcePackageRecipeBuild.date_started,
                        SourcePackageRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(SourcePackageRecipeBuild.id),
        )
        return self._getBuilds(filter_term, order_by)

    @property
    def pending_builds(self):
        """See `ISourcePackageRecipe`."""
        filter_term = SourcePackageRecipeBuild.status == BuildStatus.NEEDSBUILD
        # We want to order by date_created but this is the same as ordering
        # by id (since id increases monotonically) and is less expensive.
        order_by = Desc(SourcePackageRecipeBuild.id)
        return self._getBuilds(filter_term, order_by)

    def _getBuilds(self, filter_term, order_by):
        """The actual query to get the builds."""
        query_args = [
            SourcePackageRecipeBuild.recipe == self,
            SourcePackageRecipeBuild.archive_id == Archive.id,
            Archive._enabled == True,
        ]
        if filter_term is not None:
            query_args.append(filter_term)
        result = Store.of(self).find(SourcePackageRecipeBuild, *query_args)
        result.order_by(order_by)
        return result

    def getPendingBuildInfo(self):
        """See `ISourcePackageRecipe`."""
        builds = self.pending_builds
        result = []
        for build in builds:
            result.append(
                {
                    "distroseries": build.distroseries.displayname,
                    "archive": build.archive.reference,
                }
            )
        return result

    @property
    def last_build(self):
        """See `ISourcePackageRecipeBuild`."""
        return self._getBuilds(
            True, Desc(SourcePackageRecipeBuild.date_finished)
        ).first()

    def getMedianBuildDuration(self):
        """Return the median duration of builds of this recipe."""
        store = IStore(self)
        result = store.find(
            (
                SourcePackageRecipeBuild.date_started,
                SourcePackageRecipeBuild.date_finished,
            ),
            SourcePackageRecipeBuild.recipe == self.id,
            SourcePackageRecipeBuild.status == BuildStatus.FULLYBUILT,
            SourcePackageRecipeBuild.date_finished != None,
        )
        result.order_by(Desc(SourcePackageRecipeBuild.date_finished))
        durations = [row[1] - row[0] for row in result[:9]]
        if len(durations) == 0:
            return None
        durations.sort(reverse=True)
        return durations[len(durations) // 2]
