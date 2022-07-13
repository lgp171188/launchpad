# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.identity package."""

__all__ = []

from lp.app.security import AuthorizationBase
from lp.registry.security import EditByOwnersOrAdmins
from lp.services.identity.interfaces.emailaddress import IEmailAddress


class ViewEmailAddress(AuthorizationBase):
    permission = 'launchpad.View'
    usedfor = IEmailAddress

    def checkUnauthenticated(self):
        """See `AuthorizationBase`."""
        # Anonymous users can never see email addresses.
        return False

    def checkAuthenticated(self, user):
        """Can the user see the details of this email address?

        If the email address' owner doesn't want their email addresses to be
        hidden, anyone can see them.  Otherwise only the owner themselves or
        admins can see them.
        """
        # Always allow users to see their own email addresses.
        if self.obj.person == user:
            return True

        if not (self.obj.person is None or
                self.obj.person.hide_email_addresses):
            return True

        return (self.obj.person is not None and user.inTeam(self.obj.person)
                or user.in_commercial_admin
                or user.in_registry_experts
                or user.in_admin)


class EditEmailAddress(EditByOwnersOrAdmins):
    permission = 'launchpad.Edit'
    usedfor = IEmailAddress

    def checkAuthenticated(self, user):
        # Always allow users to see their own email addresses.
        if self.obj.person == user:
            return True
        return super().checkAuthenticated(user)
