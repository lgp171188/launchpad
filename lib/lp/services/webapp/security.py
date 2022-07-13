# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Security adapters for the lp.services.webapp package."""

__all__ = [
    "EditByRegistryExpertsOrAdmins",
]

from lp.app.security import AuthorizationBase
from lp.services.webapp.interfaces import ILaunchpadRoot


class EditByRegistryExpertsOrAdmins(AuthorizationBase):
    permission = 'launchpad.Edit'
    usedfor = ILaunchpadRoot

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_registry_experts
