# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from testtools.matchers import (
    ContainsDict,
    EndsWith,
    Equals,
    Is,
    MatchesListwise,
    Not,
    )
from zope.security.interfaces import Unauthorized
from zope.security.proxy import ProxyFactory

from lp.app.browser.tales import DateTimeFormatterAPI
from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.messages.tests.scenarios import MessageTypeScenariosMixin
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    admin_logged_in,
    api_url,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import webservice_for_person


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


class TestMessageRevisionAPI(MessageTypeScenariosMixin, TestCaseWithFactory):
    """Test editing scenarios for message revisions API."""

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

    def test_get_message_revision_list(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        msg.editContent("final content")
        dates_created = [revision.date_created for revision in msg.revisions]
        ws = self.getWebservice(self.person)
        url = self.getMessageAPIURL(msg)
        ws_message = ws.get(url).jsonBody()

        revisions = ws.get(ws_message['revisions_collection_link']).jsonBody()
        self.assertThat(revisions, ContainsDict({
            "start": Equals(0),
            "total_size": Equals(2)}))
        self.assertThat(revisions["entries"], MatchesListwise([
            ContainsDict({
                "content": Equals("initial content"),
                "date_created": Equals(dates_created[0].isoformat()),
                "date_created_display": Equals(
                    DateTimeFormatterAPI(dates_created[0]).datetime()),
                "date_deleted": Is(None),
                "self_link": EndsWith("/revisions/1")
                }),
            ContainsDict({
                "content": Equals("new content 1"),
                "date_created": Equals(dates_created[1].isoformat()),
                "date_created_display": Equals(
                    DateTimeFormatterAPI(dates_created[1]).datetime()),
                "date_deleted": Is(None),
                "self_link": EndsWith("/revisions/2")
                })]))

    def test_get_single_revision(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        date_created = msg.revisions[0].date_created
        ws = self.getWebservice(self.person)

        with person_logged_in(self.person):
            revision_url = api_url(msg.revisions[0])
        revision = ws.get(revision_url).jsonBody()
        self.assertThat(revision, ContainsDict({
            "content": Equals("initial content"),
            "date_created": Equals(date_created.isoformat()),
            "date_created_display": Equals(
                DateTimeFormatterAPI(date_created).datetime()),
            "date_deleted": Is(None),
            "self_link": EndsWith("/revisions/1")
            }))

    def test_delete_revision_content(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        msg.editContent("final content")
        dates_created = [revision.date_created for revision in msg.revisions]

        with person_logged_in(self.person):
            revision_url = api_url(msg.revisions[0])

        ws = self.getWebservice(self.person)
        response = ws.named_post(revision_url, "deleteContent")
        self.assertEqual(200, response.status)

        revision = ws.get(revision_url).jsonBody()
        self.assertThat(revision, ContainsDict({
            "content": Equals(""),
            "date_created": Equals(dates_created[0].isoformat()),
            "date_created_display": Equals(
                DateTimeFormatterAPI(dates_created[0]).datetime()),
            "date_deleted": Not(Is(None)),
            "self_link": EndsWith("/revisions/1")
            }))

    def test_delete_revision_content_denied_for_non_owners(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        msg.editContent("final content")
        dates_created = [revision.date_created for revision in msg.revisions]
        someone_else = self.factory.makePerson()

        with person_logged_in(self.person):
            revision_url = api_url(msg.revisions[0])

        ws = self.getWebservice(someone_else)
        response = ws.named_post(revision_url, "deleteContent")
        self.assertEqual(401, response.status)

        revision = ws.get(revision_url).jsonBody()
        self.assertThat(revision, ContainsDict({
            "content": Equals("initial content"),
            "date_created": Equals(dates_created[0].isoformat()),
            "date_created_display": Equals(
                DateTimeFormatterAPI(dates_created[0]).datetime()),
            "date_deleted": Is(None),
            "self_link": EndsWith("/revisions/1")
            }))
