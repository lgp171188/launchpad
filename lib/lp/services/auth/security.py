# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.auth package."""

__all__ = []

from zope.component import queryAdapter

from lp.app.interfaces.security import IAuthorization
from lp.app.security import AuthorizationBase
from lp.services.auth.interfaces import IAccessToken


class EditAccessToken(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = IAccessToken

    def checkAuthenticated(self, user):
        if user.inTeam(self.obj.owner):
            return True
        # Being able to edit the token doesn't allow extracting the secret,
        # so it's OK to allow the owner of the target to do so too.  This
        # allows target owners to exercise some control over access to their
        # object.
        adapter = queryAdapter(
            self.obj.target, IAuthorization, 'launchpad.Edit')
        if adapter is not None and adapter.checkAuthenticated(user):
            return True
        return False
