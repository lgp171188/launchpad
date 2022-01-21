# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""CI builds."""

__all__ = [
    "CIBuild",
    ]

from datetime import timedelta

import pytz
from storm.locals import (
    Bool,
    DateTime,
    Desc,
    Int,
    Reference,
    Store,
    Unicode,
    )
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer

from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildQueueStatus,
    BuildStatus,
    )
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSource
from lp.buildmaster.model.buildfarmjob import SpecificBuildFarmJobSourceMixin
from lp.buildmaster.model.packagebuild import PackageBuildMixin
from lp.code.interfaces.cibuild import (
    ICIBuild,
    ICIBuildSet,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.services.database.bulk import load_related
from lp.services.database.constants import DEFAULT
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase
from lp.services.librarian.browser import ProxiedLibraryFileAlias
from lp.services.librarian.model import (
    LibraryFileAlias,
    LibraryFileContent,
    )
from lp.services.propertycache import cachedproperty
from lp.soyuz.model.distroarchseries import DistroArchSeries


@implementer(ICIBuild)
class CIBuild(PackageBuildMixin, StormBase):
    """See `ICIBuild`."""

    __storm_table__ = "CIBuild"

    job_type = BuildFarmJobType.CIBUILD

    id = Int(name="id", primary=True)

    git_repository_id = Int(name="git_repository", allow_none=False)
    git_repository = Reference(git_repository_id, "GitRepository.id")

    commit_sha1 = Unicode(name="commit_sha1", allow_none=False)

    distro_arch_series_id = Int(name="distro_arch_series", allow_none=False)
    distro_arch_series = Reference(
        distro_arch_series_id, "DistroArchSeries.id")

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")

    virtualized = Bool(name="virtualized", allow_none=False)

    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)
    date_started = DateTime(
        name="date_started", tzinfo=pytz.UTC, allow_none=True)
    date_finished = DateTime(
        name="date_finished", tzinfo=pytz.UTC, allow_none=True)
    date_first_dispatched = DateTime(
        name="date_first_dispatched", tzinfo=pytz.UTC, allow_none=True)

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

    def __init__(self, build_farm_job, git_repository, commit_sha1,
                 distro_arch_series, processor, virtualized,
                 date_created=DEFAULT):
        """Construct a `CIBuild`."""
        super().__init__()
        self.build_farm_job = build_farm_job
        self.git_repository = git_repository
        self.commit_sha1 = commit_sha1
        self.distro_arch_series = distro_arch_series
        self.processor = processor
        self.virtualized = virtualized
        self.date_created = date_created
        self.status = BuildStatus.NEEDSBUILD

    @property
    def is_private(self):
        """See `IBuildFarmJob`."""
        return self.git_repository.private

    def __repr__(self):
        return "<CIBuild %s/+build/%s>" % (
            self.git_repository.unique_name, self.id)

    @property
    def title(self):
        """See `IBuildFarmJob`."""
        return "%s CI build of %s:%s" % (
            self.distro_arch_series.architecturetag,
            self.git_repository.unique_name, self.commit_sha1)

    @property
    def distribution(self):
        """See `IPackageBuild`."""
        return self.distro_arch_series.distroseries.distribution

    @property
    def distro_series(self):
        """See `IPackageBuild`."""
        return self.distro_arch_series.distroseries

    @property
    def pocket(self):
        """See `IPackageBuild`."""
        return PackagePublishingPocket.UPDATES

    @property
    def arch_tag(self):
        """See `ICIBuild`."""
        return self.distro_arch_series.architecturetag

    @property
    def archive(self):
        """See `IPackageBuild`."""
        return self.distribution.main_archive

    @property
    def score(self):
        """See `ICIBuild`."""
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
        # Low latency is especially useful for CI builds, so score these
        # above bulky things like live filesystem builds, but below
        # important things like builds of proposed Ubuntu stable updates.
        # See https://help.launchpad.net/Packaging/BuildScores.
        return 2600

    def getMedianBuildDuration(self):
        """Return the median duration of our recent successful builds."""
        store = IStore(self)
        result = store.find(
            (CIBuild.date_started, CIBuild.date_finished),
            CIBuild.git_repository == self.git_repository_id,
            CIBuild.distro_arch_series == self.distro_arch_series_id,
            CIBuild.status == BuildStatus.FULLYBUILT)
        result.order_by(Desc(CIBuild.date_finished))
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

    def verifySuccessfulUpload(self):
        """See `IPackageBuild`."""
        # We have no interesting checks to perform here.

    def notify(self, extra_info=None):
        """See `IPackageBuild`."""
        # We don't currently send any notifications.


@implementer(ICIBuildSet)
class CIBuildSet(SpecificBuildFarmJobSourceMixin):

    def new(self, git_repository, commit_sha1, distro_arch_series,
            date_created=DEFAULT):
        """See `ICIBuildSet`."""
        store = IMasterStore(CIBuild)
        build_farm_job = getUtility(IBuildFarmJobSource).new(
            CIBuild.job_type, BuildStatus.NEEDSBUILD, date_created)
        cibuild = CIBuild(
            build_farm_job, git_repository, commit_sha1, distro_arch_series,
            distro_arch_series.processor, virtualized=True,
            date_created=date_created)
        store.add(cibuild)
        store.flush()
        return cibuild

    def getByID(self, build_id):
        """See `ISpecificBuildFarmJobSource`."""
        store = IMasterStore(CIBuild)
        return store.get(CIBuild, build_id)

    def getByBuildFarmJob(self, build_farm_job):
        """See `ISpecificBuildFarmJobSource`."""
        return Store.of(build_farm_job).find(
            CIBuild, build_farm_job_id=build_farm_job.id).one()

    def preloadBuildsData(self, builds):
        lfas = load_related(LibraryFileAlias, builds, ["log_id"])
        load_related(LibraryFileContent, lfas, ["contentID"])
        distroarchseries = load_related(
            DistroArchSeries, builds, ["distro_arch_series_id"])
        distroseries = load_related(
            DistroSeries, distroarchseries, ["distroseriesID"])
        load_related(Distribution, distroseries, ["distributionID"])

    def getByBuildFarmJobs(self, build_farm_jobs):
        """See `ISpecificBuildFarmJobSource`."""
        if len(build_farm_jobs) == 0:
            return EmptyResultSet()
        rows = Store.of(build_farm_jobs[0]).find(
            CIBuild, CIBuild.build_farm_job_id.is_in(
                bfj.id for bfj in build_farm_jobs))
        return DecoratedResultSet(rows, pre_iter_hook=self.preloadBuildsData)

    def deleteByGitRepository(self, repository):
        """See `ICIBuildSet`."""
        IMasterStore(CIBuild).find(CIBuild, git_repository=repository).remove()
