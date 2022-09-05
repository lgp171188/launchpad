# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Personal access token webservice registrations."""

__all__ = [
    "IAccessToken",
    "IAccessTokenTarget",
]

from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.auth.interfaces import IAccessToken, IAccessTokenTarget
from lp.services.webservice.apihelpers import patch_reference_property

# IAccessToken
patch_reference_property(IAccessToken, "git_repository", IGitRepository)
