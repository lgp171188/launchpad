# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from testscenarios import WithScenarios
from zope.security.proxy import ProxyFactory

from lp.bugs.model.bugmessage import BugMessage
from lp.services.database.interfaces import IStore
from lp.testing import login_person


class MessageTypeScenariosMixin(WithScenarios):
    scenarios = [
        ("bug", {"message_type": "bug"}),
        ("question", {"message_type": "question"}),
        ("MP comment", {"message_type": "mp"}),
    ]

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        login_person(self.person)

    def makeMessage(self, content=None, **kwargs):
        owner = kwargs.pop("owner", self.person)
        if self.message_type == "bug":
            msg = self.factory.makeBugComment(
                owner=owner, body=content, **kwargs
            )
            return ProxyFactory(
                IStore(BugMessage)
                .find(BugMessage, BugMessage.message == msg)
                .one()
            )
        elif self.message_type == "question":
            question = self.factory.makeQuestion()
            return question.giveAnswer(owner, content)
        elif self.message_type == "mp":
            return self.factory.makeCodeReviewComment(
                sender=owner, body=content
            )
