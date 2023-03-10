# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Common infrastructure for security policies.

The actual security policies for content objects live in the '.security'
module of the corresponding application package, e.g. `lp.registry.security`.
"""

__all__ = [
    "AdminByAdminsTeam",
    "AdminByBuilddAdmin",
    "AdminByCommercialTeamOrAdmins",
    "ModerateByRegistryExpertsOrAdmins",
    "OnlyBazaarExpertsAndAdmins",
    "OnlyRosettaExpertsAndAdmins",
    "OnlyVcsImportsAndAdmins",
]

from datetime import datetime, timedelta, timezone

from zope.interface import Interface

from lp.app.security import AuthorizationBase
from lp.services.config import config


class ViewByLoggedInUser(AuthorizationBase):
    """The default ruleset for the launchpad.View permission.

    By default, any logged-in user can see anything. More restrictive
    rulesets are defined in other IAuthorization implementations.
    """

    permission = "launchpad.View"
    usedfor = Interface

    def checkAuthenticated(self, user):
        """Any authenticated user can see this object."""
        return True


class AnyAllowedPersonDeferredToView(AuthorizationBase):
    """The default ruleset for the launchpad.AnyAllowedPerson permission.

    An authenticated user is delegated to the View security adapter. Since
    anonymous users are not logged in, they are denied.
    """

    permission = "launchpad.AnyAllowedPerson"
    usedfor = Interface

    def checkUnauthenticated(self):
        return False

    def checkAuthenticated(self, user):
        yield self.obj, "launchpad.View"


class AnyLegitimatePerson(AuthorizationBase):
    """The default ruleset for the launchpad.AnyLegitimatePerson permission.

    Some operations are open to Launchpad users in general, but we still don't
    want drive-by vandalism.
    """

    permission = "launchpad.AnyLegitimatePerson"
    usedfor = Interface

    def checkUnauthenticated(self):
        return False

    def _hasEnoughKarma(self, user):
        return user.person.karma >= config.launchpad.min_legitimate_karma

    def _isOldEnough(self, user):
        return datetime.now(
            timezone.utc
        ) - user.person.account.date_created >= timedelta(
            days=config.launchpad.min_legitimate_account_age
        )

    def checkAuthenticated(self, user):
        if not self._hasEnoughKarma(user) and not self._isOldEnough(user):
            return False
        return self.forwardCheckAuthenticated(
            user, self.obj, "launchpad.AnyAllowedPerson"
        )


class LimitedViewDeferredToView(AuthorizationBase):
    """The default ruleset for the launchpad.LimitedView permission.

    Few objects define LimitedView permission because it is only needed
    in cases where a user may know something about a private object. The
    default behaviour is to check if the user has launchpad.View permission;
    private objects must define their own launchpad.LimitedView checker to
    truly check the permission.
    """

    permission = "launchpad.LimitedView"
    usedfor = Interface

    def checkUnauthenticated(self):
        yield self.obj, "launchpad.View"

    def checkAuthenticated(self, user):
        yield self.obj, "launchpad.View"


class AdminByAdminsTeam(AuthorizationBase):
    permission = "launchpad.Admin"
    usedfor = Interface

    def checkAuthenticated(self, user):
        return user.in_admin


class AdminByCommercialTeamOrAdmins(AuthorizationBase):
    permission = "launchpad.Commercial"
    usedfor = Interface

    def checkAuthenticated(self, user):
        return user.in_commercial_admin or user.in_admin


class ModerateByRegistryExpertsOrAdmins(AuthorizationBase):
    permission = "launchpad.Moderate"
    usedfor = None

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_registry_experts


class OnlyRosettaExpertsAndAdmins(AuthorizationBase):
    """Base class that allow access to Rosetta experts and Launchpad admins."""

    def checkAuthenticated(self, user):
        """Allow Launchpad's admins and Rosetta experts edit all fields."""
        return user.in_admin or user.in_rosetta_experts


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
    permission = "launchpad.Admin"

    def checkAuthenticated(self, user):
        """Allow admins and buildd_admins."""
        return user.in_buildd_admin or user.in_admin
