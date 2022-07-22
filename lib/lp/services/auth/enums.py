# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enumerations used in lp.services.auth."""

__all__ = [
    "AccessTokenScope",
]

from lazr.enum import EnumeratedType, Item


class AccessTokenScope(EnumeratedType):
    """A scope specifying the capabilities of an access token."""

    REPOSITORY_BUILD_STATUS = Item(
        """
        repository:build_status

        Can see and update the build status for all commits in a repository.
        """
    )

    REPOSITORY_PUSH = Item(
        """
        repository:push

        Can push to a repository.
        """
    )
