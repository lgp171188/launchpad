# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import base64
from datetime import datetime

from fixtures.testcase import TestWithFixtures
from nacl.public import PrivateKey
from pytz import utc
import responses
from storm.store import Store
from testtools.matchers import MatchesStructure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.services.database.interfaces import IMasterStore
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
    )
from lp.services.signing.model.signingkey import (
    ArchiveSigningKey,
    SigningKey,
    )
from lp.services.signing.tests.test_proxy import SigningServiceResponseFactory
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestSigningKey(TestCaseWithFactory, TestWithFixtures):

    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super(TestSigningKey, self).setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

        client = removeSecurityProxy(getUtility(ISigningServiceClient))
        self.addCleanup(client._cleanCaches)

    @responses.activate
    def test_generate_signing_key_saves_correctly(self):
        self.signing_service.addResponses(self)

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
    def test_inject_signing_key_saves_correctly(self):
        self.signing_service.addResponses(self)

        priv_key = PrivateKey.generate()
        pub_key = priv_key.public_key
        created_at = datetime(2020, 4, 16, 16, 35).replace(tzinfo=utc)

        key = SigningKey.inject(
            SigningKeyType.KMOD, bytes(priv_key), bytes(pub_key),
            u"This is a test key", created_at)
        self.assertIsInstance(key, SigningKey)

        store = IMasterStore(SigningKey)
        store.invalidate()

        rs = store.find(SigningKey)
        self.assertEqual(1, rs.count())
        db_key = rs.one()

        self.assertEqual(SigningKeyType.KMOD, db_key.key_type)
        self.assertEqual(
            self.signing_service.generated_fingerprint, db_key.fingerprint)
        self.assertEqual(bytes(pub_key), db_key.public_key)
        self.assertEqual(u"This is a test key", db_key.description)
        self.assertEqual(created_at, db_key.date_created)

    @responses.activate
    def test_sign_some_data(self):
        self.signing_service.addResponses(self)

        s = SigningKey(
            SigningKeyType.UEFI, u"a fingerprint",
            bytes(self.signing_service.generated_public_key),
            description=u"This is my key!")
        signed = s.sign("secure message", "message_name")

        # Checks if the returned value is actually the returning value from
        # HTTP POST /sign call to lp-signing service
        self.assertEqual(3, len(responses.calls))
        self.assertEqual(self.signing_service.getAPISignedContent(), signed)


class TestArchiveSigningKey(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def setUp(self, *args, **kwargs):
        super(TestArchiveSigningKey, self).setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

        client = removeSecurityProxy(getUtility(ISigningServiceClient))
        self.addCleanup(client._cleanCaches)

    @responses.activate
    def test_generate_saves_correctly(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        arch_key = getUtility(IArchiveSigningKeySet).generate(
            SigningKeyType.UEFI, u"some description", archive,
            earliest_distro_series=distro_series)

        store = Store.of(arch_key)
        store.invalidate()

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, rs.count())

        db_arch_key = rs.one()
        self.assertThat(db_arch_key, MatchesStructure.byEquality(
            key_type=SigningKeyType.UEFI, archive=archive,
            earliest_distro_series=distro_series))

        self.assertThat(db_arch_key.signing_key, MatchesStructure.byEquality(
            key_type=SigningKeyType.UEFI, description=u"some description",
            fingerprint=self.signing_service.generated_fingerprint,
            public_key=bytes(self.signing_service.generated_public_key)))

    @responses.activate
    def test_inject_saves_correctly(self):
        self.signing_service.addResponses(self)

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        priv_key = PrivateKey.generate()
        pub_key = priv_key.public_key

        now = datetime.now().replace(tzinfo=utc)
        arch_key = getUtility(IArchiveSigningKeySet).inject(
            SigningKeyType.UEFI, bytes(priv_key), bytes(pub_key),
            u"Some description", now, archive,
            earliest_distro_series=distro_series)

        store = Store.of(arch_key)
        store.invalidate()

        rs = store.find(ArchiveSigningKey)
        self.assertEqual(1, rs.count())

        db_arch_key = rs.one()
        self.assertThat(db_arch_key, MatchesStructure.byEquality(
            key_type=SigningKeyType.UEFI, archive=archive,
            earliest_distro_series=distro_series))

        self.assertThat(db_arch_key.signing_key, MatchesStructure.byEquality(
            key_type=SigningKeyType.UEFI, description=u"Some description",
            fingerprint=self.signing_service.generated_fingerprint,
            public_key=bytes(pub_key)))

    def test_create(self):
        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]
        signing_key = self.factory.makeSigningKey()

        arch_signing_key_set = getUtility(IArchiveSigningKeySet)

        arch_key = arch_signing_key_set.create(
            archive, distro_series, signing_key)

        store = Store.of(arch_key)
        store.invalidate()
        rs = store.find(ArchiveSigningKey)

        self.assertEqual(1, rs.count())
        db_arch_key = rs.one()
        self.assertThat(db_arch_key, MatchesStructure.byEquality(
            key_type=signing_key.key_type, archive=archive,
            earliest_distro_series=distro_series,
            signing_key=signing_key))

        # Saving another type should create a new entry
        signing_key_from_another_type = self.factory.makeSigningKey(
            key_type=SigningKeyType.KMOD)
        arch_signing_key_set.create(
            archive, distro_series, signing_key_from_another_type)

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
        other_archive = self.factory.makeArchive()
        arch_signing_key_set = getUtility(IArchiveSigningKeySet)
        arch_signing_key_set.create(
            other_archive, None, self.factory.makeSigningKey())

        # Create a key for the archive (no specific series)
        arch_uefi_key = arch_signing_key_set.create(
            archive, None, uefi_key)
        arch_kmod_key = arch_signing_key_set.create(
            archive, None, kmod_key)

        # Should find the keys if we ask for the archive key
        self.assertEqual(
            arch_uefi_key.signing_key,
            arch_signing_key_set.getSigningKey(UEFI, archive, None))
        self.assertEqual(
            arch_kmod_key.signing_key,
            arch_signing_key_set.getSigningKey(KMOD, archive, None))

        # Should find the key if we ask for archive + distro_series key
        self.assertEqual(
            arch_uefi_key.signing_key,
            arch_signing_key_set.getSigningKey(UEFI, archive, distro_series))
        self.assertEqual(
            arch_kmod_key.signing_key,
            arch_signing_key_set.getSigningKey(KMOD, archive, distro_series))

    def test_get_signing_keys_with_distro_series_configured(self):
        UEFI = SigningKeyType.UEFI
        KMOD = SigningKeyType.KMOD

        archive = self.factory.makeArchive()
        series = archive.distribution.series
        uefi_key = self.factory.makeSigningKey(key_type=UEFI)
        kmod_key = self.factory.makeSigningKey(key_type=KMOD)

        # Fill the database with keys from other archives to make sure we
        # are filtering it out
        other_archive = self.factory.makeArchive()
        arch_signing_key_set = getUtility(IArchiveSigningKeySet)
        arch_signing_key_set.create(
            other_archive, None, self.factory.makeSigningKey())

        # Create a key for the archive (no specific series)
        arch_uefi_key = arch_signing_key_set.create(
            archive, None, uefi_key)

        # for kmod, should give back this one if provided a
        # newer distro series
        arch_kmod_key = arch_signing_key_set.create(
            archive, series[1], kmod_key)
        old_arch_kmod_key = arch_signing_key_set.create(
            archive, series[2], kmod_key)

        # If no distroseries is specified, it should give back no KMOD key,
        # since we don't have a default
        self.assertEqual(
            arch_uefi_key.signing_key,
            arch_signing_key_set.getSigningKey(UEFI, archive, None))
        self.assertEqual(
            None,
            arch_signing_key_set.getSigningKey(KMOD, archive, None))

        # For the most recent series, use the KMOD key we've set for the
        # previous one
        self.assertEqual(
            arch_uefi_key.signing_key,
            arch_signing_key_set.getSigningKey(UEFI, archive, series[0]))
        self.assertEqual(
            arch_kmod_key.signing_key,
            arch_signing_key_set.getSigningKey(KMOD, archive, series[0]))

        # For the previous series, we have a KMOD key configured
        self.assertEqual(
            arch_uefi_key.signing_key,
            arch_signing_key_set.getSigningKey(UEFI, archive, series[1]))
        self.assertEqual(
            arch_kmod_key.signing_key,
            arch_signing_key_set.getSigningKey(KMOD, archive, series[1]))

        # For the old series, we have an old KMOD key configured
        self.assertEqual(
            arch_uefi_key.signing_key,
            arch_signing_key_set.getSigningKey(UEFI, archive, series[2]))
        self.assertEqual(
            old_arch_kmod_key.signing_key,
            arch_signing_key_set.getSigningKey(KMOD, archive, series[2]))
