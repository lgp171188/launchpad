# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "SnapBuild",
    "SnapFile",
]

from datetime import timedelta, timezone
from operator import attrgetter

import six
from storm.expr import Column, Table, With
from storm.locals import (
    JSON,
    SQL,
    And,
    Bool,
    DateTime,
    Desc,
    Int,
    List,
    Or,
    Reference,
    Select,
    Store,
    Unicode,
)
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.event import notify
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
from lp.buildmaster.interfaces.packagebuild import is_upload_log
from lp.buildmaster.model.buildfarmjob import SpecificBuildFarmJobSourceMixin
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.code.interfaces.gitrepository import IGitRepository
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
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import Job
from lp.services.librarian.browser import ProxiedLibraryFileAlias
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.macaroons.interfaces import (
    NO_USER,
    BadMacaroonContext,
    IMacaroonIssuer,
)
from lp.services.macaroons.model import MacaroonIssuerBase
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.snappy.interfaces.snap import ISnapSet
from lp.snappy.interfaces.snapbuild import (
    CannotScheduleStoreUpload,
    ISnapBuild,
    ISnapBuildSet,
    ISnapBuildStatusChangedEvent,
    ISnapFile,
    SnapBuildStoreUploadStatus,
)
from lp.snappy.interfaces.snapbuildjob import ISnapStoreUploadJobSource
from lp.snappy.mail.snapbuild import SnapBuildMailer
from lp.snappy.model.snapbase import SnapBase
from lp.snappy.model.snapbuildjob import SnapBuildJob, SnapBuildJobType
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.model.archive import Archive
from lp.soyuz.model.archivedependency import ArchiveDependency
from lp.soyuz.model.distroarchseries import DistroArchSeries


@implementer(ISnapBuildStatusChangedEvent)
class SnapBuildStatusChangedEvent(ObjectEvent):
    """See `ISnapBuildStatusChangedEvent`."""


@implementer(ISnapFile)
class SnapFile(StormBase):
    """See `ISnap`."""

    __storm_table__ = "SnapFile"

    id = Int(name="id", primary=True)

    snapbuild_id = Int(name="snapbuild", allow_none=False)
    snapbuild = Reference(snapbuild_id, "SnapBuild.id")

    libraryfile_id = Int(name="libraryfile", allow_none=False)
    libraryfile = Reference(libraryfile_id, "LibraryFileAlias.id")

    def __init__(self, snapbuild, libraryfile):
        """Construct a `SnapFile`."""
        super().__init__()
        self.snapbuild = snapbuild
        self.libraryfile = libraryfile


@implementer(ISnapBuild)
class SnapBuild(PackageBuildMixin, StormBase):
    """See `ISnapBuild`."""

    __storm_table__ = "SnapBuild"

    job_type = BuildFarmJobType.SNAPBUILD

    id = Int(name="id", primary=True)

    build_farm_job_id = Int(name="build_farm_job", allow_none=False)
    build_farm_job = Reference(build_farm_job_id, "BuildFarmJob.id")

    build_request_id = Int(name="build_request", allow_none=True)

    requester_id = Int(name="requester", allow_none=False)
    requester = Reference(requester_id, "Person.id")

    snap_id = Int(name="snap", allow_none=False)
    snap = Reference(snap_id, "Snap.id")

    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, "Archive.id")

    distro_arch_series_id = Int(name="distro_arch_series", allow_none=False)
    distro_arch_series = Reference(
        distro_arch_series_id, "DistroArchSeries.id"
    )

    target_architectures = List("target_architectures", allow_none=True)

    pocket = DBEnum(enum=PackagePublishingPocket, allow_none=False)

    snap_base_id = Int(name="snap_base", allow_none=True)
    snap_base = Reference(snap_base_id, "SnapBase.id")
    channels = JSON("channels", allow_none=True)

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")
    virtualized = Bool(name="virtualized")

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )
    date_started = DateTime(name="date_started", tzinfo=timezone.utc)
    date_finished = DateTime(name="date_finished", tzinfo=timezone.utc)
    date_first_dispatched = DateTime(
        name="date_first_dispatched", tzinfo=timezone.utc
    )

    builder_id = Int(name="builder")
    builder = Reference(builder_id, "Builder.id")

    status = DBEnum(name="status", enum=BuildStatus, allow_none=False)

    revision_id = Unicode(name="revision_id")

    log_id = Int(name="log")
    log = Reference(log_id, "LibraryFileAlias.id")

    upload_log_id = Int(name="upload_log")
    upload_log = Reference(upload_log_id, "LibraryFileAlias.id")

    dependencies = Unicode(name="dependencies")

    failure_count = Int(name="failure_count", allow_none=False)

    store_upload_revision = Int(name="store_upload_revision", allow_none=True)

    store_upload_metadata = JSON("store_upload_json_data", allow_none=True)

    def __init__(
        self,
        build_farm_job,
        requester,
        snap,
        archive,
        distro_arch_series,
        pocket,
        snap_base,
        channels,
        processor,
        virtualized,
        date_created,
        store_upload_metadata=None,
        build_request=None,
        target_architectures=None,
    ):
        """Construct a `SnapBuild`."""
        super().__init__()
        self.build_farm_job = build_farm_job
        self.requester = requester
        self.snap = snap
        self.archive = archive
        self.distro_arch_series = distro_arch_series
        self.pocket = pocket
        self.snap_base = snap_base
        self.channels = channels
        self.processor = processor
        self.virtualized = virtualized
        self.date_created = date_created
        self.store_upload_metadata = store_upload_metadata
        self.target_architectures = target_architectures
        if build_request is not None:
            self.build_request_id = build_request.id
        self.status = BuildStatus.NEEDSBUILD

    @property
    def build_request(self):
        """See `ISnapBuild`."""
        if self.build_request_id is not None:
            return self.snap.getBuildRequest(self.build_request_id)

    @property
    def is_private(self):
        """See `IBuildFarmJob`."""
        return (
            self.snap.private
            or self.snap.owner.private
            or self.archive.private
        )

    private = is_private

    def __repr__(self):
        return "<SnapBuild ~%s/+snap/%s/+build/%d>" % (
            self.snap.owner.name,
            self.snap.name,
            self.id,
        )

    @property
    def title(self):
        das = self.distro_arch_series
        snap_title = "%s snap package" % self.snap.name
        if (
            self.snap.store_name is not None
            and self.snap.store_name != self.snap.name
        ):
            snap_title += " (%s)" % self.snap.store_name
        return "%s build of %s in %s %s" % (
            das.architecturetag,
            snap_title,
            das.distroseries.distribution.name,
            das.distroseries.getSuite(self.pocket),
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
        """See `ISnapBuild`."""
        return self.distro_arch_series.architecturetag

    @property
    def current_component(self):
        component = self.archive.default_component
        if component is not None:
            return component
        else:
            # XXX cjwatson 2015-07-17: Hardcode to multiverse for the time
            # being.
            return getUtility(IComponentSet)["multiverse"]

    @property
    def score(self):
        """See `ISnapBuild`."""
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
        return 2510 + self.archive.relative_build_score

    def getMedianBuildDuration(self):
        """Return the median duration of our successful builds."""
        store = IStore(self)
        result = store.find(
            (SnapBuild.date_started, SnapBuild.date_finished),
            SnapBuild.snap == self.snap_id,
            SnapBuild.distro_arch_series == self.distro_arch_series_id,
            SnapBuild.status == BuildStatus.FULLYBUILT,
        )
        result.order_by(Desc(SnapBuild.date_finished))
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
        return timedelta(minutes=30)

    def getFiles(self):
        """See `ISnapBuild`."""
        result = Store.of(self).find(
            (SnapFile, LibraryFileAlias, LibraryFileContent),
            SnapFile.snapbuild == self.id,
            LibraryFileAlias.id == SnapFile.libraryfile_id,
            LibraryFileContent.id == LibraryFileAlias.content_id,
        )
        return result.order_by([LibraryFileAlias.filename, SnapFile.id])

    def getFileByName(self, filename):
        """See `ISnapBuild`."""
        if filename.endswith(".txt.gz"):
            file_object = self.log
        elif is_upload_log(filename):
            file_object = self.upload_log
        else:
            file_object = (
                Store.of(self)
                .find(
                    LibraryFileAlias,
                    SnapFile.snapbuild == self.id,
                    LibraryFileAlias.id == SnapFile.libraryfile_id,
                    LibraryFileAlias.filename == filename,
                )
                .one()
            )

        if file_object is not None and file_object.filename == filename:
            return file_object

        raise NotFoundError(filename)

    def addFile(self, lfa):
        """See `ISnapBuild`."""
        snapfile = SnapFile(snapbuild=self, libraryfile=lfa)
        IPrimaryStore(SnapFile).add(snapfile)
        return snapfile

    def verifySuccessfulUpload(self) -> bool:
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
        old_status = self.status
        super().updateStatus(
            status,
            builder=builder,
            worker_status=worker_status,
            date_started=date_started,
            date_finished=date_finished,
            force_invalid_transition=force_invalid_transition,
        )
        if worker_status is not None:
            revision_id = worker_status.get("revision_id")
            if revision_id is not None:
                self.revision_id = six.ensure_text(revision_id)
        if status != old_status:
            notify(SnapBuildStatusChangedEvent(self))

    def notify(self, extra_info=None):
        """See `IPackageBuild`."""
        if not config.builddmaster.send_build_notification:
            return
        if self.status == BuildStatus.FULLYBUILT:
            return
        mailer = SnapBuildMailer.forStatus(self)
        mailer.sendAll()

    def lfaUrl(self, lfa):
        """Return the URL for a LibraryFileAlias in this context."""
        if lfa is None:
            return None
        return ProxiedLibraryFileAlias(lfa, self).http_url

    @property
    def log_url(self):
        """See `IBuildFarmJob`."""
        return self.lfaUrl(self.log)

    @property
    def upload_log_url(self):
        """See `IPackageBuild`."""
        return self.lfaUrl(self.upload_log)

    def getFileUrls(self):
        return [self.lfaUrl(lfa) for _, lfa, _ in self.getFiles()]

    @property
    def build_metadata_url(self):
        metadata_filename = BUILD_METADATA_FILENAME_FORMAT.format(
            build_id=self.build_cookie
        )
        try:
            return self.lfaUrl(self.getFileByName(metadata_filename))
        except NotFoundError:
            return None

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

    @property
    def store_upload_jobs(self):
        jobs = Store.of(self).find(
            SnapBuildJob,
            SnapBuildJob.snapbuild == self,
            SnapBuildJob.job_type == SnapBuildJobType.STORE_UPLOAD,
        )
        jobs.order_by(Desc(SnapBuildJob.job_id))

        def preload_jobs(rows):
            load_related(Job, rows, ["job_id"])

        return DecoratedResultSet(
            jobs, lambda job: job.makeDerived(), pre_iter_hook=preload_jobs
        )

    @cachedproperty
    def last_store_upload_job(self):
        return self.store_upload_jobs.first()

    @property
    def store_upload_status(self):
        job = self.last_store_upload_job
        if job is None or job.job.status == JobStatus.SUSPENDED:
            return SnapBuildStoreUploadStatus.UNSCHEDULED
        elif job.job.status in (JobStatus.WAITING, JobStatus.RUNNING):
            return SnapBuildStoreUploadStatus.PENDING
        elif job.job.status == JobStatus.COMPLETED:
            return SnapBuildStoreUploadStatus.UPLOADED
        else:
            if job.store_url:
                return SnapBuildStoreUploadStatus.FAILEDTORELEASE
            else:
                return SnapBuildStoreUploadStatus.FAILEDTOUPLOAD

    @property
    def store_upload_url(self):
        job = self.last_store_upload_job
        return job and job.store_url

    @property
    def store_upload_error_message(self):
        job = self.last_store_upload_job
        return job and job.error_message

    @property
    def store_upload_error_messages(self):
        job = self.last_store_upload_job
        if job:
            if job.error_messages:
                return job.error_messages
            elif job.error_message:
                return [{"message": job.error_message}]
        return []

    def scheduleStoreUpload(self):
        """See `ISnapBuild`."""
        if not self.snap.can_upload_to_store:
            raise CannotScheduleStoreUpload(
                "Cannot upload this package to the store because it is not "
                "properly configured."
            )
        if not self.was_built or self.getFiles().is_empty():
            raise CannotScheduleStoreUpload(
                "Cannot upload this package because it has no files."
            )
        if self.store_upload_status == SnapBuildStoreUploadStatus.PENDING:
            raise CannotScheduleStoreUpload(
                "An upload of this package is already in progress."
            )
        elif self.store_upload_status == SnapBuildStoreUploadStatus.UPLOADED:
            raise CannotScheduleStoreUpload(
                "Cannot upload this package because it has already been "
                "uploaded."
            )
        getUtility(ISnapStoreUploadJobSource).create(self)


@implementer(ISnapBuildSet)
class SnapBuildSet(SpecificBuildFarmJobSourceMixin):
    def new(
        self,
        requester,
        snap,
        archive,
        distro_arch_series,
        pocket,
        snap_base=None,
        channels=None,
        date_created=DEFAULT,
        store_upload_metadata=None,
        build_request=None,
        target_architectures=None,
    ):
        """See `ISnapBuildSet`."""
        store = IPrimaryStore(SnapBuild)
        build_farm_job = getUtility(IBuildFarmJobSource).new(
            SnapBuild.job_type,
            BuildStatus.NEEDSBUILD,
            date_created,
            None,
            archive,
        )
        snapbuild = SnapBuild(
            build_farm_job,
            requester,
            snap,
            archive,
            distro_arch_series,
            pocket,
            snap_base,
            channels,
            distro_arch_series.processor,
            not distro_arch_series.processor.supports_nonvirtualized
            or snap.require_virtualized
            or archive.require_virtualized,
            date_created,
            store_upload_metadata=store_upload_metadata,
            build_request=build_request,
            target_architectures=target_architectures,
        )
        store.add(snapbuild)
        store.flush()
        return snapbuild

    def getByID(self, build_id):
        """See `ISpecificBuildFarmJobSource`."""
        store = IPrimaryStore(SnapBuild)
        return store.get(SnapBuild, build_id)

    def getByBuildFarmJob(self, build_farm_job):
        """See `ISpecificBuildFarmJobSource`."""
        return (
            Store.of(build_farm_job)
            .find(SnapBuild, build_farm_job_id=build_farm_job.id)
            .one()
        )

    def preloadBuildsData(self, builds):
        # Circular import.
        from lp.snappy.model.snap import Snap

        load_related(Person, builds, ["requester_id"])
        lfas = load_related(LibraryFileAlias, builds, ["log_id"])
        load_related(LibraryFileContent, lfas, ["content_id"])
        archives = load_related(Archive, builds, ["archive_id"])
        load_related(Person, archives, ["owner_id"])
        distroarchseries = load_related(
            DistroArchSeries, builds, ["distro_arch_series_id"]
        )
        distroseries = load_related(
            DistroSeries, distroarchseries, ["distroseries_id"]
        )
        load_related(Distribution, distroseries, ["distribution_id"])
        snaps = load_related(Snap, builds, ["snap_id"])
        getUtility(ISnapSet).preloadDataForSnaps(snaps)
        snapbuild_ids = set(map(attrgetter("id"), builds))
        latest_jobs_cte = With(
            "LatestJobs",
            Select(
                (
                    SnapBuildJob.job_id,
                    SQL(
                        "rank() OVER "
                        "(PARTITION BY snapbuild ORDER BY job DESC) AS rank"
                    ),
                ),
                tables=SnapBuildJob,
                where=And(
                    SnapBuildJob.snapbuild_id.is_in(snapbuild_ids),
                    SnapBuildJob.job_type == SnapBuildJobType.STORE_UPLOAD,
                ),
            ),
        )
        LatestJobs = Table("LatestJobs")
        sbjs = list(
            IStore(SnapBuildJob)
            .with_(latest_jobs_cte)
            .using(SnapBuildJob, LatestJobs)
            .find(
                SnapBuildJob,
                SnapBuildJob.job_id == Column("job", LatestJobs),
                Column("rank", LatestJobs) == 1,
            )
        )
        sbj_map = {}
        for sbj in sbjs:
            sbj_map[sbj.snapbuild] = sbj.makeDerived()
        for build in builds:
            get_property_cache(build).last_store_upload_job = sbj_map.get(
                build
            )
        load_related(Job, sbjs, ["job_id"])

    def getByBuildFarmJobs(self, build_farm_jobs):
        """See `ISpecificBuildFarmJobSource`."""
        if len(build_farm_jobs) == 0:
            return EmptyResultSet()
        rows = Store.of(build_farm_jobs[0]).find(
            SnapBuild,
            SnapBuild.build_farm_job_id.is_in(
                bfj.id for bfj in build_farm_jobs
            ),
        )
        return DecoratedResultSet(rows, pre_iter_hook=self.preloadBuildsData)


@implementer(IMacaroonIssuer)
class SnapBuildMacaroonIssuer(MacaroonIssuerBase):
    identifier = "snap-build"
    issuable_via_authserver = True

    def checkIssuingContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`.

        For issuing, the context is an `ISnapBuild`.
        """
        if not ISnapBuild.providedBy(context):
            raise BadMacaroonContext(context)
        # We allow issuing macaroons for public builds.  It's harmless, and
        # it allows using SnapBases that have archive dependencies on
        # private PPAs.
        return removeSecurityProxy(context).id

    def checkVerificationContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`."""
        if not IGitRepository.providedBy(context) and not IArchive.providedBy(
            context
        ):
            raise BadMacaroonContext(context)
        return context

    def verifyPrimaryCaveat(
        self, verified, caveat_value, context, user=None, **kwargs
    ):
        """See `MacaroonIssuerBase`.

        For verification, the context is an `IGitRepository` or an
        `IArchive`.  We check that the repository or archive is needed to
        build the `ISnapBuild` that is the context of the macaroon, and that
        the context build is currently building.
        """
        # Circular import.
        from lp.snappy.model.snap import Snap

        # Snap builds only support free-floating macaroons for Git
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
        clauses = [
            SnapBuild.id == build_id,
            SnapBuild.status == BuildStatus.BUILDING,
        ]
        if IGitRepository.providedBy(context):
            clauses.extend(
                [
                    SnapBuild.snap_id == Snap.id,
                    Snap.git_repository == context,
                ]
            )
        elif IArchive.providedBy(context):
            clauses.append(
                Or(
                    SnapBuild.archive == context,
                    SnapBuild.archive_id.is_in(
                        Select(
                            Archive.id,
                            where=And(
                                ArchiveDependency.archive == Archive.id,
                                ArchiveDependency.dependency == context,
                            ),
                        )
                    ),
                    SnapBuild.snap_base_id.is_in(
                        Select(
                            SnapBase.id,
                            where=And(
                                ArchiveDependency.snap_base == SnapBase.id,
                                ArchiveDependency.dependency == context,
                            ),
                        )
                    ),
                )
            )
        else:
            return False
        return not IStore(SnapBuild).find(SnapBuild, *clauses).is_empty()
