#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

from lp.app.security import AuthorizationBase
from lp.services.features.interfaces import IFeatureRules


class ViewFeatureRules(AuthorizationBase):
    """
    A member of ~admin, ~registry or ~launchpad can view the feature rules.
    """

    permission = "launchpad.View"
    usedfor = IFeatureRules

    def checkAuthenticated(self, user):
        return (
            user.in_admin
            or user.in_registry_experts
            or user.in_launchpad_developers
        )


class EditFeatureRules(AuthorizationBase):
    """
    A member of ~admin or ~launchpad can edit the feature rules.
    """

    permission = "launchpad.Edit"
    usedfor = IFeatureRules

    def checkAuthenticated(self, user):
        return user.in_admin or user.in_launchpad_developers
