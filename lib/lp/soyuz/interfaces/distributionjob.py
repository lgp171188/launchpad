# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    "DistributionJobType",
    "IDistributionJob",
    "IDistroSeriesDifferenceJob",
    "IDistroSeriesDifferenceJobSource",
    "IInitializeDistroSeriesJob",
    "IInitializeDistroSeriesJobSource",
    "InitializationCompleted",
    "InitializationPending",
]

from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    )
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Int,
    Object,
    )

from canonical.launchpad import _
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.services.job.interfaces.job import (
    IJob,
    IJobSource,
    IRunnableJob,
    )


class IDistributionJob(Interface):
    """A Job that initializes acts on a distribution."""

    id = Int(
        title=_('DB ID'), required=True, readonly=True,
        description=_("The tracking number for this job."))

    distribution = Object(
        title=_('The Distribution this job is about.'),
        schema=IDistribution, required=True)

    distroseries = Object(
        title=_('The DistroSeries this job is about.'),
        schema=IDistroSeries, required=False)

    job = Object(
        title=_('The common Job attributes'), schema=IJob, required=True)

    metadata = Attribute('A dict of data about the job.')

    def destroySelf():
        """Destroy this object."""


class DistributionJobType(DBEnumeratedType):

    INITIALIZE_SERIES = DBItem(1, """
        Initialize a Distro Series.

        This job initializes a given distro series, creating builds, and
        populating the archive from the parent distroseries.
        """)

    DISTROSERIESDIFFERENCE = DBItem(3, """
        Create, delete, or update a Distro Series Difference.

        Updates the status of a potential difference between a derived
        distribution release series and its parent series.
        """)


class InitializationPending(Exception):
    """The initialization of the distroseries has already been scheduled.

    :ivar job: The `InitializeDistroSeriesJob` that's already scheduled.
    """

    def __init__(self, job):
        super(InitializationPending, self).__init__()
        self.job = job


class InitializationCompleted(Exception):
    """The initialization of the distroseries has already been done.

    :ivar job: The `InitializeDistroSeriesJob` that's already scheduled.
    """

    def __init__(self, job):
        super(InitializationCompleted, self).__init__()
        self.job = job


class IInitializeDistroSeriesJobSource(IJobSource):
    """An interface for acquiring IInitializeDistroSeriesJobs."""

    def create(parents, arches, packagesets, rebuild, overlay,
               overlay_pockets, overlay_components):
        """Create a new initialization job for a distroseries."""

    def getJobsForDistroseries(distroseries, statuses=None):
        """Retrieve initialization jobs for a distroseries.

        :param statuses: If `None` return pending jobs, otherwise return jobs
            with one of the given statuses.
        :type statuses: Any iterable, or `None`.
        """


class IInitializeDistroSeriesJob(IRunnableJob):
    """A Job that performs actions on a distribution."""


class IDistroSeriesDifferenceJobSource(IJobSource):
    """An `IJob` for creating `DistroSeriesDifference`s."""

    def createForPackagePublication(derivedseries, sourcepackagename, pocket,
                                    parent_series=None):
        """Create jobs as appropriate for a given status publication.

        :param derived_series: A `DistroSeries` that is assumed to be
            derived from `parent_series`.
        :param sourcepackagename: A `SourcePackageName` that is being
            published in `derived_series` or `parent_series`.
        :param pocket: The `PackagePublishingPocket` for the publication.
        :param parent_series: The parent `DistroSeries` whose version of
            `sourcepackagename` is to be compared with that in
            `derived_series`.
        :return: An iterable of `DistroSeriesDifferenceJob`.
        """
        # XXX JeroenVermeulen 2011-05-26 bug=758906: Make parent_series
        # mandatory as part of multi-parent support.

    def getPendingJobsForDifferences(derived_series, distroseriesdifferences):
        """Find `DistroSeriesDifferenceJob`s for `DistroSeriesDifference`s.

        :param derived_series: The derived `DistroSeries` that the
            differences (and jobs) must be for.
        :param distroseriesdifferences:
            An iterable of `DistroSeriesDifference`s.
        :return: A dict mapping each of `distroseriesdifferences` that has
            pending jobs to a list of its jobs.
        """


class IDistroSeriesDifferenceJob(IRunnableJob):
    """A `Job` that performs actions related to `DistroSeriesDifference`s."""
