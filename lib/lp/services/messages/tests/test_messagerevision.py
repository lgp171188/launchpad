# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from zope.security.interfaces import Unauthorized
from zope.security.proxy import ProxyFactory

from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    )


class TestMessageRevision(TestCaseWithFactory):
    """Test scenarios for MessageRevision objects."""

    layer = DatabaseFunctionalLayer

    def makeMessage(self):
        msg = self.factory.makeMessage()
        return ProxyFactory(msg)

    def makeMessageRevision(self):
        msg = self.makeMessage()
        with person_logged_in(msg.owner):
            msg.editContent('something edited #%s' % len(msg.revisions))
        return msg.revisions[-1]

    def test_non_owner_cannot_delete_message_revision_content(self):
        rev = self.makeMessageRevision()
        someone_else = self.factory.makePerson()
        with person_logged_in(someone_else):
            self.assertRaises(Unauthorized, getattr, rev, "deleteContent")

    def test_msg_owner_can_delete_message_revision_content(self):
        rev = self.makeMessageRevision()
        msg = rev.message
        with person_logged_in(rev.message.owner):
            rev.deleteContent()
        self.assertEqual(1, len(msg.revisions))
        self.assertEqual("", rev.content)
        self.assertEqual(0, len(rev.chunks))
        self.assertEqual(
            get_transaction_timestamp(IStore(rev)), rev.date_deleted)
