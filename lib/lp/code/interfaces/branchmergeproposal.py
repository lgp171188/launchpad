# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The interface for branch merge proposals."""

__all__ = [
    "BRANCH_MERGE_PROPOSAL_FINAL_STATES",
    "BRANCH_MERGE_PROPOSAL_OBSOLETE_STATES",
    "IBranchMergeProposal",
    "IBranchMergeProposalGetter",
    "IBranchMergeProposalJob",
    "IBranchMergeProposalJobSource",
    "IBranchMergeProposalListingBatchNavigator",
    "ICodeReviewCommentEmailJob",
    "ICodeReviewCommentEmailJobSource",
    "IGenerateIncrementalDiffJob",
    "IGenerateIncrementalDiffJobSource",
    "IMergeProposalNeedsReviewEmailJob",
    "IMergeProposalNeedsReviewEmailJobSource",
    "IMergeProposalUpdatedEmailJob",
    "IMergeProposalUpdatedEmailJobSource",
    "IReviewRequestedEmailJob",
    "IReviewRequestedEmailJobSource",
    "IUpdatePreviewDiffJob",
    "IUpdatePreviewDiffJobSource",
]


from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    export_factory_operation,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
    operation_returns_collection_of,
    operation_returns_entry,
    rename_parameters_as,
)
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
from zope.interface import Attribute, Interface
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Dict,
    Int,
    Object,
    Text,
    TextLine,
)

from lp import _
from lp.app.interfaces.launchpad import IPrivacy
from lp.bugs.interfaces.buglink import IBugLinkTarget
from lp.code.enums import BranchMergeProposalStatus, CodeReviewVote
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.diff import IPreviewDiff
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.person import IPerson
from lp.services.database.constants import DEFAULT
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    Summary,
    Whiteboard,
)
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob
from lp.services.webapp.interfaces import ITableBatchNavigator
from lp.services.webservice.apihelpers import patch_reference_property

BRANCH_MERGE_PROPOSAL_FINAL_STATES = (
    BranchMergeProposalStatus.REJECTED,
    BranchMergeProposalStatus.MERGED,
    BranchMergeProposalStatus.SUPERSEDED,
)


BRANCH_MERGE_PROPOSAL_OBSOLETE_STATES = (
    BranchMergeProposalStatus.MERGE_FAILED,
    BranchMergeProposalStatus.QUEUED,
)


class IBranchMergeProposalPublic(IPrivacy):
    id = Int(
        title=_("DB ID"),
        required=True,
        readonly=True,
        description=_("The tracking number for this merge proposal."),
    )
    source_branch_id = Int(
        title=_("Source branch ID"), required=False, readonly=True
    )
    source_git_repository_id = Int(
        title=_("Source Git repository ID"), required=False, readonly=True
    )
    prerequisite_branch_id = Int(
        title=_("Prerequisite branch ID"), required=False, readonly=True
    )
    prerequisite_git_repository_id = Int(
        title=_("Prerequisite Git repository ID"),
        required=False,
        readonly=True,
    )

    # This is redefined from IPrivacy.private because the attribute is
    # read-only. The value is determined by the involved branches.
    private = exported(
        Bool(
            title=_("Proposal is confidential"),
            required=False,
            readonly=True,
            default=False,
            description=_(
                "If True, this proposal is visible only to subscribers."
            ),
        )
    )

    source_branch = exported(
        ReferenceChoice(
            title=_("Source branch"),
            schema=IBranch,
            vocabulary="Branch",
            required=False,
            readonly=True,
            description=_("The branch that has code to land."),
        )
    )
    source_git_repository = exported(
        ReferenceChoice(
            title=_("Source Git repository"),
            schema=IGitRepository,
            vocabulary="GitRepository",
            required=False,
            readonly=True,
            description=_("The Git repository that has code to land."),
        )
    )
    source_git_path = exported(
        TextLine(
            title=_("Source Git branch path"),
            required=False,
            readonly=True,
            description=_("The path of the Git branch that has code to land."),
        )
    )
    source_git_commit_sha1 = TextLine(
        title=_("Source Git commit SHA-1"), required=False, readonly=True
    )
    source_git_ref = Reference(
        title=_("Source Git branch"),
        schema=IGitRef,
        required=False,
        readonly=True,
    )

    target_branch = exported(
        ReferenceChoice(
            title=_("Target branch"),
            schema=IBranch,
            vocabulary="Branch",
            required=False,
            readonly=True,
            description=_(
                "The branch that the source branch will be merged into."
            ),
        )
    )
    target_git_repository = exported(
        ReferenceChoice(
            title=_("Target Git repository"),
            schema=IGitRepository,
            vocabulary="GitRepository",
            required=False,
            readonly=True,
            description=_(
                "The Git repository that the source branch will be merged "
                "into."
            ),
        )
    )
    target_git_path = exported(
        TextLine(
            title=_("Target Git branch path"),
            required=False,
            readonly=True,
            description=_(
                "The path of the Git branch that the source branch will be "
                "merged into."
            ),
        )
    )
    target_git_commit_sha1 = TextLine(
        title=_("Target Git commit SHA-1"), required=False, readonly=True
    )
    target_git_ref = Reference(
        title=_("Target Git branch"),
        schema=IGitRef,
        required=False,
        readonly=True,
    )

    prerequisite_branch = exported(
        ReferenceChoice(
            title=_("Prerequisite branch"),
            schema=IBranch,
            vocabulary="Branch",
            required=False,
            readonly=True,
            description=_(
                "The branch that the source branch branched from. "
                "If this branch is the same as the target branch, then "
                "leave this field blank."
            ),
        )
    )
    prerequisite_git_repository = exported(
        ReferenceChoice(
            title=_("Prerequisite Git repository"),
            schema=IGitRepository,
            vocabulary="GitRepository",
            required=False,
            readonly=True,
            description=_(
                "The Git repository containing the branch that the source "
                "branch branched from. If this branch is the same as the "
                "target branch, then leave this field blank."
            ),
        )
    )
    prerequisite_git_path = exported(
        TextLine(
            title=_("Prerequisite Git branch path"),
            required=False,
            readonly=True,
            description=_(
                "The path of the Git branch that the source branch branched "
                "from. If this branch is the same as the target branch, then "
                "leave this field blank."
            ),
        )
    )
    prerequisite_git_commit_sha1 = TextLine(
        title=_("Prerequisite Git commit SHA-1"), required=False, readonly=True
    )
    prerequisite_git_ref = Reference(
        title=_("Prerequisite Git branch"),
        schema=IGitRef,
        required=False,
        readonly=True,
    )

    merge_source = Attribute(
        "The branch that has code to land (VCS-agnostic)."
    )

    merge_target = Attribute(
        "The branch that the source branch will be merged into "
        "(VCS-agnostic)."
    )

    merge_prerequisite = Attribute(
        "The branch that the source branch branched from (VCS-agnostic)."
    )

    parent = Attribute(
        "The parent object for use in navigation: source branch for Bazaar, "
        "or source repository for Git."
    )


class IBranchMergeProposalView(Interface):
    registrant = exported(
        PublicPersonChoice(
            title=_("Person"),
            required=True,
            vocabulary="ValidPersonOrTeam",
            readonly=True,
            description=_("The person who registered the merge proposal."),
        )
    )

    description = exported(
        Text(
            title=_("Description"),
            required=False,
            description=_(
                "A detailed description of the changes that are being "
                "addressed by the branch being proposed to be merged."
            ),
            max_length=50000,
        )
    )

    whiteboard = Whiteboard(
        title=_("Whiteboard"),
        required=False,
        description=_("Notes about the merge."),
    )

    queue_status = exported(
        Choice(
            title=_("Status"),
            vocabulary=BranchMergeProposalStatus,
            required=True,
            readonly=True,
            description=_("The current state of the proposal."),
        )
    )

    # Not to be confused with a code reviewer. A code reviewer is someone who
    # can vote or has voted on a proposal.
    reviewer = exported(
        PersonChoice(
            title=_("Review person or team"),
            required=False,
            readonly=True,
            vocabulary="ValidPersonOrTeam",
            description=_(
                "The person that accepted (or rejected) the code "
                "for merging."
            ),
        )
    )

    next_preview_diff_job = Attribute(
        "The next BranchMergeProposalJob that will update a preview diff."
    )

    preview_diffs = exported(
        CollectionField(
            title=_("All preview diffs for this merge proposal."),
            value_type=Reference(schema=IPreviewDiff),
            readonly=True,
        )
    )

    preview_diff = exported(
        Reference(
            IPreviewDiff,
            title=_(
                "The current diff of the source branch against the "
                "target branch."
            ),
            readonly=True,
        )
    )

    reviewed_revision_id = exported(
        TextLine(
            title=_("The revision id that has been approved by the reviewer.")
        ),
        exported_as="reviewed_revid",
    )

    commit_message = exported(
        Summary(
            title=_("Commit message"),
            required=False,
            description=_(
                "The commit message that should be used when "
                "merging the source branch."
            ),
            strip_text=True,
        )
    )

    merged_revno = exported(
        Int(
            title=_("Merged revision number"),
            required=False,
            readonly=True,
            description=_(
                "The revision number on the target branch which contains the "
                "merge from the source branch (Bazaar only)."
            ),
        )
    )

    merged_revision_id = exported(
        TextLine(
            title=_("Merged revision ID"),
            required=False,
            readonly=True,
            description=_(
                "The revision ID on the target branch which contains the "
                "merge from the source branch (currently Git only)."
            ),
        )
    )

    merged_revision = Attribute(
        "The revision on the target branch which contains the merge from the "
        "source branch (VCS-agnostic)."
    )

    date_merged = exported(
        Datetime(
            title=_("Date merged"),
            required=False,
            readonly=True,
            description=_(
                "The date that the source branch was merged into "
                "the target branch"
            ),
        )
    )

    title = Attribute(
        "A nice human readable name to describe the merge proposal. "
        "This is generated from the source and target branch, and used "
        "as the tal fmt:link text and for email subjects."
    )

    merge_reporter = exported(
        PublicPersonChoice(
            title=_("Merge reporter"),
            vocabulary="ValidPerson",
            required=False,
            readonly=True,
            description=_("The user that marked the branch as merged."),
        )
    )

    supersedes = exported(
        Reference(
            title=_("Supersedes"),
            schema=Interface,
            required=False,
            readonly=True,
            description=_(
                "The branch merge proposal that this one " "supersedes."
            ),
        )
    )
    superseded_by = exported(
        Reference(
            title=_("Superseded by"),
            schema=Interface,
            required=False,
            readonly=True,
            description=_(
                "The branch merge proposal that supersedes this one."
            ),
        )
    )

    date_created = exported(
        Datetime(title=_("Date created"), required=True, readonly=True)
    )
    date_review_requested = exported(
        Datetime(
            title=_("Date review requested"), required=False, readonly=True
        )
    )
    date_reviewed = exported(
        Datetime(title=_("Date reviewed"), required=False, readonly=True)
    )
    root_message_id = Text(
        title=_("The email message id from the first message"), required=False
    )
    all_comments = exported(
        CollectionField(
            title=_("All messages discussing this merge proposal"),
            # Really ICodeReviewComment.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )

    address = exported(
        TextLine(
            title=_("The email address for this proposal."),
            readonly=True,
            description=_(
                "Any emails sent to this address will result"
                "in comments being added."
            ),
        )
    )

    revision_end_date = Datetime(
        title=_("Cutoff date for showing revisions."),
        required=False,
        readonly=True,
    )

    @operation_parameters(id=Int(title=_("A CodeReviewComment ID.")))
    # Really ICodeReviewComment.
    @operation_returns_entry(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getComment(id):
        """Return the CodeReviewComment with the specified ID.

        :raises WrongBranchMergeProposal: if the comment with this ID is not
            on this merge proposal.
        """

    def userCanSetCommentVisibility(user):
        """Can `user` set code review comment visibility?

        Admins and registry experts can set the visibility of any code
        review comment.

        Comment authors can also set the visibility of their own comments,
        but that is not checked here; this method determines whether
        arbitrary users can set the visibility of comments they did not make
        themselves.
        """

    @operation_parameters(
        # Really comment_id, but this lets us use common JavaScript code.
        comment_number=Int(title=_("The comment ID."), required=True),
        visible=Bool(title=_("Show this comment?"), required=True),
    )
    @call_with(user=REQUEST_USER)
    @export_write_operation()
    @operation_for_version("devel")
    def setCommentVisibility(user, comment_number, visible):
        """Set the visible attribute on a code review comment.

        This is restricted to Launchpad admins, registry experts, and
        comment authors, and will return a HTTP Error 401: Unauthorized
        error for non-admin callers.

        :raises WrongBranchMergeProposal: if the comment with this ID is not
            on this merge proposal.
        """

    @call_with(user=REQUEST_USER)
    # Really IBugTask.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getRelatedBugTasks(user):
        """Return the Bug tasks related to this merge proposal."""

    def updateRelatedBugsFromSource():
        """Update related bug links based on commits in the source branch.

        This is currently only meaningful for Git-based merge proposals.
        """

    def getRevisionsSinceReviewStart():
        """Return all the revisions added since the review began.

        Revisions are grouped by creation (i.e. push) time.
        :return: An iterator of (date, iterator of revision data)
        """

    def getVoteReference(id):
        """Return the CodeReviewVoteReference with the specified ID."""

    def getNotificationRecipients(min_level):
        """Return the people who should be notified.

        Recipients will be returned as a dictionary where the key is the
        person, and the values are (subscription, rationale) tuples.

        :param min_level: The minimum notification level needed to be
            notified.
        """

    votes = exported(
        CollectionField(
            title=_("The votes cast or expected for this proposal"),
            # Really ICodeReviewVoteReference.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )

    def isValidTransition(next_state, user=None):
        """True if it is valid for user update the proposal to next_state."""

    def isInProgress():
        """Is the proposal still in progress?

        As long as the proposal isn't in one of the end states, it is active
        and can eventually be merged.
        """

    def getUnlandedSourceBranchRevisions():
        """Return a sequence of `BranchRevision` objects.

        Returns up to 10 revisions that are in the revision history for the
        source branch that are not in the revision history of the target
        branch.  These are the revisions that have been committed to the
        source branch since it branched off the target branch.

        For Bazaar, this returns a sequence of `BranchRevision` objects.
        For Git, this returns a sequence of commit information dicts.
        """

    def getUsersVoteReference(user):
        """Get the existing vote reference for the given user.

        :return: A `CodeReviewVoteReference` or None.
        """

    def generateIncrementalDiff(old_revision, new_revision, diff=None):
        """Generate an incremental diff for the merge proposal.

        :param old_revision: The `Revision` to generate the diff from.
        :param new_revision: The `Revision` to generate the diff to.
        :param diff: If supplied, a pregenerated `Diff`.
        """

    def getIncrementalDiffs(revision_list):
        """Return a list of diffs for the specified revisions.

        :param revision_list: A list of tuples of (`Revision`, `Revision`).
            The first revision in the tuple is the old revision.  The second
            is the new revision.
        :return: A list of IncrementalDiffs in the same order as the supplied
            Revisions.
        """

    def getPreviewDiff(id):
        """Return the preview diff with the given id.

        :param id: The id of the target `PreviewDiff`.
        """

    @export_read_operation()
    @operation_parameters(previewdiff_id=Int())
    @operation_for_version("devel")
    def getInlineComments(previewdiff_id):
        """Return a list of inline comments related to this MP.

        The return value is an list of dictionaries (objects), each one
        representing a comment with 'line_number', 'person', 'text' and
        'date' attributes.

        :param previewdiff_id: The ID of the target `PreviewDiff`.
        """

    def getLatestDiffUpdateJob():
        """Return the latest IUpdatePreviewDiffJob for this MP."""

    def getStatusReports(commit_sha1):
        """Get status reports for the source repository at the given commit"""


class IBranchMergeProposalEdit(Interface):
    def deleteProposal():
        """Delete the proposal to merge."""

    def updatePreviewDiff(
        diff_content,
        source_revision_id,
        target_revision_id,
        prerequisite_revision_id=None,
        conflicts=None,
    ):
        """Update the preview diff for this proposal.

        If there is not an existing preview diff, one will be created.

        :param diff_content: The raw bytes (or text, which will be encoded
            using UTF-8) of the diff content to be put in the librarian.
        :param diff_stat: Text describing the files added, remove or modified.
        :param source_revision_id: The revision id that was used from the
            source branch.
        :param target_revision_id: The revision id that was used from the
            target branch.
        :param prerequisite_revision_id: The revision id that was used from
            the prerequisite branch.
        :param conflicts: Text describing the conflicts if any.
        """

    @call_with(return_jobs=False)
    @export_write_operation()
    @operation_for_version("devel")
    def scheduleDiffUpdates(return_jobs=True):
        """Schedule updates of the diffs for this proposal.

        This can be used if the previous attempt to generate diffs crashed,
        or if Launchpad failed to notice that the current diffs are outdated
        for some reason.

        :param return_jobs: If True, return the created jobs.
        """

    @call_with(user=REQUEST_USER)
    @rename_parameters_as(revision_id="revid")
    @operation_parameters(
        status=Choice(
            title=_("The new status of the merge proposal."),
            vocabulary=BranchMergeProposalStatus,
        ),
        revision_id=TextLine(
            description=_(
                "An optional parameter for specifying the "
                "revision of the branch for the status change."
            ),
            required=False,
        ),
    )
    @export_write_operation()
    @operation_for_version("beta")
    def setStatus(status, user, revision_id):
        """Set the state of the merge proposal to the specified status.

        :param status: The new status of the merge proposal.
        :param user: The user making the change.
        :param revision_id: The revision id to provide to the underlying
            status change method.
        """

    def setAsWorkInProgress():
        """Set the state of the merge proposal to 'Work in progress'.

        This is often useful if the proposal was rejected and is being worked
        on again, or if the code failed to merge and requires rework.
        """

    def requestReview():
        """Set the state of merge proposal to 'Needs review'.

        As long as the branch is not yet merged, a review can be requested.
        Requesting a review sets the date_review_requested.
        """

    def approveBranch(reviewer, revision_id):
        """Mark the proposal as 'Code approved'.

        The time that the branch was approved is recoreded in `date_reviewed`.

        :param reviewer: A person authorised to review branches for merging.
        :param revision_id: The revision id of the branch that was
                            reviewed by the `reviewer`.

        :raises: UserNotBranchReviewer if the reviewer is not in the team of
                 the branch reviewer for the target branch.
        """

    def rejectBranch(reviewer, revision_id):
        """Mark the proposal as 'Rejected'.

        The time that the branch was rejected is recoreded in `date_reviewed`.

        :param reviewer: A person authorised to review branches for merging.
        :param revision_id: The revision id of the branch that was
                            reviewed by the `reviewer`.

        :raises: UserNotBranchReviewer if the reviewer is not in the team of
                 the branch reviewer for the target branch.
        """

    def markAsMerged(merged_revno=None, date_merged=None, merge_reporter=None):
        """Mark the branch merge proposal as merged.

        If the `merged_revno` is supplied, then the `BranchRevision` is
        checked to see that revision is available in the target branch.  If it
        is then the date from that revision is used as the `date_merged`.  If
        it is not available, then the `date_merged` is set as if the
        merged_revno was not supplied.

        If no `merged_revno` is supplied, the `date_merged` is set to the
        value of date_merged, or if the parameter date_merged is None, then
        UTC_NOW is used.

        :param merged_revno: The revision number in the target branch that
                             contains the merge of the source branch.
        :type merged_revno: ``int``

        :param date_merged: The date/time that the merge took place.
        :type merged_revno: ``datetime`` or a stringified date time value.

        :param merge_reporter: The user that is marking the branch as merged.
        :type merge_reporter: ``Person``
        """

    def resubmit(
        registrant,
        merge_source=None,
        merge_target=None,
        merge_prerequisite=DEFAULT,
        commit_message=None,
        description=None,
    ):
        """Mark the branch merge proposal as superseded and return a new one.

        The new proposal is created as work-in-progress, and copies across
        user-entered data like the whiteboard.  All the current proposal's
        reviewers, including those who have only been nominated, are requested
        to review the new proposal.

        :param registrant: The person registering the new proposal.
        :param merge_source: The merge_source for the new proposal (defaults
            to the current merge_source).
        :param merge_target: The merge_target for the new proposal (defaults
            to the current merge_target).
        :param merge_prerequisite: The merge_prerequisite for the new
            proposal (defaults to the current merge_prerequisite).
        :param commit_message: The commit message for the new proposal
            (defaults to the current commit message).
        :param description: The description for the new proposal (defaults to
            the current description).
        """

    @operation_parameters(
        reviewer=Reference(title=_("A reviewer."), schema=IPerson),
        review_type=Text(),
    )
    @call_with(registrant=REQUEST_USER)
    # Really ICodeReviewVoteReference.
    @operation_returns_entry(Interface)
    @export_write_operation()
    @operation_for_version("beta")
    def nominateReviewer(reviewer, registrant, review_type=None):
        """Set the specified person as a reviewer.

        If they are not already a reviewer, a vote is created.  Otherwise,
        the details are updated.
        """


class IBranchMergeProposalAnyAllowedPerson(IBugLinkTarget):
    @operation_parameters(
        subject=Text(),
        content=Text(),
        vote=Choice(vocabulary=CodeReviewVote),
        review_type=Text(),
        parent=Reference(schema=Interface),
        previewdiff_id=Int(),
        inline_comments=Dict(key_type=TextLine(), value_type=Text()),
    )
    @call_with(owner=REQUEST_USER)
    # ICodeReviewComment supplied as Interface to avoid circular imports.
    @export_factory_operation(Interface, [])
    @operation_for_version("beta")
    def createComment(
        owner,
        subject=None,
        content=None,
        vote=None,
        review_type=None,
        parent=None,
        previewdiff_id=None,
        inline_comments=None,
    ):
        """Create an ICodeReviewComment associated with this merge proposal.

        :param owner: The person who the message is from.
        :param subject: The subject line to use for the message.
        :param content: The text to use for the message content.  If
            unspecified, the text of the merge proposal is used.
        :param parent: The previous CodeReviewComment in the thread.  If
            unspecified, the root message is used.
        :param previewdiff_id: the inline comments PreviewDiff ID context.
        :param inline_comments: a dictionary containing the draft inline
            comments keyed by the diff line number.
        """

    def createCommentFromMessage(message, vote, review_type, original_email):
        """Create an `ICodeReviewComment` from an IMessage.

        :param message: The IMessage to use.
        :param vote: A CodeReviewVote (or None).
        :param review_type: A string (or None).
        :param original_email: Original email message.
        """

    @export_read_operation()
    @operation_parameters(previewdiff_id=Int())
    @call_with(person=REQUEST_USER)
    @operation_for_version("devel")
    def getDraftInlineComments(previewdiff_id, person):
        """Return the draft inline comments related to this MP.

        The return value is a dictionary (object) where the keys are the
        diff lines and their values are the actual draft comment created
        by the given person.

        :param previewdiff_id: The ID of the target `PreviewDiff`.
        :param person: The `IPerson` owner of the draft comments.
        """

    @export_write_operation()
    @operation_parameters(
        previewdiff_id=Int(),
        comments=Dict(key_type=TextLine(), value_type=Text()),
    )
    @call_with(person=REQUEST_USER)
    @operation_for_version("devel")
    def saveDraftInlineComment(previewdiff_id, person, comments):
        """Save `ICodeReviewInlineCommentDraft`

        :param previewdiff_id: The ID of the target `PreviewDiff`.
        :param person: The `IPerson` making the comments.
        :param comments: The comments.
        """

    @export_write_operation()
    @operation_parameters(
        # Really IBug, patched in _schema_circular_imports.py.
        bug=Reference(schema=Interface)
    )
    @call_with(user=REQUEST_USER)
    @operation_for_version("devel")
    def linkBug(bug, user=None, check_permissions=True):
        """Link a bug to this merge proposal."""

    @export_write_operation()
    @operation_parameters(
        # Really IBug, patched in _schema_circular_imports.py.
        bug=Reference(schema=Interface)
    )
    @call_with(user=REQUEST_USER)
    @operation_for_version("devel")
    def unlinkBug(bug, user=None, check_permissions=True):
        """Unlink a bug from this merge proposal."""


@exported_as_webservice_entry(as_of="beta")
class IBranchMergeProposal(
    IBranchMergeProposalPublic,
    IBranchMergeProposalView,
    IBranchMergeProposalEdit,
    IBranchMergeProposalAnyAllowedPerson,
):
    """Branch merge proposals show intent of landing one branch on another."""


class IBranchMergeProposalJob(Interface):
    """A Job related to a Branch Merge Proposal."""

    id = Int(
        title=_("DB ID"),
        required=True,
        readonly=True,
        description=_("The tracking number for this job."),
    )

    branch_merge_proposal = Object(
        title=_("The BranchMergeProposal this job is about"),
        schema=IBranchMergeProposal,
        required=True,
    )

    job = Object(
        title=_("The common Job attributes"), schema=IJob, required=True
    )

    metadata = Attribute("A dict of data about the job.")

    def destroySelf():
        """Destroy this object."""


class IBranchMergeProposalJobSource(IJobSource):
    """A job source that will get all supported merge proposal jobs."""


class IBranchMergeProposalListingBatchNavigator(ITableBatchNavigator):
    """A marker interface for registering the appropriate listings."""


class IBranchMergeProposalGetter(Interface):
    """Utility for getting BranchMergeProposals."""

    def get(id):
        """Return the BranchMergeProposal with specified id."""

    def activeProposalsForBranches(source, target=None):
        """Return BranchMergeProposals having a given source and target.

        :param source: source branch
        :param target: target branch
        """

    def getProposalsForContext(context, status=None, visible_by_user=None):
        """Return BranchMergeProposals associated with the context.

        :param context: Either an `IPerson` or `IProduct`.
        :param status: An iterable of queue_status of the proposals to return.
            If None is specified, all the proposals of all possible states
            are returned.
        :param visible_by_user: If a person is not supplied, only merge
            proposals based on public branches are returned.  If a person is
            supplied, merge proposals based on both public branches, and the
            private branches that the person is entitled to see are returned.
            Private branches are only visible to the owner and subscribers of
            the branch, and to LP admins.
        :raises BadBranchMergeProposalSearchContext: If the context is not
            understood.
        """

    def getProposalsForParticipant(
        participant, status=None, visible_by_user=None
    ):
        """Return BranchMergeProposals associated with the context.

        :param participant: An `IPerson` that is participating in the merge
            proposal, either a reviewer or reviewee.
        :param status: An iterable of queue_status of the proposals to return.
            If None is specified, all the proposals of all possible states
            are returned.
        :param visible_by_user: If a person is not supplied, only merge
            proposals based on public branches are returned.  If a person is
            supplied, merge proposals based on both public branches, and the
            private branches that the person is entitled to see are returned.
            Private branches are only visible to the owner and subscribers of
            the branch, and to LP admins.
        """

    def getVotesForProposals(proposals):
        """Return a dict containing a mapping of proposals to vote references.

        The values of the dict are lists of CodeReviewVoteReference objects.
        """

    def getVoteSummariesForProposals(proposals):
        """Return the vote summaries for the proposals.

        A vote summary is a dict has a 'comment_count' and may also have
        values for each of the CodeReviewVote enumerated values.

        :return: A dict keyed on the proposals.
        """


for name in ["supersedes", "superseded_by"]:
    patch_reference_property(IBranchMergeProposal, name, IBranchMergeProposal)


class IMergeProposalNeedsReviewEmailJob(IRunnableJob):
    """Email about a merge proposal needing a review.."""


class IMergeProposalNeedsReviewEmailJobSource(Interface):
    """Interface for acquiring MergeProposalNeedsReviewEmailJobs."""

    def create(bmp):
        """Create a needs review email job for the specified proposal."""


class IUpdatePreviewDiffJob(IRunnableJob):
    """Interface for the job to update the diff for a merge proposal."""

    def checkReady():
        """Check to see if this job is ready to run."""


class IUpdatePreviewDiffJobSource(Interface):
    """Create or retrieve jobs that update preview diffs."""

    def create(bmp):
        """Create a job to update the diff for this merge proposal."""

    def get(id):
        """Return the UpdatePreviewDiffJob with this id."""


class IGenerateIncrementalDiffJob(IRunnableJob):
    """Interface for the job to update the diff for a merge proposal."""


class IGenerateIncrementalDiffJobSource(Interface):
    """Create or retrieve jobs that update preview diffs."""

    def create(bmp, old_revision_id, new_revision_id):
        """Create job to generate incremental diff for this merge proposal."""

    def get(id):
        """Return the GenerateIncrementalDiffJob with this id."""


class ICodeReviewCommentEmailJob(IRunnableJob):
    """Interface for the job to send code review comment email."""

    code_review_comment = Attribute("The code review comment.")


class ICodeReviewCommentEmailJobSource(Interface):
    """Create or retrieve jobs that update preview diffs."""

    def create(code_review_comment):
        """Create a job to email subscribers about the comment."""


class IReviewRequestedEmailJob(IRunnableJob):
    """Interface for the job to sends review request emails."""

    reviewer = Attribute(
        "The person or team asked to do the review. "
        "If left blank, then the default reviewer for the "
        "selected target branch will be used."
    )
    requester = Attribute("The person who has asked for the review.")


class IReviewRequestedEmailJobSource(Interface):
    """Create or retrieve jobs that email review requests."""

    def create(review_request):
        """Create a job to email a review request.

        :param review_request: A vote reference for the requested review.
        """


class IMergeProposalUpdatedEmailJob(IRunnableJob):
    """Interface for the job to sends email about merge proposal updates."""

    editor = Attribute("The person that did the editing.")
    delta_text = Attribute("The textual representation of the changed fields.")


class IMergeProposalUpdatedEmailJobSource(Interface):
    """Create or retrieve jobs that email about merge proposal updates."""

    def create(merge_proposal, delta_text, editor):
        """Create a job to email merge proposal updates to subscribers.

        :param merge_proposal: The merge proposal that has been edited.
        :param delta_text: The text representation of the changed fields.
        :param editor: The person who did the editing.
        """
