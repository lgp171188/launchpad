# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the craft package."""

__all__ = []

from lp.app.security import AuthorizationBase
from lp.crafts.interfaces.craftrecipe import ICraftRecipe


class ViewCraftRecipe(AuthorizationBase):
    """Private craft recipes are only visible to their owners and admins."""

    permission = "launchpad.View"
    usedfor = ICraftRecipe

    def checkAuthenticated(self, user):
        return self.obj.visibleByUser(user.person)

    def checkUnauthenticated(self):
        return self.obj.visibleByUser(None)


class EditCraftRecipe(AuthorizationBase):
    permission = "launchpad.Edit"
    usedfor = ICraftRecipe

    def checkAuthenticated(self, user):
        return (
            user.isOwner(self.obj) or user.in_commercial_admin or user.in_admin
        )


class AdminCraftRecipe(AuthorizationBase):
    """Restrict changing build settings on craft recipes.

    The security of the non-virtualised build farm depends on these
    settings, so they can only be changed by "PPA"/commercial admins, or by
    "PPA" self admins on craft recipes that they can already edit.
    """

    permission = "launchpad.Admin"
    usedfor = ICraftRecipe

    def checkAuthenticated(self, user):
        if user.in_ppa_admin or user.in_commercial_admin or user.in_admin:
            return True
        return user.in_ppa_self_admins and EditCraftRecipe(
            self.obj
        ).checkAuthenticated(user)
