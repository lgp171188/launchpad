# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for events used in the launchpad code application."""

__all__ = [
    "IBranchMergeProposalNeedsReviewEvent",
    "IGitRefsCreatedEvent",
    "IGitRefsUpdatedEvent",
    "IReviewerNominatedEvent",
]


from zope.interface.interfaces import IObjectEvent


class IReviewerNominatedEvent(IObjectEvent):
    """A reviewer has been nominated."""


class IBranchMergeProposalNeedsReviewEvent(IObjectEvent):
    """The merge proposal has moved from work in progress to needs reivew."""


class IGitRefsCreatedEvent(IObjectEvent):
    """Some references in a Git repository have been created."""


class IGitRefsUpdatedEvent(IObjectEvent):
    """Some references in a Git repository have been updated."""
