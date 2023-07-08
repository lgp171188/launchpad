# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test update-pkgcache."""

import transaction

from lp.services.log.logger import BufferLogger
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.model.distroseriespackagecache import DistroSeriesPackageCache
from lp.soyuz.scripts.update_pkgcache import PackageCacheUpdater
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.layers import ZopelessDatabaseLayer


# XXX cjwatson 2022-04-01: Most functional tests currently live in
# lib/lp/soyuz/doc/package-cache-script.rst, but should be moved here.
class TestPackageCacheUpdater(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer
    dbuser = "update-pkg-cache"

    def makeScript(self):
        script = PackageCacheUpdater(test_args=[])
        script.logger = BufferLogger()
        script.txn = transaction
        return script

    def test_archive_disabled_during_run(self):
        distribution = self.factory.makeDistribution()
        archives = [
            self.factory.makeArchive(distribution=distribution)
            for _ in range(2)
        ]
        for archive in archives:
            self.assertEqual(0, archive.sources_cached)
            self.factory.makeSourcePackagePublishingHistory(archive=archive)
        script = self.makeScript()
        with dbuser(self.dbuser):
            script.updateDistributionCache(distribution, archives[0])
            archives[0].updateArchiveCache()
        self.assertEqual(1, archives[0].sources_cached)
        archives[1].disable()
        with dbuser(self.dbuser):
            script.updateDistributionCache(distribution, archives[1])
            archives[1].updateArchiveCache()
        self.assertEqual(0, archives[1].sources_cached)

    def test_binary_deleted_during_run(self):
        distroseries = self.factory.makeDistroSeries()
        das = self.factory.makeDistroArchSeries(distroseries=distroseries)
        archive = self.factory.makeArchive(
            distribution=distroseries.distribution
        )
        bpns = [self.factory.makeBinaryPackageName() for _ in range(4)]
        bpphs = [
            self.factory.makeBinaryPackagePublishingHistory(
                binarypackagename=bpn,
                distroarchseries=das,
                status=PackagePublishingStatus.PUBLISHED,
                archive=archive,
            )
            for bpn in bpns
        ]

        class InstrumentedTransaction:
            def commit(self):
                transaction.commit()
                # Change this binary package publishing history's status
                # after the first commit, to simulate the situation where a
                # BPPH ceases to be active part-way through an
                # update-pkgcache run.
                if bpphs[2].status == PackagePublishingStatus.PUBLISHED:
                    with dbuser("launchpad"):
                        bpphs[2].requestDeletion(archive.owner)

        logger = BufferLogger()
        with dbuser(self.dbuser):
            DistroSeriesPackageCache.updateAll(
                distroseries,
                archive=archive,
                ztm=InstrumentedTransaction(),
                log=logger,
                commit_chunk=2,
            )
            archive.updateArchiveCache()
        self.assertEqual(4, archive.binaries_cached)
        self.assertEqual(
            "DEBUG Considering binaries {bpns[0].name}, {bpns[1].name}\n"
            "DEBUG Committing\n"
            "DEBUG Considering binaries {bpns[2].name}, {bpns[3].name}\n"
            "DEBUG No active publishing details found for {bpns[2].name};"
            " perhaps removed in parallel with update-pkgcache?  Skipping.\n"
            "DEBUG Committing\n".format(bpns=bpns),
            logger.getLogBuffer(),
        )
