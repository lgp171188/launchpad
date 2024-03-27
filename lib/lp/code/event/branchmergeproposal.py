# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event implementation classes for branch merge proposal events."""

__all__ = [
    "BranchMergeProposalNeedsReviewEvent",
    "ReviewerNominatedEvent",
]

from zope.interface import implementer
from zope.interface.interfaces import ObjectEvent

from lp.code.interfaces.event import (
    IBranchMergeProposalNeedsReviewEvent,
    IReviewerNominatedEvent,
)


@implementer(IBranchMergeProposalNeedsReviewEvent)
class BranchMergeProposalNeedsReviewEvent(ObjectEvent):
    """The merge proposal has moved from work in progress to needs reivew."""


@implementer(IReviewerNominatedEvent)
class ReviewerNominatedEvent(ObjectEvent):
    """A reviewer has been nominated."""
