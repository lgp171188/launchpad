# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe builds."""

__all__ = [
    "CraftFile",
    "CraftRecipeBuild",
    "ICraftRecipeBuildStatusChangedEvent",
]

from datetime import timedelta, timezone

import six
from storm.databases.postgres import JSON
from storm.locals import Bool, DateTime, Desc, Int, Reference, Store, Unicode
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer
from zope.interface.interfaces import ObjectEvent
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.buildmaster.builderproxy import BUILD_METADATA_FILENAME_FORMAT
from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildQueueStatus,
    BuildStatus,
)
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSource
from lp.buildmaster.model.buildfarmjob import SpecificBuildFarmJobSourceMixin
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.code.interfaces.gitrepository import IGitRepository
from lp.crafts.interfaces.craftrecipebuild import (
    ICraftFile,
    ICraftRecipeBuild,
    ICraftRecipeBuildSet,
    ICraftRecipeBuildStatusChangedEvent,
)
from lp.crafts.mail.craftrecipebuild import CraftRecipeBuildMailer
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.person import Person
from lp.services.config import config
from lp.services.database.bulk import load_related
from lp.services.database.constants import DEFAULT
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.librarian.browser import ProxiedLibraryFileAlias
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.macaroons.interfaces import (
    NO_USER,
    BadMacaroonContext,
    IMacaroonIssuer,
)
from lp.services.macaroons.model import MacaroonIssuerBase
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.webapp.snapshot import notify_modified
from lp.soyuz.model.distroarchseries import DistroArchSeries


@implementer(ICraftRecipeBuildStatusChangedEvent)
class CraftRecipeBuildStatusChangedEvent(ObjectEvent):
    """See `ICraftRecipeBuildStatusChangedEvent`."""


@implementer(ICraftRecipeBuild)
class CraftRecipeBuild(PackageBuildMixin, StormBase):
    """See `ICraftRecipeBuild`."""

    __storm_table__ = "CraftRecipeBuild"

    job_type = BuildFarmJobType.CRAFTRECIPEBUILD

    id = Int(name="id", primary=True)

    build_request_id = Int(name="build_request", allow_none=False)

    requester_id = Int(name="requester", allow_none=False)
    requester = Reference(requester_id, "Person.id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "CraftRecipe.id")

    distro_arch_series_id = Int(name="distro_arch_series", allow_none=False)
    distro_arch_series = Reference(
        distro_arch_series_id, "DistroArchSeries.id"
    )

    channels = JSON("channels", allow_none=True)

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")

    virtualized = Bool(name="virtualized", allow_none=False)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )
    date_started = DateTime(
        name="date_started", tzinfo=timezone.utc, allow_none=True
    )
    date_finished = DateTime(
        name="date_finished", tzinfo=timezone.utc, allow_none=True
    )
    date_first_dispatched = DateTime(
        name="date_first_dispatched", tzinfo=timezone.utc, allow_none=True
    )

    builder_id = Int(name="builder", allow_none=True)
    builder = Reference(builder_id, "Builder.id")

    status = DBEnum(name="status", enum=BuildStatus, allow_none=False)

    log_id = Int(name="log", allow_none=True)
    log = Reference(log_id, "LibraryFileAlias.id")

    upload_log_id = Int(name="upload_log", allow_none=True)
    upload_log = Reference(upload_log_id, "LibraryFileAlias.id")

    dependencies = Unicode(name="dependencies", allow_none=True)

    failure_count = Int(name="failure_count", allow_none=False)

    build_farm_job_id = Int(name="build_farm_job", allow_none=False)
    build_farm_job = Reference(build_farm_job_id, "BuildFarmJob.id")

    revision_id = Unicode(name="revision_id", allow_none=True)

    store_upload_metadata = JSON("store_upload_json_data", allow_none=True)

    def __init__(
        self,
        build_farm_job,
        build_request,
        recipe,
        distro_arch_series,
        processor,
        virtualized,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
    ):
        """Construct a `CraftRecipeBuild`."""
        requester = build_request.requester
        super().__init__()
        self.build_farm_job = build_farm_job
        self.build_request_id = build_request.id
        self.requester = requester
        self.recipe = recipe
        self.distro_arch_series = distro_arch_series
        self.processor = processor
        self.virtualized = virtualized
        self.channels = channels
        self.store_upload_metadata = store_upload_metadata
        self.date_created = date_created
        self.status = BuildStatus.NEEDSBUILD

    @property
    def build_request(self):
        return self.recipe.getBuildRequest(self.build_request_id)

    @property
    def is_private(self):
        """See `IBuildFarmJob`."""
        return self.recipe.private or self.recipe.owner.private

    def __repr__(self):
        return "<CraftRecipeBuild ~%s/%s/+craft/%s/+build/%d>" % (
            self.recipe.owner.name,
            self.recipe.project.name,
            self.recipe.name,
            self.id,
        )

    @property
    def title(self):
        return "%s build of /~%s/%s/+craft/%s" % (
            self.distro_arch_series.architecturetag,
            self.recipe.owner.name,
            self.recipe.project.name,
            self.recipe.name,
        )

    @property
    def distribution(self):
        """See `IPackageBuild`."""
        return self.distro_arch_series.distroseries.distribution

    @property
    def distro_series(self):
        """See `IPackageBuild`."""
        return self.distro_arch_series.distroseries

    @property
    def arch_tag(self):
        """See `ICraftRecipeBuild`."""
        return self.distro_arch_series.architecturetag

    @property
    def archive(self):
        """See `IPackageBuild`."""
        return self.distribution.main_archive

    @property
    def pocket(self):
        """See `IPackageBuild`."""
        return PackagePublishingPocket.UPDATES

    @property
    def score(self):
        """See `ICraftRecipeBuild`."""
        if self.buildqueue_record is None:
            return None
        else:
            return self.buildqueue_record.lastscore

    @property
    def can_be_retried(self):
        """See `IBuildFarmJob`."""
        # First check that the behaviour would accept the build if it
        # succeeded.
        if self.distro_series.status == SeriesStatus.OBSOLETE:
            return False
        return super().can_be_retried

    def calculateScore(self):
        """See `IBuildFarmJob`."""
        # XXX ruinedyourlife 2024-09-25: We'll probably need something like
        # CraftRecipe.relative_build_score at some point.
        return 2510

    def getMedianBuildDuration(self):
        """Return the median duration of our successful builds."""
        store = IStore(self)
        result = store.find(
            (CraftRecipeBuild.date_started, CraftRecipeBuild.date_finished),
            CraftRecipeBuild.recipe == self.recipe,
            CraftRecipeBuild.processor == self.processor,
            CraftRecipeBuild.status == BuildStatus.FULLYBUILT,
        )
        result.order_by(Desc(CraftRecipeBuild.date_finished))
        durations = [row[1] - row[0] for row in result[:9]]
        if len(durations) == 0:
            return None
        durations.sort()
        return durations[len(durations) // 2]

    def estimateDuration(self):
        """See `IBuildFarmJob`."""
        median = self.getMedianBuildDuration()
        if median is not None:
            return median
        return timedelta(minutes=10)

    @cachedproperty
    def eta(self):
        """The datetime when the build job is estimated to complete.

        This is the BuildQueue.estimated_duration plus the
        Job.date_started or BuildQueue.getEstimatedJobStartTime.
        """
        if self.buildqueue_record is None:
            return None
        queue_record = self.buildqueue_record
        if queue_record.status == BuildQueueStatus.WAITING:
            start_time = queue_record.getEstimatedJobStartTime()
        else:
            start_time = queue_record.date_started
        if start_time is None:
            return None
        duration = queue_record.estimated_duration
        return start_time + duration

    @property
    def estimate(self):
        """If true, the date value is an estimate."""
        if self.date_finished is not None:
            return False
        return self.eta is not None

    @property
    def date(self):
        """The date when the build completed or is estimated to complete."""
        if self.estimate:
            return self.eta
        return self.date_finished

    def getFiles(self):
        """See `ICraftRecipeBuild`."""
        result = Store.of(self).find(
            (CraftFile, LibraryFileAlias, LibraryFileContent),
            CraftFile.build == self.id,
            LibraryFileAlias.id == CraftFile.library_file_id,
            LibraryFileContent.id == LibraryFileAlias.content_id,
        )
        return result.order_by([LibraryFileAlias.filename, CraftFile.id])

    def getFileByName(self, filename):
        """See `ICraftRecipeBuild`."""
        if filename.endswith(".txt.gz"):
            file_object = self.log
        elif filename.endswith("_log.txt"):
            file_object = self.upload_log
        else:
            file_object = (
                Store.of(self)
                .find(
                    LibraryFileAlias,
                    CraftFile.build == self.id,
                    LibraryFileAlias.id == CraftFile.library_file_id,
                    LibraryFileAlias.filename == filename,
                )
                .one()
            )

        if file_object is not None and file_object.filename == filename:
            return file_object

        raise NotFoundError(filename)

    def addFile(self, lfa):
        """See `ICraftRecipeBuild`."""
        craft_file = CraftFile(build=self, library_file=lfa)
        IPrimaryStore(CraftFile).add(craft_file)
        return craft_file

    def verifySuccessfulUpload(self):
        """See `IPackageBuild`."""
        return not self.getFiles().is_empty()

    def updateStatus(
        self,
        status,
        builder=None,
        worker_status=None,
        date_started=None,
        date_finished=None,
        force_invalid_transition=False,
    ):
        """See `IBuildFarmJob`."""
        edited_fields = set()
        with notify_modified(
            self, edited_fields, snapshot_names=("status", "revision_id")
        ) as previous_obj:
            super().updateStatus(
                status,
                builder=builder,
                worker_status=worker_status,
                date_started=date_started,
                date_finished=date_finished,
                force_invalid_transition=force_invalid_transition,
            )
            if self.status != previous_obj.status:
                edited_fields.add("status")
            if worker_status is not None:
                revision_id = worker_status.get("revision_id")
                if revision_id is not None:
                    self.revision_id = six.ensure_text(revision_id)
                if revision_id != previous_obj.revision_id:
                    edited_fields.add("revision_id")
        # notify_modified evaluates all attributes mentioned in the
        # interface, but we may then make changes that affect self.eta.
        del get_property_cache(self).eta

    def notify(self, extra_info=None):
        """See `IPackageBuild`."""
        if not config.builddmaster.send_build_notification:
            return
        if self.status == BuildStatus.FULLYBUILT:
            return
        mailer = CraftRecipeBuildMailer.forStatus(self)
        mailer.sendAll()

    def getFileUrls(self):
        """See `ICraftRecipeBuild`."""
        return [
            ProxiedLibraryFileAlias(lfa, self).http_url
            for _, lfa, _ in self.getFiles()
        ]

    @property
    def build_metadata_url(self):
        metadata_filename = BUILD_METADATA_FILENAME_FORMAT.format(
            build_id=self.build_cookie
        )
        for url in self.getFileUrls():
            if url.endswith(metadata_filename):
                return url
        return None


@implementer(ICraftRecipeBuildSet)
class CraftRecipeBuildSet(SpecificBuildFarmJobSourceMixin):
    """See `ICraftRecipeBuildSet`."""

    def new(
        self,
        build_request,
        recipe,
        distro_arch_series,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
    ):
        """See `ICraftRecipeBuildSet`."""
        store = IPrimaryStore(CraftRecipeBuild)
        build_farm_job = getUtility(IBuildFarmJobSource).new(
            CraftRecipeBuild.job_type, BuildStatus.NEEDSBUILD, date_created
        )
        virtualized = (
            not distro_arch_series.processor.supports_nonvirtualized
            or recipe.require_virtualized
        )
        build = CraftRecipeBuild(
            build_farm_job,
            build_request,
            recipe,
            distro_arch_series,
            distro_arch_series.processor,
            virtualized,
            channels=channels,
            store_upload_metadata=store_upload_metadata,
            date_created=date_created,
        )
        store.add(build)
        return build

    def getByID(self, build_id):
        """See `ISpecificBuildFarmJobSource`."""
        store = IPrimaryStore(CraftRecipeBuild)
        return store.get(CraftRecipeBuild, build_id)

    def getByBuildFarmJob(self, build_farm_job):
        """See `ISpecificBuildFarmJobSource`."""
        return (
            Store.of(build_farm_job)
            .find(CraftRecipeBuild, build_farm_job_id=build_farm_job.id)
            .one()
        )

    def preloadBuildsData(self, builds):
        # Circular import.
        # from lp.crafts.model.craftrecipe import CraftRecipe

        load_related(Person, builds, ["requester_id"])
        lfas = load_related(LibraryFileAlias, builds, ["log_id"])
        load_related(LibraryFileContent, lfas, ["content_id"])
        distroarchserieses = load_related(
            DistroArchSeries, builds, ["distro_arch_series_id"]
        )
        distroserieses = load_related(
            DistroSeries, distroarchserieses, ["distroseries_id"]
        )
        load_related(Distribution, distroserieses, ["distribution_id"])
        # XXX ruinedyourlife 2024-09-25: we need to skip preloading until
        # function is able to handle rock recipes with external git
        # repositories, see https://warthogs.atlassian.net/browse/LP-1972
        # recipes = load_related(CraftRecipe, builds, ["recipe_id"])
        # getUtility(ICraftRecipeSet).preloadDataForRecipes(recipes)

    def getByBuildFarmJobs(self, build_farm_jobs):
        """See `ISpecificBuildFarmJobSource`."""
        if len(build_farm_jobs) == 0:
            return EmptyResultSet()
        rows = Store.of(build_farm_jobs[0]).find(
            CraftRecipeBuild,
            CraftRecipeBuild.build_farm_job_id.is_in(
                bfj.id for bfj in build_farm_jobs
            ),
        )
        return DecoratedResultSet(rows, pre_iter_hook=self.preloadBuildsData)


@implementer(IMacaroonIssuer)
class CraftRecipeBuildMacaroonIssuer(MacaroonIssuerBase):
    identifier = "craft-recipe-build"
    issuable_via_authserver = True

    def checkIssuingContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`.

        For issuing, the context is an `ICraftRecipeBuild`.
        """
        if not ICraftRecipeBuild.providedBy(context):
            raise BadMacaroonContext(context)
        if not removeSecurityProxy(context).is_private:
            raise BadMacaroonContext(
                context, "Refusing to issue macaroon for public build."
            )
        return removeSecurityProxy(context).id

    def checkVerificationContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`."""
        if not IGitRepository.providedBy(context):
            raise BadMacaroonContext(context)
        return context

    def verifyPrimaryCaveat(
        self, verified, caveat_value, context, user=None, **kwargs
    ):
        """See `MacaroonIssuerBase`.

        For verification, the context is an `IGitRepository`. We check that
        the repository is needed to build the `ICraftRecipeBuild` that is the
        context of the macaroon, and that the context build is currently
        building.
        """
        # Circular import.
        from lp.crafts.model.craftrecipe import CraftRecipe

        # CraftRecipeBuild builds only support free-floating macaroons for Git
        # authentication, not ones bound to a user.
        if user:
            return False
        verified.user = NO_USER

        if context is None:
            # We're only verifying that the macaroon could be valid for some
            # context.
            return True

        try:
            build_id = int(caveat_value)
        except ValueError:
            return False
        return (
            not IStore(CraftRecipeBuild)
            .find(
                CraftRecipeBuild,
                CraftRecipeBuild.id == build_id,
                CraftRecipeBuild.recipe_id == CraftRecipe.id,
                CraftRecipe.git_repository == context,
                CraftRecipeBuild.status == BuildStatus.BUILDING,
            )
            .is_empty()
        )


@implementer(ICraftFile)
class CraftFile(StormBase):
    """See `ICraftFile`."""

    __storm_table__ = "CraftFile"

    id = Int(name="id", primary=True)

    build_id = Int(name="build", allow_none=False)
    build = Reference(build_id, "CraftRecipeBuild.id")

    library_file_id = Int(name="library_file", allow_none=False)
    library_file = Reference(library_file_id, "LibraryFileAlias.id")

    def __init__(self, build, library_file):
        """Construct a `CraftFile`."""
        super().__init__()
        self.build = build
        self.library_file = library_file
