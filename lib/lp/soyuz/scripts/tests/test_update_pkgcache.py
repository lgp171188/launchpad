# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test update-pkgcache."""

import transaction

from lp.services.log.logger import BufferLogger
from lp.soyuz.scripts.update_pkgcache import PackageCacheUpdater
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


# XXX cjwatson 2022-04-01: Most functional tests currently live in
# lib/lp/soyuz/doc/package-cache-script.txt, but should be moved here.
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
            for _ in range(2)]
        for archive in archives:
            self.assertEqual(0, archive.sources_cached)
            self.factory.makeSourcePackagePublishingHistory(archive=archive)
        script = self.makeScript()
        script.updateDistributionCache(distribution, archives[0])
        archives[0].updateArchiveCache()
        self.assertEqual(1, archives[0].sources_cached)
        archives[1].disable()
        script.updateDistributionCache(distribution, archives[1])
        archives[1].updateArchiveCache()
        self.assertEqual(0, archives[1].sources_cached)
