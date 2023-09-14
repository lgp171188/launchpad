# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Classes to represent source package releases in a distribution."""

__all__ = [
    "DistributionSourcePackageRelease",
]

from operator import itemgetter

from lazr.delegates import delegate_to
from storm.expr import SQL, And, Desc, Join, LeftJoin
from storm.store import Store
from zope.interface import implementer

from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.soyuz.interfaces.distributionsourcepackagerelease import (
    IDistributionSourcePackageRelease,
)
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.distroarchseries import DistroArchSeries
from lp.soyuz.model.distroseriesbinarypackage import DistroSeriesBinaryPackage
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
)


@implementer(IDistributionSourcePackageRelease)
@delegate_to(ISourcePackageRelease, context="sourcepackagerelease")
class DistributionSourcePackageRelease:
    """This is a "Magic Distribution Source Package Release". It is not an
    SQLObject, but it represents the concept of a specific source package
    release in the distribution. You can then query it for useful
    information.
    """

    def __init__(self, distribution, sourcepackagerelease):
        self.distribution = distribution
        self.sourcepackagerelease = sourcepackagerelease

    @staticmethod
    def getPublishingHistories(distribution, sprs):
        from lp.registry.model.distroseries import DistroSeries

        res = Store.of(distribution).find(
            SourcePackagePublishingHistory,
            SourcePackagePublishingHistory.archive_id.is_in(
                distribution.all_distro_archive_ids
            ),
            SourcePackagePublishingHistory.distroseries_id == DistroSeries.id,
            DistroSeries.distribution == distribution,
            SourcePackagePublishingHistory.sourcepackagerelease_id.is_in(
                spr.id for spr in sprs
            ),
        )
        return res.order_by(
            Desc(SourcePackagePublishingHistory.sourcepackagerelease_id),
            Desc(SourcePackagePublishingHistory.datecreated),
            Desc(SourcePackagePublishingHistory.id),
        )

    @property
    def sourcepackage(self):
        """See IDistributionSourcePackageRelease"""
        return self.distribution.getSourcePackage(
            self.sourcepackagerelease.sourcepackagename
        )

    @property
    def displayname(self):
        """See IDistributionSourcePackageRelease."""
        return "%s %s" % (self.name, self.version)

    @property
    def title(self):
        """See IDistributionSourcePackageRelease."""
        return "%s %s source package in %s" % (
            self.name,
            self.version,
            self.distribution.displayname,
        )

    @property
    def publishing_history(self):
        """See IDistributionSourcePackageRelease."""
        return self.getPublishingHistories(
            self.distribution, [self.sourcepackagerelease]
        )

    def _getBuilds(self, clauses=[]):
        # First, get all the builds built in a main archive (this will
        # include new and failed builds.)
        builds_built_in_main_archives = Store.of(self.distribution).find(
            BinaryPackageBuild,
            BinaryPackageBuild.source_package_release
            == self.sourcepackagerelease,
            BinaryPackageBuild.archive_id.is_in(
                self.distribution.all_distro_archive_ids
            ),
            *clauses,
        )

        # Next get all the builds that have a binary published in the
        # main archive... this will include many of those in the above
        # query, but not the new/failed ones. It will also include
        # ppa builds that have been published in main archives.
        builds_published_in_main_archives = (
            Store.of(self.distribution)
            .find(
                BinaryPackageBuild,
                BinaryPackageBuild.source_package_release
                == self.sourcepackagerelease,
                BinaryPackageRelease.build == BinaryPackageBuild.id,
                BinaryPackagePublishingHistory.binarypackagerelease
                == BinaryPackageRelease.id,
                BinaryPackagePublishingHistory.archive_id.is_in(
                    self.distribution.all_distro_archive_ids
                ),
                *clauses,
            )
            .config(distinct=True)
        )

        return builds_built_in_main_archives.union(
            builds_published_in_main_archives
        ).order_by(Desc(BinaryPackageBuild.id))

    @property
    def builds(self):
        """See IDistributionSourcePackageRelease."""
        return self._getBuilds()

    def getBuildsByArchTag(self, arch_tag):
        """See IDistributionSourcePackageRelease."""
        clauses = [
            BinaryPackageBuild.distro_arch_series_id == DistroArchSeries.id,
            DistroArchSeries.architecturetag == arch_tag,
        ]
        return self._getBuilds(clauses)

    @property
    def sample_binary_packages(self):
        """See IDistributionSourcePackageRelease."""
        # Avoid circular imports.
        from lp.registry.model.distroseries import DistroSeries
        from lp.soyuz.model.distroarchseries import DistroArchSeries
        from lp.soyuz.model.distroseriespackagecache import (
            DistroSeriesPackageCache,
        )

        archive_ids = list(self.distribution.all_distro_archive_ids)
        result_row = (
            SQL("DISTINCT ON(BinaryPackageName.name) 0 AS ignore"),
            DistroSeries,
            BinaryPackageName,
            DistroSeriesPackageCache,
        )
        tables = (
            BinaryPackagePublishingHistory,
            Join(
                DistroArchSeries,
                DistroArchSeries.id
                == BinaryPackagePublishingHistory.distroarchseries_id,
            ),
            Join(
                DistroSeries,
                DistroArchSeries.distroseries == DistroSeries.id,
            ),
            Join(
                BinaryPackageRelease,
                BinaryPackageRelease.id
                == BinaryPackagePublishingHistory.binarypackagerelease_id,
            ),
            Join(
                BinaryPackageName,
                BinaryPackageName.id
                == BinaryPackageRelease.binarypackagename_id,
            ),
            Join(
                BinaryPackageBuild,
                BinaryPackageBuild.id == BinaryPackageRelease.build_id,
            ),
            LeftJoin(
                DistroSeriesPackageCache,
                And(
                    DistroSeriesPackageCache.distroseries == DistroSeries.id,
                    DistroSeriesPackageCache.archive_id.is_in(archive_ids),
                    DistroSeriesPackageCache.binarypackagename
                    == BinaryPackageName.id,
                ),
            ),
        )

        all_published = (
            Store.of(self.distribution)
            .using(*tables)
            .find(
                result_row,
                DistroSeries.distribution == self.distribution,
                BinaryPackagePublishingHistory.archive_id.is_in(archive_ids),
                BinaryPackageBuild.source_package_release
                == self.sourcepackagerelease,
            )
        )
        all_published = all_published.order_by(BinaryPackageName.name)

        def make_dsb_package(row):
            _, ds, bpn, package_cache = row
            return DistroSeriesBinaryPackage(ds, bpn, package_cache)

        return DecoratedResultSet(all_published, make_dsb_package)

    def getBinariesForSeries(self, distroseries):
        """See `IDistributionSourcePackageRelease`."""
        # Avoid circular imports.
        from lp.soyuz.model.distroarchseries import DistroArchSeries

        store = Store.of(distroseries)
        result_row = (
            BinaryPackageRelease,
            BinaryPackageBuild,
            BinaryPackageName,
        )

        tables = (
            BinaryPackageRelease,
            Join(
                BinaryPackageBuild,
                BinaryPackageBuild.id == BinaryPackageRelease.build_id,
            ),
            Join(
                BinaryPackagePublishingHistory,
                BinaryPackageRelease.id
                == BinaryPackagePublishingHistory.binarypackagerelease_id,
            ),
            Join(
                DistroArchSeries,
                DistroArchSeries.id
                == BinaryPackagePublishingHistory.distroarchseries_id,
            ),
            Join(
                BinaryPackageName,
                BinaryPackageName.id
                == BinaryPackageRelease.binarypackagename_id,
            ),
        )
        archive_ids = list(self.distribution.all_distro_archive_ids)
        binaries = store.using(*tables).find(
            result_row,
            And(
                DistroArchSeries.distroseries == distroseries,
                BinaryPackagePublishingHistory.archive_id.is_in(archive_ids),
                BinaryPackageBuild.source_package_release
                == self.sourcepackagerelease,
            ),
        )
        binaries.order_by(Desc(BinaryPackageRelease.id)).config(distinct=True)
        return DecoratedResultSet(binaries, itemgetter(0))
