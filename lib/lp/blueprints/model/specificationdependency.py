# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["SpecificationDependency"]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.blueprints.interfaces.specificationdependency import (
    ISpecificationDependency,
)
from lp.services.database.stormbase import StormBase


@implementer(ISpecificationDependency)
class SpecificationDependency(StormBase):
    """A link between a spec and a bug."""

    __storm_table__ = "SpecificationDependency"

    id = Int(primary=True)

    specification_id = Int(name="specification", allow_none=False)
    specification = Reference(specification_id, "Specification.id")

    dependency_id = Int(name="dependency", allow_none=False)
    dependency = Reference(dependency_id, "Specification.id")

    def __init__(self, specification, dependency):
        super().__init__()
        self.specification = specification
        self.dependency = dependency
