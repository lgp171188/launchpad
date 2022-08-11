#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import Interface


class IHasBadges(Interface):
    """A method to determine visible badges.

    Badges are used to show connections between different content objects, for
    example a BugBranch is a link between a bug and a branch.  To represent
    this link a bug has a branch badge, and the branch has a bug badge.

    Badges should honour the visibility of the linked objects.
    """

    def getVisibleBadges():
        """Return a list of `Badge` objects that the logged-in user can see."""
