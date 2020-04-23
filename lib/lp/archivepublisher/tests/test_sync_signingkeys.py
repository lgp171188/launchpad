# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test cases for the script that injects signing keys into signing service."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type


__all__ = [
    'SyncSigningKeysScript',
    ]

import os

from fixtures import TempDir
from testtools.matchers import (
    Equals,
    MatchesDict,
    )

from lp.archivepublisher.scripts.sync_signingkeys import SyncSigningKeysScript
from lp.services.database.interfaces import IStore
from lp.services.log.logger import BufferLogger
from lp.services.signing.enums import SigningKeyType
from lp.soyuz.model.archive import Archive
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestSyncSigningKeysScript(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def makeScript(self, test_args):
        script = SyncSigningKeysScript("test-sync", test_args=test_args)
        script.logger = BufferLogger()
        return script

    def makeArchives(self):
        for i in range(10):
            self.factory.makeArchive()
        return IStore(Archive).find(Archive).order_by(Archive.id)

    def test_fetch_archives_without_limit_and_offset(self):
        script = self.makeScript([])
        all_archives = list(self.makeArchives())
        archives = list(script.getArchives())
        self.assertEqual(all_archives, archives)

    def test_fetch_archives_with_limit_and_offset(self):
        script = self.makeScript([
            "--limit", "3",
            "--offset", "2"
        ])
        all_archives = list(self.makeArchives())
        archives = list(script.getArchives())
        self.assertEqual(all_archives[2:5], archives)

    def test_get_keys_per_type(self):
        keys_dir = self.useFixture(TempDir()).path

        # Create fake uefi keys, and missing opal pem
        for filename in ["uefi.key", "uefi.crt", "opal.x509"]:
            with open(os.path.join(keys_dir, filename), 'wb') as fd:
                fd.write(b"something something")

        script = self.makeScript([])
        self.assertThat(script.getKeysPerType(keys_dir), MatchesDict({
            SigningKeyType.UEFI: Equals(("uefi.key", "uefi.crt"))
        }))

    def test_get_series_paths(self):
        signing_root_dir = self.useFixture(TempDir()).path
        self.pushConfig(
            "personalpackagearchive", signing_keys_root=signing_root_dir)

        distro = self.factory.makeDistribution()
        series1 = self.factory.makeDistroSeries(distribution=distro)
        series2 = self.factory.makeDistroSeries(distribution=distro)
        # For this series, we will not create the keys directory.
        self.factory.makeDistroSeries(distribution=distro)

        archive = self.factory.makeArchive(distribution=distro)
        archive_root = os.path.join(
            signing_root_dir, "signing", archive.owner.name, archive.name)

        os.makedirs(archive_root)
        for series in [series1, series2]:
            os.makedirs(os.path.join(archive_root, series.name))

        script = self.makeScript([])
        self.assertThat(script.getSeriesPaths(archive), MatchesDict({
            series1: Equals(os.path.join(archive_root, series1.name)),
            series2: Equals(os.path.join(archive_root, series2.name)),
            None: Equals(archive_root)
        }))
