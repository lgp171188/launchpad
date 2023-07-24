# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Storm implementation of IQuestionMessage."""

__all__ = [
    "QuestionMessage",
]

from lazr.delegates import delegate_to
from storm.locals import Int, Reference
from zope.interface import implementer

from lp.answers.enums import QuestionAction, QuestionStatus
from lp.answers.interfaces.questionmessage import IQuestionMessage
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.services.messages.interfaces.message import IMessage
from lp.services.propertycache import cachedproperty


@implementer(IQuestionMessage)
@delegate_to(IMessage, context="message")
class QuestionMessage(StormBase):
    """A table linking questions and messages."""

    __storm_table__ = "QuestionMessage"

    id = Int(primary=True)
    question_id = Int(name="question", allow_none=False)
    question = Reference(question_id, "Question.id")

    message_id = Int(name="message", allow_none=False)
    message = Reference(message_id, "Message.id")

    action = DBEnum(
        name="action",
        enum=QuestionAction,
        default=QuestionAction.COMMENT,
        allow_none=False,
    )

    new_status = DBEnum(
        name="new_status",
        enum=QuestionStatus,
        default=QuestionStatus.OPEN,
        allow_none=False,
    )

    owner_id = Int(
        name="owner", allow_none=False, validator=validate_public_person
    )
    owner = Reference(owner_id, "Person.id")

    def __init__(self, question, message, action, new_status, owner):
        self.question = question
        self.message = message
        self.action = action
        self.new_status = new_status
        self.owner = owner if owner else self.message.owner

    def __iter__(self):
        """See IMessage."""
        # Delegates do not proxy __ methods, because of the name mangling.
        return iter(self.chunks)

    @cachedproperty
    def index(self):
        return list(self.question.messages).index(self)

    @cachedproperty
    def display_index(self):
        # Return the index + 1 so that messages appear 1-indexed in the UI.
        return self.index + 1

    @property
    def visible(self):
        """See `IQuestionMessage.`"""
        return self.message.visible
