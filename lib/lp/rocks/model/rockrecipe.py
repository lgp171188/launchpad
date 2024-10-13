# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Rock recipes."""

__all__ = [
    "RockRecipe",
    "get_rock_recipe_privacy_filter",
]

from datetime import timezone
from operator import attrgetter, itemgetter

import yaml
from lazr.lifecycle.event import ObjectCreatedEvent
from storm.databases.postgres import JSON
from storm.locals import (
    And,
    Bool,
    DateTime,
    Desc,
    Int,
    Join,
    Not,
    Or,
    Reference,
    Select,
    Store,
    Unicode,
)
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import (
    FREE_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
)
from lp.app.errors import IncompatibleArguments
from lp.buildmaster.builderproxy import FetchServicePolicy
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.model.builder import Builder
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.errors import GitRepositoryBlobNotFound, GitRepositoryScanFault
from lp.code.interfaces.gitcollection import (
    IAllGitRepositories,
    IGitCollection,
)
from lp.code.interfaces.gitref import IGitRef, IGitRefRemoteSet
from lp.code.interfaces.gitrepository import IGitRepository
from lp.code.model.gitcollection import GenericGitCollection
from lp.code.model.gitref import GitRef
from lp.code.model.gitrepository import GitRepository
from lp.code.model.reciperegistry import recipe_registry
from lp.registry.errors import PrivatePersonLinkageError
from lp.registry.interfaces.person import (
    IPerson,
    IPersonSet,
    validate_public_person,
)
from lp.registry.interfaces.product import IProduct
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.product import Product
from lp.registry.model.series import ACTIVE_STATUSES
from lp.rocks.adapters.buildarch import determine_instances_to_build
from lp.rocks.interfaces.rockbase import IRockBaseSet, NoSuchRockBase
from lp.rocks.interfaces.rockrecipe import (
    ROCK_RECIPE_ALLOW_CREATE,
    ROCK_RECIPE_PRIVATE_FEATURE_FLAG,
    BadRockRecipeSearchContext,
    CannotFetchRockcraftYaml,
    CannotParseRockcraftYaml,
    DuplicateRockRecipeName,
    IRockRecipe,
    IRockRecipeBuildRequest,
    IRockRecipeSet,
    MissingRockcraftYaml,
    NoSourceForRockRecipe,
    NoSuchRockRecipe,
    RockRecipeBuildAlreadyPending,
    RockRecipeBuildDisallowedArchitecture,
    RockRecipeBuildRequestStatus,
    RockRecipeFeatureDisabled,
    RockRecipeNotOwner,
    RockRecipePrivacyMismatch,
    RockRecipePrivateFeatureDisabled,
)
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuildSet
from lp.rocks.interfaces.rockrecipejob import IRockRecipeRequestBuildsJobSource
from lp.rocks.model.rockbase import RockBase
from lp.rocks.model.rockrecipebuild import RockRecipeBuild
from lp.rocks.model.rockrecipejob import RockRecipeJob
from lp.services.database.bulk import load_related
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import Greatest, NullsLast
from lp.services.features import getFeatureFlag
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import Job
from lp.services.librarian.model import LibraryFileAlias
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.soyuz.model.distroarchseries import DistroArchSeries, PocketChroot


def rock_recipe_modified(recipe, event):
    """Update the date_last_modified property when a rock recipe is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on rock recipes.
    """
    removeSecurityProxy(recipe).date_last_modified = UTC_NOW


@implementer(IRockRecipeBuildRequest)
class RockRecipeBuildRequest:
    """See `IRockRecipeBuildRequest`.

    This is not directly backed by a database table; instead, it is a
    webservice-friendly view of an asynchronous build request.
    """

    def __init__(self, recipe, id):
        self.recipe = recipe
        self.id = id

    @classmethod
    def fromJob(cls, job):
        """See `IRockRecipeBuildRequest`."""
        request = cls(job.recipe, job.job_id)
        get_property_cache(request)._job = job
        return request

    @cachedproperty
    def _job(self):
        job_source = getUtility(IRockRecipeRequestBuildsJobSource)
        return job_source.getByRecipeAndID(self.recipe, self.id)

    @property
    def date_requested(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.date_created

    @property
    def date_finished(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.date_finished

    @property
    def status(self):
        """See `IRockRecipeBuildRequest`."""
        status_map = {
            JobStatus.WAITING: RockRecipeBuildRequestStatus.PENDING,
            JobStatus.RUNNING: RockRecipeBuildRequestStatus.PENDING,
            JobStatus.COMPLETED: RockRecipeBuildRequestStatus.COMPLETED,
            JobStatus.FAILED: RockRecipeBuildRequestStatus.FAILED,
            JobStatus.SUSPENDED: RockRecipeBuildRequestStatus.PENDING,
        }
        return status_map[self._job.job.status]

    @property
    def error_message(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.error_message

    @property
    def builds(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.builds

    @property
    def requester(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.requester

    @property
    def channels(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.channels

    @property
    def architectures(self):
        """See `IRockRecipeBuildRequest`."""
        return self._job.architectures


@implementer(IRockRecipe)
class RockRecipe(StormBase):
    """See `IRockRecipe`."""

    __storm_table__ = "RockRecipe"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=timezone.utc, allow_none=False
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    def _validate_owner(self, attr, value):
        if not self.private:
            try:
                validate_public_person(self, attr, value)
            except PrivatePersonLinkageError:
                raise RockRecipePrivacyMismatch(
                    "A public rock recipe cannot have a private owner."
                )
        return value

    owner_id = Int(name="owner", allow_none=False, validator=_validate_owner)
    owner = Reference(owner_id, "Person.id")

    project_id = Int(name="project", allow_none=False)
    project = Reference(project_id, "Product.id")

    name = Unicode(name="name", allow_none=False)

    description = Unicode(name="description", allow_none=True)

    def _validate_git_repository(self, attr, value):
        if not self.private and value is not None:
            if IStore(GitRepository).get(GitRepository, value).private:
                raise RockRecipePrivacyMismatch(
                    "A public rock recipe cannot have a private repository."
                )
        return value

    git_repository_id = Int(
        name="git_repository",
        allow_none=True,
        validator=_validate_git_repository,
    )
    git_repository = Reference(git_repository_id, "GitRepository.id")

    git_repository_url = Unicode(name="git_repository_url", allow_none=True)

    git_path = Unicode(name="git_path", allow_none=True)

    build_path = Unicode(name="build_path", allow_none=True)

    require_virtualized = Bool(name="require_virtualized")

    def _valid_information_type(self, attr, value):
        if not getUtility(IRockRecipeSet).isValidInformationType(
            value, self.owner, self.git_ref
        ):
            raise RockRecipePrivacyMismatch
        return value

    information_type = DBEnum(
        enum=InformationType,
        default=InformationType.PUBLIC,
        name="information_type",
        validator=_valid_information_type,
        allow_none=False,
    )

    auto_build = Bool(name="auto_build", allow_none=False)

    auto_build_channels = JSON("auto_build_channels", allow_none=True)

    is_stale = Bool(name="is_stale", allow_none=False)

    store_upload = Bool(name="store_upload", allow_none=False)

    store_name = Unicode(name="store_name", allow_none=True)

    store_secrets = JSON("store_secrets", allow_none=True)

    _store_channels = JSON("store_channels", allow_none=True)

    use_fetch_service = Bool(name="use_fetch_service", allow_none=False)

    fetch_service_policy = DBEnum(
        enum=FetchServicePolicy,
        default=FetchServicePolicy.STRICT,
        name="fetch_service_policy",
        allow_none=True,
    )

    def __init__(
        self,
        registrant,
        owner,
        project,
        name,
        description=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
        use_fetch_service=False,
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """Construct a `RockRecipe`."""
        if not getFeatureFlag(ROCK_RECIPE_ALLOW_CREATE):
            raise RockRecipeFeatureDisabled()
        super().__init__()

        # Set this first for use by other validators.
        self.information_type = information_type

        self.date_created = date_created
        self.date_last_modified = date_created
        self.registrant = registrant
        self.owner = owner
        self.project = project
        self.name = name
        self.description = description
        self.git_ref = git_ref
        self.build_path = build_path
        self.require_virtualized = require_virtualized
        self.auto_build = auto_build
        self.auto_build_channels = auto_build_channels
        self.store_upload = store_upload
        self.store_name = store_name
        self.store_secrets = store_secrets
        self.store_channels = store_channels
        self.use_fetch_service = use_fetch_service
        self.fetch_service_policy = fetch_service_policy

    def __repr__(self):
        return "<RockRecipe ~%s/%s/+rock/%s>" % (
            self.owner.name,
            self.project.name,
            self.name,
        )

    @property
    def private(self):
        """See `IRockRecipe`."""
        return self.information_type not in PUBLIC_INFORMATION_TYPES

    @cachedproperty
    def _git_ref(self):
        if self.git_repository is not None:
            return self.git_repository.getRefByPath(self.git_path)
        elif self.git_repository_url is not None:
            return getUtility(IGitRefRemoteSet).new(
                self.git_repository_url, self.git_path
            )
        else:
            return None

    @property
    def git_ref(self):
        """See `IRockRecipe`."""
        return self._git_ref

    @git_ref.setter
    def git_ref(self, value):
        """See `IRockRecipe`."""
        if value is not None:
            self.git_repository = value.repository
            self.git_repository_url = value.repository_url
            self.git_path = value.path
        else:
            self.git_repository = None
            self.git_repository_url = None
            self.git_path = None
        get_property_cache(self)._git_ref = value

    @property
    def source(self):
        """See `IRockRecipe`."""
        return self.git_ref

    @property
    def store_channels(self):
        """See `IRockRecipe`."""
        return self._store_channels or []

    @store_channels.setter
    def store_channels(self, value):
        """See `IRockRecipe`."""
        self._store_channels = value or None

    def getAllowedInformationTypes(self, user):
        """See `IRockRecipe`."""
        # XXX jugmac00 2024-08-29: Only allow free information types until
        # we have more privacy infrastructure in place.
        return FREE_INFORMATION_TYPES

    def visibleByUser(self, user):
        """See `IRockRecipe`."""
        if self.information_type in PUBLIC_INFORMATION_TYPES:
            return True
        if user is None:
            return False
        return (
            not IStore(RockRecipe)
            .find(
                RockRecipe,
                RockRecipe.id == self.id,
                get_rock_recipe_privacy_filter(user),
            )
            .is_empty()
        )

    def _isBuildableArchitectureAllowed(self, das, rock_base=None):
        """Check whether we may build for a buildable `DistroArchSeries`.

        The caller is assumed to have already checked that a suitable chroot
        is available (either directly or via
        `DistroSeries.buildable_architectures`).
        """
        return (
            das.enabled
            and (
                das.processor.supports_virtualized
                or not self.require_virtualized
            )
            and (rock_base is None or das.processor in rock_base.processors)
        )

    def _isArchitectureAllowed(self, das, rock_base=None):
        """Check whether we may build for a `DistroArchSeries`."""
        return (
            das.getChroot() is not None
            and self._isBuildableArchitectureAllowed(das, rock_base=rock_base)
        )

    def getAllowedArchitectures(self):
        """See `ICharmRecipe`."""
        store = Store.of(self)
        origin = [
            DistroArchSeries,
            Join(
                DistroSeries, DistroArchSeries.distroseries == DistroSeries.id
            ),
            Join(Distribution, DistroSeries.distribution == Distribution.id),
            Join(
                PocketChroot,
                PocketChroot.distroarchseries == DistroArchSeries.id,
            ),
            Join(LibraryFileAlias, PocketChroot.chroot == LibraryFileAlias.id),
        ]
        # Preload DistroSeries and Distribution, since we'll need those in
        # determine_architectures_to_build.
        results = store.using(*origin).find(
            (DistroArchSeries, DistroSeries, Distribution),
            DistroSeries.status.is_in(ACTIVE_STATUSES),
        )
        all_buildable_dases = DecoratedResultSet(results, itemgetter(0))
        rock_bases = {
            rock_base.distro_series_id: rock_base
            for rock_base in store.find(
                RockBase,
                RockBase.distro_series_id.is_in(
                    {das.distroseries_id for das in all_buildable_dases}
                ),
            )
        }
        return [
            das
            for das in all_buildable_dases
            if self._isBuildableArchitectureAllowed(
                das, rock_base=rock_bases.get(das.id)
            )
        ]

    def _checkRequestBuild(self, requester):
        """May `requester` request builds of this rock recipe?"""
        if not requester.inTeam(self.owner):
            raise RockRecipeNotOwner(
                "%s cannot create rock recipe builds owned by %s."
                % (requester.display_name, self.owner.display_name)
            )

    def requestBuild(
        self, build_request, distro_arch_series, rock_base=None, channels=None
    ):
        """Request a single build of this rock recipe.

        This method is for internal use; external callers should use
        `requestBuilds` instead.

        :param build_request: The `IRockRecipeBuildRequest` job being
            processed.
        :param distro_arch_series: The architecture to build for.
        :param channels: A dictionary mapping snap names to channels to use
            for this build.
        :return: `IRockRecipeBuild`.
        """
        self._checkRequestBuild(build_request.requester)
        if not self._isArchitectureAllowed(
            distro_arch_series, rock_base=rock_base
        ):
            raise RockRecipeBuildDisallowedArchitecture(distro_arch_series)

        if not channels:
            channels_clause = Or(
                RockRecipeBuild.channels == None,
                RockRecipeBuild.channels == {},
            )
        else:
            channels_clause = RockRecipeBuild.channels == channels
        pending = IStore(self).find(
            RockRecipeBuild,
            RockRecipeBuild.recipe == self,
            RockRecipeBuild.processor == distro_arch_series.processor,
            channels_clause,
            RockRecipeBuild.status == BuildStatus.NEEDSBUILD,
        )
        if pending.any() is not None:
            raise RockRecipeBuildAlreadyPending

        build = getUtility(IRockRecipeBuildSet).new(
            build_request, self, distro_arch_series, channels=channels
        )
        build.queueBuild()
        notify(ObjectCreatedEvent(build, user=build_request.requester))
        return build

    def requestBuilds(self, requester, channels=None, architectures=None):
        """See `IRockRecipe`."""
        self._checkRequestBuild(requester)
        job = getUtility(IRockRecipeRequestBuildsJobSource).create(
            self, requester, channels=channels, architectures=architectures
        )
        return self.getBuildRequest(job.job_id)

    def requestBuildsFromJob(
        self,
        build_request,
        channels=None,
        architectures=None,
        allow_failures=False,
        logger=None,
    ):
        """See `IRockRecipe`."""
        try:
            rockcraft_data = removeSecurityProxy(
                getUtility(IRockRecipeSet).getRockcraftYaml(self)
            )
            supported_arches = sorted(
                self.getAllowedArchitectures(),
                key=attrgetter(
                    "distroseries.distribution.id",
                    "distroseries.id",
                    "processor.id",
                ),
            )
            instances_to_build = determine_instances_to_build(
                rockcraft_data,
                supported_arches=supported_arches,
                requested_architectures=architectures,
            )
        except Exception as e:
            if not allow_failures:
                raise
            elif logger is not None:
                logger.exception(
                    " - %s/%s/%s: %s",
                    self.owner.name,
                    self.project.name,
                    self.name,
                    e,
                )

        builds = []
        for das in instances_to_build:
            try:
                rock_base = getUtility(IRockBaseSet).getByDistroSeries(
                    das.distroseries
                )
            except NoSuchRockBase:
                rock_base = None
            if rock_base is not None:
                arch_channels = dict(rock_base.build_channels)
                channels_by_arch = arch_channels.pop("_byarch", {})
                if das.architecturetag in channels_by_arch:
                    arch_channels.update(channels_by_arch[das.architecturetag])
                if channels is not None:
                    arch_channels.update(channels)
            else:
                arch_channels = channels
            try:
                build = self.requestBuild(
                    build_request, das, channels=arch_channels
                )
                if logger is not None:
                    logger.debug(
                        " - %s/%s/%s %s/%s/%s: Build requested.",
                        self.owner.name,
                        self.project.name,
                        self.name,
                        das.distroseries.distribution.name,
                        das.distroseries.name,
                        das.architecturetag,
                    )
                builds.append(build)
            except RockRecipeBuildAlreadyPending:
                pass
            except Exception as e:
                if not allow_failures:
                    raise
                elif logger is not None:
                    logger.exception(
                        " - %s/%s/%s %s/%s/%s: %s",
                        self.owner.name,
                        self.project.name,
                        self.name,
                        das.distroseries.distribution.name,
                        das.distroseries.name,
                        das.architecturetag,
                        e,
                    )
        return builds

    def getBuildRequest(self, job_id):
        """See `IRockRecipe`."""
        return RockRecipeBuildRequest(self, job_id)

    @property
    def pending_build_requests(self):
        """See `IRockRecipe`."""
        job_source = getUtility(IRockRecipeRequestBuildsJobSource)
        # The returned jobs are ordered by descending ID.
        jobs = job_source.findByRecipe(
            self, statuses=(JobStatus.WAITING, JobStatus.RUNNING)
        )
        return DecoratedResultSet(
            jobs, result_decorator=RockRecipeBuildRequest.fromJob
        )

    @property
    def failed_build_requests(self):
        """See `IRockRecipe`."""
        job_source = getUtility(IRockRecipeRequestBuildsJobSource)
        # The returned jobs are ordered by descending ID.
        jobs = job_source.findByRecipe(self, statuses=(JobStatus.FAILED,))
        return DecoratedResultSet(
            jobs, result_decorator=RockRecipeBuildRequest.fromJob
        )

    def _getBuilds(self, filter_term, order_by):
        """The actual query to get the builds."""
        query_args = [
            RockRecipeBuild.recipe == self,
        ]
        if filter_term is not None:
            query_args.append(filter_term)
        result = Store.of(self).find(RockRecipeBuild, *query_args)
        result.order_by(order_by)

        def eager_load(rows):
            getUtility(IRockRecipeBuildSet).preloadBuildsData(rows)
            getUtility(IBuildQueueSet).preloadForBuildFarmJobs(rows)
            load_related(Builder, rows, ["builder_id"])

        return DecoratedResultSet(result, pre_iter_hook=eager_load)

    @property
    def builds(self):
        """See `IRockRecipe`."""
        order_by = (
            NullsLast(
                Desc(
                    Greatest(
                        RockRecipeBuild.date_started,
                        RockRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(RockRecipeBuild.date_created),
            Desc(RockRecipeBuild.id),
        )
        return self._getBuilds(None, order_by)

    @property
    def _pending_states(self):
        """All the build states we consider pending (non-final)."""
        return [
            BuildStatus.NEEDSBUILD,
            BuildStatus.BUILDING,
            BuildStatus.UPLOADING,
            BuildStatus.CANCELLING,
        ]

    @property
    def completed_builds(self):
        """See `IRockRecipe`."""
        filter_term = Not(RockRecipeBuild.status.is_in(self._pending_states))
        order_by = (
            NullsLast(
                Desc(
                    Greatest(
                        RockRecipeBuild.date_started,
                        RockRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(RockRecipeBuild.id),
        )
        return self._getBuilds(filter_term, order_by)

    @property
    def pending_builds(self):
        """See `IRockRecipe`."""
        filter_term = RockRecipeBuild.status.is_in(self._pending_states)
        # We want to order by date_created but this is the same as ordering
        # by id (since id increases monotonically) and is less expensive.
        order_by = Desc(RockRecipeBuild.id)
        return self._getBuilds(filter_term, order_by)

    @property
    def can_upload_to_store(self):
        # no store upload planned for the initial implementation, as artifacts
        # get pulled from Launchpad for now only.
        return False

    def destroySelf(self):
        """See `IRockRecipe`."""
        store = IStore(self)
        # Remove build jobs. There won't be many queued builds, so we can
        # afford to do this the safe but slow way via BuildQueue.destroySelf
        # rather than in bulk.
        buildqueue_records = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id == RockRecipeBuild.build_farm_job_id,
            RockRecipeBuild.recipe == self,
        )
        for buildqueue_record in buildqueue_records:
            buildqueue_record.destroySelf()
        build_farm_job_ids = list(
            store.find(
                RockRecipeBuild.build_farm_job_id,
                RockRecipeBuild.recipe == self,
            )
        )
        store.execute(
            """
            DELETE FROM RockFile
            USING RockRecipeBuild
            WHERE
                RockFile.build = RockRecipeBuild.id AND
                RockRecipeBuild.recipe = ?
            """,
            (self.id,),
        )
        store.find(RockRecipeBuild, RockRecipeBuild.recipe == self).remove()
        affected_jobs = Select(
            [RockRecipeJob.job_id],
            And(RockRecipeJob.job == Job.id, RockRecipeJob.recipe == self),
        )
        store.find(Job, Job.id.is_in(affected_jobs)).remove()
        # XXX jugmac00 2024-09-10: we need to remove webhooks once implemented
        # getUtility(IWebhookSet).delete(self.webhooks)
        store.remove(self)
        store.find(
            BuildFarmJob, BuildFarmJob.id.is_in(build_farm_job_ids)
        ).remove()


@recipe_registry.register_recipe_type(
    IRockRecipeSet, "Some rock recipes build from this repository."
)
@implementer(IRockRecipeSet)
class RockRecipeSet:
    """See `IRockRecipeSet`."""

    def new(
        self,
        registrant,
        owner,
        project,
        name,
        description=None,
        git_repository=None,
        git_repository_url=None,
        git_path=None,
        git_ref=None,
        build_path=None,
        require_virtualized=True,
        information_type=InformationType.PUBLIC,
        auto_build=False,
        auto_build_channels=None,
        store_upload=False,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        date_created=DEFAULT,
        use_fetch_service=False,
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """See `IRockRecipeSet`."""
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise RockRecipeNotOwner(
                    "%s is not a member of %s."
                    % (registrant.displayname, owner.displayname)
                )
            else:
                raise RockRecipeNotOwner(
                    "%s cannot create rock recipes owned by %s."
                    % (registrant.displayname, owner.displayname)
                )

        if (
            sum(
                [
                    git_repository is not None,
                    git_repository_url is not None,
                    git_ref is not None,
                ]
            )
            > 1
        ):
            raise IncompatibleArguments(
                "You cannot specify more than one of 'git_repository', "
                "'git_repository_url', and 'git_ref'."
            )
        if (git_repository is None and git_repository_url is None) != (
            git_path is None
        ):
            raise IncompatibleArguments(
                "You must specify both or neither of "
                "'git_repository'/'git_repository_url' and 'git_path'."
            )
        if git_repository is not None:
            git_ref = git_repository.getRefByPath(git_path)
        elif git_repository_url is not None:
            git_ref = getUtility(IGitRefRemoteSet).new(
                git_repository_url, git_path
            )

        if git_ref is None:
            raise NoSourceForRockRecipe
        if self.exists(owner, project, name):
            raise DuplicateRockRecipeName

        # The relevant validators will do their own checks as well, but we
        # do a single up-front check here in order to avoid an
        # IntegrityError due to exceptions being raised during object
        # creation and to ensure that everything relevant is in the Storm
        # cache.
        if not self.isValidInformationType(information_type, owner, git_ref):
            raise RockRecipePrivacyMismatch
        store = IPrimaryStore(RockRecipe)
        recipe = RockRecipe(
            registrant,
            owner,
            project,
            name,
            description=description,
            git_ref=git_ref,
            build_path=build_path,
            require_virtualized=require_virtualized,
            information_type=information_type,
            auto_build=auto_build,
            auto_build_channels=auto_build_channels,
            store_upload=store_upload,
            store_name=store_name,
            store_secrets=store_secrets,
            store_channels=store_channels,
            date_created=date_created,
            use_fetch_service=use_fetch_service,
            fetch_service_policy=fetch_service_policy,
        )
        store.add(recipe)

        return recipe

    def _getByName(self, owner, project, name):
        return (
            IStore(RockRecipe)
            .find(RockRecipe, owner=owner, project=project, name=name)
            .one()
        )

    def exists(self, owner, project, name):
        """See `IRockRecipeSet."""
        return self._getByName(owner, project, name) is not None

    def getByName(self, owner, project, name):
        """See `IRockRecipeSet`."""
        recipe = self._getByName(owner, project, name)
        if recipe is None:
            raise NoSuchRockRecipe(name)
        return recipe

    def _getRecipesFromCollection(
        self, collection, owner=None, visible_by_user=None
    ):
        id_column = RockRecipe.git_repository_id
        ids = collection.getRepositoryIds()
        expressions = [id_column.is_in(ids._get_select())]
        if owner is not None:
            expressions.append(RockRecipe.owner == owner)
        expressions.append(get_rock_recipe_privacy_filter(visible_by_user))
        return IStore(RockRecipe).find(RockRecipe, *expressions)

    def findByPerson(self, person, visible_by_user=None):
        """See `IRockRecipeSet`."""

        def _getRecipes(collection):
            collection = collection.visibleByUser(visible_by_user)
            owned = self._getRecipesFromCollection(
                collection.ownedBy(person), visible_by_user=visible_by_user
            )
            packaged = self._getRecipesFromCollection(
                collection, owner=person, visible_by_user=visible_by_user
            )
            return owned.union(packaged)

        git_collection = removeSecurityProxy(getUtility(IAllGitRepositories))
        git_recipes = _getRecipes(git_collection)
        git_url_recipes = IStore(RockRecipe).find(
            RockRecipe,
            RockRecipe.owner == person,
            RockRecipe.git_repository_url != None,
        )
        return git_recipes.union(git_url_recipes)

    def findByProject(self, project, visible_by_user=None):
        """See `IRockRecipeSet`."""

        def _getRecipes(collection):
            return self._getRecipesFromCollection(
                collection.visibleByUser(visible_by_user),
                visible_by_user=visible_by_user,
            )

        recipes_for_project = IStore(RockRecipe).find(
            RockRecipe,
            RockRecipe.project == project,
            get_rock_recipe_privacy_filter(visible_by_user),
        )
        git_collection = removeSecurityProxy(IGitCollection(project))
        return recipes_for_project.union(_getRecipes(git_collection))

    def findByGitRepository(
        self,
        repository,
        paths=None,
        visible_by_user=None,
        check_permissions=True,
    ):
        """See `IRockRecipeSet`."""
        clauses = [RockRecipe.git_repository == repository]
        if paths is not None:
            clauses.append(RockRecipe.git_path.is_in(paths))
        if check_permissions:
            clauses.append(get_rock_recipe_privacy_filter(visible_by_user))
        return IStore(RockRecipe).find(RockRecipe, *clauses)

    def findByGitRef(self, ref, visible_by_user=None):
        """See `IRockRecipeSet`."""
        return IStore(RockRecipe).find(
            RockRecipe,
            RockRecipe.git_repository == ref.repository,
            RockRecipe.git_path == ref.path,
            get_rock_recipe_privacy_filter(visible_by_user),
        )

    def findByContext(self, context, visible_by_user=None, order_by_date=True):
        """See `IRockRecipeSet`."""
        if IPerson.providedBy(context):
            recipes = self.findByPerson(
                context, visible_by_user=visible_by_user
            )
        elif IProduct.providedBy(context):
            recipes = self.findByProject(
                context, visible_by_user=visible_by_user
            )
        elif IGitRepository.providedBy(context):
            recipes = self.findByGitRepository(
                context, visible_by_user=visible_by_user
            )
        elif IGitRef.providedBy(context):
            recipes = self.findByGitRef(
                context, visible_by_user=visible_by_user
            )
        else:
            raise BadRockRecipeSearchContext(context)
        if order_by_date:
            recipes = recipes.order_by(Desc(RockRecipe.date_last_modified))
        return recipes

    def isValidInformationType(self, information_type, owner, git_ref=None):
        """See `IRockRecipeSet`."""
        private = information_type not in PUBLIC_INFORMATION_TYPES
        if private:
            # If appropriately enabled via feature flag.
            if not getFeatureFlag(ROCK_RECIPE_PRIVATE_FEATURE_FLAG):
                raise RockRecipePrivateFeatureDisabled
            return True

        # Public rock recipes with private sources are not allowed.
        if git_ref is not None and git_ref.private:
            return False

        # Public rock recipes owned by private teams are not allowed.
        if owner is not None and owner.private:
            return False

        return True

    def preloadDataForRecipes(self, recipes, user=None):
        """See `IRockRecipeSet`."""
        recipes = [removeSecurityProxy(recipe) for recipe in recipes]

        load_related(Product, recipes, ["project_id"])

        person_ids = set()
        for recipe in recipes:
            person_ids.add(recipe.registrant_id)
            person_ids.add(recipe.owner_id)

        repositories = load_related(
            GitRepository, recipes, ["git_repository_id"]
        )
        if repositories:
            GenericGitCollection.preloadDataForRepositories(repositories)

        git_refs = GitRef.findByReposAndPaths(
            [(recipe.git_repository, recipe.git_path) for recipe in recipes]
        )
        for recipe in recipes:
            git_ref = git_refs.get((recipe.git_repository, recipe.git_path))
            if git_ref is not None:
                get_property_cache(recipe)._git_ref = git_ref

        # Add repository owners to the list of pre-loaded persons. We need
        # the target repository owner as well, since repository unique names
        # aren't trigger-maintained.
        person_ids.update(repository.owner_id for repository in repositories)

        list(
            getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                person_ids, need_validity=True
            )
        )

    def getRockcraftYaml(self, context, logger=None):
        """See `IRockRecipeSet`."""
        if IRockRecipe.providedBy(context):
            recipe = context
            source = context.git_ref
        else:
            recipe = None
            source = context
        if source is None:
            raise CannotFetchRockcraftYaml("Rock source is not defined")
        try:
            path = "rockcraft.yaml"
            if recipe is not None and recipe.build_path is not None:
                path = "/".join((recipe.build_path, path))
            try:
                blob = source.getBlob(path)
            except GitRepositoryBlobNotFound:
                if logger is not None:
                    logger.exception(
                        "Cannot find rockcraft.yaml in %s", source.unique_name
                    )
                raise MissingRockcraftYaml(source.unique_name)
        except GitRepositoryScanFault as e:
            msg = "Failed to get rockcraft.yaml from %s"
            if logger is not None:
                logger.exception(msg, source.unique_name)
            raise CannotFetchRockcraftYaml(
                "%s: %s" % (msg % source.unique_name, e)
            )

        try:
            rockcraft_data = yaml.safe_load(blob)
        except Exception as e:
            # Don't bother logging parsing errors from user-supplied YAML.
            raise CannotParseRockcraftYaml(
                "Cannot parse rockcraft.yaml from %s: %s"
                % (source.unique_name, e)
            )

        if not isinstance(rockcraft_data, dict):
            raise CannotParseRockcraftYaml(
                "The top level of rockcraft.yaml from %s is not a mapping"
                % source.unique_name
            )

        return rockcraft_data

    def findByOwner(self, owner):
        """See `ICharmRecipeSet`."""
        return IStore(RockRecipe).find(RockRecipe, owner=owner)

    def detachFromGitRepository(self, repository):
        """See `ICharmRecipeSet`."""
        recipes = self.findByGitRepository(repository)
        for recipe in recipes:
            get_property_cache(recipe)._git_ref = None
        recipes.set(
            git_repository_id=None, git_path=None, date_last_modified=UTC_NOW
        )

    def empty_list(self):
        """See `IRockRecipeSet`."""
        return []


def get_rock_recipe_privacy_filter(user):
    """Return a Storm query filter to find rock recipes visible to `user`."""
    public_filter = RockRecipe.information_type.is_in(PUBLIC_INFORMATION_TYPES)

    # XXX jugmac00 2024-09-016: Flesh this out once we have more privacy
    # infrastructure.
    return [public_filter]
