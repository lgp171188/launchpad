# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test cases for copying signing keys between archives."""

import transaction
from testtools.content import text_content
from testtools.matchers import MatchesSetwise, MatchesStructure

from lp.archivepublisher.scripts.copy_signingkeys import CopySigningKeysScript
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.log.logger import BufferLogger
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.model.signingkey import ArchiveSigningKey
from lp.testing import TestCaseWithFactory
from lp.testing.fixture import CapturedOutput
from lp.testing.layers import ZopelessDatabaseLayer
from lp.testing.script import run_script


class TestCopySigningKeysScript(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def makeScript(self, test_args=None, archives=None, expect_exit=False):
        test_args = [] if test_args is None else list(test_args)
        if archives is None:
            archives = [self.factory.makeArchive() for _ in range(2)]
        test_args.extend(archive.reference for archive in archives)
        try:
            with CapturedOutput() as captured:
                script = CopySigningKeysScript(
                    "copy-signingkeys",
                    dbuser=config.archivepublisher.dbuser,
                    test_args=test_args,
                )
                script.processOptions()
        except SystemExit:
            exited = True
        else:
            exited = False
        stdout = captured.stdout.getvalue()
        stderr = captured.stderr.getvalue()
        if stdout:
            self.addDetail("stdout", text_content(stdout))
        if stderr:
            self.addDetail("stderr", text_content(stderr))
        if expect_exit:
            if not exited:
                raise AssertionError("Script unexpectedly exited successfully")
        else:
            if exited:
                raise AssertionError(
                    "Script unexpectedly exited unsuccessfully"
                )
            self.assertEqual("", stderr)
            script.logger = BufferLogger()
            return script

    def findKeys(self, archives):
        return IStore(ArchiveSigningKey).find(
            ArchiveSigningKey,
            ArchiveSigningKey.archive_id.is_in(
                archive.id for archive in archives
            ),
        )

    def test_getArchive(self):
        archives = [self.factory.makeArchive() for _ in range(2)]
        script = self.makeScript(archives=archives)
        self.assertEqual(archives[0], script.from_archive)
        self.assertEqual(archives[1], script.to_archive)

    def test_getKeyTypes_all(self):
        script = self.makeScript()
        self.assertEqual(list(SigningKeyType.items), script.key_types)

    def test_getKeyTypes_with_selection(self):
        script = self.makeScript(test_args=["--key-type", "UEFI"])
        self.assertEqual([SigningKeyType.UEFI], script.key_types)

    def test_getSeries_none(self):
        script = self.makeScript()
        self.assertIsNone(script.series)

    def test_getSeries_no_such_series(self):
        archives = [self.factory.makeArchive() for _ in range(2)]
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "Could not find series 'nonexistent' in %s."
            % (archives[0].distribution.display_name),
            self.makeScript,
            test_args=["-s", "nonexistent"],
            archives=archives,
        )

    def test_getSeries(self):
        archives = [self.factory.makeArchive() for _ in range(2)]
        distro_series = self.factory.makeDistroSeries(
            distribution=archives[0].distribution
        )
        script = self.makeScript(
            test_args=["-s", distro_series.name], archives=archives
        )
        self.assertEqual(distro_series, script.series)

    def test_wrong_number_of_arguments(self):
        archives = [self.factory.makeArchive() for _ in range(3)]
        self.makeScript(archives=archives[:1], expect_exit=True)
        self.makeScript(archives=archives, expect_exit=True)

    def test_copy_all_no_series(self):
        archives = [self.factory.makeArchive() for _ in range(3)]
        signing_keys = [
            self.factory.makeSigningKey(key_type=key_type)
            for key_type in (
                SigningKeyType.UEFI,
                SigningKeyType.KMOD,
                SigningKeyType.OPAL,
            )
        ]
        for signing_key in signing_keys[:2]:
            self.factory.makeArchiveSigningKey(
                archive=archives[0], signing_key=signing_key
            )
        distro_series = self.factory.makeDistroSeries(
            distribution=archives[0].distribution
        )
        self.factory.makeArchiveSigningKey(
            archive=archives[0],
            distro_series=distro_series,
            signing_key=signing_keys[1],
        )
        self.factory.makeArchiveSigningKey(
            archive=archives[2], signing_key=signing_keys[2]
        )
        script = self.makeScript(archives=archives[:2])
        script.main()
        expected_log = [
            "INFO Copying UEFI signing key %s from %s / None to %s / None"
            % (
                signing_keys[0].fingerprint,
                archives[0].reference,
                archives[1].reference,
            ),
            "INFO Copying Kmod signing key %s from %s / None to %s / None"
            % (
                signing_keys[1].fingerprint,
                archives[0].reference,
                archives[1].reference,
            ),
            "INFO No OPAL signing key for %s / None" % archives[0].reference,
            "INFO No SIPL signing key for %s / None" % archives[0].reference,
            "INFO No FIT signing key for %s / None" % archives[0].reference,
            "INFO No OpenPGP signing key for %s / None"
            % archives[0].reference,
            "INFO No CV2 Kernel signing key for %s / None"
            % archives[0].reference,
            "INFO No Android Kernel signing key for %s / None"
            % archives[0].reference,
        ]
        self.assertEqual(
            expected_log, script.logger.content.as_text().splitlines()
        )
        self.assertThat(
            self.findKeys(archives),
            MatchesSetwise(
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=distro_series,
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
                MatchesStructure.byEquality(
                    archive=archives[2],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.OPAL,
                    signing_key=signing_keys[2],
                ),
            ),
        )

    def test_copy_by_key_type(self):
        archives = [self.factory.makeArchive() for _ in range(3)]
        signing_keys = [
            self.factory.makeSigningKey(key_type=key_type)
            for key_type in (SigningKeyType.UEFI, SigningKeyType.KMOD)
        ]
        for signing_key in signing_keys:
            self.factory.makeArchiveSigningKey(
                archive=archives[0], signing_key=signing_key
            )
        distro_series = self.factory.makeDistroSeries(
            distribution=archives[0].distribution
        )
        self.factory.makeArchiveSigningKey(
            archive=archives[0],
            distro_series=distro_series,
            signing_key=signing_keys[0],
        )
        script = self.makeScript(
            test_args=["--key-type", "UEFI"], archives=archives[:2]
        )
        script.main()
        expected_log = [
            "INFO Copying UEFI signing key %s from %s / None to %s / None"
            % (
                signing_keys[0].fingerprint,
                archives[0].reference,
                archives[1].reference,
            ),
        ]
        self.assertEqual(
            expected_log, script.logger.content.as_text().splitlines()
        )
        self.assertThat(
            self.findKeys(archives),
            MatchesSetwise(
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=distro_series,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
            ),
        )

    def test_copy_by_series(self):
        distribution = self.factory.makeDistribution()
        archives = [
            self.factory.makeArchive(distribution=distribution)
            for _ in range(3)
        ]
        signing_keys = [
            self.factory.makeSigningKey(key_type=key_type)
            for key_type in (SigningKeyType.UEFI, SigningKeyType.KMOD)
        ]
        distro_serieses = [
            self.factory.makeDistroSeries(distribution=distribution)
            for _ in range(2)
        ]
        for signing_key in signing_keys:
            self.factory.makeArchiveSigningKey(
                archive=archives[0],
                distro_series=distro_serieses[0],
                signing_key=signing_key,
            )
        self.factory.makeArchiveSigningKey(
            archive=archives[0], signing_key=signing_keys[0]
        )
        self.factory.makeArchiveSigningKey(
            archive=archives[0],
            distro_series=distro_serieses[1],
            signing_key=signing_keys[0],
        )
        script = self.makeScript(
            test_args=["-s", distro_serieses[0].name], archives=archives[:2]
        )
        script.main()
        expected_log = [
            "INFO Copying UEFI signing key %s from %s / %s to %s / %s"
            % (
                signing_keys[0].fingerprint,
                archives[0].reference,
                distro_serieses[0].name,
                archives[1].reference,
                distro_serieses[0].name,
            ),
            "INFO Copying Kmod signing key %s from %s / %s to %s / %s"
            % (
                signing_keys[1].fingerprint,
                archives[0].reference,
                distro_serieses[0].name,
                archives[1].reference,
                distro_serieses[0].name,
            ),
            "INFO No OPAL signing key for %s / %s"
            % (archives[0].reference, distro_serieses[0].name),
            "INFO No SIPL signing key for %s / %s"
            % (archives[0].reference, distro_serieses[0].name),
            "INFO No FIT signing key for %s / %s"
            % (archives[0].reference, distro_serieses[0].name),
            "INFO No OpenPGP signing key for %s / %s"
            % (archives[0].reference, distro_serieses[0].name),
            "INFO No CV2 Kernel signing key for %s / %s"
            % (archives[0].reference, distro_serieses[0].name),
            "INFO No Android Kernel signing key for %s / %s"
            % (archives[0].reference, distro_serieses[0].name),
        ]
        self.assertEqual(
            expected_log, script.logger.content.as_text().splitlines()
        )
        self.assertThat(
            self.findKeys(archives),
            MatchesSetwise(
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=distro_serieses[0],
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=distro_serieses[0],
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=distro_serieses[1],
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=distro_serieses[0],
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=distro_serieses[0],
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
            ),
        )

    def test_copy_refuses_overwrite(self):
        archives = [self.factory.makeArchive() for _ in range(2)]
        signing_keys = [
            self.factory.makeSigningKey(key_type=SigningKeyType.UEFI)
            for _ in range(2)
        ]
        for archive, signing_key in zip(archives, signing_keys):
            self.factory.makeArchiveSigningKey(
                archive=archive, signing_key=signing_key
            )
        script = self.makeScript(
            test_args=["--key-type", "UEFI"], archives=archives[:2]
        )
        script.main()
        expected_log = [
            "WARNING UEFI signing key for %s / None already exists"
            % archives[1].reference,
        ]
        self.assertEqual(
            expected_log, script.logger.content.as_text().splitlines()
        )
        self.assertThat(
            self.findKeys(archives),
            MatchesSetwise(
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[1],
                ),
            ),
        )

    def test_copy_forced_overwrite(self):
        archives = [self.factory.makeArchive() for _ in range(2)]
        signing_keys = [
            self.factory.makeSigningKey(key_type=SigningKeyType.UEFI)
            for _ in range(2)
        ]
        for archive, signing_key in zip(archives, signing_keys):
            self.factory.makeArchiveSigningKey(
                archive=archive, signing_key=signing_key
            )
        script = self.makeScript(
            test_args=["--key-type", "UEFI", "--overwrite"],
            archives=archives[:2],
        )
        script.main()

        expected_log = [
            "WARNING UEFI signing key for %s / None being overwritten"
            % (archives[1].reference),
            "INFO Copying UEFI signing key %s from %s / %s to %s / %s"
            % (
                signing_keys[0].fingerprint,
                archives[0].reference,
                None,
                archives[1].reference,
                None,
            ),
        ]
        self.assertEqual(
            expected_log, script.logger.content.as_text().splitlines()
        )
        self.assertThat(
            self.findKeys(archives),
            MatchesSetwise(
                # First archive keeps its signing keys.
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                # Second archive uses the same signing_key from first archive.
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
            ),
        )

    def runScript(self, args=None):
        transaction.commit()
        ret, out, err = run_script("scripts/copy-signingkeys.py", args=args)
        if out:
            self.addDetail("stdout", text_content(out))
        if err:
            self.addDetail("stderr", text_content(err))
        self.assertEqual(0, ret)
        transaction.commit()

    def test_script(self):
        archives = [self.factory.makeArchive() for _ in range(2)]
        signing_keys = [
            self.factory.makeSigningKey(key_type=key_type)
            for key_type in (SigningKeyType.UEFI, SigningKeyType.KMOD)
        ]
        for signing_key in signing_keys[:2]:
            self.factory.makeArchiveSigningKey(
                archive=archives[0], signing_key=signing_key
            )

        self.runScript(args=[archive.reference for archive in archives])

        self.assertThat(
            self.findKeys(archives),
            MatchesSetwise(
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[0],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.UEFI,
                    signing_key=signing_keys[0],
                ),
                MatchesStructure.byEquality(
                    archive=archives[1],
                    earliest_distro_series=None,
                    key_type=SigningKeyType.KMOD,
                    signing_key=signing_keys[1],
                ),
            ),
        )
