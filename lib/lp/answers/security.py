# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the answers package."""

from typing import List

from lp.answers.interfaces.faq import IFAQ
from lp.answers.interfaces.faqtarget import IFAQTarget
from lp.answers.interfaces.question import IQuestion
from lp.answers.interfaces.questionmessage import IQuestionMessage
from lp.answers.interfaces.questionsperson import IQuestionsPerson
from lp.answers.interfaces.questiontarget import IQuestionTarget
from lp.app.security import AnonymousAuthorization, AuthorizationBase
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.security import EditByOwnersOrAdmins

__all__: List[str] = []


class AdminQuestion(AuthorizationBase):
    permission = "launchpad.Admin"
    usedfor = IQuestion

    def checkAuthenticated(self, user):
        """Allow only admins and owners of the question pillar target."""
        context = self.obj.product or self.obj.distribution
        return (
            user.in_admin
            or user.in_registry_experts
            or user.inTeam(context.owner)
        )


class AppendQuestion(AdminQuestion):
    permission = "launchpad.Append"
    usedfor = IQuestion

    def checkAuthenticated(self, user):
        """Allow user who can administer the question and answer contacts."""
        if AdminQuestion.checkAuthenticated(self, user):
            return True
        question_target = self.obj.target
        if IDistributionSourcePackage.providedBy(question_target):
            question_targets = (question_target, question_target.distribution)
        else:
            question_targets = (question_target,)
        questions_person = IQuestionsPerson(user.person)
        for target in questions_person.getDirectAnswerQuestionTargets():
            if target in question_targets:
                return True
        for target in questions_person.getTeamAnswerQuestionTargets():
            if target in question_targets:
                return True
        return False


class QuestionOwner(AuthorizationBase):
    permission = "launchpad.Owner"
    usedfor = IQuestion

    def checkAuthenticated(self, user):
        """Allow the question's owner."""
        return user.inTeam(self.obj.owner)


class EditQuestion(AuthorizationBase):
    permission = "launchpad.Edit"
    usedfor = IQuestion

    def checkAuthenticated(self, user):
        return AdminQuestion(self.obj).checkAuthenticated(
            user
        ) or QuestionOwner(self.obj).checkAuthenticated(user)


class ViewQuestion(AnonymousAuthorization):
    usedfor = IQuestion


class ViewQuestionMessage(AnonymousAuthorization):
    usedfor = IQuestionMessage


class ModerateQuestionMessage(AuthorizationBase):
    permission = "launchpad.Moderate"
    usedfor = IQuestionMessage

    def checkAuthenticated(self, user):
        """Admins, Registry, Maintainers, and comment owners can moderate."""
        return (
            user.in_admin
            or user.in_registry_experts
            or user.inTeam(self.obj.owner)
            or user.inTeam(self.obj.question.target.owner)
        )


class AppendFAQTarget(EditByOwnersOrAdmins):
    permission = "launchpad.Append"
    usedfor = IFAQTarget

    def checkAuthenticated(self, user):
        """Allow people with launchpad.Edit or an answer contact."""
        if (
            EditByOwnersOrAdmins.checkAuthenticated(self, user)
            or user.in_registry_experts
        ):
            return True
        if IQuestionTarget.providedBy(self.obj):
            # Adapt QuestionTargets to FAQTargets to ensure the correct
            # object is being examined; the implementers are not synonymous.
            faq_target = IFAQTarget(self.obj)
            questions_person = IQuestionsPerson(user.person)
            for target in questions_person.getDirectAnswerQuestionTargets():
                if IFAQTarget(target) == faq_target:
                    return True
            for target in questions_person.getTeamAnswerQuestionTargets():
                if IFAQTarget(target) == faq_target:
                    return True
        return False


class EditFAQ(AuthorizationBase):
    permission = "launchpad.Edit"
    usedfor = IFAQ

    def checkAuthenticated(self, user):
        """Allow only admins and owners of the FAQ target."""
        return (
            user.in_admin
            or user.in_registry_experts
            or user.inTeam(self.obj.target.owner)
        )


class DeleteFAQ(AuthorizationBase):
    permission = "launchpad.Delete"
    usedfor = IFAQ

    def checkAuthenticated(self, user):
        return user.in_registry_experts or user.in_admin
