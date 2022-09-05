# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["Section", "SectionSelection", "SectionSet"]

from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.interfaces.section import (
    ISection,
    ISectionSelection,
    ISectionSet,
)


@implementer(ISection)
class Section(StormBase):
    """See ISection"""

    __storm_table__ = "Section"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super().__init__()
        self.name = name


@implementer(ISectionSelection)
class SectionSelection(StormBase):
    """See ISectionSelection."""

    __storm_table__ = "SectionSelection"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")
    section_id = Int(name="section", allow_none=False)
    section = Reference(section_id, "Section.id")

    def __init__(self, distroseries, section):
        super().__init__()
        self.distroseries = distroseries
        self.section = section


@implementer(ISectionSet)
class SectionSet:
    """See ISectionSet."""

    def __iter__(self):
        """See ISectionSet."""
        return iter(IStore(Section).find(Section))

    def __getitem__(self, name):
        """See ISectionSet."""
        section = IStore(Section).find(Section, name=name).one()
        if section is not None:
            return section
        raise NotFoundError(name)

    def get(self, section_id):
        """See ISectionSet."""
        return IStore(Section).get(Section, section_id)

    def ensure(self, name):
        """See ISectionSet."""
        section = IStore(Section).find(Section, name=name).one()
        if section is not None:
            return section
        return self.new(name)

    def new(self, name):
        """See ISectionSet."""
        section = Section(name=name)
        IStore(Section).add(section)
        return section
