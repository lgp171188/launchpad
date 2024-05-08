# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""`PPAKeyUpdater` script class tests."""
import random

import responses
from fixtures.testcase import TestWithFixtures
from testtools.testcase import ExpectedException
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    PUBLISHER_GPG_USES_SIGNING_SERVICE,
    IArchiveGPGSigningKey,
)
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.gpg import IGPGKeySet
from lp.services.features.testing import FeatureFixture
from lp.services.gpg.interfaces import IGPGHandler
from lp.services.log.logger import BufferLogger
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
)
from lp.services.signing.tests.test_proxy import SigningServiceResponseFactory
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.scripts.ppakeyupdater import PPAKeyUpdater
from lp.testing import TestCaseWithFactory
from lp.testing.faketransaction import FakeTransaction
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import LaunchpadZopelessLayer


class FakeGPGHandlerSubmitKey:
    def submitKey(self, content):
        return


def fingerprintGenerator(prefix="4096"):
    letters = ["A", "B", "C", "D", "E", "F"]
    return prefix + "".join(
        random.choice(letters) for _ in range(40 - len(prefix))
    )


class TestPPAKeyUpdater(TestCaseWithFactory, TestWithFixtures):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()

        self.response_factory = SigningServiceResponseFactory(
            fingerprintGenerator
        )

        client = removeSecurityProxy(getUtility(ISigningServiceClient))
        self.addCleanup(client._cleanCaches)
        self.useFixture(
            ZopeUtilityFixture(FakeGPGHandlerSubmitKey(), IGPGHandler)
        )

    def makeArchivesWithRSAKey(self, key_size, archives_number=1):
        archives = []
        key_fingerprint = fingerprintGenerator(str(key_size))
        owner = self.factory.makePerson()
        self.factory.makeGPGKey(
            owner=owner,
            keyid=key_fingerprint[-8:],
            fingerprint=key_fingerprint,
            keysize=key_size,
        )
        self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=key_fingerprint
        )
        for _ in range(archives_number):
            ppa = self.factory.makeArchive(
                owner=owner,
                distribution=getUtility(IDistributionSet).getByName(
                    "ubuntutest"
                ),
                purpose=ArchivePurpose.PPA,
            )
            ppa.signing_key_fingerprint = key_fingerprint
            archives.append(ppa)
        return archives

    def _getKeyUpdater(self, limit=None, txn=None):
        """Return a `PPAKeyUpdater` instance.

        Monkey-patch the script instance with a fake transaction manager.
        """
        test_args = []
        if limit:
            test_args.extend(["-L", limit])

        self.logger = BufferLogger()
        key_generator = PPAKeyUpdater(
            name="ppa-generate-keys", test_args=test_args, logger=self.logger
        )

        if txn is None:
            txn = FakeTransaction()
        key_generator.txn = txn

        return key_generator

    def testNoPPAsToUpdate(self):
        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 0", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 0)

    def testNoPPAsToUpdate_with_nothing_to_update(self):
        # Create archives with 4096-bit RSA key.
        self.makeArchivesWithRSAKey(key_size=4096, archives_number=10)

        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 0", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 0)

    @responses.activate
    def testNoPPAsToUpdate_mixed(self):
        self.response_factory.addResponses(self)
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        # Create archives with 4096-bit RSA key.
        self.makeArchivesWithRSAKey(key_size=4096, archives_number=10)

        # Create archives with 1024-bit RSA key.
        self.makeArchivesWithRSAKey(key_size=1024, archives_number=10)

        # Update the archives with 1024 so that they have both keys.
        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 10", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 10)

        # Now we have 10 archives with 4096-bit RSA key
        # and 10 archives with both 1024-bit and 4096-bit RSA key.
        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 0", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 0)

    @responses.activate
    def testGenerate4096KeyForPPAsWithSameOwner(self):
        """Test signing key update for PPAs with the same owner.

        Verify that a new 4096-bit signing key is generated for the
        default ppa and propagated to the other PPAs.
        """
        self.response_factory.addResponses(self)
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        archives_number = 3
        archives = self.makeArchivesWithRSAKey(
            key_size=1024, archives_number=archives_number
        )

        # Create archives with 4096-bit RSA key.
        self.makeArchivesWithRSAKey(
            key_size=4096, archives_number=archives_number
        )

        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 3", self.logger.getLogBuffer())
        self.assertIn("Archives updated!", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, archives_number)
        new_signing_keys = []
        for archive in archives:

            # Check if 4096-bit RSA signing key exists.
            signing_key = getUtility(
                IArchiveSigningKeySet
            ).get4096BitRSASigningKey(archive)
            self.assertIsNot(None, signing_key)

            # Retrieve the old 1024-bit RSA signing key using
            # the archive fingerprint.
            old_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                archive.signing_key_fingerprint
            )
            self.assertIsNot(None, old_gpg_key)
            self.assertEqual(1024, old_gpg_key.keysize)

            # Check if the new signing key is correctly
            # added to the `gpgkey` table.
            new_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                signing_key.fingerprint
            )
            self.assertIsNot(None, new_gpg_key)
            self.assertEqual(4096, new_gpg_key.keysize)

            # Assert that the two keys are different.
            self.assertIsNot(old_gpg_key, new_gpg_key)
            new_signing_keys.append(signing_key.fingerprint)

        # Assert that all the new keys are equal.
        self.assertEqual(1, len(set(new_signing_keys)))

    @responses.activate
    def testGenerate4096KeyForPPAsDifferentOwners(self):
        """Test signing key update for PPAs with different owners.

        Verify that a new 4096-bit RSA signing key is generated per
        archive owner and propagated to all archives of the same owner.
        """
        self.response_factory.addResponses(self)
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        archives_number = 3
        archives = []
        for _ in range(archives_number):
            archives.extend(self.makeArchivesWithRSAKey(key_size=1024))

        # Create archives with 4096-bit RSA key.
        self.makeArchivesWithRSAKey(
            key_size=4096, archives_number=archives_number
        )

        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 3", self.logger.getLogBuffer())
        self.assertIn("Archives updated!", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, archives_number)

        new_signing_keys = []
        for archive in archives:

            # Check if 4096-bit RSA signing key exists.
            signing_key = getUtility(
                IArchiveSigningKeySet
            ).get4096BitRSASigningKey(archive)
            self.assertIsNot(None, signing_key)

            # Retrieve the old 1024-bit signing key using
            # the archive fingerprint.
            old_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                archive.signing_key_fingerprint
            )
            self.assertIsNot(None, old_gpg_key)
            self.assertEqual(1024, old_gpg_key.keysize)

            # Check if the new signing key is correctly
            # added to the `gpgkey` table.
            new_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                signing_key.fingerprint
            )
            self.assertIsNot(None, new_gpg_key)
            self.assertEqual(4096, new_gpg_key.keysize)

            # Assert that the two keys are different.
            self.assertIsNot(old_gpg_key, new_gpg_key)
            new_signing_keys.append(signing_key.fingerprint)

        # Assert that all the keys are different since PPAs
        # belong to different users.
        self.assertEqual(len(new_signing_keys), len(set(new_signing_keys)))

    @responses.activate
    def testGenerate4096KeyForPPAsLimit(self):
        """Test limiting the archives to update the key for in a run.

        Verify that only the specified number of archives are processed.
        """
        self.response_factory.addResponses(self)
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        archives_number = 3
        archives = self.makeArchivesWithRSAKey(
            key_size=1024, archives_number=archives_number
        )

        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn, limit="2")
        key_generator.main()

        # 2/3 PPAs processed.
        self.assertIn("Archives to update: 2", self.logger.getLogBuffer())
        self.assertIn("Archives updated!", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 2)

        new_signing_keys = []
        # Check the first 2 archives.
        for archive in archives[:2]:

            # Check if 4096-bit RSA signing key exists.
            signing_key = getUtility(
                IArchiveSigningKeySet
            ).get4096BitRSASigningKey(archive)
            self.assertIsNot(None, signing_key)

            # Retrieve the old 1024-bit signing key using
            # the archive fingerprint.
            old_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                archive.signing_key_fingerprint
            )
            self.assertIsNot(None, old_gpg_key)
            self.assertEqual(1024, old_gpg_key.keysize)

            # Check if the new signing key is correctly
            # added to the `gpgkey` table.
            new_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                signing_key.fingerprint
            )
            self.assertIsNot(None, new_gpg_key)
            self.assertEqual(4096, new_gpg_key.keysize)

            # Assert that the two keys are different
            self.assertIsNot(old_gpg_key, new_gpg_key)
            new_signing_keys.append(signing_key.fingerprint)

        key_generator = self._getKeyUpdater(limit="2", txn=txn)
        key_generator.main()

        # 3/3 PPAs processed.
        self.assertIn("Archives to update: 1", self.logger.getLogBuffer())
        self.assertIn("Archives updated!", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 3)

        # Check the last archive.
        for archive in archives[-1:]:

            # Check if 4096-bit RSA signing key exists.
            signing_key = getUtility(
                IArchiveSigningKeySet
            ).get4096BitRSASigningKey(archive)
            self.assertIsNot(None, signing_key)

            # Retrieve the old 1024-bit signing key using
            # the archive fingerprint.
            old_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                archive.signing_key_fingerprint
            )
            self.assertIsNot(None, old_gpg_key)
            self.assertEqual(1024, old_gpg_key.keysize)

            # Check if the new signing key is correctly
            # added to the `gpgkey` table.
            new_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
                signing_key.fingerprint
            )
            self.assertIsNot(None, new_gpg_key)
            self.assertEqual(4096, new_gpg_key.keysize)

            # Assert that the two keys are different.
            self.assertIsNot(old_gpg_key, new_gpg_key)
            new_signing_keys.append(signing_key.fingerprint)

        self.assertEqual(archives_number, len(new_signing_keys))

    def testPPAFingerprintNone(self):
        """Signing key update for PPA without a key.

        This should raise an AssertionError.
        """
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        archive = self.factory.makeArchive()
        archive_signing_key = IArchiveGPGSigningKey(archive)
        with ExpectedException(
            AssertionError,
            "Archive doesn't have an existing signing key to update.",
        ):
            archive_signing_key.generate4096BitRSASigningKey()

    def testPPAAlreadyUpdated(self):
        """Signing key update for PPA with a 4096-bit RSA key.

        This should raise an AssertionError.
        """
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        archives = self.makeArchivesWithRSAKey(key_size=4096)
        archive = archives[0]
        archive_signing_key = IArchiveGPGSigningKey(archive)
        with ExpectedException(
            AssertionError, "Archive already has a 4096-bit RSA signing key."
        ):
            archive_signing_key.generate4096BitRSASigningKey()

    def testPPAUpdaterNoneFlag(self):
        """Signing key update with signing service disabled.

        This should raise an AssertionError.
        """
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: None})
        )
        archive = self.factory.makeArchive()
        archive_signing_key = IArchiveGPGSigningKey(archive)
        with ExpectedException(
            AssertionError,
            "Signing service should be enabled to use this feature.",
        ):
            archive_signing_key.generate4096BitRSASigningKey()

    @responses.activate
    def testMatchingArchiveButDefaultArchiveHasNoFingerprint(self):
        self.response_factory.addResponses(self)
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        owner = self.factory.makePerson()
        default_archive = self.factory.makeArchive(owner=owner)
        another_archive = self.factory.makeArchive(owner=owner)
        fingerprint = self.factory.getUniqueHexString(40).upper()
        logger = BufferLogger()
        self.factory.makeGPGKey(
            owner=owner,
            keyid=fingerprint[-8:],
            fingerprint=fingerprint,
            keysize=1024,
        )
        self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=fingerprint
        )
        another_archive.signing_key_fingerprint = fingerprint
        # The default archive does not a have a signing key fingerprint
        self.assertIsNone(default_archive.signing_key_fingerprint)

        archive_signing_key = IArchiveGPGSigningKey(another_archive)
        archive_signing_key.generate4096BitRSASigningKey(log=logger)

        # The default archive should now have a signing key fingerprint
        self.assertIsNotNone(default_archive.signing_key_fingerprint)
        # The default archive's current signing key must be present
        # in the archivesigningkey table.
        default_archive_new_signing_key = getUtility(
            IArchiveSigningKeySet
        ).get4096BitRSASigningKey(default_archive)
        self.assertIsNotNone(default_archive_new_signing_key)
        # The default archive's current signing key must be present in
        # the gpgkey table.
        default_archive_new_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
            default_archive.signing_key_fingerprint
        )
        self.assertIsNotNone(default_archive_new_gpg_key)
        # 'another_archive' must have a new 4096-bit signing key in the
        # archivesigningkey table and its fingerprint must be the same as
        # that of the default archive's current/new signing key.
        another_archive_new_signing_key = getUtility(
            IArchiveSigningKeySet
        ).get4096BitRSASigningKey(another_archive)
        self.assertIsNotNone(another_archive_new_signing_key)
        self.assertEqual(
            another_archive_new_signing_key.fingerprint,
            default_archive.signing_key_fingerprint,
        )
        # 'another_archive' must also have a row in the archivesigningkey
        # table for its current signing key.
        another_archive_current_signing_key = getUtility(
            IArchiveSigningKeySet
        ).getByArchiveAndFingerprint(
            another_archive, another_archive.signing_key_fingerprint
        )
        self.assertIsNotNone(another_archive_current_signing_key)
        # Both the default archive and the 'another_archive' archive
        # no longer require the generation of a new 4096-bit RSA signing key.
        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 0", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 0)

    def testPPAMatchingArchiveDefaultArchiveHasSecureExistingKey(self):
        self.useFixture(
            FeatureFixture({PUBLISHER_GPG_USES_SIGNING_SERVICE: "on"})
        )
        owner = self.factory.makePerson()
        default_archive = self.factory.makeArchive(owner=owner)
        another_archive = self.factory.makeArchive(owner=owner)
        default_archive_fingerprint = self.factory.getUniqueHexString(
            40
        ).upper()
        default_archive.signing_key_fingerprint = default_archive_fingerprint
        self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP,
            fingerprint=default_archive_fingerprint,
        )
        another_archive_fingerprint = self.factory.getUniqueHexString(
            40
        ).upper()
        logger = BufferLogger()
        self.factory.makeGPGKey(
            owner=owner,
            keyid=another_archive_fingerprint[-8:],
            fingerprint=another_archive_fingerprint,
            keysize=1024,
        )
        self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP,
            fingerprint=another_archive_fingerprint,
        )
        another_archive.signing_key_fingerprint = another_archive_fingerprint
        archive_signing_key = IArchiveGPGSigningKey(another_archive)
        archive_signing_key.generate4096BitRSASigningKey(log=logger)

        # The default archive's current signing key must be present
        # in the archivesigningkey table.
        default_archive_signing_key = getUtility(
            IArchiveSigningKeySet
        ).get4096BitRSASigningKey(default_archive)
        self.assertIsNotNone(default_archive_signing_key)
        # The default archive's current signing key must be present in
        # the gpgkey table.
        default_archive_gpg_key = getUtility(IGPGKeySet).getByFingerprint(
            default_archive.signing_key_fingerprint
        )
        self.assertIsNotNone(default_archive_gpg_key)
        # 'another_archive' must have a new 4096-bit signing key in the
        # archivesigningkey table and its fingerprint must be the same as
        # that of the default archive's current/new signing key.
        another_archive_new_signing_key = getUtility(
            IArchiveSigningKeySet
        ).get4096BitRSASigningKey(another_archive)
        self.assertIsNotNone(another_archive_new_signing_key)
        self.assertEqual(
            another_archive_new_signing_key.fingerprint,
            default_archive.signing_key_fingerprint,
        )
        # 'another_archive' must also have a row in the archivesigningkey
        # table for its current signing key.
        another_archive_current_signing_key = getUtility(
            IArchiveSigningKeySet
        ).getByArchiveAndFingerprint(
            another_archive, another_archive.signing_key_fingerprint
        )
        self.assertIsNotNone(another_archive_current_signing_key)
        # Both the default archive and the 'another_archive' archive
        # no longer require the generation of a new 4096-bit RSA signing key.
        txn = FakeTransaction()
        key_generator = self._getKeyUpdater(txn=txn)
        key_generator.main()

        self.assertIn("Archives to update: 0", self.logger.getLogBuffer())
        self.assertEqual(txn.commit_count, 0)
