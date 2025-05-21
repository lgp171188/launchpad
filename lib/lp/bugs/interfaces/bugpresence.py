# Copyright 2009-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""BugPresence interfaces"""

__all__ = [
    "IBugPresence",
    "IBugPresenceSet",
]

from zope.interface import Interface
from zope.schema import Dict, Int

from lp import _
from lp.services.fields import BugField


class IBugPresence(Interface):
    """A single `BugPresence` database entry."""

    id = Int(title=_("ID"), required=True, readonly=True)
    bug = BugField(title=_("Bug"), readonly=True)
    product = Int(title=_("Product"))
    distribution = Int(title=_("Distribution"))
    source_package_name = Int(title=_("Source Package Name"))
    git_repository = Int(title=_("Git Repository"))
    break_fix_data = Dict(title=_("Break-Fix"))

    def destroySelf(self):
        """Destroy this `IBugPresence` object."""


class IBugPresenceSet(Interface):
    """The set of `IBugPresence` objects."""

    def __getitem__(id):
        """Get a `IBugPresence` by id."""

    def create(
        id,
        bug,
        product,
        distribution,
        source_package_name,
        git_repository,
        break_fix_data,
    ):
        """Create a new `IBugPresence`."""
