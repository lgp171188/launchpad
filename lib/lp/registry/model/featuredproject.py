# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for Featured Projects."""

__all__ = [
    "FeaturedProject",
]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.registry.interfaces.featuredproject import IFeaturedProject
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IFeaturedProject)
class FeaturedProject(StormBase):
    """A featured project reference.

    This is a reference to the name of a project, product or distribution
    that is currently being "featured" by being listed on the Launchpad home
    page.
    """

    __storm_table__ = "FeaturedProject"
    __storm_order__ = ["id"]

    id = Int(primary=True)
    pillar_name_id = Int(name="pillar_name", allow_none=False)
    pillar_name = Reference(pillar_name_id, "PillarName.id")

    def __init__(self, pillar_name):
        super().__init__()
        self.pillar_name = pillar_name

    def destroySelf(self):
        IStore(self).remove(self)
