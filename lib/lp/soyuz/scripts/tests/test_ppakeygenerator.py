# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""`PPAKeyGenerator` script class tests."""

from zope.component import getUtility

from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.gpg import IGPGKeySet
from lp.registry.interfaces.person import IPersonSet
from lp.services.propertycache import get_property_cache
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.scripts.ppakeygenerator import PPAKeyGenerator
from lp.testing import TestCaseWithFactory
from lp.testing.faketransaction import FakeTransaction
from lp.testing.layers import LaunchpadZopelessLayer


class TestPPAKeyGenerator(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def _fixArchiveForKeyGeneration(self, archive):
        """Override the given archive distribution to 'ubuntutest'.

        This is necessary because 'ubuntutest' is the only distribution in
        the sampledata that contains a usable publishing configuration.
        """
        ubuntutest = getUtility(IDistributionSet).getByName("ubuntutest")
        archive.distribution = ubuntutest

    def _getKeyGenerator(
        self, archive_reference=None, copy_archives=False, txn=None
    ):
        """Return a `PPAKeyGenerator` instance.

        Monkey-patch the script object with a fake transaction manager
        and also make it use an alternative (fake and lighter) procedure
        to generate keys for each PPA.
        """
        test_args = []

        if archive_reference is not None:
            test_args.extend(["-A", archive_reference])
        if copy_archives:
            test_args.append("--copy-archives")

        key_generator = PPAKeyGenerator(
            name="ppa-generate-keys", test_args=test_args
        )

        if txn is None:
            txn = FakeTransaction()
        key_generator.txn = txn

        def fake_key_generation(archive):
            a_key = getUtility(IGPGKeySet).getByFingerprint(
                "ABCDEF0123456789ABCDDCBA0000111112345678"
            )
            archive.signing_key_fingerprint = a_key.fingerprint
            archive.signing_key_owner = a_key.owner
            del get_property_cache(archive).signing_key

        key_generator.generateKey = fake_key_generation

        return key_generator

    def testArchiveNotFound(self):
        """Raises an error if the specified archive does not exist."""
        key_generator = self._getKeyGenerator(archive_reference="~biscuit")
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "No archive named '~biscuit' could be found.",
            key_generator.main,
        )

    def testPPAAlreadyHasSigningKey(self):
        """Raises an error if the specified PPA already has a signing_key."""
        cprov = getUtility(IPersonSet).getByName("cprov")
        a_key = getUtility(IGPGKeySet).getByFingerprint(
            "ABCDEF0123456789ABCDDCBA0000111112345678"
        )
        cprov.archive.signing_key_fingerprint = a_key.fingerprint
        cprov.archive.signing_key_owner = a_key.owner

        key_generator = self._getKeyGenerator(
            archive_reference="~cprov/ubuntu/ppa"
        )
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            (
                "~cprov/ubuntu/ppa (PPA for Celso Providelo) already has a "
                "signing_key (%s)" % cprov.archive.signing_key_fingerprint
            ),
            key_generator.main,
        )

    def testGenerateKeyForASinglePPA(self):
        """Signing key generation for a single PPA.

        The 'signing_key' for the specified PPA is generated and
        the transaction is committed once.
        """
        cprov = getUtility(IPersonSet).getByName("cprov")
        self._fixArchiveForKeyGeneration(cprov.archive)

        self.assertIsNone(cprov.archive.signing_key_fingerprint)

        txn = FakeTransaction()
        key_generator = self._getKeyGenerator(
            archive_reference="~cprov/ubuntutest/ppa", txn=txn
        )
        key_generator.main()

        self.assertIsNotNone(cprov.archive.signing_key_fingerprint)
        self.assertEqual(txn.commit_count, 1)

    def testGenerateKeyForAllPPA(self):
        """Signing key generation for all PPAs.

        The 'signing_key' for all 'pending-signing-key' PPAs are generated
        and the transaction is committed once for each PPA.
        """
        archives = list(getUtility(IArchiveSet).getArchivesPendingSigningKey())

        for archive in archives:
            self._fixArchiveForKeyGeneration(archive)
            self.assertIsNone(archive.signing_key_fingerprint)

        txn = FakeTransaction()
        key_generator = self._getKeyGenerator(txn=txn)
        key_generator.main()

        for archive in archives:
            self.assertIsNotNone(archive.signing_key_fingerprint)

        self.assertEqual(txn.commit_count, len(archives))

    def testGenerateKeyForAllCopyArchives(self):
        """Signing key generation for all PPAs.

        The 'signing_key' for all 'pending-signing-key' PPAs are generated
        and the transaction is committed once for each PPA.
        """
        for _ in range(3):
            rebuild = self.factory.makeArchive(
                distribution=getUtility(IDistributionSet).getByName(
                    "ubuntutest"
                ),
                purpose=ArchivePurpose.COPY,
            )
            self.factory.makeSourcePackagePublishingHistory(archive=rebuild)

        archives = list(
            getUtility(IArchiveSet).getArchivesPendingSigningKey(
                purpose=ArchivePurpose.COPY
            )
        )
        self.assertNotEqual([], archives)

        for archive in archives:
            self._fixArchiveForKeyGeneration(archive)
            self.assertIsNone(archive.signing_key_fingerprint)

        txn = FakeTransaction()
        key_generator = self._getKeyGenerator(copy_archives=True, txn=txn)
        key_generator.main()

        for archive in archives:
            self.assertIsNotNone(archive.signing_key_fingerprint)

        self.assertEqual(txn.commit_count, len(archives))
