# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes for linking specifications and branches."""

__all__ = [
    "SpecificationBranch",
    "SpecificationBranchSet",
]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Store
from zope.interface import implementer

from lp.blueprints.interfaces.specificationbranch import (
    ISpecificationBranch,
    ISpecificationBranchSet,
)
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(ISpecificationBranch)
class SpecificationBranch(StormBase):
    """See `ISpecificationBranch`."""

    __storm_table__ = "SpecificationBranch"

    id = Int(primary=True)

    datecreated = DateTime(
        name="datecreated",
        tzinfo=timezone.utc,
        allow_none=False,
        default=UTC_NOW,
    )
    specification_id = Int(name="specification", allow_none=False)
    specification = Reference(specification_id, "Specification.id")
    branch_id = Int(name="branch", allow_none=False)
    branch = Reference(branch_id, "Branch.id")

    registrant_id = Int(
        name="registrant", allow_none=False, validator=validate_public_person
    )
    registrant = Reference(registrant_id, "Person.id")

    def __init__(self, specification, branch, registrant):
        super().__init__()
        self.specification = specification
        self.branch = branch
        self.registrant = registrant

    def destroySelf(self):
        Store.of(self).remove(self)


@implementer(ISpecificationBranchSet)
class SpecificationBranchSet:
    """See `ISpecificationBranchSet`."""

    def getSpecificationBranchesForBranches(self, branches, user):
        """See `ISpecificationBranchSet`."""
        branch_ids = [branch.id for branch in branches]
        if not branch_ids:
            return []

        # When specifications gain the ability to be private, this
        # method will need to be updated to enforce the privacy checks.
        return IStore(SpecificationBranch).find(
            SpecificationBranch,
            SpecificationBranch.branch_id.is_in(branch_ids),
        )
