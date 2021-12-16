# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views of bases for charms."""

__all__ = [
    "CharmBaseSetNavigation",
    ]

from zope.component import getUtility

from lp.charms.interfaces.charmbase import ICharmBaseSet
from lp.services.webapp.publisher import Navigation


class CharmBaseSetNavigation(Navigation):
    """Navigation methods for `ICharmBaseSet`."""
    usedfor = ICharmBaseSet

    def traverse(self, name):
        try:
            base_id = int(name)
        except ValueError:
            return None
        return getUtility(ICharmBaseSet).getByID(base_id)
