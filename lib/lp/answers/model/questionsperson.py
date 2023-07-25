# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "QuestionsPersonMixin",
]

from storm.expr import Or, Select, Union

from lp.answers.enums import QUESTION_STATUS_DEFAULT_SEARCH
from lp.answers.model.answercontact import AnswerContact
from lp.answers.model.question import Question, QuestionPersonSearch
from lp.answers.model.questionmessage import QuestionMessage
from lp.answers.model.questionsubscription import QuestionSubscription
from lp.registry.model.teammembership import TeamParticipation
from lp.services.database.interfaces import IStore
from lp.services.worlddata.model.language import Language


class QuestionsPersonMixin:
    """See `IQuestionsPerson`."""

    def searchQuestions(
        self,
        search_text=None,
        status=QUESTION_STATUS_DEFAULT_SEARCH,
        language=None,
        sort=None,
        participation=None,
        needs_attention=None,
    ):
        """See `IQuestionsPerson`."""
        return QuestionPersonSearch(
            person=self,
            search_text=search_text,
            status=status,
            language=language,
            sort=sort,
            participation=participation,
            needs_attention=needs_attention,
        ).getResults()

    def getQuestionLanguages(self):
        """See `IQuestionCollection`."""
        return set(
            IStore(Language)
            .find(
                Language,
                Question.language == Language.id,
                Question.id.is_in(
                    Union(
                        Select(
                            Question.id,
                            where=Or(
                                Question.owner == self,
                                Question.answerer == self,
                                Question.assignee == self,
                            ),
                        ),
                        Select(
                            QuestionSubscription.question_id,
                            QuestionSubscription.person == self,
                        ),
                        Select(
                            QuestionMessage.question_id,
                            QuestionMessage.owner == self,
                        ),
                    )
                ),
            )
            .config(distinct=True)
        )

    def getDirectAnswerQuestionTargets(self):
        """See `IQuestionsPerson`."""
        answer_contacts = IStore(AnswerContact).find(
            AnswerContact, AnswerContact.person == self
        )
        return self._getQuestionTargetsFromAnswerContacts(answer_contacts)

    def getTeamAnswerQuestionTargets(self):
        """See `IQuestionsPerson`."""
        answer_contacts = (
            IStore(AnswerContact)
            .find(
                AnswerContact,
                AnswerContact.person == TeamParticipation.team_id,
                TeamParticipation.person == self,
                AnswerContact.person != self,
            )
            .config(distinct=True)
        )
        return self._getQuestionTargetsFromAnswerContacts(answer_contacts)

    def _getQuestionTargetsFromAnswerContacts(self, answer_contacts):
        """Return a list of active IQuestionTargets.

        :param answer_contacts: an iterable of `AnswerContact`s.
        :return: a list of active `IQuestionTarget`s.
        :raise AssertionError: if the IQuestionTarget is not a `Product`,
            `Distribution`, or `SourcePackage`.
        """
        targets = set()
        for answer_contact in answer_contacts:
            if answer_contact.product is not None:
                target = answer_contact.product
                pillar = target
            elif answer_contact.sourcepackagename is not None:
                assert (
                    answer_contact.distribution is not None
                ), "Missing distribution."
                distribution = answer_contact.distribution
                target = distribution.getSourcePackage(
                    answer_contact.sourcepackagename
                )
                pillar = distribution
            elif answer_contact.distribution is not None:
                target = answer_contact.distribution
                pillar = target
            else:
                raise AssertionError("Unknown IQuestionTarget.")

            if pillar.active:
                # Deactivated pillars are not valid IQuestionTargets.
                targets.add(target)

        return list(targets)
