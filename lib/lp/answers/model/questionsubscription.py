# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""StormBase implementation of IQuestionSubscription."""

__all__ = ["QuestionSubscription"]

from datetime import timezone

from storm.locals import DateTime, Int, Reference
from zope.interface import implementer

from lp.answers.interfaces.questionsubscription import IQuestionSubscription
from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.role import IPersonRoles
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase


@implementer(IQuestionSubscription)
class QuestionSubscription(StormBase):
    """A subscription for person to a question."""

    __storm_table__ = "QuestionSubscription"

    id = Int(primary=True)
    question_id = Int(name="question", allow_none=False)
    question = Reference(question_id, "Question.id")

    person_id = Int(
        name="person", allow_none=False, validator=validate_public_person
    )
    person = Reference(person_id, "Person.id")

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )

    def __init__(self, question, person):
        self.question = question
        self.person = person

    def canBeUnsubscribedByUser(self, user):
        """See `IQuestionSubscription`."""
        if user is None:
            return False
        # The people who can unsubscribe someone are:
        # - lp admins
        # - the person themselves
        # - the question owner
        # - people who can reject questions (eg target owner, answer contacts)
        return (
            user.inTeam(self.question.owner)
            or user.inTeam(self.person)
            or IPersonRoles(user).in_admin
            or self.question.canReject(user)
        )
