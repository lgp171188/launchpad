# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Storm implementation of IQuestionReopening."""

__all__ = ["QuestionReopening", "create_questionreopening"]

from datetime import timezone

from lazr.lifecycle.event import ObjectCreatedEvent
from storm.locals import DateTime, Int, Reference
from zope.event import notify
from zope.interface import implementer
from zope.security.proxy import ProxyFactory

from lp.answers.enums import QuestionStatus
from lp.answers.interfaces.questionreopening import IQuestionReopening
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase


@implementer(IQuestionReopening)
class QuestionReopening(StormBase):
    """A table recording each time a question is re-opened."""

    __storm_table__ = "QuestionReopening"

    id = Int(primary=True)

    question_id = Int(name="question", allow_none=False)
    question = Reference(question_id, "Question.id")
    datecreated = DateTime(
        name="datecreated",
        allow_none=False,
        default=DEFAULT,
        tzinfo=timezone.utc,
    )
    reopener_id = Int(
        name="reopener", allow_none=False, validator=validate_public_person
    )
    reopener = Reference(reopener_id, "Person.id")
    answerer_id = Int(
        name="answerer",
        allow_none=True,
        default=None,
        validator=validate_public_person,
    )
    answerer = Reference(answerer_id, "Person.id")
    date_solved = DateTime(allow_none=True, default=None, tzinfo=timezone.utc)
    priorstate = DBEnum(
        name="priorstate", enum=QuestionStatus, allow_none=False
    )

    def __init__(
        self,
        question,
        reopener,
        datecreated,
        answerer,
        date_solved,
        priorstate,
    ):
        self.question = question
        self.reopener = reopener
        self.datecreated = datecreated
        self.answerer = answerer
        self.date_solved = date_solved
        self.priorstate = priorstate


def create_questionreopening(
    question, reopen_msg, old_status, old_answerer, old_date_solved
):
    """Helper function to handle question reopening.

    A QuestionReopening is created when question with an answer changes back
    to the OPEN state.
    """
    # XXX jcsackett This guard has to be maintained because reopen can
    # be called with the question in a bad state.
    if old_answerer is None:
        return
    reopening = QuestionReopening(
        question=question,
        reopener=reopen_msg.owner,
        datecreated=reopen_msg.datecreated,
        answerer=old_answerer,
        date_solved=old_date_solved,
        priorstate=old_status,
    )
    reopening = ProxyFactory(reopening)
    notify(ObjectCreatedEvent(reopening, user=reopen_msg.owner))
