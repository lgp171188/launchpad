# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.openid package."""

__all__ = []

from lp.app.security import AuthorizationBase
from lp.services.openid.interfaces.openididentifier import IOpenIdIdentifier


class ViewOpenIdIdentifierBySelfOrAdmin(AuthorizationBase):
    permission = "launchpad.View"
    usedfor = IOpenIdIdentifier

    def checkAuthenticated(self, user):
        return user.in_admin or user.person.account_id == self.obj.account_id
