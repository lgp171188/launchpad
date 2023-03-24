# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes for linking bugtasks and branches."""

__all__ = [
    "BugBranch",
    "BugBranchSet",
]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Store
from zope.interface import implementer

from lp.bugs.interfaces.bugbranch import IBugBranch, IBugBranchSet
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IBugBranch)
class BugBranch(StormBase):
    """See `IBugBranch`."""

    __storm_table__ = "BugBranch"

    id = Int(primary=True)

    datecreated = DateTime(
        name="datecreated",
        tzinfo=timezone.utc,
        allow_none=False,
        default=UTC_NOW,
    )
    bug_id = Int(name="bug", allow_none=False)
    bug = Reference(bug_id, "Bug.id")
    branch_id = Int(name="branch", allow_none=False)
    branch = Reference(branch_id, "Branch.id")

    registrant_id = Int(
        name="registrant", allow_none=False, validator=validate_public_person
    )
    registrant = Reference(registrant_id, "Person.id")

    def __init__(self, branch, bug, registrant):
        super().__init__()
        self.branch = branch
        self.bug = bug
        self.registrant = registrant

    def destroySelf(self):
        Store.of(self).remove(self)


@implementer(IBugBranchSet)
class BugBranchSet:
    def getBranchesWithVisibleBugs(self, branches, user):
        """See `IBugBranchSet`."""
        # Avoid circular imports.
        from lp.bugs.model.bugtaskflat import BugTaskFlat
        from lp.bugs.model.bugtasksearch import get_bug_privacy_filter

        branch_ids = [branch.id for branch in branches]
        if not branch_ids:
            return []

        visible = get_bug_privacy_filter(user)
        return (
            IStore(BugBranch)
            .find(
                BugBranch.branch_id,
                BugBranch.branch_id.is_in(branch_ids),
                BugTaskFlat.bug_id == BugBranch.bug_id,
                visible,
            )
            .config(distinct=True)
        )
