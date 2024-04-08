# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64
from datetime import datetime, timezone

import responses
from fixtures.testcase import TestWithFixtures
from nacl.public import PrivateKey
from storm.store import Store
from testtools.matchers import (
    AfterPreprocessing,
    Equals,
    MatchesDict,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.services.database.interfaces import IPrimaryStore
from lp.services.signing.enums import SigningKeyType, SigningMode
from lp.services.signing.interfaces.signingkey import (
    IArchiveSigningKeySet,
    ISigningKeySet,
)
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
)
from lp.services.signing.model.signingkey import ArchiveSigningKey, SigningKey
from lp.services.signing.tests.test_proxy import SigningServiceResponseFactory
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestSigningKey(TestCaseWithFactory, TestWithFixtures):
    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

        client = removeSecurityProxy(getUtility(ISigningServiceClient))
        self.addCleanup(client._cleanCaches)

    def test_get(self):
        signing_keys = [
            self.factory.makeSigningKey(key_type=key_type)
            for key_type in (SigningKeyType.UEFI, SigningKeyType.OPENPGP)
        ]
        fingerprints = [
            signing_key.fingerprint for signing_key in signing_keys
        ]
        signing_key_set = getUtility(ISigningKeySet)
        self.assertEqual(
            signing_keys[0],
            signing_key_set.get(SigningKeyType.UEFI, fingerprints[0]),
        )
        self.assertEqual(
            signing_keys[1],
            signing_key_set.get(SigningKeyType.OPENPGP, fingerprints[1]),
        )
        self.assertIsNone(
            signing_key_set.get(SigningKeyType.UEFI, fingerprints[1])
        )
        self.assertIsNone(
            signing_key_set.get(SigningKeyType.OPENPGP, fingerprints[0])
        )

    @responses.activate
    def test_generate_signing_key_saves_correctly(self):
        self.signing_service.addResponses(self)

        key = SigningKey.generate(SigningKeyType.UEFI, "this is my key")
        self.assertIsInstance(key, SigningKey)

        store = IPrimaryStore(SigningKey)
        store.invalidate()

        rs = store.find(SigningKey)
        self.assertEqual(1, rs.count())
        db_key = rs.one()

        self.assertEqual(SigningKeyType.UEFI, db_key.key_type)
        self.assertEqual(
            self.signing_service.generated_fingerprint, db_key.fingerprint
        )
        self.assertEqual(
            self.signing_service.b64_generated_public_key.encode("UTF-8"),
            base64.b64encode(db_key.public_key),
        )
        self.assertEqual("this is my key", db_key.description)

    @responses.activate
    def test_inject_signing_key_saves_correctly(self):
        self.signing_service.addResponses(self)

        priv_key = PrivateKey.generate()
        pub_key = priv_key.public_key
        created_at = datetime(2020, 4, 16, 16, 35).replace(tzinfo=timezone.utc)

        key = SigningKey.inject(
            SigningKeyType.KMOD,
            bytes(priv_key),
            bytes(pub_key),
            "This is a test key",
            created_at,
        )
        self.assertIsInstance(key, SigningKey)

        store = IPrimaryStore(SigningKey)
        store.invalidate()

        rs = store.find(SigningKey)
        self.assertEqual(1, rs.count())
        db_key = rs.one()

        self.assertEqual(SigningKeyType.KMOD, db_key.key_type)
        self.assertEqual(
            self.signing_service.generated_fingerprint, db_key.fingerprint
        )
        self.assertEqual(bytes(pub_key), db_key.public_key)
        self.assertEqual("This is a test key", db_key.description)
        self.assertEqual(created_at, db_key.date_created)

    @responses.activate
    def test_inject_signing_key_with_existing_fingerprint(self):
        self.signing_service.addResponses(self)

        priv_key = PrivateKey.generate()
        pub_key = priv_key.public_key
        created_at = datetime(2020, 4, 16, 16, 35).replace(tzinfo=timezone.utc)

        key = SigningKey.inject(
            SigningKeyType.KMOD,
            bytes(priv_key),
            bytes(pub_key),
            "This is a test key",
            created_at,
        )
        self.assertIsInstance(key, SigningKey)

        store = IPrimaryStore(SigningKey)
        store.flush()

        # This should give back the same key
        new_key = SigningKey.inject(
            SigningKeyType.KMOD,
            bytes(priv_key),
            bytes(pub_key),
            "This is a test key with another description",
            created_at,
        )
        store.flush()

        self.assertEqual(key.id, new_key.id)
        self.assertEqual(5, len(responses.calls))

    @responses.activate
    def test_sign(self):
        self.signing_service.addResponses(self)

        s = SigningKey(
            SigningKeyType.UEFI,
            "a fingerprint",
            bytes(self.signing_service.generated_public_key),
            description="This is my key!",
        )
        signed = s.sign(b"secure message", "message_name")

        # Checks if the returned value is actually the returning value from
        # HTTP POST /sign call to lp-signing service
        self.assertEqual(3, len(responses.calls))
        self.assertThat(
            responses.calls[2].request,
            MatchesStructure(
                url=Equals(self.signing_service.getUrl("/sign")),
                body=AfterPreprocessing(
                    self.signing_service._decryptPayload,
                    MatchesDict(
                        {
                            "key-type": Equals("UEFI"),
                            "fingerprint": Equals("a fingerprint"),
                            "message-name": Equals("message_name"),
                            "message": Equals(
                                base64.b64encode(b"secure message").decode(
                                    "UTF-8"
                                )
                            ),
                            "mode": Equals("ATTACHED"),
                        }
                    ),
                ),
            ),
        )
        self.assertEqual(self.signing_service.getAPISignedContent(), signed)

    @responses.activate
    def test_sign_openpgp_modes(self):
        self.signing_service.addResponses(self)

        s = SigningKey(
            SigningKeyType.OPENPGP,
            "a fingerprint",
            bytes(self.signing_service.generated_public_key),
            description="This is my key!",
        )
        s.sign(b"secure message", "message_name")
        s.sign(b"another message", "another_name", mode=SigningMode.CLEAR)

        self.assertEqual(5, len(responses.calls))
        self.assertThat(
            responses.calls[2].request,
            MatchesStructure(
                url=Equals(self.signing_service.getUrl("/sign")),
                body=AfterPreprocessing(
                    self.signing_service._decryptPayload,
                    MatchesDict(
                        {
                            "key-type": Equals("OPENPGP"),
                            "fingerprint": Equals("a fingerprint"),
                            "message-name": Equals("message_name"),
                            "message": Equals(
                                base64.b64encode(b"secure message").decode(
                                    "UTF-8"
                                )
                            ),
                            "mode": Equals("DETACHED"),
                        }
                    ),
                ),
            ),
        )
        self.assertThat(
            responses.calls[4].request,
            MatchesStructure(
                url=Equals(self.signing_service.getUrl("/sign")),
                body=AfterPreprocessing(
                    self.signing_service._decryptPayload,
                    MatchesDict(
                        {
                            "key-type": Equals("OPENPGP"),
                            "fingerprint": Equals("a fingerprint"),
                            "message-name": Equals("another_name"),
                            "message": Equals(
                                base64.b64encode(b"another message").decode(
                                    "UTF-8"
                                )
                            ),
                            "mode": Equals("CLEAR"),
                        }
                    ),
                ),
            ),
        )

    @responses.activate
    def test_addAuthorization(self):
        self.signing_service.addResponses(self)

        s = SigningKey(
            SigningKeyType.UEFI,
            "a fingerprint",
            bytes(self.signing_service.generated_public_key),
            description="This is my key!",
        )
        self.assertIsNone(s.addAuthorization("another-client"))

        self.assertEqual(3, len(responses.calls))
        self.assertThat(
            responses.calls[2].request,
            MatchesStructure(
                url=Equals(self.signing_service.getUrl("/authorizations/add")),
                body=AfterPreprocessing(
                    self.signing_service._decryptPayload,
                    MatchesDict(
                        {
                            "key-type": Equals("UEFI"),
                            "fingerprint": Equals("a fingerprint"),
                            "client-name": Equals("another-client"),
                        }
                    ),
                ),
            ),
        )


class TestArchiveSigningKey(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

        client = removeSecurityProxy(getUtility(ISigningServiceClient))
        self.addCleanup(client._cleanCaches)

    def assertGet(
        self,
        expected_archive_signing_key,
        key_type,
        archive,
        distro_series,
        exact_match=False,
    ):
        # get and getSigningKey return the expected results.
        arch_signing_key_set = getUtility(IArchiveSigningKeySet)
        expected_signing_key = (
            None
            if expected_archive_signing_key is None
            else expected_archive_signing_key.signing_key
        )
        self.assertEqual(
            expected_archive_signing_key,
            arch_signing_key_set.get(
                key_type, archive, distro_series, exact_match=exact_match
            ),
        )
        self.assertEqual(
            expected_signing_key,
            arch_signing_key_set.getSigningKey(
                key_type, archive, distro_series, exact_match=exact_match
            ),
        )

    @responses.activate
    def test_generate_saves_correctly(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        arch_key = getUtility(IArchiveSigningKeySet).generate(
            SigningKeyType.UEFI,
            "some description",
            archive,
            earliest_distro_series=distro_series,
        )

        store = Store.of(arch_key)
        store.invalidate()

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, rs.count())

        db_arch_key = rs.one()
        self.assertThat(
            db_arch_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                archive=archive,
                earliest_distro_series=distro_series,
            ),
        )

        self.assertThat(
            db_arch_key.signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                description="some description",
                fingerprint=self.signing_service.generated_fingerprint,
                public_key=bytes(self.signing_service.generated_public_key),
            ),
        )

    @responses.activate
    def test_getByArchiveAndFingerprint(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        arch_key = getUtility(IArchiveSigningKeySet).generate(
            SigningKeyType.UEFI,
            "some description",
            archive,
            earliest_distro_series=distro_series,
        )

        store = Store.of(arch_key)
        store.invalidate()

        archive_signing_key = getUtility(
            IArchiveSigningKeySet
        ).getByArchiveAndFingerprint(archive, arch_key.signing_key.fingerprint)
        self.assertIsNot(None, archive_signing_key)

        self.assertThat(
            archive_signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                archive=archive,
                earliest_distro_series=distro_series,
            ),
        )

        self.assertThat(
            archive_signing_key.signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                fingerprint=self.signing_service.generated_fingerprint,
                public_key=bytes(self.signing_service.generated_public_key),
            ),
        )

    @responses.activate
    def test_getByArchiveAndFingerprint_wrong_fingerprint(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        arch_key = getUtility(IArchiveSigningKeySet).generate(
            SigningKeyType.UEFI,
            "some description",
            archive,
            earliest_distro_series=distro_series,
        )

        store = Store.of(arch_key)
        store.invalidate()

        archive_signing_key = getUtility(
            IArchiveSigningKeySet
        ).getByArchiveAndFingerprint(archive, "wrong_fingerprint")
        self.assertEqual(None, archive_signing_key)

    @responses.activate
    def test_get4096BitRSASigningKey(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()

        gpg_key = self.factory.makeGPGKey(
            archive.owner,
            keysize=4096,
        )
        expected_signing_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=gpg_key.fingerprint
        )

        archive_signing_key = getUtility(IArchiveSigningKeySet).create(
            archive, None, expected_signing_key
        )

        store = Store.of(archive_signing_key)
        store.invalidate()

        actual_signing_key = getUtility(
            IArchiveSigningKeySet
        ).get4096BitRSASigningKey(archive)

        self.assertIsNot(None, actual_signing_key)
        self.assertEqual(expected_signing_key, actual_signing_key)

    @responses.activate
    def test_get4096BitRSASigningKey_none(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()

        gpg_key = self.factory.makeGPGKey(
            archive.owner,
            keysize=1024,
        )
        signing_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=gpg_key.fingerprint
        )

        archive_signing_key = getUtility(IArchiveSigningKeySet).create(
            archive, None, signing_key
        )

        store = Store.of(archive_signing_key)
        store.invalidate()

        actual_signing_key = getUtility(
            IArchiveSigningKeySet
        ).get4096BitRSASigningKey(archive)

        self.assertEqual(None, actual_signing_key)

    @responses.activate
    def test_inject_saves_correctly(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        priv_key = PrivateKey.generate()
        pub_key = priv_key.public_key

        now = datetime.now().replace(tzinfo=timezone.utc)
        arch_key = getUtility(IArchiveSigningKeySet).inject(
            SigningKeyType.UEFI,
            bytes(priv_key),
            bytes(pub_key),
            "Some description",
            now,
            archive,
            earliest_distro_series=distro_series,
        )

        store = Store.of(arch_key)
        store.invalidate()

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, rs.count())

        db_arch_key = rs.one()
        self.assertThat(
            db_arch_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                archive=archive,
                earliest_distro_series=distro_series,
            ),
        )

        self.assertThat(
            db_arch_key.signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                description="Some description",
                fingerprint=self.signing_service.generated_fingerprint,
                public_key=bytes(pub_key),
            ),
        )

    @responses.activate
    def test_inject_same_key_for_different_archives(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        priv_key = PrivateKey.generate()
        pub_key = priv_key.public_key

        now = datetime.now().replace(tzinfo=timezone.utc)
        arch_key = getUtility(IArchiveSigningKeySet).inject(
            SigningKeyType.UEFI,
            bytes(priv_key),
            bytes(pub_key),
            "Some description",
            now,
            archive,
            earliest_distro_series=distro_series,
        )

        store = Store.of(arch_key)

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, rs.count())

        db_arch_key = rs.one()
        self.assertThat(
            db_arch_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                archive=archive,
                earliest_distro_series=distro_series,
            ),
        )

        self.assertThat(
            db_arch_key.signing_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                description="Some description",
                fingerprint=self.signing_service.generated_fingerprint,
                public_key=bytes(pub_key),
            ),
        )

        # Inject the same key for a new archive, and check that the
        # corresponding SigningKey object is the same.
        another_archive = self.factory.makeArchive()

        another_arch_key = getUtility(IArchiveSigningKeySet).inject(
            SigningKeyType.UEFI,
            bytes(priv_key),
            bytes(pub_key),
            "Another description",
            now,
            another_archive,
        )

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(2, rs.count())

        another_db_arch_key = rs.order_by("id").last()
        self.assertNotEqual(another_arch_key.id, arch_key.id)
        self.assertEqual(another_arch_key.signing_key, arch_key.signing_key)

        self.assertThat(
            another_db_arch_key,
            MatchesStructure.byEquality(
                key_type=SigningKeyType.UEFI,
                archive=another_archive,
                earliest_distro_series=None,
            ),
        )

    def test_create(self):
        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]
        signing_key = self.factory.makeSigningKey()

        arch_signing_key_set = getUtility(IArchiveSigningKeySet)

        arch_key = arch_signing_key_set.create(
            archive, distro_series, signing_key
        )

        store = Store.of(arch_key)
        store.invalidate()
        rs = store.find(ArchiveSigningKey)

        self.assertEqual(1, rs.count())
        db_arch_key = rs.one()
        self.assertThat(
            db_arch_key,
            MatchesStructure.byEquality(
                key_type=signing_key.key_type,
                archive=archive,
                earliest_distro_series=distro_series,
                signing_key=signing_key,
            ),
        )

        # Saving another type should create a new entry
        signing_key_from_another_type = self.factory.makeSigningKey(
            key_type=SigningKeyType.KMOD
        )
        arch_signing_key_set.create(
            archive, distro_series, signing_key_from_another_type
        )

        self.assertEqual(2, store.find(ArchiveSigningKey).count())

    def test_get_signing_keys_without_distro_series_configured(self):
        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]
        uefi_key = self.factory.makeSigningKey(key_type=SigningKeyType.UEFI)
        kmod_key = self.factory.makeSigningKey(key_type=SigningKeyType.KMOD)

        # Fill the database with keys from other archives to make sure we
        # are filtering it out
        other_archive = self.factory.makeArchive()
        arch_signing_key_set = getUtility(IArchiveSigningKeySet)
        arch_signing_key_set.create(
            other_archive, None, self.factory.makeSigningKey()
        )

        # Create a key for the archive (no specific series)
        arch_uefi_key = arch_signing_key_set.create(archive, None, uefi_key)
        arch_kmod_key = arch_signing_key_set.create(archive, None, kmod_key)

        # Should find the keys if we ask for the archive key
        self.assertGet(arch_uefi_key, SigningKeyType.UEFI, archive, None)
        self.assertGet(arch_kmod_key, SigningKeyType.KMOD, archive, None)

        # Should find the key if we ask for archive + distro_series key
        self.assertGet(
            arch_uefi_key, SigningKeyType.UEFI, archive, distro_series
        )
        self.assertGet(
            arch_kmod_key, SigningKeyType.KMOD, archive, distro_series
        )

    def test_get_signing_key_exact_match(self):
        archive = self.factory.makeArchive()
        distro_series1 = archive.distribution.series[0]
        distro_series2 = archive.distribution.series[1]
        uefi_key = self.factory.makeSigningKey(key_type=SigningKeyType.UEFI)
        kmod_key = self.factory.makeSigningKey(key_type=SigningKeyType.KMOD)

        arch_signing_key_set = getUtility(IArchiveSigningKeySet)

        # Create a key for the first distro series
        series1_uefi_key = arch_signing_key_set.create(
            archive, distro_series1, uefi_key
        )

        # Create a key for the archive
        arch_kmod_key = arch_signing_key_set.create(archive, None, kmod_key)

        # Should get the UEFI key for distro_series1
        self.assertGet(
            series1_uefi_key,
            SigningKeyType.UEFI,
            archive,
            distro_series1,
            exact_match=True,
        )
        # Should get the archive's KMOD key.
        self.assertGet(
            arch_kmod_key, SigningKeyType.KMOD, archive, None, exact_match=True
        )
        # distro_series1 has no KMOD key.
        self.assertGet(
            None,
            SigningKeyType.KMOD,
            archive,
            distro_series1,
            exact_match=True,
        )
        # distro_series2 has no key at all.
        self.assertGet(
            None,
            SigningKeyType.KMOD,
            archive,
            distro_series2,
            exact_match=True,
        )

    def test_get_signing_keys_with_distro_series_configured(self):
        archive = self.factory.makeArchive()
        series = archive.distribution.series
        uefi_key = self.factory.makeSigningKey(key_type=SigningKeyType.UEFI)
        kmod_key = self.factory.makeSigningKey(key_type=SigningKeyType.KMOD)

        # Fill the database with keys from other archives to make sure we
        # are filtering it out
        other_archive = self.factory.makeArchive()
        arch_signing_key_set = getUtility(IArchiveSigningKeySet)
        arch_signing_key_set.create(
            other_archive, None, self.factory.makeSigningKey()
        )

        # Create a key for the archive (no specific series)
        arch_uefi_key = arch_signing_key_set.create(archive, None, uefi_key)

        # for kmod, should give back this one if provided a
        # newer distro series
        arch_kmod_key = arch_signing_key_set.create(
            archive, series[1], kmod_key
        )
        old_arch_kmod_key = arch_signing_key_set.create(
            archive, series[2], kmod_key
        )

        # If no distroseries is specified, it should give back no KMOD key,
        # since we don't have a default
        self.assertGet(arch_uefi_key, SigningKeyType.UEFI, archive, None)
        self.assertGet(None, SigningKeyType.KMOD, archive, None)

        # For the most recent series, use the KMOD key we've set for the
        # previous one
        self.assertGet(arch_uefi_key, SigningKeyType.UEFI, archive, series[0])
        self.assertGet(arch_kmod_key, SigningKeyType.KMOD, archive, series[0])

        # For the previous series, we have a KMOD key configured
        self.assertGet(arch_uefi_key, SigningKeyType.UEFI, archive, series[1])
        self.assertGet(arch_kmod_key, SigningKeyType.KMOD, archive, series[1])

        # For the old series, we have an old KMOD key configured
        self.assertGet(arch_uefi_key, SigningKeyType.UEFI, archive, series[2])
        self.assertGet(
            old_arch_kmod_key, SigningKeyType.KMOD, archive, series[2]
        )
