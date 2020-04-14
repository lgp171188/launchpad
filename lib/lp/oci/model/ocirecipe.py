# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A recipe for building Open Container Initiative images."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipe',
    'OCIRecipeBuildRequest',
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
from zope.component import (
    getAdapter,
    getUtility,
    )
from zope.event import notify
from zope.interface import implementer
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.security import IAuthorization
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.model.processor import Processor
from lp.oci.enums import OCIRecipeBuildRequestStatus
from lp.oci.interfaces.ocirecipe import (
    CannotModifyOCIRecipeProcessor,
    DuplicateOCIRecipeName,
    IOCIRecipe,
    IOCIRecipeBuildRequest,
    IOCIRecipeSet,
    NoSourceForOCIRecipe,
    NoSuchOCIRecipe,
    OCI_RECIPE_ALLOW_CREATE,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeFeatureDisabled,
    OCIRecipeNotOwner,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.interfaces.ocirecipejob import IOCIRecipeRequestBuildsJobSource
from lp.oci.model.ocipushrule import OCIPushRule
from lp.oci.model.ocirecipebuild import OCIRecipeBuild
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.series import ACTIVE_STATUSES
from lp.services.database.constants import (
    DEFAULT,
    UTC_NOW,
    )
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormexpr import (
    Greatest,
    NullsLast,
    )
from lp.services.features import getFeatureFlag
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import cachedproperty
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.model import WebhookTargetMixin
from lp.soyuz.model.distroarchseries import DistroArchSeries


def oci_recipe_modified(recipe, event):
    """Update the date_last_modified property when an OCIRecipe is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on OCI recipes.
    """
    removeSecurityProxy(recipe).date_last_modified = UTC_NOW


@implementer(IOCIRecipe)
class OCIRecipe(Storm, WebhookTargetMixin):

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
    description = Unicode(name="description", allow_none=True)

    official = Bool(name="official", default=False)

    git_repository_id = Int(name="git_repository", allow_none=True)
    git_repository = Reference(git_repository_id, "GitRepository.id")
    git_path = Unicode(name="git_path", allow_none=True)
    build_file = Unicode(name="build_file", allow_none=False)

    require_virtualized = Bool(name="require_virtualized", default=True,
                               allow_none=False)

    build_daily = Bool(name="build_daily", default=False)

    def __init__(self, name, registrant, owner, oci_project, git_ref,
                 description=None, official=False, require_virtualized=True,
                 build_file=None, build_daily=False, date_created=DEFAULT):
        if not getFeatureFlag(OCI_RECIPE_ALLOW_CREATE):
            raise OCIRecipeFeatureDisabled()
        super(OCIRecipe, self).__init__()
        self.name = name
        self.registrant = registrant
        self.owner = owner
        self.oci_project = oci_project
        self.description = description
        self.build_file = build_file
        self.official = official
        self.require_virtualized = require_virtualized
        self.build_daily = build_daily
        self.date_created = date_created
        self.date_last_modified = date_created
        self.git_ref = git_ref

    @property
    def valid_webhook_event_types(self):
        return ["oci-recipe:build:0.1"]

    def destroySelf(self):
        """See `IOCIRecipe`."""
        # XXX twom 2019-11-26 This needs to expand as more build artifacts
        # are added
        store = IStore(OCIRecipe)
        store.find(OCIRecipeArch, OCIRecipeArch.recipe == self).remove()
        buildqueue_records = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id == OCIRecipeBuild.build_farm_job_id,
            OCIRecipeBuild.recipe == self)
        for buildqueue_record in buildqueue_records:
            buildqueue_record.destroySelf()
        build_farm_job_ids = list(store.find(
            OCIRecipeBuild.build_farm_job_id, OCIRecipeBuild.recipe == self))
        store.find(OCIRecipeBuild, OCIRecipeBuild.recipe == self).remove()
        getUtility(IWebhookSet).delete(self.webhooks)
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
            self.git_repository = value.repository
            self.git_path = value.path
        else:
            self.git_repository = None
            self.git_path = None

    @property
    def distribution(self):
        # XXX twom 2019-12-05 This may need to change when an OCIProject
        # pillar isn't just a distribution
        return self.oci_project.distribution

    @property
    def distro_series(self):
        # For OCI builds we default to the series set by the feature flag.
        # If the feature flag is not set we default to the current series of
        # the recipe's distribution.
        oci_series = getFeatureFlag('oci.build_series.%s'
                                    % self.distribution.name)
        if oci_series:
            return self.distribution.getSeries(oci_series)
        else:
            return self.distribution.currentseries

    @property
    def available_processors(self):
        """See `IOCIRecipe`."""
        clauses = [Processor.id == DistroArchSeries.processor_id]
        if self.distro_series is not None:
            clauses.append(DistroArchSeries.id.is_in(
                self.distro_series.enabled_architectures.get_select_expr(
                    DistroArchSeries.id)))
        else:
            # We might not know the series if the OCI project's distribution
            # has no series at all, which can happen in tests.  Fall back to
            # just returning enabled architectures for any active series,
            # which is a bit of a hack but works.
            clauses.extend([
                DistroArchSeries.enabled,
                DistroArchSeries.distroseriesID == DistroSeries.id,
                DistroSeries.status.is_in(ACTIVE_STATUSES),
                ])
        return Store.of(self).find(Processor, *clauses).config(distinct=True)

    def _getProcessors(self):
        return list(Store.of(self).find(
            Processor,
            Processor.id == OCIRecipeArch.processor_id,
            OCIRecipeArch.recipe == self))

    def setProcessors(self, processors, check_permissions=False, user=None):
        """See `IOCIRecipe`."""
        if check_permissions:
            can_modify = None
            if user is not None:
                roles = IPersonRoles(user)
                authz = lambda perm: getAdapter(self, IAuthorization, perm)
                if authz('launchpad.Admin').checkAuthenticated(roles):
                    can_modify = lambda proc: True
                elif authz('launchpad.Edit').checkAuthenticated(roles):
                    can_modify = lambda proc: not proc.restricted
            if can_modify is None:
                raise Unauthorized(
                    'Permission launchpad.Admin or launchpad.Edit required '
                    'on %s.' % self)
        else:
            can_modify = lambda proc: True

        enablements = dict(Store.of(self).find(
            (Processor, OCIRecipeArch),
            Processor.id == OCIRecipeArch.processor_id,
            OCIRecipeArch.recipe == self))
        for proc in enablements:
            if proc not in processors:
                if not can_modify(proc):
                    raise CannotModifyOCIRecipeProcessor(proc)
                Store.of(self).remove(enablements[proc])
        for proc in processors:
            if proc not in self.processors:
                if not can_modify(proc):
                    raise CannotModifyOCIRecipeProcessor(proc)
                Store.of(self).add(OCIRecipeArch(self, proc))

    processors = property(_getProcessors, setProcessors)

    def _isBuildableArchitectureAllowed(self, das):
        """Check whether we may build for a buildable `DistroArchSeries`.

        The caller is assumed to have already checked that a suitable chroot
        is available (either directly or via
        `DistroSeries.buildable_architectures`).
        """
        return (
            das.enabled
            and das.processor in self.processors
            and (
                das.processor.supports_virtualized
                or not self.require_virtualized))

    def _isArchitectureAllowed(self, das, pocket):
        return (
            das.getChroot(pocket=pocket) is not None
            and self._isBuildableArchitectureAllowed(das))

    def getAllowedArchitectures(self, distro_series=None):
        """See `IOCIRecipe`."""
        if distro_series is None:
            distro_series = self.distro_series
        return [
            das for das in distro_series.buildable_architectures
            if self._isBuildableArchitectureAllowed(das)]

    def _checkRequestBuild(self, requester):
        if not requester.inTeam(self.owner):
            raise OCIRecipeNotOwner(
                "%s cannot create OCI image builds owned by %s." %
                (requester.display_name, self.owner.display_name))

    def _hasPendingBuilds(self, processors):
        """Checks if this OCIRecipe has pending builds for any of the given
        processors."""
        pending = IStore(self).find(
            OCIRecipeBuild,
            OCIRecipeBuild.recipe == self.id,
            OCIRecipeBuild.processor_id.is_in([i.id for i in processors]),
            OCIRecipeBuild.status == BuildStatus.NEEDSBUILD)
        return pending.any() is not None

    def _createBuild(self, requester, distro_arch_series):
        """Creates a build without checking anything."""
        build = getUtility(IOCIRecipeBuildSet).new(
            requester, self, distro_arch_series)
        build.queueBuild()
        notify(ObjectCreatedEvent(build, user=requester))
        return build

    def requestBuild(self, requester, distro_arch_series):
        self._checkRequestBuild(requester)
        if self._hasPendingBuilds([distro_arch_series.processor]):
            raise OCIRecipeBuildAlreadyPending

        return self._createBuild(requester, distro_arch_series)

    def getBuildRequest(self, job_id):
        return OCIRecipeBuildRequest(self, job_id)

    def requestBuildsFromJob(self, requester):
        self._checkRequestBuild(requester)
        processors = self.available_processors
        if self._hasPendingBuilds(processors):
            raise OCIRecipeBuildAlreadyPending

        builds = []
        for distro_arch_series in self.oci_project.distribution.architectures:
            builds.append(self._createBuild(requester, distro_arch_series))
        return builds

    def requestBuilds(self, requester):
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            self, requester)
        return self.getBuildRequest(job.job_id)

    @property
    def push_rules(self):
        rules = IStore(self).find(
            OCIPushRule,
            OCIPushRule.recipe == self.id)
        return rules

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
            build_daily=False, processors=None, date_created=DEFAULT):
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
            official, require_virtualized, build_file, build_daily,
            date_created)
        store.add(oci_recipe)

        if processors is None:
            processors = [
                p for p in oci_recipe.available_processors
                if p.build_by_default]
        oci_recipe.setProcessors(processors)

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

    def findByOwner(self, owner):
        """See `IOCIRecipeSet`."""
        return IStore(OCIRecipe).find(OCIRecipe, OCIRecipe.owner == owner)

    def findByOCIProject(self, oci_project):
        """See `IOCIRecipeSet`."""
        return IStore(OCIRecipe).find(
            OCIRecipe, OCIRecipe.oci_project == oci_project)

    def findByGitRepository(self, repository, paths=None):
        """See `IOCIRecipeSet`."""
        clauses = [OCIRecipe.git_repository == repository]
        if paths is not None:
            clauses.append(OCIRecipe.git_path.is_in(paths))
        return IStore(OCIRecipe).find(OCIRecipe, *clauses)

    def detachFromGitRepository(self, repository):
        """See `IOCIRecipeSet`."""
        self.findByGitRepository(repository).set(
            git_repository_id=None, git_path=None, date_last_modified=UTC_NOW)

    def preloadDataForOCIRecipes(self, recipes, user=None):
        """See `IOCIRecipeSet`."""
        recipes = [removeSecurityProxy(recipe) for recipe in recipes]

        person_ids = set()
        for recipe in recipes:
            person_ids.add(recipe.registrant_id)
            person_ids.add(recipe.owner_id)

        list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(
            person_ids, need_validity=True))


@implementer(IOCIRecipeBuildRequest)
class OCIRecipeBuildRequest:
    def __init__(self, oci_recipe, id):
        self.oci_recipe = oci_recipe
        self.id = id

    @cachedproperty
    def job(self):
        util = getUtility(IOCIRecipeRequestBuildsJobSource)
        return util.findByOCIRecipeAndID(
            self.oci_recipe, self.id)

    @property
    def date_requested(self):
        return self.job.date_created

    @property
    def date_finished(self):
        return self.job.date_finished

    @property
    def status(self):
        status_map = {
            JobStatus.WAITING: OCIRecipeBuildRequestStatus.PENDING,
            JobStatus.RUNNING: OCIRecipeBuildRequestStatus.PENDING,
            JobStatus.COMPLETED: OCIRecipeBuildRequestStatus.COMPLETED,
            JobStatus.FAILED: OCIRecipeBuildRequestStatus.FAILED,
            JobStatus.SUSPENDED: OCIRecipeBuildRequestStatus.PENDING,
        }
        return status_map[self.job.status]

    @property
    def error_message(self):
        return self.job.error_message

    @property
    def builds(self):
        return self.job.builds

    @property
    def requester(self):
        return self.job.requester
