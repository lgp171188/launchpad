# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security policies for using content objects."""

__all__ = [
    'AdminByAdminsTeam',
    'AdminByBuilddAdmin',
    'AdminByCommercialTeamOrAdmins',
    'BugTargetOwnerOrBugSupervisorOrAdmins',
    'EditByOwnersOrAdmins',
    'EditByRegistryExpertsOrAdmins',
    'is_commercial_case',
    'ModerateByRegistryExpertsOrAdmins',
    'OnlyBazaarExpertsAndAdmins',
    'OnlyRosettaExpertsAndAdmins',
    'OnlyVcsImportsAndAdmins',
    ]

from datetime import (
    datetime,
    timedelta,
    )

import pytz
from zope.interface import Interface

from lp.app.security import AuthorizationBase
from lp.bugs.interfaces.bugtarget import IOfficialBugTagTargetRestricted
from lp.bugs.interfaces.structuralsubscription import IStructuralSubscription
from lp.registry.interfaces.role import IHasOwner
from lp.services.config import config
from lp.services.webapp.interfaces import ILaunchpadRoot


def is_commercial_case(obj, user):
    """Is this a commercial project and the user is a commercial admin?"""
    return obj.has_current_commercial_subscription and user.in_commercial_admin


class ViewByLoggedInUser(AuthorizationBase):
    """The default ruleset for the launchpad.View permission.

    By default, any logged-in user can see anything. More restrictive
    rulesets are defined in other IAuthorization implementations.
    """
    permission = 'launchpad.View'
    usedfor = Interface

    def checkAuthenticated(self, user):
        """Any authenticated user can see this object."""
        return True


class AnyAllowedPersonDeferredToView(AuthorizationBase):
    """The default ruleset for the launchpad.AnyAllowedPerson permission.

    An authenticated user is delegated to the View security adapter. Since
    anonymous users are not logged in, they are denied.
    """
    permission = 'launchpad.AnyAllowedPerson'
    usedfor = Interface

    def checkUnauthenticated(self):
        return False

    def checkAuthenticated(self, user):
        yield self.obj, 'launchpad.View'


class AnyLegitimatePerson(AuthorizationBase):
    """The default ruleset for the launchpad.AnyLegitimatePerson permission.

    Some operations are open to Launchpad users in general, but we still don't
    want drive-by vandalism.
    """
    permission = 'launchpad.AnyLegitimatePerson'
    usedfor = Interface

    def checkUnauthenticated(self):
        return False

    def _hasEnoughKarma(self, user):
        return user.person.karma >= config.launchpad.min_legitimate_karma

    def _isOldEnough(self, user):
        return (
            datetime.now(pytz.UTC) - user.person.account.date_created >=
            timedelta(days=config.launchpad.min_legitimate_account_age))

    def checkAuthenticated(self, user):
        if not self._hasEnoughKarma(user) and not self._isOldEnough(user):
            return False
        return self.forwardCheckAuthenticated(
            user, self.obj, 'launchpad.AnyAllowedPerson')


class LimitedViewDeferredToView(AuthorizationBase):
    """The default ruleset for the launchpad.LimitedView permission.

    Few objects define LimitedView permission because it is only needed
    in cases where a user may know something about a private object. The
    default behaviour is to check if the user has launchpad.View permission;
    private objects must define their own launchpad.LimitedView checker to
    truly check the permission.
    """
    permission = 'launchpad.LimitedView'
    usedfor = Interface

    def checkUnauthenticated(self):
        yield self.obj, 'launchpad.View'

    def checkAuthenticated(self, user):
        yield self.obj, 'launchpad.View'


class AdminByAdminsTeam(AuthorizationBase):
    permission = 'launchpad.Admin'
    usedfor = Interface

    def checkAuthenticated(self, user):
        return user.in_admin


class AdminByCommercialTeamOrAdmins(AuthorizationBase):
    permission = 'launchpad.Commercial'
    usedfor = Interface

    def checkAuthenticated(self, user):
        return user.in_commercial_admin or user.in_admin


class EditByRegistryExpertsOrAdmins(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = ILaunchpadRoot

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_registry_experts


class ModerateByRegistryExpertsOrAdmins(AuthorizationBase):
    permission = 'launchpad.Moderate'
    usedfor = None

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_registry_experts


class EditByOwnersOrAdmins(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IHasOwner

    def checkAuthenticated(self, user):
        return user.isOwner(self.obj) or user.in_admin


class OnlyRosettaExpertsAndAdmins(AuthorizationBase):
    """Base class that allow access to Rosetta experts and Launchpad admins.
    """

    def checkAuthenticated(self, user):
        """Allow Launchpad's admins and Rosetta experts edit all fields."""
        return user.in_admin or user.in_rosetta_experts


class BugTargetOwnerOrBugSupervisorOrAdmins(AuthorizationBase):
    """Product's owner and bug supervisor can set official bug tags."""

    permission = 'launchpad.BugSupervisor'
    usedfor = IOfficialBugTagTargetRestricted

    def checkAuthenticated(self, user):
        return (user.inTeam(self.obj.bug_supervisor) or
                user.inTeam(self.obj.owner) or
                user.in_admin)


class EditStructuralSubscription(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IStructuralSubscription

    def checkAuthenticated(self, user):
        """Who can edit StructuralSubscriptions."""

        assert self.obj.target

        # Removal of a target cascades removals to StructuralSubscriptions,
        # so we need to allow editing to those who can edit the target itself.
        can_edit_target = self.forwardCheckAuthenticated(
            user, self.obj.target)

        # Who is actually allowed to edit a subscription is determined by
        # a helper method on the model.
        can_edit_subscription = self.obj.target.userCanAlterSubscription(
            self.obj.subscriber, user.person)

        return (can_edit_target or can_edit_subscription)


class OnlyBazaarExpertsAndAdmins(AuthorizationBase):
    """Base class that allows only the Launchpad admins and Bazaar
    experts."""

    def checkAuthenticated(self, user):
        return user.in_admin


class OnlyVcsImportsAndAdmins(AuthorizationBase):
    """Base class that allows only the Launchpad admins and VCS Imports
    experts."""

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_vcs_imports


class AdminByBuilddAdmin(AuthorizationBase):
    permission = 'launchpad.Admin'

    def checkAuthenticated(self, user):
        """Allow admins and buildd_admins."""
        return user.in_buildd_admin or user.in_admin
