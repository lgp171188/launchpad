# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A recipe for building Open Container Initiative images."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipe',
    'OCIRecipeSet',
    ]


from lazr.lifecycle.event import ObjectCreatedEvent
import pytz
from storm.expr import (
    Desc,
    Not,
    )
from storm.locals import (
    Bool,
    DateTime,
    Int,
    Reference,
    Store,
    Storm,
    Unicode,
    )
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.oci.interfaces.ocirecipe import (
    DuplicateOCIRecipeName,
    IOCIRecipe,
    IOCIRecipeSet,
    NoSourceForOCIRecipe,
    NoSuchOCIRecipe,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeNotOwner,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.model.ocirecipebuild import OCIRecipeBuild
from lp.services.database.constants import DEFAULT
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormexpr import (
    Greatest,
    NullsLast,
    )


@implementer(IOCIRecipe)
class OCIRecipe(Storm):

    __storm_table__ = 'OCIRecipe'

    id = Int(primary=True)
    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=pytz.UTC, allow_none=False)

    registrant_id = Int(name='registrant', allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    owner_id = Int(name='owner', allow_none=False)
    owner = Reference(owner_id, 'Person.id')

    oci_project_id = Int(name='oci_project', allow_none=False)
    oci_project = Reference(oci_project_id, "OCIProject.id")

    name = Unicode(name="name", allow_none=False)
    description = Unicode(name="description")

    official = Bool(name="official", default=False)

    git_repository_id = Int(name="git_repository", allow_none=False)
    git_repository = Reference(git_repository_id, "GitRepository.id")
    git_path = Unicode(name="git_path", allow_none=False)
    build_file = Unicode(name="build_file", allow_none=False)

    require_virtualized = Bool(name="require_virtualized", default=True,
                               allow_none=False)

    build_daily = Bool(name="build_daily", default=False)

    def __init__(self, name, registrant, owner, oci_project, git_ref,
                 description=None, official=False, require_virtualized=True,
                 build_file=None, date_created=DEFAULT):
        super(OCIRecipe, self).__init__()
        self.name = name
        self.registrant = registrant
        self.owner = owner
        self.oci_project = oci_project
        self.description = description
        self.build_file = build_file
        self.official = official
        self.require_virtualized = require_virtualized
        self.date_created = date_created
        self.git_ref = git_ref

    def destroySelf(self):
        """See `IOCIRecipe`."""
        # XXX twom 2019-11-26 This needs to expand as more build artifacts
        # are added
        store = IStore(OCIRecipe)
        buildqueue_records = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id == OCIRecipeBuild.build_farm_job_id,
            OCIRecipeBuild.recipe == self)
        for buildqueue_record in buildqueue_records:
            buildqueue_record.destroySelf()
        build_farm_job_ids = list(store.find(
            OCIRecipeBuild.build_farm_job_id, OCIRecipeBuild.recipe == self))
        store.find(OCIRecipeBuild, OCIRecipeBuild.recipe == self).remove()
        store.remove(self)
        store.find(
            BuildFarmJob, BuildFarmJob.id.is_in(build_farm_job_ids)).remove()

    @property
    def git_ref(self):
        """See `IOCIRecipe`."""
        if self.git_repository is not None:
            return self.git_repository.getRefByPath(self.git_path)
        return None

    @git_ref.setter
    def git_ref(self, value):
        """See `IOCIRecipe`."""
        if value is not None:
            self.git_path = value.path
            self.git_repository = value.repository
        else:
            self.git_repository = None
            self.git_path = None

    def _checkRequestBuild(self, requester):
        if not requester.inTeam(self.owner):
            raise OCIRecipeNotOwner(
                "%s cannot create OCI image builds owned by %s." %
                (requester.display_name, self.owner.display_name))

    def requestBuild(self, requester, distro_arch_series):
        self._checkRequestBuild(requester)

        pending = IStore(self).find(
            OCIRecipeBuild,
            OCIRecipeBuild.recipe == self.id,
            OCIRecipeBuild.processor == distro_arch_series.processor,
            OCIRecipeBuild.status == BuildStatus.NEEDSBUILD)
        if pending.any() is not None:
            raise OCIRecipeBuildAlreadyPending

        build = getUtility(IOCIRecipeBuildSet).new(
            requester, self, distro_arch_series)
        build.queueBuild()
        notify(ObjectCreatedEvent(build, user=requester))
        return build

    @property
    def _pending_states(self):
        """All the build states we consider pending (non-final)."""
        return [
            BuildStatus.NEEDSBUILD,
            BuildStatus.BUILDING,
            BuildStatus.UPLOADING,
            BuildStatus.CANCELLING,
            ]

    def _getBuilds(self, filter_term, order_by):
        """The actual query to get the builds."""
        query_args = [
            OCIRecipeBuild.recipe == self,
            ]
        if filter_term is not None:
            query_args.append(filter_term)
        result = Store.of(self).find(OCIRecipeBuild, *query_args)
        result.order_by(order_by)

        def eager_load(rows):
            getUtility(IOCIRecipeBuildSet).preloadBuildsData(rows)
            getUtility(IBuildQueueSet).preloadForBuildFarmJobs(rows)

        return DecoratedResultSet(result, pre_iter_hook=eager_load)

    @property
    def builds(self):
        """See `IOCIRecipe`."""
        order_by = (
            NullsLast(Desc(Greatest(
                OCIRecipeBuild.date_started,
                OCIRecipeBuild.date_finished))),
            Desc(OCIRecipeBuild.date_created),
            Desc(OCIRecipeBuild.id))
        return self._getBuilds(None, order_by)

    @property
    def completed_builds(self):
        """See `IOCIRecipe`."""
        filter_term = (Not(OCIRecipeBuild.status.is_in(self._pending_states)))
        order_by = (
            NullsLast(Desc(Greatest(
                OCIRecipeBuild.date_started,
                OCIRecipeBuild.date_finished))),
            Desc(OCIRecipeBuild.id))
        return self._getBuilds(filter_term, order_by)

    @property
    def pending_builds(self):
        """See `IOCIRecipe`."""
        filter_term = (OCIRecipeBuild.status.is_in(self._pending_states))
        # We want to order by date_created but this is the same as ordering
        # by id (since id increases monotonically) and is less expensive.
        order_by = Desc(OCIRecipeBuild.id)
        return self._getBuilds(filter_term, order_by)


class OCIRecipeArch(Storm):
    """Link table to back `OCIRecipe.processors`."""

    __storm_table__ = "OCIRecipeArch"
    __storm_primary__ = ("recipe_id", "processor_id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "OCIRecipe.id")

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")

    def __init__(self, recipe, processor):
        self.recipe = recipe
        self.processor = processor


@implementer(IOCIRecipeSet)
class OCIRecipeSet:

    def new(self, name, registrant, owner, oci_project, git_ref, build_file,
            description=None, official=False, require_virtualized=True,
            date_created=DEFAULT):
        """See `IOCIRecipeSet`."""
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise OCIRecipeNotOwner(
                    "%s is not a member of %s." %
                    (registrant.displayname, owner.displayname))
            else:
                raise OCIRecipeNotOwner(
                    "%s cannot create OCI images owned by %s." %
                    (registrant.displayname, owner.displayname))

        if not (git_ref and build_file):
            raise NoSourceForOCIRecipe

        if self.exists(owner, oci_project, name):
            raise DuplicateOCIRecipeName

        store = IMasterStore(OCIRecipe)
        oci_recipe = OCIRecipe(
            name, registrant, owner, oci_project, git_ref, description,
            official, require_virtualized, build_file, date_created)
        store.add(oci_recipe)

        return oci_recipe

    def _getByName(self, owner, oci_project, name):
        return IStore(OCIRecipe).find(
            OCIRecipe,
            OCIRecipe.owner == owner,
            OCIRecipe.name == name,
            OCIRecipe.oci_project == oci_project).one()

    def exists(self, owner, oci_project, name):
        """See `IOCIRecipeSet`."""
        return self._getByName(owner, oci_project, name) is not None

    def getByName(self, owner, oci_project, name):
        """See `IOCIRecipeSet`."""
        oci_recipe = self._getByName(owner, oci_project, name)
        if oci_recipe is None:
            raise NoSuchOCIRecipe(name)
        return oci_recipe
