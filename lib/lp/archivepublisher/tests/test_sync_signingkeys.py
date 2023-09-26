# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test cases for the script that injects signing keys into signing service."""

__all__ = [
    "SyncSigningKeysScript",
]

import os
from datetime import datetime, timezone
from textwrap import dedent
from unittest import mock

import transaction
from fixtures import MockPatch, TempDir
from testtools.content import text_content
from testtools.matchers import (
    ContainsAll,
    Equals,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
    StartsWith,
)
from testtools.twistedsupport import AsynchronousDeferredRunTest
from twisted.internet import defer
from zope.component import getUtility

from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
    ISignableArchive,
)
from lp.archivepublisher.model.publisherconfig import PublisherConfig
from lp.archivepublisher.scripts.sync_signingkeys import SyncSigningKeysScript
from lp.services.config import config
from lp.services.config.fixture import ConfigFixture, ConfigUseFixture
from lp.services.database.interfaces import IStore
from lp.services.log.logger import BufferLogger
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.services.signing.model.signingkey import SigningKey
from lp.services.signing.testing.fixture import SigningServiceFixture
from lp.services.signing.tests.helpers import SigningServiceClientFixture
from lp.soyuz.model.archive import Archive
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.gpgkeys import gpgkeysdir
from lp.testing.keyserver import InProcessKeyServerFixture
from lp.testing.layers import ZopelessDatabaseLayer
from lp.testing.script import run_script


class TestSyncSigningKeysScript(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer
    # A timeout of 30 seconds is slightly too short and can lead to
    # non-relevant test failures. 45 seconds is a value estimated from trial
    # and error.
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=45)

    def setUp(self):
        super().setUp()
        self.signing_root_dir = self.useFixture(TempDir()).path
        # Add our local configuration to an on-disk configuration file so
        # that it can be used by subprocesses.
        config_name = self.factory.getUniqueString()
        config_fixture = self.useFixture(
            ConfigFixture(config_name, os.environ["LPCONFIG"])
        )
        config_fixture.add_section(
            dedent(
                """
            [personalpackagearchive]
            signing_keys_root: {}
            """
            ).format(self.signing_root_dir)
        )
        self.useFixture(ConfigUseFixture(config_name))

    def makeScript(self, test_args):
        script = SyncSigningKeysScript(
            "test-sync",
            dbuser=config.archivepublisher.dbuser,
            test_args=test_args,
        )
        script.logger = BufferLogger()
        return script

    def makeArchives(self):
        for i in range(10):
            self.factory.makeArchive()
        conditions = PublisherConfig.distribution_id == Archive.distribution_id
        return IStore(Archive).find(Archive, conditions).order_by(Archive.id)

    def makeArchiveSigningDir(self, ppa, series=None):
        """Creates the directory tree to hold signing keys for the PPA
        and specific list of DistroSeries provided.

        :param archive: The Archive that will hold the keys (should be PPA)
        :param series: A list of DistroSeries
        :return: A dict with series as keys (and None for the root archive)
                 and the values being the directory where the keys should be.
        """
        archive_root = os.path.join(
            self.signing_root_dir, "signing", ppa.owner.name, ppa.name
        )
        os.makedirs(archive_root)

        ret = {None: archive_root}
        for series in series or []:
            path = os.path.join(archive_root, series.name)
            ret[series] = path
            os.makedirs(path)
        return ret

    def test_fetch_archives_without_limit_and_offset(self):
        script = self.makeScript([])
        all_archives = list(self.makeArchives())
        archives = list(script.getArchives())
        self.assertEqual(all_archives, archives)

    def test_fetch_archives_with_limit_and_offset(self):
        script = self.makeScript(["--limit", "3", "--offset", "2"])
        all_archives = list(self.makeArchives())
        archives = list(script.getArchives())
        self.assertEqual(all_archives[2:5], archives)

    def test_fetch_archives_with_reference(self):
        all_archives = list(self.makeArchives())
        script = self.makeScript(["--archive", all_archives[0].reference])
        archives = list(script.getArchives())
        self.assertEqual([all_archives[0]], archives)

    def test_get_key_types(self):
        script = self.makeScript([])
        key_types = script.getKeyTypes()
        expected_key_types = [
            SigningKeyType.UEFI,
            SigningKeyType.KMOD,
            SigningKeyType.OPAL,
            SigningKeyType.SIPL,
            SigningKeyType.FIT,
            SigningKeyType.OPENPGP,
        ]
        self.assertEqual(expected_key_types, key_types)

    def test_get_key_types_with_selection(self):
        script = self.makeScript(["--type", "UEFI"])
        key_types = script.getKeyTypes()
        self.assertEqual([SigningKeyType.UEFI], key_types)

    def test_get_keys_per_type(self):
        keys_dir = self.signing_root_dir

        # Create fake UEFI and FIT keys, and missing OPAL PEM.
        for filename in ("uefi.key", "uefi.crt", "opal.x509"):
            with open(os.path.join(keys_dir, filename), "wb") as fd:
                fd.write(b"something something")
        # Create fake FIT keys, which live in a subdirectory.
        os.makedirs(os.path.join(keys_dir, "fit"))
        for filename in ("fit.key", "fit.crt"):
            with open(os.path.join(keys_dir, "fit", filename), "wb") as fd:
                fd.write(b"something something")

        script = self.makeScript([])
        self.assertThat(
            script.getKeysPerType(keys_dir),
            MatchesDict(
                {
                    SigningKeyType.UEFI: Equals(
                        (
                            os.path.join(keys_dir, "uefi.key"),
                            os.path.join(keys_dir, "uefi.crt"),
                        )
                    ),
                    SigningKeyType.FIT: Equals(
                        (
                            os.path.join(keys_dir, "fit", "fit.key"),
                            os.path.join(keys_dir, "fit", "fit.crt"),
                        )
                    ),
                }
            ),
        )

    def test_get_series_paths(self):
        distro = self.factory.makeDistribution()
        series1 = self.factory.makeDistroSeries(distribution=distro)
        series2 = self.factory.makeDistroSeries(distribution=distro)
        # For this series, we will not create the keys directory.
        self.factory.makeDistroSeries(distribution=distro)

        archive = self.factory.makeArchive(distribution=distro)
        key_dirs = self.makeArchiveSigningDir(archive, [series1, series2])
        archive_root = key_dirs[None]

        script = self.makeScript([])
        self.assertThat(
            script.getSeriesPaths(archive),
            MatchesDict(
                {
                    series1: Equals(os.path.join(archive_root, series1.name)),
                    series2: Equals(os.path.join(archive_root, series2.name)),
                    None: Equals(archive_root),
                }
            ),
        )

    def test_get_series_paths_override_local_keys_directory(self):
        distro = self.factory.makeDistribution()
        series1 = self.factory.makeDistroSeries(distribution=distro)
        series2 = self.factory.makeDistroSeries(distribution=distro)
        # For this series, we will not create the keys directory.
        self.factory.makeDistroSeries(distribution=distro)
        local_keys = self.useFixture(TempDir()).path
        os.makedirs(os.path.join(local_keys, series1.name))
        os.makedirs(os.path.join(local_keys, series2.name))

        archive = self.factory.makeArchive(distribution=distro)

        script = self.makeScript(["--local-keys", local_keys])
        self.assertThat(
            script.getSeriesPaths(archive),
            MatchesDict(
                {
                    series1: Equals(os.path.join(local_keys, series1.name)),
                    series2: Equals(os.path.join(local_keys, series2.name)),
                    None: Equals(local_keys),
                }
            ),
        )

    def test_process_archive(self):
        distro = self.factory.makeDistribution()
        series1 = self.factory.makeDistroSeries(distribution=distro)
        series2 = self.factory.makeDistroSeries(distribution=distro)

        archive = self.factory.makeArchive(distribution=distro)
        key_dirs = self.makeArchiveSigningDir(archive, [series1, series2])

        archive_root = key_dirs[None]

        # Create fake UEFI keys for the root
        for filename in ("uefi.key", "uefi.crt"):
            with open(os.path.join(archive_root, filename), "w") as fd:
                fd.write("Root %s" % filename)

        # Create fake OPAL and Kmod keys for series1
        for filename in ("opal.pem", "opal.x509", "kmod.pem", "kmod.x509"):
            with open(os.path.join(key_dirs[series1], filename), "w") as fd:
                fd.write("Series 1 %s" % filename)

        # Create fake FIT keys for series1
        os.makedirs(os.path.join(key_dirs[series1], "fit"))
        for filename in ("fit.key", "fit.crt"):
            with open(
                os.path.join(key_dirs[series1], "fit", filename), "w"
            ) as fd:
                fd.write("Series 1 %s" % filename)

        script = self.makeScript(["--archive", archive.reference])
        script.inject = mock.Mock()
        script.main()

        self.assertItemsEqual(
            [
                mock.call(
                    archive,
                    SigningKeyType.KMOD,
                    series1,
                    os.path.join(key_dirs[series1], "kmod.pem"),
                    os.path.join(key_dirs[series1], "kmod.x509"),
                ),
                mock.call(
                    archive,
                    SigningKeyType.OPAL,
                    series1,
                    os.path.join(key_dirs[series1], "opal.pem"),
                    os.path.join(key_dirs[series1], "opal.x509"),
                ),
                mock.call(
                    archive,
                    SigningKeyType.FIT,
                    series1,
                    os.path.join(key_dirs[series1], "fit", "fit.key"),
                    os.path.join(key_dirs[series1], "fit", "fit.crt"),
                ),
                mock.call(
                    archive,
                    SigningKeyType.UEFI,
                    None,
                    os.path.join(archive_root, "uefi.key"),
                    os.path.join(archive_root, "uefi.crt"),
                ),
            ],
            script.inject.call_args_list,
        )

        # Check the log messages.
        content = script.logger.content.as_text()
        self.assertIn(
            "DEBUG #0 - Processing keys for archive %s." % archive.reference,
            content,
        )

        tpl = "INFO Found key files %s / %s (type=%s, series=%s)."
        self.assertIn(
            tpl
            % (
                os.path.join(key_dirs[series1], "kmod.pem"),
                os.path.join(key_dirs[series1], "kmod.x509"),
                SigningKeyType.KMOD,
                series1.name,
            ),
            content,
        )
        self.assertIn(
            tpl
            % (
                os.path.join(key_dirs[series1], "opal.pem"),
                os.path.join(key_dirs[series1], "opal.x509"),
                SigningKeyType.OPAL,
                series1.name,
            ),
            content,
        )
        self.assertIn(
            tpl
            % (
                os.path.join(key_dirs[series1], "fit", "fit.key"),
                os.path.join(key_dirs[series1], "fit", "fit.crt"),
                SigningKeyType.FIT,
                series1.name,
            ),
            content,
        )
        self.assertIn(
            tpl
            % (
                os.path.join(archive_root, "uefi.key"),
                os.path.join(archive_root, "uefi.crt"),
                SigningKeyType.UEFI,
                None,
            ),
            content,
        )

        self.assertIn("INFO 1 archive processed; committing.", content)

    def test_process_archive_dry_run(self):
        signing_service_client = self.useFixture(
            SigningServiceClientFixture(self.factory)
        )

        distro = self.factory.makeDistribution()
        series1 = self.factory.makeDistroSeries(distribution=distro)
        series2 = self.factory.makeDistroSeries(distribution=distro)

        archive = self.factory.makeArchive(distribution=distro)
        key_dirs = self.makeArchiveSigningDir(archive, [series1, series2])

        archive_root = key_dirs[None]

        archive_signing_key_fit = self.factory.makeArchiveSigningKey(
            archive=archive,
            distro_series=series1,
            signing_key=self.factory.makeSigningKey(
                key_type=SigningKeyType.FIT
            ),
        )
        fingerprint_fit = archive_signing_key_fit.signing_key.fingerprint

        transaction.commit()

        # Create fake UEFI keys for the root
        for filename in ("uefi.key", "uefi.crt"):
            with open(os.path.join(archive_root, filename), "w") as fd:
                fd.write("Root %s" % filename)

        # Create fake OPAL and Kmod keys for series1
        for filename in ("opal.pem", "opal.x509", "kmod.pem", "kmod.x509"):
            with open(os.path.join(key_dirs[series1], filename), "w") as fd:
                fd.write("Series 1 %s" % filename)

        # Create fake FIT keys for series1
        os.makedirs(os.path.join(key_dirs[series1], "fit"))
        for filename in ("fit.key", "fit.crt"):
            with open(
                os.path.join(key_dirs[series1], "fit", filename), "w"
            ) as fd:
                fd.write("Series 1 %s" % filename)

        script = self.makeScript(
            ["--archive", archive.reference, "--overwrite", "--dry-run"]
        )
        script.main()

        self.assertEqual(0, signing_service_client.inject.call_count)

        # No changes are committed to the database.
        archive_signing_key_set = getUtility(IArchiveSigningKeySet)
        self.assertIsNone(
            archive_signing_key_set.getSigningKey(
                SigningKeyType.UEFI, archive, None, exact_match=True
            )
        )
        self.assertIsNone(
            archive_signing_key_set.getSigningKey(
                SigningKeyType.KMOD, archive, series1, exact_match=True
            )
        )
        self.assertIsNone(
            archive_signing_key_set.getSigningKey(
                SigningKeyType.OPAL, archive, series1, exact_match=True
            )
        )
        self.assertThat(
            archive_signing_key_set.getSigningKey(
                SigningKeyType.FIT, archive, series1, exact_match=True
            ),
            MatchesStructure.byEquality(fingerprint=fingerprint_fit),
        )

        # Check the log messages.
        found_tpl = "INFO Found key files %s / %s (type=%s, series=%s)."
        overwrite_tpl = (
            "INFO Overwriting existing signing key for %s / %s / %s"
        )
        inject_tpl = "INFO Would inject signing key for %s / %s / %s"
        self.assertThat(
            script.logger.content.as_text().splitlines(),
            ContainsAll(
                [
                    "DEBUG #0 - Processing keys for archive %s."
                    % archive.reference,
                    found_tpl
                    % (
                        os.path.join(archive_root, "uefi.key"),
                        os.path.join(archive_root, "uefi.crt"),
                        SigningKeyType.UEFI,
                        None,
                    ),
                    inject_tpl
                    % (SigningKeyType.UEFI, archive.reference, None),
                    found_tpl
                    % (
                        os.path.join(key_dirs[series1], "kmod.pem"),
                        os.path.join(key_dirs[series1], "kmod.x509"),
                        SigningKeyType.KMOD,
                        series1.name,
                    ),
                    inject_tpl
                    % (SigningKeyType.KMOD, archive.reference, series1.name),
                    found_tpl
                    % (
                        os.path.join(key_dirs[series1], "opal.pem"),
                        os.path.join(key_dirs[series1], "opal.x509"),
                        SigningKeyType.OPAL,
                        series1.name,
                    ),
                    inject_tpl
                    % (SigningKeyType.OPAL, archive.reference, series1.name),
                    found_tpl
                    % (
                        os.path.join(key_dirs[series1], "fit", "fit.key"),
                        os.path.join(key_dirs[series1], "fit", "fit.crt"),
                        SigningKeyType.FIT,
                        series1.name,
                    ),
                    overwrite_tpl
                    % (SigningKeyType.FIT, archive.reference, series1.name),
                    inject_tpl
                    % (SigningKeyType.FIT, archive.reference, series1.name),
                ]
            ),
        )

    def test_process_archive_openpgp(self):
        archive = self.factory.makeArchive()

        # Create a fake OpenPGP key.
        gpgkey = self.factory.makeGPGKey(archive.owner)
        secret_key_path = os.path.join(
            self.signing_root_dir, "%s.gpg" % gpgkey.fingerprint
        )
        with open(secret_key_path, "w") as fd:
            fd.write("Private key %s" % gpgkey.fingerprint)
        archive.signing_key_owner = archive.owner
        archive.signing_key_fingerprint = gpgkey.fingerprint

        script = self.makeScript(["--archive", archive.reference])
        script.injectGPG = mock.Mock()
        script.main()

        script.injectGPG.assert_called_once_with(archive, secret_key_path)

        # Check the log messages.
        content = script.logger.content.as_text()
        self.assertIn(
            "DEBUG #0 - Processing keys for archive %s." % archive.reference,
            content,
        )
        self.assertIn(
            "INFO Found key file %s (type=%s)."
            % (secret_key_path, SigningKeyType.OPENPGP),
            content,
        )
        self.assertIn("INFO 1 archive processed; committing.", content)

    def test_process_archive_openpgp_missing(self):
        archive = self.factory.makeArchive()

        # Create a fake OpenPGP key, but don't write anything to disk.
        gpgkey = self.factory.makeGPGKey(archive.owner)
        archive.signing_key_owner = archive.owner
        archive.signing_key_fingerprint = gpgkey.fingerprint

        script = self.makeScript(["--archive", archive.reference])
        script.injectGPG = mock.Mock()
        script.main()

        self.assertEqual(0, script.injectGPG.call_count)

        # Check the log messages.
        content = script.logger.content.as_text()
        self.assertIn(
            "DEBUG #0 - Processing keys for archive %s." % archive.reference,
            content,
        )
        self.assertNotIn("INFO Found key file", content)
        self.assertIn("INFO 1 archive processed; committing.", content)

    def test_inject(self):
        signing_service_client = self.useFixture(
            SigningServiceClientFixture(self.factory)
        )

        now = datetime.now()
        mock_datetime = self.useFixture(
            MockPatch("lp.archivepublisher.scripts.sync_signingkeys.datetime")
        ).mock
        mock_datetime.now = lambda: now

        tmpdir = self.useFixture(TempDir()).path
        priv_key_path = os.path.join(tmpdir, "priv.key")
        pub_key_path = os.path.join(tmpdir, "pub.crt")

        with open(priv_key_path, "wb") as fd:
            fd.write(b"Private key content")
        with open(pub_key_path, "wb") as fd:
            fd.write(b"Public key content")

        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro)
        archive = self.factory.makeArchive(distribution=distro)

        script = self.makeScript([])

        with dbuser(config.archivepublisher.dbuser):
            result_with_series = script.inject(
                archive,
                SigningKeyType.UEFI,
                series,
                priv_key_path,
                pub_key_path,
            )

        self.assertThat(
            result_with_series,
            MatchesStructure.byEquality(
                archive=archive,
                earliest_distro_series=series,
                key_type=SigningKeyType.UEFI,
            ),
        )
        self.assertThat(
            result_with_series.signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI, public_key=b"Public key content"
            ),
        )

        # Check if we called lp-signing's /inject endpoint correctly
        self.assertEqual(1, signing_service_client.inject.call_count)
        self.assertEqual(
            (
                SigningKeyType.UEFI,
                b"Private key content",
                b"Public key content",
                "UEFI key for %s" % archive.reference,
                now.replace(tzinfo=timezone.utc),
            ),
            signing_service_client.inject.call_args[0],
        )

        with dbuser(config.archivepublisher.dbuser):
            result_no_series = script.inject(
                archive, SigningKeyType.UEFI, None, priv_key_path, pub_key_path
            )

        self.assertThat(
            result_no_series,
            MatchesStructure.byEquality(
                archive=archive,
                earliest_distro_series=None,
                key_type=SigningKeyType.UEFI,
            ),
        )
        self.assertThat(
            result_no_series.signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI, public_key=b"Public key content"
            ),
        )

        # Check again lp-signing's /inject endpoint call
        self.assertEqual(2, signing_service_client.inject.call_count)
        self.assertEqual(
            (
                SigningKeyType.UEFI,
                b"Private key content",
                b"Public key content",
                "UEFI key for %s" % archive.reference,
                now.replace(tzinfo=timezone.utc),
            ),
            signing_service_client.inject.call_args[0],
        )

    def test_inject_existing_key(self):
        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro)
        archive = self.factory.makeArchive(distribution=distro)

        tmpdir = self.useFixture(TempDir()).path
        priv_key_path = os.path.join(tmpdir, "priv.key")
        pub_key_path = os.path.join(tmpdir, "pub.crt")
        with open(priv_key_path, "wb") as fd:
            fd.write(b"Private key content")
        with open(pub_key_path, "wb") as fd:
            fd.write(b"Public key content")

        expected_arch_signing_key = self.factory.makeArchiveSigningKey(
            archive=archive, distro_series=series
        )
        key_type = expected_arch_signing_key.key_type

        script = self.makeScript([])
        with dbuser(config.archivepublisher.dbuser):
            got_arch_key = script.inject(
                archive, key_type, series, priv_key_path, pub_key_path
            )
        self.assertEqual(expected_arch_signing_key, got_arch_key)

        self.assertIn(
            "Signing key for %s / %s / %s already exists"
            % (key_type, archive.reference, series.name),
            script.logger.content.as_text(),
        )

    def test_inject_existing_key_with_overwrite(self):
        signing_service_client = self.useFixture(
            SigningServiceClientFixture(self.factory)
        )

        now = datetime.now()
        mock_datetime = self.useFixture(
            MockPatch("lp.archivepublisher.scripts.sync_signingkeys.datetime")
        ).mock
        mock_datetime.now = lambda: now

        distro = self.factory.makeDistribution()
        series = self.factory.makeDistroSeries(distribution=distro)
        archive = self.factory.makeArchive(distribution=distro)

        tmpdir = self.useFixture(TempDir()).path
        priv_key_path = os.path.join(tmpdir, "priv.key")
        pub_key_path = os.path.join(tmpdir, "pub.crt")
        with open(priv_key_path, "wb") as fd:
            fd.write(b"Private key content")
        with open(pub_key_path, "wb") as fd:
            fd.write(b"Public key content")

        self.factory.makeArchiveSigningKey(
            archive=archive,
            distro_series=series,
            signing_key=self.factory.makeSigningKey(
                key_type=SigningKeyType.UEFI
            ),
        )

        script = self.makeScript(["--overwrite"])
        with dbuser(config.archivepublisher.dbuser):
            result = script.inject(
                archive,
                SigningKeyType.UEFI,
                series,
                priv_key_path,
                pub_key_path,
            )

        self.assertThat(
            result,
            MatchesStructure(
                archive=Equals(archive),
                earliest_distro_series=Equals(series),
                key_type=Equals(SigningKeyType.UEFI),
                signing_key=MatchesStructure.byEquality(
                    key_type=SigningKeyType.UEFI,
                    public_key=b"Public key content",
                ),
            ),
        )
        self.assertEqual(
            [
                (
                    SigningKeyType.UEFI,
                    b"Private key content",
                    b"Public key content",
                    "UEFI key for %s" % archive.reference,
                    now.replace(tzinfo=timezone.utc),
                )
            ],
            signing_service_client.inject.call_args,
        )
        self.assertIn(
            "Overwriting existing signing key for %s / %s / %s"
            % (SigningKeyType.UEFI, archive.reference, series.name),
            script.logger.content.as_text(),
        )

    @defer.inlineCallbacks
    def setUpArchiveKey(self, archive, secret_key_path):
        yield self.useFixture(InProcessKeyServerFixture()).start()
        yield IArchiveGPGSigningKey(archive).setSigningKey(
            secret_key_path, async_keyserver=True
        )

    @defer.inlineCallbacks
    def test_injectGPG(self):
        signing_service_client = self.useFixture(
            SigningServiceClientFixture(self.factory)
        )
        now = datetime.now()
        mock_datetime = self.useFixture(
            MockPatch("lp.archivepublisher.scripts.sync_signingkeys.datetime")
        ).mock
        mock_datetime.now = lambda: now
        archive = self.factory.makeArchive()
        secret_key_path = os.path.join(
            gpgkeysdir, "ppa-sample@canonical.com.sec"
        )
        yield self.setUpArchiveKey(archive, secret_key_path)
        self.assertIsNotNone(archive.signing_key)
        script = self.makeScript([])

        with dbuser(config.archivepublisher.dbuser):
            secret_key_path = ISignableArchive(archive).getPathForSecretKey(
                archive.signing_key
            )
            signing_key = script.injectGPG(archive, secret_key_path)

        self.assertThat(
            signing_key,
            MatchesStructure(
                key_type=Equals(SigningKeyType.OPENPGP),
                public_key=StartsWith(
                    b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
                ),
                date_created=Equals(now.replace(tzinfo=timezone.utc)),
            ),
        )
        with open(secret_key_path, "rb") as f:
            secret_key_bytes = f.read()
        self.assertEqual(1, signing_service_client.inject.call_count)
        self.assertThat(
            signing_service_client.inject.call_args[0],
            MatchesListwise(
                [
                    Equals(SigningKeyType.OPENPGP),
                    Equals(secret_key_bytes),
                    StartsWith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n"),
                    Equals("Launchpad PPA for Celso áéíóú Providelo"),
                    Equals(now.replace(tzinfo=timezone.utc)),
                ]
            ),
        )

    @defer.inlineCallbacks
    def test_injectGPG_existing_key(self):
        signing_service_client = self.useFixture(
            SigningServiceClientFixture(self.factory)
        )
        archive = self.factory.makeArchive()
        secret_key_path = os.path.join(
            gpgkeysdir, "ppa-sample@canonical.com.sec"
        )
        yield self.setUpArchiveKey(archive, secret_key_path)
        self.assertIsNotNone(archive.signing_key)
        expected_signing_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP,
            fingerprint=archive.signing_key_fingerprint,
        )
        script = self.makeScript([])

        with dbuser(config.archivepublisher.dbuser):
            secret_key_path = ISignableArchive(archive).getPathForSecretKey(
                archive.signing_key
            )
            signing_key = script.injectGPG(archive, secret_key_path)

        self.assertEqual(expected_signing_key, signing_key)
        self.assertEqual(0, signing_service_client.inject.call_count)
        self.assertIn(
            "Signing key for %s / %s already exists"
            % (SigningKeyType.OPENPGP, archive.reference),
            script.logger.content.as_text(),
        )

    def runScript(self):
        transaction.commit()
        ret, out, err = run_script("scripts/sync-signingkeys.py")
        self.addDetail("stdout", text_content(out))
        self.addDetail("stderr", text_content(err))
        self.assertEqual(0, ret)
        transaction.commit()

    @defer.inlineCallbacks
    def test_script(self):
        self.useFixture(SigningServiceFixture())
        series = self.factory.makeDistroSeries()
        archive = self.factory.makeArchive(distribution=series.distribution)
        key_dirs = self.makeArchiveSigningDir(archive)
        archive_root = key_dirs[None]
        with open(os.path.join(archive_root, "uefi.key"), "wb") as fd:
            fd.write(b"Private key content")
        with open(os.path.join(archive_root, "uefi.crt"), "wb") as fd:
            fd.write(b"Public key content")
        secret_key_path = os.path.join(
            gpgkeysdir, "ppa-sample@canonical.com.sec"
        )
        yield self.setUpArchiveKey(archive, secret_key_path)
        self.assertIsNotNone(archive.signing_key)

        self.runScript()

        archive_signing_key = getUtility(IArchiveSigningKeySet).getSigningKey(
            SigningKeyType.UEFI, archive, series
        )
        self.assertThat(
            archive_signing_key,
            MatchesStructure(
                key_type=Equals(SigningKeyType.UEFI),
                public_key=Equals(b"Public key content"),
            ),
        )
        # We can't look the key up by fingerprint in this test, because the
        # fake signing service makes up a random fingerprint.  Just look for
        # the most recently-added SigningKey.
        gpg_signing_key = (
            IStore(SigningKey)
            .find(SigningKey)
            .order_by(SigningKey.date_created)
            .last()
        )
        self.assertThat(
            gpg_signing_key,
            MatchesStructure(
                key_type=Equals(SigningKeyType.OPENPGP),
                public_key=StartsWith(
                    b"-----BEGIN PGP PUBLIC KEY BLOCK-----\n"
                ),
            ),
        )
