# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base class view for branch merge proposal listings."""

__metaclass__ = type

__all__ = [
    'ActiveReviewsView',
    'BranchMergeProposalListingItem',
    'BranchMergeProposalListingView',
    'PersonActiveReviewsView',
    ]

from zope.component import getUtility
from zope.interface import implements

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from lp.code.enums import BranchMergeProposalStatus, CodeReviewVote
from lp.code.interfaces.branchcollection import (
    IAllBranches, IBranchCollection)
from lp.code.interfaces.branchmergeproposal import (
    IBranchMergeProposal,
    IBranchMergeProposalGetter, IBranchMergeProposalListingBatchNavigator)
from canonical.launchpad.webapp import LaunchpadView
from canonical.launchpad.webapp.batching import TableBatchNavigator
from lazr.delegates import delegates


class BranchMergeProposalListingItem:
    """A branch merge proposal that knows summary values for comments."""

    delegates(IBranchMergeProposal, 'context')

    def __init__(self, branch_merge_proposal, summary, proposal_reviewer,
                 vote_references=None):
        self.context = branch_merge_proposal
        self.summary = summary
        self.proposal_reviewer = proposal_reviewer
        if vote_references is None:
            vote_references = []
        self.vote_references = vote_references

    @property
    def vote_summary_items(self):
        """A generator of votes.

        This is iterated over in TAL, and provides a items that are dict's for
        simple TAL traversal.

        The dicts contain the name and title of the enumerated vote type, the
        count of those votes and the reviewers whose latest review is of that
        type.
        """
        for vote in CodeReviewVote.items:
            vote_count = self.summary.get(vote, 0)
            if vote_count > 0:
                reviewers = []
                for ref in self.vote_references:
                    if ref.comment is not None and ref.comment.vote == vote:
                        reviewers.append(ref.reviewer.unique_displayname)
                yield {'name': vote.name, 'title': vote.title,
                       'count': vote_count,
                       'reviewers': ', '.join(sorted(reviewers))}

    @property
    def vote_type_count(self):
        """The number of vote types used on this proposal."""
        # The dict has one entry for comments and one for each type of vote.
        return len(self.summary) - 1

    @property
    def comment_count(self):
        """The number of comments (that aren't votes)."""
        return self.summary['comment_count']

    @property
    def has_no_activity(self):
        """True if no votes and no comments."""
        return self.comment_count == 0 and self.vote_type_count == 0

    @property
    def reviewer_vote(self):
        """A vote from the specified reviewer."""
        return self.context.getUsersVoteReference(self.proposal_reviewer)


class BranchMergeProposalListingBatchNavigator(TableBatchNavigator):
    """Batch up the branch listings."""
    implements(IBranchMergeProposalListingBatchNavigator)

    def __init__(self, view):
        TableBatchNavigator.__init__(
            self, view.getVisibleProposalsForUser(), view.request,
            columns_to_show=view.extra_columns,
            size=config.launchpad.branchlisting_batch_size)
        self.view = view
        # Add preview_diff to self.show_column dict if there are any diffs.
        for proposal in self.proposals:
            if proposal.preview_diff is not None:
                self.show_column['preview_diff'] = True

    @cachedproperty
    def _proposals_for_current_batch(self):
        return list(self.currentBatch())

    @cachedproperty
    def _vote_summaries(self):
        """A dict of proposals to counts of votes and comments."""
        utility = getUtility(IBranchMergeProposalGetter)
        return utility.getVoteSummariesForProposals(
            self._proposals_for_current_batch)

    def _createItem(self, proposal):
        """Create the listing item for the proposal."""
        summary = self._vote_summaries[proposal]
        return BranchMergeProposalListingItem(proposal, summary,
            proposal_reviewer=self.view.getUserFromContext())

    @cachedproperty
    def proposals(self):
        """Return a list of BranchListingItems."""
        proposals = self._proposals_for_current_batch
        return [self._createItem(proposal) for proposal in proposals]

    @property
    def table_class(self):
        if self.has_multiple_pages:
            return "listing"
        else:
            return "listing sortable"


class BranchMergeProposalListingView(LaunchpadView):
    """A base class for views of branch merge proposal listings."""

    extra_columns = []
    _queue_status = None

    @property
    def proposals(self):
        """The batch navigator for the proposals."""
        return BranchMergeProposalListingBatchNavigator(self)

    def getUserFromContext(self):
        """Get the relevant user from the context."""
        return None

    def getVisibleProposalsForUser(self):
        """Branch merge proposals that are visible by the logged in user."""
        return getUtility(IBranchMergeProposalGetter).getProposalsForContext(
            self.context, self._queue_status, self.user)

    @cachedproperty
    def proposal_count(self):
        """Return the number of proposals that will be returned."""
        return self.getVisibleProposalsForUser().count()


class PersonBMPListingView(BranchMergeProposalListingView):
    """Base class for the proposal listings that defines the user."""

    def _getCollection(self):
        """Return the branch collection for the view."""
        return getUtility(IAllBranches).visibleByUser(self.user)

    def getUserFromContext(self):
        """Get the relevant user from the context."""
        return self.context


class ActiveReviewsView(BranchMergeProposalListingView):
    """Branch merge proposals for a context that are needing review."""

    show_diffs = False

    # The grouping classifications.
    APPROVED = 'approved'
    TO_DO = 'to_do'
    ARE_DOING = 'are_doing'
    CAN_DO = 'can_do'
    MINE = 'mine'
    OTHER = 'other'
    WIP = 'wip'

    def getProposals(self):
        """Get the proposals for the view."""
        collection = IBranchCollection(self.context)
        collection = collection.visibleByUser(self.user)
        proposals = collection.getMergeProposals(
            [BranchMergeProposalStatus.CODE_APPROVED,
             BranchMergeProposalStatus.NEEDS_REVIEW,])
        return proposals

    def _getReviewGroup(self, proposal, votes, reviewer):
        """One of APPROVED, MINE, TO_DO, CAN_DO, ARE_DOING, OTHER or WIP.

        These groupings define the different tables that the user is able
        to see.

        Proposals with a status of CODE_APPROVED or WORK_IN_PROGRESS are the
        groups APPROVED or WIP respectively.

        If the source branch is owned by the reviewer, or the proposal was
        registered by the reviewer, then the group is MINE.

        If the reviewer is a team, there is no MINE, nor can a team vote, so
        there is no ARE_DOING.  Since a team can't really have TO_DOs, they
        are explicitly checked for, so all possibles are CAN_DO.

        If there is a pending vote reference for the reviewer, then the group
        is TO_DO as the reviewer is expected to review.  If there is a vote
        reference where it is not pending, this means that the reviewer has
        reviewed, so the group is ARE_DOING.  If there is a pending review
        requested of a team that the reviewer is in, then the review becomes a
        CAN_DO.  All others are OTHER.
        """
        bmp_status = BranchMergeProposalStatus
        if proposal.queue_status == bmp_status.CODE_APPROVED:
            return self.APPROVED
        if proposal.queue_status == bmp_status.WORK_IN_PROGRESS:
            return self.WIP

        if (reviewer is not None and
            (proposal.source_branch.owner == reviewer or
             (reviewer.inTeam(proposal.source_branch.owner) and
              proposal.registrant == reviewer))):
            return self.MINE

        result = self.OTHER

        for vote in votes:
            if reviewer is not None:
                if vote.reviewer == reviewer and not reviewer.is_team:
                    if vote.comment is None:
                        return self.TO_DO
                    else:
                        return self.ARE_DOING
                # Since team reviews are always pending, and we've eliminated
                # the case where the reviewer is ther person, then if the reviewer
                # is in the reviewer team, it is a can do.
                if reviewer.inTeam(vote.reviewer):
                    result = self.CAN_DO
        return result

    def _getReviewer(self):
        """The user whose point of view are the groupings are for."""
        return self.user

    def initialize(self):
        # Work out the review groups
        self.review_groups = {}
        self.getter = getUtility(IBranchMergeProposalGetter)
        reviewer = self._getReviewer()
        # Listify so it works well being passed into getting the votes and
        # summaries.
        proposals = list(self.getProposals())
        all_votes = self.getter.getVotesForProposals(proposals)
        vote_summaries = self.getter.getVoteSummariesForProposals(proposals)
        for proposal in proposals:
            proposal_votes = all_votes[proposal]
            review_group = self._getReviewGroup(
                proposal, proposal_votes, reviewer)
            self.review_groups.setdefault(review_group, []).append(
                BranchMergeProposalListingItem(
                    proposal, vote_summaries[proposal], None, proposal_votes))
            if proposal.preview_diff is not None:
                self.show_diffs = True
        # Sort each collection...
        self.proposal_count = len(proposals)

    @cachedproperty
    def headings(self):
        """Return a dict of headings for the groups."""
        reviewer = self._getReviewer()
        headings = {
            self.APPROVED: 'Approved reviews ready to land',
            self.TO_DO: 'Reviews I have to do',
            self.ARE_DOING: 'Reviews I am doing',
            self.CAN_DO: 'Requested reviews I can do',
            self.MINE: 'Reviews I am waiting on',
            self.OTHER: 'Other reviews I am not actively reviewing',
            self.WIP: 'Work in progress'}
        if reviewer is None:
            # If there is no reviewer, then there will be no TO_DO, ARE_DOING,
            # CAN_DO or MINE, and we are not in a person context.
            headings[self.OTHER] = 'Reviews requested or in progress'
        elif self.user is not None and self.user.inTeam(reviewer):
            # The user is either looking at their own person review page, or a
            # reviews for a team that they are a member of.  The default
            # headings are good.
            pass
        elif reviewer.is_team:
            # Looking at a person team page.
            name = reviewer.displayname
            headings[self.CAN_DO] = 'Reviews %s can do' % name
            headings[self.OTHER] = (
                'Reviews %s is not actively reviewing' % name)
        else:
            # A user is looking at someone elses personal review page.
            name = reviewer.displayname
            headings[self.TO_DO] = 'Reviews %s has to do' % name
            headings[self.ARE_DOING] = 'Reviews %s is doing' % name
            headings[self.CAN_DO] = 'Reviews %s can do' % name
            headings[self.MINE] = 'Reviews %s is waiting on' % name
            headings[self.OTHER] = (
                'Reviews %s is not actively reviewing' % name)
        return headings

    @property
    def heading(self):
        return "Active code reviews for %s" % self.context.displayname

    page_title = heading

    @property
    def no_proposal_message(self):
        """Shown when there is no table to show."""
        return "%s has no active code reviews." % self.context.displayname


class PersonActiveReviewsView(ActiveReviewsView):
    """Branch merge proposals for the person that are needing review."""

    def _getReviewer(self):
        return self.context

    def getProposals(self):
        """See `ActiveReviewsView`."""
        collection = getUtility(IAllBranches).visibleByUser(self.user)
        proposals = collection.getMergeProposalsForPerson(
            self.context,
            [BranchMergeProposalStatus.CODE_APPROVED,
             BranchMergeProposalStatus.NEEDS_REVIEW,
             BranchMergeProposalStatus.WORK_IN_PROGRESS])

        return proposals
