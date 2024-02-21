# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BranchRevision",
]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.code.interfaces.branchrevision import IBranchRevision
from lp.services.database.stormbase import StormBase


@implementer(IBranchRevision)
class BranchRevision(StormBase):
    """See `IBranchRevision`."""

    __storm_table__ = "BranchRevision"
    __storm_primary__ = ("branch_id", "revision_id")

    branch_id = Int(name="branch", allow_none=False)
    branch = Reference(branch_id, "Branch.id")

    revision_id = Int(name="revision", allow_none=False)
    revision = Reference(revision_id, "Revision.id")

    sequence = Int(name="sequence", allow_none=True)

    def __init__(self, branch, revision, sequence=None):
        self.branch = branch
        self.revision = revision
        self.sequence = sequence
