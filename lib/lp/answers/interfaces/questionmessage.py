# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Question message interface."""

__all__ = [
    "IQuestionMessage",
]

from lazr.restful.declarations import exported, exported_as_webservice_entry
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Choice, Int

from lp import _
from lp.answers.enums import QuestionAction, QuestionStatus
from lp.services.messages.interfaces.message import IMessage, IMessageView


class IQuestionMessageView(IMessageView):
    """Publicly visible attributes of a message part of a question."""

    # This is really an Object field with schema=IQuestion, but that
    # would create a circular dependency between IQuestion
    # and IQuestionMessage
    question = exported(
        Reference(
            title=_("The question related to this message."),
            schema=Interface,
            description=_("An IQuestion object."),
            required=True,
            readonly=True,
        ),
        as_of="devel",
    )
    action = exported(
        Choice(
            title=_("Action operated on the question by this message."),
            required=True,
            readonly=True,
            default=QuestionAction.COMMENT,
            vocabulary=QuestionAction,
        ),
        as_of="devel",
    )
    new_status = exported(
        Choice(
            title=_("Question status after message"),
            description=_(
                "The status of the question after the transition "
                "related the action operated by this message."
            ),
            required=True,
            readonly=True,
            default=QuestionStatus.OPEN,
            vocabulary=QuestionStatus,
        ),
        as_of="devel",
    )
    index = Int(
        title=_("Message index."),
        description=_(
            "The messages 0-index in the question's list of messages."
        ),
        readonly=True,
    )
    display_index = exported(
        Int(
            title=_("Human readable Message index."),
            description=_(
                "The message's index in the question's list of messages."
            ),
            readonly=True,
        ),
        exported_as="index",
    )


@exported_as_webservice_entry(as_of="devel")
class IQuestionMessage(IQuestionMessageView, IMessage):
    """A message part of a question."""
