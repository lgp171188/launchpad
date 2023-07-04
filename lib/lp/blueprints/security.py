# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the blueprints package."""

__all__ = [
    "AdminSpecification",
    "EditSpecificationByRelatedPeople",
    "ViewSpecification",
]

from lp.app.security import AnonymousAuthorization, AuthorizationBase
from lp.blueprints.interfaces.specification import (
    ISpecification,
    ISpecificationPublic,
    ISpecificationView,
)
from lp.blueprints.interfaces.specificationbranch import ISpecificationBranch
from lp.blueprints.interfaces.specificationsubscription import (
    ISpecificationSubscription,
)
from lp.blueprints.interfaces.sprint import ISprint
from lp.blueprints.interfaces.sprintspecification import ISprintSpecification
from lp.registry.security import EditByOwnersOrAdmins
from lp.security import ModerateByRegistryExpertsOrAdmins


class EditSpecificationBranch(AuthorizationBase):
    usedfor = ISpecificationBranch
    permission = "launchpad.Edit"

    def checkAuthenticated(self, user):
        """See `IAuthorization.checkAuthenticated`.

        :return: True or False.
        """
        return True


class ViewSpecificationBranch(EditSpecificationBranch):
    permission = "launchpad.View"

    def checkUnauthenticated(self):
        """See `IAuthorization.checkUnauthenticated`.

        :return: True or False.
        """
        return True


class AnonymousAccessToISpecificationPublic(AnonymousAuthorization):
    """Anonymous users have launchpad.View on ISpecificationPublic.

    This is only needed because lazr.restful is hard-coded to check that
    permission before returning things in a collection.
    """

    permission = "launchpad.View"
    usedfor = ISpecificationPublic


class ViewSpecification(AuthorizationBase):
    permission = "launchpad.LimitedView"
    usedfor = ISpecificationView

    def checkAuthenticated(self, user):
        return self.obj.userCanView(user)

    def checkUnauthenticated(self):
        return self.obj.userCanView(None)


class EditSpecificationByRelatedPeople(AuthorizationBase):
    """We want everybody "related" to a specification to be able to edit it.
    You are related if you have a role on the spec, or if you have a role on
    the spec target (distro/product) or goal (distroseries/productseries).
    """

    permission = "launchpad.Edit"
    usedfor = ISpecification

    def checkAuthenticated(self, user):
        assert self.obj.target
        goal = self.obj.goal
        if goal is not None:
            if user.isOwner(goal) or user.isDriver(goal):
                return True
        return (
            user.in_admin
            or user.in_registry_experts
            or user.isOwner(self.obj.target)
            or user.isDriver(self.obj.target)
            or user.isOneOf(
                self.obj, ["owner", "drafter", "assignee", "approver"]
            )
        )


class AdminSpecification(AuthorizationBase):
    permission = "launchpad.Admin"
    usedfor = ISpecification

    def checkAuthenticated(self, user):
        assert self.obj.target
        return (
            user.in_admin
            or user.in_registry_experts
            or user.isOwner(self.obj.target)
            or user.isDriver(self.obj.target)
        )


class DriverSpecification(AuthorizationBase):
    permission = "launchpad.Driver"
    usedfor = ISpecification

    def checkAuthenticated(self, user):
        # If no goal is proposed for the spec then there can be no
        # drivers for it - we use launchpad.Driver on a spec to decide
        # if the person can see the page which lets you decide whether
        # to accept the goal, and if there is no goal then this is
        # extremely difficult to do :-)
        return self.obj.goal and self.forwardCheckAuthenticated(
            user, self.obj.goal
        )


class EditSprintSpecification(AuthorizationBase):
    """The sprint owner or driver can say what makes it onto the agenda for
    the sprint.
    """

    permission = "launchpad.Driver"
    usedfor = ISprintSpecification

    def checkAuthenticated(self, user):
        sprint = self.obj.sprint
        return user.isOwner(sprint) or user.isDriver(sprint) or user.in_admin


class DriveSprint(AuthorizationBase):
    """The sprint owner or driver can say what makes it onto the agenda for
    the sprint.
    """

    permission = "launchpad.Driver"
    usedfor = ISprint

    def checkAuthenticated(self, user):
        return (
            user.isOwner(self.obj) or user.isDriver(self.obj) or user.in_admin
        )


class ViewSprint(AuthorizationBase):
    """An attendee, owner, or driver of a sprint."""

    permission = "launchpad.View"
    usedfor = ISprint

    def checkAuthenticated(self, user):
        return (
            user.isOwner(self.obj)
            or user.isDriver(self.obj)
            or user.person
            in [attendance.attendee for attendance in self.obj.attendances]
            or user.in_admin
        )


class EditSprint(EditByOwnersOrAdmins):
    usedfor = ISprint


class ModerateSprint(ModerateByRegistryExpertsOrAdmins):
    """The sprint owner, registry experts, and admins can moderate sprints."""

    permission = "launchpad.Moderate"
    usedfor = ISprint

    def checkAuthenticated(self, user):
        return super().checkAuthenticated(user) or user.isOwner(self.obj)


class EditSpecificationSubscription(AuthorizationBase):
    """The subscriber, and people related to the spec or the target of the
    spec can determine who is essential."""

    permission = "launchpad.Edit"
    usedfor = ISpecificationSubscription

    def checkAuthenticated(self, user):
        if self.obj.specification.goal is not None:
            if user.isDriver(self.obj.specification.goal):
                return True
        else:
            if user.isDriver(self.obj.specification.target):
                return True
        return (
            user.inTeam(self.obj.person)
            or user.isOneOf(
                self.obj.specification,
                ["owner", "drafter", "assignee", "approver"],
            )
            or user.in_admin
        )
