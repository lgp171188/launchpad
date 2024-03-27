# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["BranchSubscription"]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.code.enums import (
    BranchSubscriptionDiffSize,
    BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel,
)
from lp.code.interfaces.branchsubscription import IBranchSubscription
from lp.code.interfaces.branchtarget import IHasBranchTarget
from lp.code.security import BranchSubscriptionEdit
from lp.registry.interfaces.person import validate_person
from lp.registry.interfaces.role import IPersonRoles
from lp.services.database.constants import DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase


@implementer(IBranchSubscription, IHasBranchTarget)
class BranchSubscription(StormBase):
    """A relationship between a person and a branch."""

    __storm_table__ = "BranchSubscription"

    id = Int(primary=True)

    person_id = Int(name="person", allow_none=False, validator=validate_person)
    person = Reference(person_id, "Person.id")
    branch_id = Int(name="branch", allow_none=False)
    branch = Reference(branch_id, "Branch.id")
    notification_level = DBEnum(
        enum=BranchSubscriptionNotificationLevel,
        allow_none=False,
        default=DEFAULT,
    )
    max_diff_lines = DBEnum(
        enum=BranchSubscriptionDiffSize, allow_none=True, default=DEFAULT
    )
    review_level = DBEnum(
        enum=CodeReviewNotificationLevel, allow_none=False, default=DEFAULT
    )
    subscribed_by_id = Int(
        name="subscribed_by", allow_none=False, validator=validate_person
    )
    subscribed_by = Reference(subscribed_by_id, "Person.id")

    def __init__(
        self,
        person,
        branch,
        notification_level,
        max_diff_lines,
        review_level,
        subscribed_by,
    ):
        super().__init__()
        self.person = person
        self.branch = branch
        self.notification_level = notification_level
        self.max_diff_lines = max_diff_lines
        self.review_level = review_level
        self.subscribed_by = subscribed_by

    @property
    def target(self):
        """See `IHasBranchTarget`."""
        return self.branch.target

    def canBeUnsubscribedByUser(self, user):
        """See `IBranchSubscription`."""
        if user is None:
            return False
        permission_check = BranchSubscriptionEdit(self)
        return permission_check.checkAuthenticated(IPersonRoles(user))
