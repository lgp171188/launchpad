# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Event subscribers for branch merge proposals."""

from zope.component import getUtility
from zope.principalregistry.principalregistry import UnauthenticatedPrincipal

from lp.code.adapters.branch import BranchMergeProposalNoPreviewDiffDelta
from lp.code.enums import BranchMergeProposalStatus
from lp.code.interfaces.branchmergeproposal import (
    IBranchMergeProposal,
    IMergeProposalNeedsReviewEmailJobSource,
    IMergeProposalUpdatedEmailJobSource,
    IReviewRequestedEmailJobSource,
    IUpdatePreviewDiffJobSource,
)
from lp.registry.interfaces.person import IPerson
from lp.services.utils import text_delta
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet
from lp.services.webhooks.payload import compose_webhook_payload


def _compose_merge_proposal_webhook_payload(merge_proposal):
    fields = [
        "registrant",
        "source_branch",
        "source_git_repository",
        "source_git_path",
        "target_branch",
        "target_git_repository",
        "target_git_path",
        "prerequisite_branch",
        "prerequisite_git_repository",
        "prerequisite_git_path",
        "queue_status",
        "commit_message",
        "whiteboard",
        "description",
        "preview_diff",
    ]
    return compose_webhook_payload(
        IBranchMergeProposal, merge_proposal, fields
    )


def _trigger_webhook(merge_proposal, payload, event_type):
    payload = dict(payload)
    payload["merge_proposal"] = canonical_url(
        merge_proposal, force_local_path=True
    )
    if merge_proposal.target_branch is not None:
        target = merge_proposal.target_branch
    else:
        target = merge_proposal.target_git_repository

    git_refs = []
    if "new" in payload:
        git_refs.append(payload["new"]["target_git_path"])
    if "old" in payload:
        git_refs.append(payload["old"]["target_git_path"])

    getUtility(IWebhookSet).trigger(
        target,
        event_type,
        payload,
        context=merge_proposal,
        git_refs=git_refs,
    )


def review_comment_created(comment, event):
    """Trigger a webhook when a main comment is posted.

    Originally, creating inline comments triggered the 'merge-proposal:0.1'
    webhook. To keep a similar behavior, we now prevent the trigger when
    we add inline comments and instead trigger it when a main (top-level)
    comment is submitted. The event type and payload structure is preserved.
    """
    merge_proposal = comment.branch_merge_proposal
    base_payload = _compose_merge_proposal_webhook_payload(merge_proposal)
    payload = {
        "action": "reviewed",
        "old": base_payload,
        "new": base_payload,
    }
    _trigger_webhook(merge_proposal, payload, "merge-proposal:0.1::review")


def merge_proposal_created(merge_proposal, event):
    """A new merge proposal has been created.

    Create a job to update the diff for the merge proposal; trigger webhooks.
    """
    getUtility(IUpdatePreviewDiffJobSource).create(merge_proposal)
    payload = {
        "action": "created",
        "new": _compose_merge_proposal_webhook_payload(merge_proposal),
    }
    _trigger_webhook(merge_proposal, payload, "merge-proposal:0.1::create")


def merge_proposal_needs_review(merge_proposal, event):
    """A new merge proposal needs a review.

    This event is raised when the proposal moves from work in progress to
    needs review.
    """
    getUtility(IMergeProposalNeedsReviewEmailJobSource).create(merge_proposal)


def merge_proposal_modified(merge_proposal, event):
    """Notify branch subscribers when merge proposals are updated."""
    old_status = event.object_before_modification.queue_status
    new_status = merge_proposal.queue_status
    # No webhook triggered if neither the status nor any of the merge proposal
    # fields were changed
    if event.edited_fields is None and old_status == new_status:
        return
    # Check the user.
    if event.user is None:
        return
    if isinstance(event.user, UnauthenticatedPrincipal):
        from_person = None
    else:
        from_person = IPerson(event.user)

    in_progress_states = (
        BranchMergeProposalStatus.WORK_IN_PROGRESS,
        BranchMergeProposalStatus.NEEDS_REVIEW,
    )

    # If the merge proposal was work in progress and is now needs review,
    # then we don't want to send out an email as the needs review email will
    # cover that.
    if (
        old_status != BranchMergeProposalStatus.WORK_IN_PROGRESS
        or new_status not in in_progress_states
    ):
        # Create a delta of the changes.  If there are no changes to report,
        # then we're done.
        delta = BranchMergeProposalNoPreviewDiffDelta.construct(
            event.object_before_modification, merge_proposal
        )
        if delta is not None:
            changes = text_delta(
                delta, delta.delta_values, delta.new_values, delta.interface
            )
            # Now create the job to send the email.
            getUtility(IMergeProposalUpdatedEmailJobSource).create(
                merge_proposal, changes, from_person
            )
    payload = {
        "action": "modified",
        "old": _compose_merge_proposal_webhook_payload(
            event.object_before_modification
        ),
        "new": _compose_merge_proposal_webhook_payload(merge_proposal),
    }
    # Some fields may not be in the before-modification snapshot; take
    # values for these from the new object instead.
    for field in payload["old"]:
        if not hasattr(event.object_before_modification, field):
            payload["old"][field] = payload["new"][field]

    if old_status != new_status:
        event_type = "merge-proposal:0.1::status-change"
    elif "preview_diff" in event.edited_fields:
        event_type = "merge-proposal:0.1::push"
    else:
        event_type = "merge-proposal:0.1::edit"
    _trigger_webhook(
        merge_proposal,
        payload,
        event_type=event_type,
    )


def review_requested(vote_reference, event):
    """Notify the reviewer that they have been requested to review."""
    # Don't send email if the proposal is work in progress.
    bmp_status = vote_reference.branch_merge_proposal.queue_status
    if bmp_status != BranchMergeProposalStatus.WORK_IN_PROGRESS:
        getUtility(IReviewRequestedEmailJobSource).create(vote_reference)


def merge_proposal_deleted(merge_proposal, event):
    """A merge proposal has been deleted."""
    # The merge proposal link will be invalid by the time the webhook is
    # delivered, but this may still be useful for endpoints that might e.g.
    # want to cancel CI jobs in flight.
    payload = {
        "action": "deleted",
        "old": _compose_merge_proposal_webhook_payload(merge_proposal),
    }
    _trigger_webhook(merge_proposal, payload, "merge-proposal:0.1::delete")
