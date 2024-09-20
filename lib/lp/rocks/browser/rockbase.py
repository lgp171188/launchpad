# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views of bases for rocks."""

__all__ = [
    "RockBaseSetNavigation",
]

from zope.component import getUtility

from lp.rocks.interfaces.rockbase import IRockBaseSet
from lp.services.webapp.publisher import Navigation


class RockBaseSetNavigation(Navigation):
    """Navigation methods for `IRockBaseSet`."""

    usedfor = IRockBaseSet

    def traverse(self, name):
        try:
            base_id = int(name)
        except ValueError:
            return None
        return getUtility(IRockBaseSet).getByID(base_id)
