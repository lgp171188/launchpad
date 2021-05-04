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
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    )
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

    def test_export_message_revisions(self):
        msg = self.makeMessage(content="initial content")
        msg.editContent("new content 1")
        msg.editContent("final content")
        ws = self.getWebservice(self.person)
        url = self.getMessageAPIURL(msg)

        ws_message = ws.get(url).jsonBody()
        if self.message_type != "question":
            return
        revisions = ws.get(ws_message['revisions_collection_link']).jsonBody()
        revisions = ws.get(ws_message['revisions_collection_link']
                           + "/1").jsonBody()

