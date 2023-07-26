# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A recipe for building Open Container Initiative images."""

__all__ = [
    "get_ocirecipe_privacy_filter",
    "OCIRecipe",
    "OCIRecipeBuildRequest",
    "OCIRecipeSet",
]

from datetime import timezone

from lazr.lifecycle.event import ObjectCreatedEvent
from storm.databases.postgres import JSON
from storm.expr import SQL, And, Coalesce, Desc, Exists, Join, Not, Or, Select
from storm.locals import Bool, DateTime, Int, Reference, Store, Unicode
from zope.component import getAdapter, getUtility
from zope.event import notify
from zope.interface import implementer
from zope.security.interfaces import Unauthorized
from zope.security.proxy import isinstance as zope_isinstance
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import PUBLIC_INFORMATION_TYPES, InformationType
from lp.app.errors import (
    SubscriptionPrivacyViolation,
    UserCannotUnsubscribePerson,
)
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.security import IAuthorization
from lp.app.interfaces.services import IService
from lp.app.validators.validation import validate_oci_branch_name
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.model.processor import Processor
from lp.code.model.gitcollection import GenericGitCollection
from lp.code.model.gitref import GitRef
from lp.code.model.gitrepository import GitRepository
from lp.oci.enums import OCIRecipeBuildRequestStatus
from lp.oci.interfaces.ocipushrule import IOCIPushRuleSet
from lp.oci.interfaces.ocirecipe import (
    OCI_RECIPE_ALLOW_CREATE,
    OCI_RECIPE_BUILD_DISTRIBUTION,
    CannotModifyOCIRecipeProcessor,
    DuplicateOCIRecipeName,
    IOCIRecipe,
    IOCIRecipeBuildRequest,
    IOCIRecipeSet,
    NoSourceForOCIRecipe,
    NoSuchOCIRecipe,
    OCIRecipeBranchHasInvalidFormat,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeFeatureDisabled,
    OCIRecipeNotOwner,
    OCIRecipePrivacyMismatch,
    UsingDistributionCredentials,
)
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.interfaces.ocirecipejob import IOCIRecipeRequestBuildsJobSource
from lp.oci.interfaces.ociregistrycredentials import IOCIRegistryCredentialsSet
from lp.oci.model.ocipushrule import OCIDistributionPushRule, OCIPushRule
from lp.oci.model.ocirecipebuild import OCIRecipeBuild
from lp.oci.model.ocirecipejob import OCIRecipeJob
from lp.oci.model.ocirecipesubscription import OCIRecipeSubscription
from lp.registry.errors import PrivatePersonLinkageError
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactGrantSource,
    IAccessArtifactSource,
)
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.ociproject import IOCIProject
from lp.registry.interfaces.person import (
    IPerson,
    IPersonSet,
    validate_public_person,
)
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.model.accesspolicy import (
    AccessPolicyGrant,
    reconcile_access_for_artifacts,
)
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.person import Person
from lp.registry.model.series import ACTIVE_STATUSES
from lp.registry.model.teammembership import TeamParticipation
from lp.services.database.bulk import load_related
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import (
    Array,
    ArrayAgg,
    ArrayIntersects,
    Greatest,
    NullsLast,
)
from lp.services.features import getFeatureFlag
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import Job
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.model import WebhookTargetMixin
from lp.soyuz.interfaces.binarypackagebuild import BuildSetStatus
from lp.soyuz.model.distroarchseries import DistroArchSeries


def oci_recipe_modified(recipe, event):
    """Update the date_last_modified property when an OCIRecipe is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on OCI recipes.
    """
    removeSecurityProxy(recipe).date_last_modified = UTC_NOW


@implementer(IOCIRecipe)
class OCIRecipe(StormBase, WebhookTargetMixin):
    __storm_table__ = "OCIRecipe"

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
                raise OCIRecipePrivacyMismatch(
                    "A public OCI recipe cannot have a private owner."
                )
        return value

    owner_id = Int(name="owner", allow_none=False, validator=_validate_owner)
    owner = Reference(owner_id, "Person.id")

    def _valid_information_type(self, attr, value):
        if value not in PUBLIC_INFORMATION_TYPES:
            return value
        # If the OCI recipe is public, it cannot be associated with private
        # repo or owner.
        if self.git_ref is not None and self.git_ref.private:
            raise OCIRecipePrivacyMismatch
        if self.owner is not None and self.owner.private:
            raise OCIRecipePrivacyMismatch
        return value

    _information_type = DBEnum(
        enum=InformationType,
        default=InformationType.PUBLIC,
        name="information_type",
        validator=_valid_information_type,
    )

    oci_project_id = Int(name="oci_project", allow_none=False)
    oci_project = Reference(oci_project_id, "OCIProject.id")

    name = Unicode(name="name", allow_none=False)
    description = Unicode(name="description", allow_none=True)

    # OCIRecipe.official shouldn't be set directly. Instead, call
    # oci_project.setOfficialRecipe method.
    _official = Bool(name="official", default=False)

    def _validate_git_repository(self, attr, value):
        if not self.private and value is not None:
            if IStore(GitRepository).get(GitRepository, value).private:
                raise OCIRecipePrivacyMismatch(
                    "A public OCI recipe cannot have a private repository."
                )
        return value

    git_repository_id = Int(
        name="git_repository",
        allow_none=True,
        validator=_validate_git_repository,
    )
    git_repository = Reference(git_repository_id, "GitRepository.id")
    git_path = Unicode(name="git_path", allow_none=True)
    build_file = Unicode(name="build_file", allow_none=False)
    build_path = Unicode(name="build_path", allow_none=False)
    _build_args = JSON(name="build_args", allow_none=True)

    require_virtualized = Bool(
        name="require_virtualized", default=True, allow_none=False
    )

    allow_internet = Bool(name="allow_internet", allow_none=False)

    build_daily = Bool(name="build_daily", default=False)

    _image_name = Unicode(name="image_name", allow_none=True)

    def __init__(
        self,
        name,
        registrant,
        owner,
        oci_project,
        git_ref,
        description=None,
        official=False,
        require_virtualized=True,
        build_file=None,
        build_daily=False,
        date_created=DEFAULT,
        allow_internet=True,
        build_args=None,
        build_path=None,
        image_name=None,
        information_type=InformationType.PUBLIC,
    ):
        if not getFeatureFlag(OCI_RECIPE_ALLOW_CREATE):
            raise OCIRecipeFeatureDisabled()
        super().__init__()
        self._information_type = information_type
        self.oci_project = oci_project
        self.name = name
        self.registrant = registrant
        self.owner = owner
        self.description = description
        self.build_file = build_file
        self._official = official
        self.require_virtualized = require_virtualized
        self.build_daily = build_daily
        self.date_created = date_created
        self.date_last_modified = date_created
        self.git_ref = git_ref
        self.allow_internet = allow_internet
        self.build_args = build_args or {}
        self.build_path = build_path
        self.image_name = image_name

    def __repr__(self):
        return "<OCIRecipe ~%s/%s/+oci/%s/+recipe/%s>" % (
            self.owner.name,
            self.oci_project.pillar.name,
            self.oci_project.name,
            self.name,
        )

    @property
    def information_type(self):
        if self._information_type is None:
            return InformationType.PUBLIC
        return self._information_type

    @information_type.setter
    def information_type(self, information_type):
        if information_type == self._information_type:
            return
        self._information_type = information_type
        self._reconcileAccess()

    @property
    def private(self):
        return self.information_type not in PUBLIC_INFORMATION_TYPES

    @property
    def pillar(self):
        return self.oci_project.pillar

    @property
    def valid_webhook_event_types(self):
        return ["oci-recipe:build:0.1"]

    @property
    def official(self):
        """See `IOCIProject.setOfficialRecipe` method."""
        return self._official

    @property
    def is_valid_branch_format(self):
        return validate_oci_branch_name(self.git_ref.path)

    @property
    def build_args(self):
        return self._build_args or {}

    @build_args.setter
    def build_args(self, value):
        assert value is None or isinstance(value, dict)
        self._build_args = {k: str(v) for k, v in (value or {}).items()}

    def _reconcileAccess(self):
        """Reconcile the OCI recipe's sharing information.

        Takes the privacy and pillar and makes the related AccessArtifact
        and AccessPolicyArtifacts match.
        """
        reconcile_access_for_artifacts(
            [self], self.information_type, [self.pillar]
        )

    def getAllowedInformationTypes(self, user):
        """See `IOCIRecipe`."""
        return self.oci_project.getAllowedInformationTypes(user)

    def visibleByUser(self, user):
        """See `IOCIRecipe`."""
        if self.information_type in PUBLIC_INFORMATION_TYPES:
            return True
        if user is None:
            return False
        store = IStore(self)
        return not store.find(
            OCIRecipe,
            OCIRecipe.id == self.id,
            get_ocirecipe_privacy_filter(user),
        ).is_empty()

    def getSubscription(self, person):
        """See `IOCIRecipe`."""
        if person is None:
            return None
        return (
            Store.of(self)
            .find(
                OCIRecipeSubscription,
                OCIRecipeSubscription.person == person,
                OCIRecipeSubscription.recipe == self,
            )
            .one()
        )

    def userCanBeSubscribed(self, person):
        """Checks if the given person can subscribe to this OCI recipe."""
        return not (
            self.private and person.is_team and person.anyone_can_join()
        )

    @property
    def subscriptions(self):
        return Store.of(self).find(
            OCIRecipeSubscription, OCIRecipeSubscription.recipe == self
        )

    @property
    def subscribers(self):
        return Store.of(self).find(
            Person,
            OCIRecipeSubscription.person_id == Person.id,
            OCIRecipeSubscription.recipe == self,
        )

    def subscribe(self, person, subscribed_by, ignore_permissions=False):
        """See `IOCIRecipe`."""
        if not self.userCanBeSubscribed(person):
            raise SubscriptionPrivacyViolation(
                "Open and delegated teams cannot be subscribed to private "
                "OCI recipes."
            )
        subscription = self.getSubscription(person)
        if subscription is None:
            subscription = OCIRecipeSubscription(
                person=person, recipe=self, subscribed_by=subscribed_by
            )
            Store.of(subscription).flush()
        service = getUtility(IService, "sharing")
        ocirecipes = service.getVisibleArtifacts(
            person, ocirecipes=[self], ignore_permissions=True
        )["ocirecipes"]
        if not ocirecipes:
            service.ensureAccessGrants(
                [person],
                subscribed_by,
                ocirecipes=[self],
                ignore_permissions=ignore_permissions,
            )

    def unsubscribe(self, person, unsubscribed_by, ignore_permissions=False):
        """See `IOCIRecipe`."""
        subscription = self.getSubscription(person)
        if subscription is None:
            return
        if (
            not ignore_permissions
            and not subscription.canBeUnsubscribedByUser(unsubscribed_by)
        ):
            raise UserCannotUnsubscribePerson(
                "%s does not have permission to unsubscribe %s."
                % (unsubscribed_by.displayname, person.displayname)
            )
        artifact = getUtility(IAccessArtifactSource).find([self])
        getUtility(IAccessArtifactGrantSource).revokeByArtifact(
            artifact, [person]
        )
        store = Store.of(subscription)
        store.remove(subscription)
        IStore(self).flush()

    def _deleteAccessGrants(self):
        """Delete access grants for this snap recipe prior to deleting it."""
        getUtility(IAccessArtifactSource).delete([self])

    def _deleteOCIRecipeSubscriptions(self):
        subscriptions = Store.of(self).find(
            OCIRecipeSubscription, OCIRecipeSubscription.recipe == self
        )
        subscriptions.remove()

    def destroySelf(self):
        """See `IOCIRecipe`."""
        # XXX twom 2019-11-26 This needs to expand as more build artifacts
        # are added
        store = IStore(OCIRecipe)
        self._deleteOCIRecipeSubscriptions()
        self._deleteAccessGrants()
        store.find(OCIRecipeArch, OCIRecipeArch.recipe == self).remove()
        buildqueue_records = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id == OCIRecipeBuild.build_farm_job_id,
            OCIRecipeBuild.recipe == self,
        )
        for buildqueue_record in buildqueue_records:
            buildqueue_record.destroySelf()
        build_farm_job_ids = list(
            store.find(
                OCIRecipeBuild.build_farm_job_id, OCIRecipeBuild.recipe == self
            )
        )

        store.execute(
            """
            DELETE FROM OCIFile
            USING OCIRecipeBuild
            WHERE
                OCIFile.build = OCIRecipeBuild.id AND
                OCIRecipeBuild.recipe = ?
            """,
            (self.id,),
        )
        store.execute(
            """
            DELETE FROM OCIRecipeBuildJob
            USING OCIRecipeBuild
            WHERE
                OCIRecipeBuildJob.build = OCIRecipeBuild.id AND
                OCIRecipeBuild.recipe = ?
            """,
            (self.id,),
        )

        affected_jobs = Select(
            [OCIRecipeJob.job_id],
            And(OCIRecipeJob.job == Job.id, OCIRecipeJob.recipe == self),
        )
        builds = store.find(OCIRecipeBuild, OCIRecipeBuild.recipe == self)
        builds.remove()
        store.find(Job, Job.id.is_in(affected_jobs)).remove()
        for push_rule in self.push_rules:
            push_rule.destroySelf()
        getUtility(IWebhookSet).delete(self.webhooks)
        store.remove(self)
        store.find(
            BuildFarmJob, BuildFarmJob.id.is_in(build_farm_job_ids)
        ).remove()

    @cachedproperty
    def _git_ref(self):
        return self.git_repository.getRefByPath(self.git_path)

    @property
    def git_ref(self):
        """See `IOCIRecipe`."""
        if self.git_repository_id is not None:
            return self._git_ref
        return None

    @git_ref.setter
    def git_ref(self, value):
        """See `IOCIRecipe`."""
        get_property_cache(self)._git_ref = value
        if value is not None:
            self.git_repository = value.repository
            self.git_path = value.path
        else:
            self.git_repository = None
            self.git_path = None

    @property
    def distribution(self):
        if self.oci_project.distribution:
            return self.oci_project.distribution
        # For OCI projects that are not based on distribution, we use the
        # default distribution set by the following feature flag (or
        # defaults to Ubuntu, if none is set).
        distro_name = getFeatureFlag(OCI_RECIPE_BUILD_DISTRIBUTION)
        if not distro_name:
            return getUtility(ILaunchpadCelebrities).ubuntu
        distro = getUtility(IDistributionSet).getByName(distro_name)
        if not distro:
            raise ValueError(
                "'%s' is not a valid value for feature flag '%s'"
                % (distro_name, OCI_RECIPE_BUILD_DISTRIBUTION)
            )
        return distro

    @property
    def distro_series(self):
        # For OCI builds we default to the series set by the feature flag.
        # If the feature flag is not set we default to the current series of
        # the recipe's distribution.
        oci_series = getFeatureFlag(
            "oci.build_series.%s" % self.distribution.name
        )
        if oci_series:
            return self.distribution.getSeries(oci_series)
        else:
            return self.distribution.currentseries

    @property
    def available_processors(self):
        """See `IOCIRecipe`."""
        clauses = [Processor.id == DistroArchSeries.processor_id]
        if self.distro_series is not None:
            enabled_archs_resultset = removeSecurityProxy(
                self.distro_series.enabled_architectures
            )
            clauses.append(
                DistroArchSeries.id.is_in(
                    enabled_archs_resultset.get_select_expr(
                        DistroArchSeries.id
                    )
                )
            )
        else:
            # We might not know the series if the OCI project's distribution
            # has no series at all, which can happen in tests.  Fall back to
            # just returning enabled architectures for any active series,
            # which is a bit of a hack but works.
            clauses.extend(
                [
                    DistroArchSeries.enabled,
                    DistroArchSeries.distroseriesID == DistroSeries.id,
                    DistroSeries.status.is_in(ACTIVE_STATUSES),
                ]
            )
        return Store.of(self).find(Processor, *clauses).config(distinct=True)

    def _getProcessors(self):
        return list(
            Store.of(self).find(
                Processor,
                Processor.id == OCIRecipeArch.processor_id,
                OCIRecipeArch.recipe == self,
            )
        )

    def setProcessors(self, processors, check_permissions=False, user=None):
        """See `IOCIRecipe`."""
        if check_permissions:
            can_modify = None
            if user is not None:
                roles = IPersonRoles(user)
                authz = lambda perm: getAdapter(self, IAuthorization, perm)
                if authz("launchpad.Admin").checkAuthenticated(roles):
                    can_modify = lambda proc: True
                elif authz("launchpad.Edit").checkAuthenticated(roles):
                    can_modify = lambda proc: not proc.restricted
            if can_modify is None:
                raise Unauthorized(
                    "Permission launchpad.Admin or launchpad.Edit required "
                    "on %s." % self
                )
        else:
            can_modify = lambda proc: True

        enablements = dict(
            Store.of(self).find(
                (Processor, OCIRecipeArch),
                Processor.id == OCIRecipeArch.processor_id,
                OCIRecipeArch.recipe == self,
            )
        )
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
                or not self.require_virtualized
            )
        )

    def _isArchitectureAllowed(self, das, pocket):
        return das.getChroot(
            pocket=pocket
        ) is not None and self._isBuildableArchitectureAllowed(das)

    def getAllowedArchitectures(self, distro_series=None):
        """See `IOCIRecipe`."""
        if distro_series is None:
            distro_series = self.distro_series
        return [
            das
            for das in distro_series.buildable_architectures
            if self._isBuildableArchitectureAllowed(das)
        ]

    def _checkRequestBuild(self, requester):
        if not requester.inTeam(self.owner):
            raise OCIRecipeNotOwner(
                "%s cannot create OCI image builds owned by %s."
                % (requester.display_name, self.owner.display_name)
            )

    def _hasPendingBuilds(self, distro_arch_series):
        """Checks if this OCIRecipe has pending builds for all processors
        in the given list of distro_arch_series.

        :param distro_arch_series: A list of DistroArchSeries
        :return: True if all processors have pending builds. False otherwise.
        """
        processors = {i.processor for i in distro_arch_series}
        pending = IStore(self).find(
            OCIRecipeBuild,
            OCIRecipeBuild.recipe == self.id,
            OCIRecipeBuild.processor_id.is_in([p.id for p in processors]),
            OCIRecipeBuild.status == BuildStatus.NEEDSBUILD,
        )
        pending_processors = {i.processor for i in pending}
        return len(pending_processors) == len(processors)

    def requestBuild(self, requester, distro_arch_series, build_request=None):
        self._checkRequestBuild(requester)
        if self._hasPendingBuilds([distro_arch_series]):
            raise OCIRecipeBuildAlreadyPending

        build = getUtility(IOCIRecipeBuildSet).new(
            requester, self, distro_arch_series, build_request=build_request
        )
        build.queueBuild()
        notify(ObjectCreatedEvent(build, user=requester))
        return build

    def getBuildRequest(self, job_id):
        return OCIRecipeBuildRequest(self, job_id)

    def requestBuildsFromJob(
        self, requester, build_request=None, architectures=None
    ):
        self._checkRequestBuild(requester)
        distro_arch_series = set(self.getAllowedArchitectures())

        builds = []
        for das in distro_arch_series:
            if (
                architectures is not None
                and das.architecturetag not in architectures
            ):
                continue
            try:
                builds.append(
                    self.requestBuild(
                        requester, das, build_request=build_request
                    )
                )
            except OCIRecipeBuildAlreadyPending:
                pass

        # If we have distro_arch_series, but they all failed to due
        # to pending builds, we fail the job.
        if len(distro_arch_series) > 0 and len(builds) == 0:
            raise OCIRecipeBuildAlreadyPending

        return builds

    def requestBuilds(self, requester, architectures=None):
        self._checkRequestBuild(requester)
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            self, requester, architectures
        )
        return self.getBuildRequest(job.job_id)

    @property
    def pending_build_requests(self):
        util = getUtility(IOCIRecipeRequestBuildsJobSource)
        return util.findByOCIRecipe(
            self, statuses=(JobStatus.WAITING, JobStatus.RUNNING)
        )

    @property
    def push_rules(self):
        # if we're in a distribution that has credentials set at that level
        # create a push rule using those credentials
        if self.use_distribution_credentials:
            push_rule = OCIDistributionPushRule(
                self,
                self.oci_project.distribution.oci_registry_credentials,
                self.image_name,
            )
            return [push_rule]
        rules = IStore(self).find(OCIPushRule, OCIPushRule.recipe == self.id)
        return list(rules)

    @property
    def _pending_states(self):
        """All the build states we consider pending (non-final)."""
        return [
            BuildStatus.NEEDSBUILD,
            BuildStatus.BUILDING,
            BuildStatus.GATHERING,
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
            NullsLast(
                Desc(
                    Greatest(
                        OCIRecipeBuild.date_started,
                        OCIRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(OCIRecipeBuild.date_created),
            Desc(OCIRecipeBuild.id),
        )
        return self._getBuilds(None, order_by)

    @property
    def completed_builds(self):
        """See `IOCIRecipe`."""
        filter_term = Not(OCIRecipeBuild.status.is_in(self._pending_states))
        order_by = (
            NullsLast(
                Desc(
                    Greatest(
                        OCIRecipeBuild.date_started,
                        OCIRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(OCIRecipeBuild.id),
        )
        return self._getBuilds(filter_term, order_by)

    @property
    def completed_builds_without_build_request(self):
        """See `IOCIRecipe`."""
        filter_term = (
            Not(OCIRecipeBuild.status.is_in(self._pending_states)),
            OCIRecipeBuild.build_request_id == None,
        )
        order_by = (
            NullsLast(
                Desc(
                    Greatest(
                        OCIRecipeBuild.date_started,
                        OCIRecipeBuild.date_finished,
                    )
                )
            ),
            Desc(OCIRecipeBuild.id),
        )
        return self._getBuilds(filter_term, order_by)

    @property
    def pending_builds(self):
        """See `IOCIRecipe`."""
        filter_term = OCIRecipeBuild.status.is_in(self._pending_states)
        # We want to order by date_created but this is the same as ordering
        # by id (since id increases monotonically) and is less expensive.
        order_by = Desc(OCIRecipeBuild.id)
        return self._getBuilds(filter_term, order_by)

    @property
    def can_upload_to_registry(self):
        return bool(self.push_rules)

    @property
    def use_distribution_credentials(self):
        distribution = self.oci_project.distribution
        # if we're not in a distribution, we can't use those credentials...
        if not distribution:
            return False
        official = self.official
        credentials = distribution.oci_registry_credentials
        return bool(distribution and official and credentials)

    @property
    def image_name(self):
        return self._image_name or self.name

    @image_name.setter
    def image_name(self, value):
        self._image_name = value

    def newPushRule(
        self,
        registrant,
        registry_url,
        image_name,
        credentials,
        credentials_owner=None,
    ):
        """See `IOCIRecipe`."""
        if credentials_owner is None:
            # Ideally this should probably be a required parameter, but
            # earlier versions of this method didn't allow passing the
            # credentials owner via the webservice API, so for compatibility
            # we give it a default.
            credentials_owner = self.owner
        if self.use_distribution_credentials:
            raise UsingDistributionCredentials()
        oci_credentials = getUtility(IOCIRegistryCredentialsSet).getOrCreate(
            registrant, credentials_owner, registry_url, credentials
        )
        push_rule = getUtility(IOCIPushRuleSet).new(
            self, oci_credentials, image_name
        )
        Store.of(push_rule).flush()
        return push_rule


class OCIRecipeArch(StormBase):
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
    def new(
        self,
        name,
        registrant,
        owner,
        oci_project,
        git_ref,
        build_file,
        description=None,
        official=False,
        require_virtualized=True,
        build_daily=False,
        processors=None,
        date_created=DEFAULT,
        allow_internet=True,
        build_args=None,
        build_path=None,
        image_name=None,
        information_type=InformationType.PUBLIC,
    ):
        """See `IOCIRecipeSet`."""
        if not registrant.inTeam(owner):
            if owner.is_team:
                raise OCIRecipeNotOwner(
                    "%s is not a member of %s."
                    % (registrant.displayname, owner.displayname)
                )
            else:
                raise OCIRecipeNotOwner(
                    "%s cannot create OCI images owned by %s."
                    % (registrant.displayname, owner.displayname)
                )

        if not (git_ref and build_file):
            raise NoSourceForOCIRecipe

        if self.exists(owner, oci_project, name):
            raise DuplicateOCIRecipeName

        if not validate_oci_branch_name(git_ref.name):
            raise OCIRecipeBranchHasInvalidFormat

        if build_path is None:
            build_path = "."

        store = IPrimaryStore(OCIRecipe)
        oci_recipe = OCIRecipe(
            name,
            registrant,
            owner,
            oci_project,
            git_ref,
            description,
            official,
            require_virtualized,
            build_file,
            build_daily,
            date_created,
            allow_internet,
            build_args,
            build_path,
            image_name,
            information_type,
        )
        store.add(oci_recipe)
        oci_recipe._reconcileAccess()

        # Automatically subscribe the owner to the OCI recipe.
        oci_recipe.subscribe(
            oci_recipe.owner, registrant, ignore_permissions=True
        )

        if processors is None:
            processors = [
                p
                for p in oci_recipe.available_processors
                if p.build_by_default
            ]
        oci_recipe.setProcessors(processors)

        return oci_recipe

    def _getByName(self, owner, oci_project, name):
        return (
            IStore(OCIRecipe)
            .find(
                OCIRecipe,
                OCIRecipe.owner == owner,
                OCIRecipe.name == name,
                OCIRecipe.oci_project == oci_project,
            )
            .one()
        )

    def exists(self, owner, oci_project, name):
        """See `IOCIRecipeSet`."""
        return self._getByName(owner, oci_project, name) is not None

    def findByIds(self, ocirecipe_ids, visible_by_user=None):
        """See `IOCIRecipeSet`."""
        clauses = [OCIRecipe.id.is_in(ocirecipe_ids)]
        if visible_by_user is not None:
            clauses.append(get_ocirecipe_privacy_filter(visible_by_user))
        return IStore(OCIRecipe).find(OCIRecipe, *clauses)

    def getByName(self, owner, oci_project, name):
        """See `IOCIRecipeSet`."""
        oci_recipe = self._getByName(owner, oci_project, name)
        if oci_recipe is None:
            raise NoSuchOCIRecipe(name)
        return oci_recipe

    def findByOwner(self, owner):
        """See `IOCIRecipeSet`."""
        return IStore(OCIRecipe).find(OCIRecipe, OCIRecipe.owner == owner)

    def findByOCIProject(self, oci_project, visible_by_user=None):
        """See `IOCIRecipeSet`."""
        return IStore(OCIRecipe).find(
            OCIRecipe,
            OCIRecipe.oci_project == oci_project,
            get_ocirecipe_privacy_filter(visible_by_user),
        )

    def findByContext(self, context, visible_by_user):
        if IPerson.providedBy(context):
            return self.findByOwner(context).find(
                get_ocirecipe_privacy_filter(visible_by_user)
            )
        elif IOCIProject.providedBy(context):
            return self.findByOCIProject(context, visible_by_user)
        else:
            raise NotImplementedError(
                "Unknown OCI recipe context: %s" % context
            )

    def findByGitRepository(self, repository, paths=None):
        """See `IOCIRecipeSet`."""
        clauses = [OCIRecipe.git_repository == repository]
        if paths is not None:
            clauses.append(OCIRecipe.git_path.is_in(paths))
        return IStore(OCIRecipe).find(OCIRecipe, *clauses)

    def detachFromGitRepository(self, repository):
        """See `IOCIRecipeSet`."""
        self.findByGitRepository(repository).set(
            git_repository_id=None, git_path=None, date_last_modified=UTC_NOW
        )

    def preloadDataForOCIRecipes(self, recipes, user=None):
        """See `IOCIRecipeSet`."""
        recipes = [removeSecurityProxy(recipe) for recipe in recipes]

        person_ids = set()
        for recipe in recipes:
            person_ids.add(recipe.registrant_id)
            person_ids.add(recipe.owner_id)

        list(
            getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                person_ids, need_validity=True
            )
        )

        # Preload projects
        oci_projects = [recipe.oci_project for recipe in recipes]
        load_related(Distribution, oci_projects, ["distribution_id"])

        # Preload repos
        repos = load_related(GitRepository, recipes, ["git_repository_id"])
        load_related(Person, repos, ["owner_id", "registrant_id"])
        GenericGitCollection.preloadDataForRepositories(repos)

        # Preload GitRefs.
        git_refs = GitRef.findByReposAndPaths(
            [(r.git_repository, r.git_path) for r in recipes]
        )
        for recipe in recipes:
            git_ref = git_refs.get((recipe.git_repository, recipe.git_path))
            if git_ref is not None:
                recipe.git_ref = git_ref

    def getStatusSummaryForBuilds(self, builds):
        # Create a small helper function to collect the builds for a given
        # list of build states:
        def collect_builds(*states):
            wanted = []
            for state in states:
                candidates = [
                    build for build in builds if build.status == state
                ]
                wanted.extend(candidates)
            return wanted

        failed = collect_builds(
            BuildStatus.FAILEDTOBUILD,
            BuildStatus.MANUALDEPWAIT,
            BuildStatus.CHROOTWAIT,
            BuildStatus.FAILEDTOUPLOAD,
        )
        needsbuild = collect_builds(BuildStatus.NEEDSBUILD)
        building = collect_builds(
            BuildStatus.BUILDING, BuildStatus.GATHERING, BuildStatus.UPLOADING
        )
        successful = collect_builds(BuildStatus.FULLYBUILT)
        cancelled = collect_builds(
            BuildStatus.CANCELLING, BuildStatus.CANCELLED
        )

        # Note: the BuildStatus DBItems are used here to summarize the
        # status of a set of builds:s
        if len(building) != 0:
            return {
                "status": BuildSetStatus.BUILDING,
                "builds": building,
            }
        # If there are no builds, this is a 'pending build request'
        # and needs building
        elif len(needsbuild) != 0 or len(builds) == 0:
            return {
                "status": BuildSetStatus.NEEDSBUILD,
                "builds": needsbuild,
            }
        elif len(failed) != 0 or len(cancelled) != 0:
            return {
                "status": BuildSetStatus.FAILEDTOBUILD,
                "builds": failed,
            }
        else:
            return {
                "status": BuildSetStatus.FULLYBUILT,
                "builds": successful,
            }


@implementer(IOCIRecipeBuildRequest)
class OCIRecipeBuildRequest:
    """See `IOCIRecipeBuildRequest`

    This is not directly backed by a database table; instead, it is a
    webservice-friendly view of an asynchronous build request.
    """

    def __init__(self, oci_recipe, id):
        self.recipe = oci_recipe
        self.id = id

    @cachedproperty
    def job(self):
        util = getUtility(IOCIRecipeRequestBuildsJobSource)
        return util.getByOCIRecipeAndID(self.recipe, self.id)

    @property
    def date_requested(self):
        return self.job.date_created

    @property
    def date_finished(self):
        return self.job.date_finished

    @property
    def uploaded_manifests(self):
        return self.job.uploaded_manifests

    def addUploadedManifest(self, build_id, manifest_info):
        self.job.addUploadedManifest(build_id, manifest_info)

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

    def __eq__(self, other):
        if not zope_isinstance(other, self.__class__):
            return False
        return self.id == other.id

    def __hash__(self):
        return hash((self.__class__, self.id))


def get_ocirecipe_privacy_filter(user):
    """Returns the filter for all OCI recipes that the given user has access
    to, including private OCI recipes where the user has proper permission.

    :param user: An IPerson, or a class attribute that references an IPerson
                 in the database.
    :return: A storm condition.
    """
    # XXX pappacena 2021-03-11: Once we do the migration to back fill
    # information_type, we should be able to change this.
    private_recipe = SQL(
        "COALESCE(information_type NOT IN ?, false)",
        params=[tuple(i.value for i in PUBLIC_INFORMATION_TYPES)],
    )
    if user is None:
        return private_recipe == False

    artifact_grant_query = Coalesce(
        ArrayIntersects(
            SQL("%s.access_grants" % OCIRecipe.__storm_table__),
            Select(
                ArrayAgg(TeamParticipation.teamID),
                tables=TeamParticipation,
                where=(TeamParticipation.person == user),
            ),
        ),
        False,
    )

    policy_grant_query = Coalesce(
        ArrayIntersects(
            Array(SQL("%s.access_policy" % OCIRecipe.__storm_table__)),
            Select(
                ArrayAgg(AccessPolicyGrant.policy_id),
                tables=(
                    AccessPolicyGrant,
                    Join(
                        TeamParticipation,
                        TeamParticipation.teamID
                        == AccessPolicyGrant.grantee_id,
                    ),
                ),
                where=(TeamParticipation.person == user),
            ),
        ),
        False,
    )

    admin_team_id = getUtility(ILaunchpadCelebrities).admin.id
    user_is_admin = Exists(
        Select(
            TeamParticipation.personID,
            tables=[TeamParticipation],
            where=And(
                TeamParticipation.teamID == admin_team_id,
                TeamParticipation.person == user,
            ),
        )
    )
    return Or(
        private_recipe == False,
        artifact_grant_query,
        policy_grant_query,
        user_is_admin,
    )
