# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from email.header import Header
from email.message import Message
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import (
    formatdate,
    make_msgid,
    )

import six
from testscenarios import WithScenarios
from testtools.matchers import (
    Equals,
    Is,
    MatchesStructure,
    )
import transaction
from zope.security.interfaces import Unauthorized
from zope.security.proxy import (
    ProxyFactory,
    removeSecurityProxy,
    )

from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.bugs.model.bugmessage import BugMessage
from lp.services.compat import message_as_bytes
from lp.services.database.interfaces import IStore
from lp.services.messages.model.message import MessageSet
from lp.services.utils import utc_now
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    admin_logged_in,
    api_url,
    login,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.pages import webservice_for_person


class TestMessageSet(TestCaseWithFactory):
    """Test the methods of `MessageSet`."""

    layer = LaunchpadFunctionalLayer

    # Stick to printable non-whitespace characters from ISO-8859-1 to avoid
    # confusion.  (In particular, '\x85' and '\xa0' are whitespace
    # characters according to Unicode but not according to ASCII, and this
    # would otherwise result in different test output between Python 2 and
    # 3.)
    high_characters = b''.join(six.int2byte(c) for c in range(161, 256))

    def setUp(self):
        super(TestMessageSet, self).setUp()
        # Testing behaviour, not permissions here.
        login('foo.bar@canonical.com')

    def createTestMessages(self):
        """Create some test messages."""
        message1 = self.factory.makeMessage()
        message2 = self.factory.makeMessage(parent=message1)
        message3 = self.factory.makeMessage(parent=message1)
        message4 = self.factory.makeMessage(parent=message2)
        return (message1, message2, message3, message4)

    def _makeMessageWithAttachment(self, filename='review.diff'):
        sender = self.factory.makePerson()
        msg = MIMEMultipart()
        msg['Message-Id'] = make_msgid('launchpad')
        msg['Date'] = formatdate()
        msg['To'] = 'to@example.com'
        msg['From'] = sender.preferredemail.email
        msg['Subject'] = 'Sample'
        msg.attach(MIMEText('This is the body of the email.'))
        attachment = Message()
        attachment.set_payload('This is the diff, honest.')
        attachment['Content-Type'] = 'text/x-diff'
        attachment['Content-Disposition'] = (
            'attachment; filename="%s"' % filename)
        msg.attach(attachment)
        return msg

    def test_fromEmail_keeps_attachments(self):
        """Test that the parsing of the email keeps the attachments."""
        # Build a simple multipart message with a plain text first part
        # and an text/x-diff attachment.
        msg = self._makeMessageWithAttachment()
        # Now create the message from the MessageSet.
        message = MessageSet().fromEmail(message_as_bytes(msg))
        text, diff = message.chunks
        self.assertEqual('This is the body of the email.', text.content)
        self.assertEqual('review.diff', diff.blob.filename)
        self.assertEqual('text/x-diff', diff.blob.mimetype)
        # Need to commit in order to read back out of the librarian.
        transaction.commit()
        self.assertEqual(b'This is the diff, honest.', diff.blob.read())

    def test_fromEmail_strips_attachment_paths(self):
        # Build a simple multipart message with a plain text first part
        # and an text/x-diff attachment.
        msg = self._makeMessageWithAttachment(filename='/tmp/foo/review.diff')
        # Now create the message from the MessageSet.
        message = MessageSet().fromEmail(message_as_bytes(msg))
        text, diff = message.chunks
        self.assertEqual('This is the body of the email.', text.content)
        self.assertEqual('review.diff', diff.blob.filename)
        self.assertEqual('text/x-diff', diff.blob.mimetype)
        # Need to commit in order to read back out of the librarian.
        transaction.commit()
        self.assertEqual(b'This is the diff, honest.', diff.blob.read())

    def test_fromEmail_always_creates(self):
        """Even when messages are identical, fromEmail creates a new one."""
        email = self.factory.makeEmailMessage()
        orig_message = MessageSet().fromEmail(message_as_bytes(email))
        transaction.commit()
        dupe_message = MessageSet().fromEmail(message_as_bytes(email))
        self.assertNotEqual(orig_message.id, dupe_message.id)

    def test_fromEmail_restricted_reuploads(self):
        """fromEmail will re-upload the email to the restricted librarian if
        restricted is True."""
        filealias = self.factory.makeLibraryFileAlias()
        transaction.commit()
        email = self.factory.makeEmailMessage()
        message = MessageSet().fromEmail(
            message_as_bytes(email), filealias=filealias, restricted=True)
        self.assertTrue(message.raw.restricted)
        self.assertNotEqual(message.raw.id, filealias.id)

    def test_fromEmail_restricted_attachments(self):
        """fromEmail creates restricted attachments correctly."""
        msg = self._makeMessageWithAttachment()
        message = MessageSet().fromEmail(
            message_as_bytes(msg), restricted=True)
        text, diff = message.chunks
        self.assertEqual('review.diff', diff.blob.filename)
        self.assertTrue('review.diff', diff.blob.restricted)

    def makeEncodedEmail(self, encoding_name, actual_encoding):
        email = self.factory.makeEmailMessage(body=self.high_characters)
        email.set_type('text/plain')
        email.set_charset(encoding_name)
        macroman = Header(self.high_characters, actual_encoding).encode()
        new_subject = macroman.replace(actual_encoding, encoding_name)
        email.replace_header('Subject', new_subject)
        return email

    def test_fromEmail_decodes_macintosh_encoding(self):
        """"macintosh encoding is equivalent to MacRoman."""
        high_decoded = self.high_characters.decode('macroman')
        email = self.makeEncodedEmail('macintosh', 'macroman')
        message = MessageSet().fromEmail(message_as_bytes(email))
        self.assertEqual(high_decoded, message.subject)
        self.assertEqual(high_decoded, message.text_contents)

    def test_fromEmail_decodes_booga_encoding(self):
        """"'booga' encoding is decoded as latin-1."""
        high_decoded = self.high_characters.decode('latin-1')
        email = self.makeEncodedEmail('booga', 'latin-1')
        message = MessageSet().fromEmail(message_as_bytes(email))
        self.assertEqual(high_decoded, message.subject)
        self.assertEqual(high_decoded, message.text_contents)

    def test_decode_utf8(self):
        """Test decode with a known encoding."""
        result = MessageSet.decode(u'\u1234'.encode('utf-8'), 'utf-8')
        self.assertEqual(u'\u1234', result)

    def test_decode_macintosh(self):
        """Test decode with macintosh encoding."""
        result = MessageSet.decode(self.high_characters, 'macintosh')
        self.assertEqual(self.high_characters.decode('macroman'), result)

    def test_decode_unknown_ascii(self):
        """Test decode with ascii characters in an unknown encoding."""
        result = MessageSet.decode(b'abcde', 'booga')
        self.assertEqual(u'abcde', result)

    def test_decode_unknown_high_characters(self):
        """Test decode with non-ascii characters in an unknown encoding."""
        with self.expectedLog(
            'Treating unknown encoding "booga" as latin-1.'):
            result = MessageSet.decode(self.high_characters, 'booga')
        self.assertEqual(self.high_characters.decode('latin-1'), result)


class MessageTypeScenariosMixin(WithScenarios):

    scenarios = [
        ("bug", {"message_type": "bug"}),
        ("question", {"message_type": "question"}),
        ("MP comment", {"message_type": "mp"})
        ]

    def setUp(self):
        super(MessageTypeScenariosMixin, self).setUp()
        self.person = self.factory.makePerson()
        login_person(self.person)

    def makeMessage(self, content=None, **kwargs):
        owner = kwargs.pop('owner', self.person)
        if self.message_type == "bug":
            msg = self.factory.makeBugComment(
                owner=owner, body=content, **kwargs)
            return ProxyFactory(IStore(BugMessage).find(
                BugMessage, BugMessage.message == msg).one())
        elif self.message_type == "question":
            question = self.factory.makeQuestion()
            return question.giveAnswer(owner, content)
        elif self.message_type == "mp":
            return self.factory.makeCodeReviewComment(
                sender=owner, body=content)


class TestMessageEditing(MessageTypeScenariosMixin, TestCaseWithFactory):
    """Test editing scenarios for Message objects."""

    layer = DatabaseFunctionalLayer

    def assertIsMessageHistory(
            self, msg_history, msg, created_at, content, deleted_at=None):
        """Asserts that `msg_history` is a message a message history of
        `msg` with the given extra info.
        """
        self.assertThat(msg_history, MatchesStructure(
            content=Equals(content),
            message=Equals(removeSecurityProxy(msg).message),
            date_created=Equals(created_at),
            date_deleted=Is(deleted_at)))

    def test_non_owner_cannot_edit_message(self):
        msg = self.makeMessage()
        someone_else = self.factory.makePerson()
        with person_logged_in(someone_else):
            self.assertRaises(Unauthorized, getattr, msg, "edit_content")

    def test_msg_owner_can_edit(self):
        owner = self.factory.makePerson()
        msg = self.makeMessage(owner=owner, content="initial content")
        with person_logged_in(owner):
            msg.edit_content("This is the new content")
        self.assertEqual("This is the new content", msg.text_contents)
        self.assertEqual(1, len(msg.revisions))
        self.assertIsMessageHistory(
            msg.revisions[0], msg,
            created_at=msg.datecreated, content="initial content")

    def test_multiple_edits_revisions(self):
        owner = self.factory.makePerson()
        msg = self.makeMessage(owner=owner, content="initial content")
        with person_logged_in(owner):
            msg.edit_content("first edit")
            first_edit_date = msg.date_last_edit
        self.assertEqual("first edit", msg.text_contents)
        self.assertEqual(1, len(msg.revisions))
        self.assertIsMessageHistory(
            msg.revisions[0], msg,
            content="initial content", created_at=msg.datecreated)

        with person_logged_in(owner):
            msg.edit_content("final form")
        self.assertEqual("final form", msg.text_contents)
        self.assertEqual(2, len(msg.revisions))
        self.assertIsMessageHistory(
            msg.revisions[0], msg,
            content="first edit", created_at=first_edit_date)
        self.assertIsMessageHistory(
            msg.revisions[1], msg,
            content="initial content", created_at=msg.datecreated)

    def test_non_owner_cannot_delete_message(self):
        owner = self.factory.makePerson()
        msg = self.makeMessage(owner=owner, content="initial content")
        someone_else = self.factory.makePerson()
        with person_logged_in(someone_else):
            self.assertRaises(Unauthorized, getattr, msg, "delete_content")

    def test_delete_message(self):
        owner = self.factory.makePerson()
        msg = self.makeMessage(owner=owner, content="initial content")
        with person_logged_in(owner):
            before_delete = utc_now()
            msg.delete_content()
            after_delete = utc_now()
        self.assertEqual('', msg.text_contents)
        self.assertEqual(0, len(msg.chunks))
        self.assertIsNotNone(msg.date_deleted)
        self.assertTrue(after_delete > msg.date_deleted > before_delete)


class TestMessageEditingAPI(MessageTypeScenariosMixin, TestCaseWithFactory):
    """Test editing scenarios for Message editing API."""

    layer = DatabaseFunctionalLayer

    def getWebservice(self, person):
        return webservice_for_person(
            person, permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel")

    def getMessageAPIURL(self, msg):
        with admin_logged_in():
            if IBugMessage.providedBy(msg):
                # BugMessage has a special URL mapping that uses the
                # IMessage object itself.
                return api_url(msg.message)
            else:
                return api_url(msg)

    def test_edit_message(self):
        msg = self.makeMessage(content="initial content")
        ws = self.getWebservice(self.person)
        url = self.getMessageAPIURL(msg)
        response = ws.named_post(
            url, 'edit_content', new_content="the new content")
        self.assertEqual(200, response.status)

        edited_obj = ws.get(url).jsonBody()
        self.assertEqual("the new content", edited_obj['content'])
        self.assertIsNone(edited_obj["date_deleted"])
        self.assertIsNotNone(edited_obj["date_last_edit"])

    def test_edit_message_permission_denied_for_non_owner(self):
        msg = self.makeMessage(content="initial content")
        ws = self.getWebservice(self.factory.makePerson())
        url = self.getMessageAPIURL(msg)
        response = ws.named_post(
            url, 'edit_content', new_content="the new content")
        self.assertEqual(401, response.status)

        edited_obj = ws.get(url).jsonBody()
        self.assertEqual("initial content", edited_obj['content'])
        self.assertIsNone(edited_obj["date_deleted"])
        self.assertIsNone(edited_obj["date_last_edit"])

    def test_delete_message(self):
        msg = self.makeMessage(content="initial content")
        ws = self.getWebservice(self.person)
        url = self.getMessageAPIURL(msg)

        response = ws.named_post(url, 'delete_content')
        self.assertEqual(200, response.status)

        deleted_obj = ws.get(url).jsonBody()
        self.assertEqual("", deleted_obj['content'])
        self.assertIsNotNone(deleted_obj['date_deleted'])

    def test_delete_message_permission_denied_for_non_owner(self):
        msg = self.makeMessage(content="initial content")
        ws = self.getWebservice(self.factory.makePerson())
        url = self.getMessageAPIURL(msg)

        response = ws.named_post(url, 'delete_content')
        self.assertEqual(401, response.status)

        obj = ws.get(url).jsonBody()
        self.assertEqual("initial content", obj['content'])
        self.assertIsNone(obj['date_deleted'])
