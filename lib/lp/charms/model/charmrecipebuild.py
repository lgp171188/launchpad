# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe builds."""

__all__ = [
    "CharmFile",
    "CharmRecipeBuild",
]

from datetime import timedelta, timezone
from operator import attrgetter

import six
from storm.databases.postgres import JSON
from storm.expr import Column, Table, With
from storm.locals import (
    SQL,
    And,
    Bool,
    DateTime,
    Desc,
    Int,
    Reference,
    Select,
    Store,
    Unicode,
)
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildQueueStatus,
    BuildStatus,
)
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSource
from lp.buildmaster.interfaces.packagebuild import is_upload_log
from lp.buildmaster.model.buildfarmjob import SpecificBuildFarmJobSourceMixin
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.charms.interfaces.charmrecipebuild import (
    CannotScheduleStoreUpload,
    CharmRecipeBuildStoreUploadStatus,
    ICharmFile,
    ICharmRecipeBuild,
    ICharmRecipeBuildSet,
)
from lp.charms.interfaces.charmrecipebuildjob import ICharmhubUploadJobSource
from lp.charms.mail.charmrecipebuild import CharmRecipeBuildMailer
from lp.charms.model.charmrecipebuildjob import (
    CharmRecipeBuildJob,
    CharmRecipeBuildJobType,
)
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
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.webapp.snapshot import notify_modified
from lp.soyuz.model.distroarchseries import DistroArchSeries


@implementer(ICharmRecipeBuild)
class CharmRecipeBuild(PackageBuildMixin, StormBase):
    """See `ICharmRecipeBuild`."""

    __storm_table__ = "CharmRecipeBuild"

    job_type = BuildFarmJobType.CHARMRECIPEBUILD

    id = Int(name="id", primary=True)

    build_request_id = Int(name="build_request", allow_none=False)

    requester_id = Int(name="requester", allow_none=False)
    requester = Reference(requester_id, "Person.id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "CharmRecipe.id")

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
        """Construct a `CharmRecipeBuild`."""
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
        return "<CharmRecipeBuild ~%s/%s/+charm/%s/+build/%d>" % (
            self.recipe.owner.name,
            self.recipe.project.name,
            self.recipe.name,
            self.id,
        )

    @property
    def title(self):
        return "%s build of /~%s/%s/+charm/%s" % (
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
        """See `ICharmRecipeBuild`."""
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
        """See `ICharmRecipeBuild`."""
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
        # XXX cjwatson 2021-05-28: We'll probably need something like
        # CharmRecipe.relative_build_score at some point.
        return 2510

    def getMedianBuildDuration(self):
        """Return the median duration of our successful builds."""
        store = IStore(self)
        result = store.find(
            (CharmRecipeBuild.date_started, CharmRecipeBuild.date_finished),
            CharmRecipeBuild.recipe == self.recipe,
            CharmRecipeBuild.processor == self.processor,
            CharmRecipeBuild.status == BuildStatus.FULLYBUILT,
        )
        result.order_by(Desc(CharmRecipeBuild.date_finished))
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

    @property
    def store_upload_jobs(self):
        jobs = Store.of(self).find(
            CharmRecipeBuildJob,
            CharmRecipeBuildJob.build == self,
            CharmRecipeBuildJob.job_type
            == CharmRecipeBuildJobType.CHARMHUB_UPLOAD,
        )
        jobs.order_by(Desc(CharmRecipeBuildJob.job_id))

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
            return CharmRecipeBuildStoreUploadStatus.UNSCHEDULED
        elif job.job.status in (JobStatus.WAITING, JobStatus.RUNNING):
            return CharmRecipeBuildStoreUploadStatus.PENDING
        elif job.job.status == JobStatus.COMPLETED:
            return CharmRecipeBuildStoreUploadStatus.UPLOADED
        else:
            if job.store_revision:
                return CharmRecipeBuildStoreUploadStatus.FAILEDTORELEASE
            else:
                return CharmRecipeBuildStoreUploadStatus.FAILEDTOUPLOAD

    @property
    def store_upload_revision(self):
        job = self.last_store_upload_job
        return job and job.store_revision

    @property
    def store_upload_error_message(self):
        job = self.last_store_upload_job
        return job and job.error_message

    def scheduleStoreUpload(self):
        """See `ICharmRecipeBuild`."""
        if not self.recipe.can_upload_to_store:
            raise CannotScheduleStoreUpload(
                "Cannot upload this charm to Charmhub because it is not "
                "properly configured."
            )
        if not self.was_built or self.getFiles().is_empty():
            raise CannotScheduleStoreUpload(
                "Cannot upload this charm because it has no files."
            )
        if (
            self.store_upload_status
            == CharmRecipeBuildStoreUploadStatus.PENDING
        ):
            raise CannotScheduleStoreUpload(
                "An upload of this charm is already in progress."
            )
        elif (
            self.store_upload_status
            == CharmRecipeBuildStoreUploadStatus.UPLOADED
        ):
            raise CannotScheduleStoreUpload(
                "Cannot upload this charm because it has already been "
                "uploaded."
            )
        getUtility(ICharmhubUploadJobSource).create(self)

    def getFiles(self):
        """See `ICharmRecipeBuild`."""
        result = Store.of(self).find(
            (CharmFile, LibraryFileAlias, LibraryFileContent),
            CharmFile.build == self.id,
            LibraryFileAlias.id == CharmFile.library_file_id,
            LibraryFileContent.id == LibraryFileAlias.contentID,
        )
        return result.order_by([LibraryFileAlias.filename, CharmFile.id])

    def getFileByName(self, filename):
        """See `ICharmRecipeBuild`."""
        if filename.endswith(".txt.gz"):
            file_object = self.log
        elif is_upload_log(filename):
            file_object = self.upload_log
        else:
            file_object = (
                Store.of(self)
                .find(
                    LibraryFileAlias,
                    CharmFile.build == self.id,
                    LibraryFileAlias.id == CharmFile.library_file_id,
                    LibraryFileAlias.filename == filename,
                )
                .one()
            )

        if file_object is not None and file_object.filename == filename:
            return file_object

        raise NotFoundError(filename)

    def getFileUrls(self):
        """See `ICharmRecipeBuild`."""
        return [
            ProxiedLibraryFileAlias(lfa, self).http_url
            for _, lfa, _ in self.getFiles()
        ]

    def addFile(self, lfa):
        """See `ICharmRecipeBuild`."""
        charm_file = CharmFile(build=self, library_file=lfa)
        IPrimaryStore(CharmFile).add(charm_file)
        return charm_file

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
        mailer = CharmRecipeBuildMailer.forStatus(self)
        mailer.sendAll()


@implementer(ICharmRecipeBuildSet)
class CharmRecipeBuildSet(SpecificBuildFarmJobSourceMixin):
    """See `ICharmRecipeBuildSet`."""

    def new(
        self,
        build_request,
        recipe,
        distro_arch_series,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
    ):
        """See `ICharmRecipeBuildSet`."""
        store = IPrimaryStore(CharmRecipeBuild)
        build_farm_job = getUtility(IBuildFarmJobSource).new(
            CharmRecipeBuild.job_type, BuildStatus.NEEDSBUILD, date_created
        )
        virtualized = (
            not distro_arch_series.processor.supports_nonvirtualized
            or recipe.require_virtualized
        )
        build = CharmRecipeBuild(
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
        store = IPrimaryStore(CharmRecipeBuild)
        return store.get(CharmRecipeBuild, build_id)

    def getByBuildFarmJob(self, build_farm_job):
        """See `ISpecificBuildFarmJobSource`."""
        return (
            Store.of(build_farm_job)
            .find(CharmRecipeBuild, build_farm_job_id=build_farm_job.id)
            .one()
        )

    def preloadBuildsData(self, builds):
        # Circular import.
        from lp.charms.model.charmrecipe import CharmRecipe

        load_related(Person, builds, ["requester_id"])
        lfas = load_related(LibraryFileAlias, builds, ["log_id"])
        load_related(LibraryFileContent, lfas, ["contentID"])
        distroarchserieses = load_related(
            DistroArchSeries, builds, ["distro_arch_series_id"]
        )
        distroserieses = load_related(
            DistroSeries, distroarchserieses, ["distroseries_id"]
        )
        load_related(Distribution, distroserieses, ["distributionID"])
        recipes = load_related(CharmRecipe, builds, ["recipe_id"])
        getUtility(ICharmRecipeSet).preloadDataForRecipes(recipes)
        build_ids = set(map(attrgetter("id"), builds))
        latest_jobs_cte = With(
            "LatestJobs",
            Select(
                (
                    CharmRecipeBuildJob.job_id,
                    SQL(
                        "rank() OVER "
                        "(PARTITION BY build ORDER BY job DESC) AS rank"
                    ),
                ),
                tables=CharmRecipeBuildJob,
                where=And(
                    CharmRecipeBuildJob.build_id.is_in(build_ids),
                    CharmRecipeBuildJob.job_type
                    == CharmRecipeBuildJobType.CHARMHUB_UPLOAD,
                ),
            ),
        )
        LatestJobs = Table("LatestJobs")
        crbjs = list(
            IStore(CharmRecipeBuildJob)
            .with_(latest_jobs_cte)
            .using(CharmRecipeBuildJob, LatestJobs)
            .find(
                CharmRecipeBuildJob,
                CharmRecipeBuildJob.job_id == Column("job", LatestJobs),
                Column("rank", LatestJobs) == 1,
            )
        )
        crbj_map = {}
        for crbj in crbjs:
            crbj_map[crbj.build] = crbj.makeDerived()
        for build in builds:
            get_property_cache(build).last_store_upload_job = crbj_map.get(
                build
            )
        load_related(Job, crbjs, ["job_id"])

    def getByBuildFarmJobs(self, build_farm_jobs):
        """See `ISpecificBuildFarmJobSource`."""
        if len(build_farm_jobs) == 0:
            return EmptyResultSet()
        rows = Store.of(build_farm_jobs[0]).find(
            CharmRecipeBuild,
            CharmRecipeBuild.build_farm_job_id.is_in(
                bfj.id for bfj in build_farm_jobs
            ),
        )
        return DecoratedResultSet(rows, pre_iter_hook=self.preloadBuildsData)


@implementer(ICharmFile)
class CharmFile(StormBase):
    """See `ICharmFile`."""

    __storm_table__ = "CharmFile"

    id = Int(name="id", primary=True)

    build_id = Int(name="build", allow_none=False)
    build = Reference(build_id, "CharmRecipeBuild.id")

    library_file_id = Int(name="library_file", allow_none=False)
    library_file = Reference(library_file_id, "LibraryFileAlias.id")

    def __init__(self, build, library_file):
        """Construct a `CharmFile`."""
        super().__init__()
        self.build = build
        self.library_file = library_file
