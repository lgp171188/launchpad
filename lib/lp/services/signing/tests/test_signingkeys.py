# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import base64

import mock
import responses

from lp.services.signing.enums import SigningKeyType
from lp.services.signing.model.signingkeys import SigningKey
from lp.services.database.interfaces import IMasterStore
from lp.services.signing.tests.test_proxy import SigningServiceResponseFactory
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestSigningServiceSigningKey(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self, *args, **kwargs):
        super(TestSigningServiceSigningKey, self).setUp(*args, **kwargs)
        self.signing_service = SigningServiceResponseFactory()

    def test_save_signing_key(self):
        archive = self.factory.makeArchive()
        s = SigningKey(
            key_type=SigningKeyType.UEFI,
            archive=archive, fingerprint=u"a fingerprint",
            public_key=base64.b64decode(
                self.signing_service.b64_generated_public_key),
            description=u"This is my key!")
        store = IMasterStore(SigningKey)
        store.add(s)
        store.commit()

        store.invalidate()

        resultset = store.find(SigningKey)
        self.assertEqual(1, resultset.count())
        db_key = resultset.one()
        self.assertEqual(SigningKeyType.UEFI, db_key.key_type)
        self.assertEqual(archive, db_key.archive)
        self.assertEqual("a fingerprint", db_key.fingerprint)
        self.assertEqual(
            self.signing_service.b64_generated_public_key,
            base64.b64encode(db_key.public_key))
        self.assertEqual("This is my key!", db_key.description)

    @responses.activate
    def test_generate_signing_key_saves_correctly(self):
        self.signing_service.patch()

        archive = self.factory.makeArchive()
        distro_series = archive.distribution.series[0]

        key = SigningKey.generate(
            SigningKeyType.UEFI, archive, distro_series, u"this is my key")
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
        self.assertEqual(archive, db_key.archive)
        self.assertEqual(distro_series, db_key.distro_series)
        self.assertEqual("this is my key", db_key.description)

    @responses.activate
    def test_sign_some_data(self):
        self.signing_service.patch()

        archive = self.factory.makeArchive()

        s = SigningKey(
            SigningKeyType.UEFI, archive, u"a fingerprint",
            self.signing_service.b64_generated_public_key,
            description=u"This is my key!")
        signed = s.sign("ATTACHED", "secure message", "message_name")

        # Checks if the returned value is actually the returning value from
        # HTTP POST /sign call to lp-signing service
        self.assertEqual(3, len(responses.calls))
        http_sign = responses.calls[-1]
        api_resp = http_sign.response.json()
        self.assertIsNotNone(api_resp, "The API was never called")
        self.assertEqual(
            base64.b64decode(api_resp['signed-message']), signed)
