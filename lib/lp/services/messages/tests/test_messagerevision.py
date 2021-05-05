# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from testscenarios import WithScenarios
from testtools.matchers import (
    ContainsDict,
    EndsWith,
    Equals,
    Is,
    MatchesListwise,
    Not,
    )
from zope.security.proxy import ProxyFactory

from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.bugs.model.bugmessage import BugMessage
from lp.services.database.interfaces import IStore
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    admin_logged_in,
    api_url,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import webservice_for_person


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


class TestMessageHistoryAPI(MessageTypeScenariosMixin, TestCaseWithFactory):
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
        ws = self.getWebservice(self.person)
        url = self.getMessageAPIURL(msg)
        ws_message = ws.get(url).jsonBody()

        revisions = ws.get(ws_message['revisions_collection_link']).jsonBody()
        self.assertThat(revisions, ContainsDict({
            "start": Equals(0),
            "total_size": Equals(2)}))
        self.assertThat(revisions["entries"], MatchesListwise([
            ContainsDict({
                "date_created": Not(Is(None)),
                "date_deleted": Is(None),
                "content": Equals("initial content"),
                "self_link": EndsWith("/revisions/1")
            }),
            ContainsDict({
                "date_created": Not(Is(None)),
                "date_deleted": Is(None),
                "content": Equals("new content 1"),
                "self_link": EndsWith("/revisions/2")
            })]))

    def test_get_single_revision(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        ws = self.getWebservice(self.person)

        with person_logged_in(self.person):
            revision_url = api_url(msg.revisions[0])
        revision = ws.get(revision_url).jsonBody()
        self.assertThat(revision, ContainsDict({
                "date_created": Not(Is(None)),
                "date_deleted": Is(None),
                "content": Equals("initial content"),
                "self_link": EndsWith("/revisions/1")
            }))

    def test_delete_revision_content(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        msg.editContent("final content")

        with person_logged_in(self.person):
            revision_url = api_url(msg.revisions[0])

        ws = self.getWebservice(self.person)
        response = ws.named_post(revision_url, "deleteContent")
        self.assertEqual(200, response.status)

        revision = ws.get(revision_url).jsonBody()
        self.assertThat(revision, ContainsDict({
            "date_created": Not(Is(None)),
            "date_deleted": Not(Is(None)),
            "content": Is(None),
            "self_link": EndsWith("/revisions/1")
        }))

    def test_delete_revision_content_denied_for_non_owners(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        msg.editContent("final content")
        someone_else = self.factory.makePerson()

        with person_logged_in(self.person):
            revision_url = api_url(msg.revisions[0])

        ws = self.getWebservice(someone_else)
        response = ws.named_post(revision_url, "deleteContent")
        self.assertEqual(401, response.status)

        revision = ws.get(revision_url).jsonBody()
        self.assertThat(revision, ContainsDict({
            "date_created": Not(Is(None)),
            "date_deleted": Is(None),
            "content": Equals("initial content"),
            "self_link": EndsWith("/revisions/1")
        }))
