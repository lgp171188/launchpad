# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.archivepublisher.model.signingkeys import SigningKey
from lp.services.database.interfaces import IMasterStore
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestSigningServiceSigningKey(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_save_signing_key(self):
        archive = self.factory.makeArchive()
        s = SigningKey(archive, u'a fingerprint', u'a public_key')
        store = IMasterStore(SigningKey)
        store.add(s)
        store.commit()

        resultset = store.find(SigningKey)
        self.assertEqual(1, resultset.count())
        db_key = resultset.one()
        self.assertEqual(archive, db_key.archive)
        self.assertEqual('a fingerprint', db_key.fingerprint)
        self.assertEqual('a public_key', db_key.public_key)