# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["Component", "ComponentSelection", "ComponentSet"]

from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.interfaces.component import (
    IComponent,
    IComponentSelection,
    IComponentSet,
)


@implementer(IComponent)
class Component(StormBase):
    """See IComponent."""

    __storm_table__ = "Component"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super().__init__()
        self.name = name

    def __repr__(self):
        return "<%s '%s'>" % (self.__class__.__name__, self.name)


@implementer(IComponentSelection)
class ComponentSelection(StormBase):
    """See IComponentSelection."""

    __storm_table__ = "ComponentSelection"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")
    component_id = Int(name="component", allow_none=False)
    component = Reference(component_id, "Component.id")

    def __init__(self, distroseries, component):
        super().__init__()
        self.distroseries = distroseries
        self.component = component


@implementer(IComponentSet)
class ComponentSet:
    """See IComponentSet."""

    def __iter__(self):
        """See IComponentSet."""
        return iter(IStore(Component).find(Component))

    def __getitem__(self, name):
        """See IComponentSet."""
        component = IStore(Component).find(Component, name=name).one()
        if component is not None:
            return component
        raise NotFoundError(name)

    def get(self, component_id):
        """See IComponentSet."""
        return IStore(Component).get(Component, component_id)

    def ensure(self, name):
        """See IComponentSet."""
        component = IStore(Component).find(Component, name=name).one()
        if component is not None:
            return component
        return self.new(name)

    def new(self, name):
        """See IComponentSet."""
        component = Component(name=name)
        IStore(Component).add(component)
        return component
