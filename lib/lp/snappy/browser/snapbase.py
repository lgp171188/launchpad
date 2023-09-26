# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views of bases for snaps."""

__all__ = [
    "SnapBaseNavigation",
    "SnapBaseSetNavigation",
]

from zope.component import getUtility

from lp.services.webapp import GetitemNavigation, Navigation, stepthrough
from lp.snappy.interfaces.snapbase import ISnapBase, ISnapBaseSet
from lp.soyuz.interfaces.archive import IArchiveSet


class SnapBaseNavigation(Navigation):
    """Navigation methods for `ISnapBase`."""

    usedfor = ISnapBase

    @stepthrough("+dependency")
    def traverse_dependency(self, id):
        """Traverse to an archive dependency by archive ID.

        We use `IArchive.getArchiveDependency` here, which is protected by
        `launchpad.View`, so you cannot get to a dependency of a private
        archive that you can't see.
        """
        try:
            id = int(id)
        except ValueError:
            # Not a number.
            return None

        archive = getUtility(IArchiveSet).get(id)
        if archive is None:
            return None

        return self.context.getArchiveDependency(archive)


class SnapBaseSetNavigation(GetitemNavigation):
    """Navigation methods for `ISnapBaseSet`."""

    usedfor = ISnapBaseSet
