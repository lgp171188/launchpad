# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import base64

import responses
from storm.store import Store
from testtools.matchers import MatchesStructure
from zope.component._api import getUtility

from lp.services.database.interfaces import IMasterStore
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
    )
from lp.services.signing.model.signingkey import (
    ArchiveSigningKey,
    ArchiveSigningKeySet,
    SigningKey,
    )
from lp.services.signing.proxy import SigningServiceClient
from lp.services.signing.tests.test_proxy import SigningServiceResponseFactory
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestSigningKey(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self, *args, **kwargs):
        super(TestSigningKey, self).setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

    def tearDown(self):
        super(TestSigningKey, self).tearDown()
        # clean singleton instance of signing service.
        getUtility(ISigningServiceClient)._cleanCaches()

    @responses.activate
    def test_generate_signing_key_saves_correctly(self):
        self.signing_service.addResponses()

        key = SigningKey.generate(SigningKeyType.UEFI, u"this is my key")
        self.assertIsInstance(key, SigningKey)

        store = IMasterStore(SigningKey)
        store.invalidate()

        rs = store.find(SigningKey)
        self.assertEqual(1, rs.count())
        db_key = rs.one()

        self.assertEqual(SigningKeyType.UEFI, db_key.key_type)
        self.assertEqual(
            self.signing_service.generated_fingerprint, db_key.fingerprint)
        self.assertEqual(
            self.signing_service.b64_generated_public_key,
            base64.b64encode(db_key.public_key))
        self.assertEqual("this is my key", db_key.description)

    @responses.activate
    def test_sign_some_data(self):
        self.signing_service.addResponses()

        s = SigningKey(
            SigningKeyType.UEFI, u"a fingerprint",
            self.signing_service.b64_generated_public_key,
            description=u"This is my key!")
        signed = s.sign("secure message", "message_name")

        # Checks if the returned value is actually the returning value from
        # HTTP POST /sign call to lp-signing service
        self.assertEqual(3, len(responses.calls))
        http_sign = responses.calls[-1]
        api_resp = http_sign.response.json()
        self.assertEqual(
            base64.b64decode(api_resp['signed-message']), signed)


class TestArchiveSigningKey(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self, *args, **kwargs):
        super(TestArchiveSigningKey, self).setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

    @responses.activate
    def test_generate_saves_correctly(self):
        self.signing_service.addResponses()

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        arch_key = ArchiveSigningKeySet.generate(
            SigningKeyType.UEFI, archive, distro_series=distro_series,
            description=u"some description")

        store = Store.of(arch_key)
        store.invalidate()

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, rs.count())

        db_arch_key = rs.one()
        self.assertThat(db_arch_key, MatchesStructure.byEquality(
            archive=archive, distro_series=distro_series))

        self.assertThat(db_arch_key.signing_key, MatchesStructure.byEquality(
            key_type=SigningKeyType.UEFI, description=u"some description",
            fingerprint=self.signing_service.generated_fingerprint,
            public_key=self.signing_service.generated_public_key))

    def test_create_or_update(self):
        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]
        signing_key = self.factory.makeSigningKey()

        arch_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, distro_series, signing_key)

        store = Store.of(arch_key)
        store.invalidate()
        rs = store.find(ArchiveSigningKey)

        self.assertEqual(1, rs.count())
        db_arch_key = rs.one()
        self.assertTrue(created)
        self.assertThat(db_arch_key, MatchesStructure.byEquality(
            archive=archive, distro_series=distro_series,
            signing_key=signing_key))

        another_signing_key = self.factory.makeSigningKey()
        updated_arch_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, distro_series, another_signing_key)

        store.invalidate()
        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, store.find(ArchiveSigningKey).count())
        db_arch_key = rs.one()
        self.assertFalse(created)
        self.assertThat(db_arch_key, MatchesStructure.byEquality(
            archive=archive, distro_series=distro_series,
            signing_key=signing_key))

        # Saving another type should create a new entry
        signing_key_from_another_type = self.factory.makeSigningKey(
            key_type=SigningKeyType.KMOD)
        arch_key_another_type, created = ArchiveSigningKeySet.createOrUpdate(
            archive, distro_series, signing_key_from_another_type)

        self.assertTrue(created)
        self.assertEqual(2, store.find(ArchiveSigningKey).count())

    def test_get_signing_keys_without_distro_series_configured(self):
        UEFI = SigningKeyType.UEFI
        KMOD = SigningKeyType.KMOD

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]
        uefi_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.UEFI)
        kmod_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.KMOD)

        # Fill the database with keys from other archives to make sure we
        # are filtering it out
        other_archive = archive = self.factory.makeArchive()
        ArchiveSigningKeySet.createOrUpdate(
            other_archive, None, self.factory.makeSigningKey())

        # Create a key for the archive (no specific series)
        arch_uefi_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, None, uefi_key)
        arch_kmod_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, None, kmod_key)

        # Should find the keys if we ask for the archive key
        self.assertEqual(
            {UEFI: arch_uefi_key, KMOD: arch_kmod_key},
            ArchiveSigningKeySet.getSigningKeys(archive, None))

        # Should find the key if we ask for archive + distro_series key
        self.assertEqual(
            {UEFI: arch_uefi_key, KMOD: arch_kmod_key},
            ArchiveSigningKeySet.getSigningKeys(archive, distro_series))

    def test_get_signing_keys_with_distro_series_configured(self):
        UEFI = SigningKeyType.UEFI
        KMOD = SigningKeyType.KMOD

        archive = self.factory.makeArchive()
        series = archive.distribution.series
        uefi_key = self.factory.makeSigningKey(key_type=UEFI)
        kmod_key = self.factory.makeSigningKey(key_type=KMOD)

        # Fill the database with keys from other archives to make sure we
        # are filtering it out
        other_archive = archive = self.factory.makeArchive()
        ArchiveSigningKeySet.createOrUpdate(
            other_archive, None, self.factory.makeSigningKey())

        # Create a key for the archive (no specific series)
        arch_uefi_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, None, uefi_key)

        # for kmod, should give back this one if provided a
        # newer distro series
        arch_kmod_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, series[1], kmod_key)
        old_arch_kmod_key, created = ArchiveSigningKeySet.createOrUpdate(
            archive, series[2], kmod_key)

        # If no distroseries is specified, it should give back no KMOD key,
        # since we don't have a default
        self.assertEqual(
            {UEFI: arch_uefi_key, KMOD: None},
            ArchiveSigningKeySet.getSigningKeys(archive, None))

        # For the most recent series, use the KMOD key we've set for the
        # previous one
        self.assertEqual(
            {UEFI: arch_uefi_key, KMOD: arch_kmod_key},
            ArchiveSigningKeySet.getSigningKeys(archive, series[0]))

        # For the previous series, we have a KMOD key configured
        self.assertEqual(
            {UEFI: arch_uefi_key, KMOD: arch_kmod_key},
            ArchiveSigningKeySet.getSigningKeys(archive, series[1]))

        # For the old series, we have an old KMOD key configured
        self.assertEqual(
            {UEFI: arch_uefi_key, KMOD: old_arch_kmod_key},
            ArchiveSigningKeySet.getSigningKeys(archive, series[2]))
