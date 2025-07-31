# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for BranchMergeProposals."""

import hashlib
from datetime import datetime, timedelta, timezone
from difflib import unified_diff
from unittest import TestCase

import transaction
from fixtures import FakeLogger
from lazr.lifecycle.event import ObjectCreatedEvent
from lazr.restfulclient.errors import BadRequest
from storm.locals import Store
from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools.matchers import (
    ContainsDict,
    Equals,
    Is,
    MatchesDict,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import IPrivacy
from lp.code.adapters.branch import BranchMergeProposalNoPreviewDiffDelta
from lp.code.enums import (
    BranchMergeProposalStatus,
    BranchSubscriptionDiffSize,
    BranchSubscriptionNotificationLevel,
    CodeReviewNotificationLevel,
    CodeReviewVote,
    MergeType,
    RevisionStatusResult,
)
from lp.code.errors import (
    BadStateTransition,
    BranchMergeProposalExists,
    BranchMergeProposalFeatureDisabled,
    BranchMergeProposalMergeFailed,
    BranchMergeProposalNotMergeable,
    DiffNotFound,
    WrongBranchMergeProposal,
)
from lp.code.event.branchmergeproposal import (
    BranchMergeProposalNeedsReviewEvent,
    ReviewerNominatedEvent,
)
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.branchmergeproposal import (
    BRANCH_MERGE_PROPOSAL_FINAL_STATES as FINAL_STATES,
)
from lp.code.interfaces.branchmergeproposal import (
    BRANCH_MERGE_PROPOSAL_OBSOLETE_STATES as OBSOLETE_STATES,
)
from lp.code.interfaces.branchmergeproposal import (
    IBranchMergeProposal,
    IBranchMergeProposalGetter,
    IBranchMergeProposalJobSource,
)
from lp.code.model.branchmergeproposal import (
    PROPOSAL_MERGE_ENABLED_FEATURE_FLAG,
    BranchMergeProposal,
    BranchMergeProposalGetter,
    is_valid_transition,
)
from lp.code.model.branchmergeproposaljob import (
    BranchMergeProposalJob,
    MergeProposalNeedsReviewEmailJob,
    UpdatePreviewDiffJob,
)
from lp.code.model.tests.test_diff import DiffTestCase
from lp.code.tests.helpers import (
    GitHostingFixture,
    add_revision_to_branch,
    make_merge_proposal_without_reviewers,
)
from lp.registry.enums import TeamMembershipPolicy
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.product import IProductSet
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.webapp import canonical_url
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.services.xref.interfaces import IXRefSet
from lp.testing import (
    ExpectedException,
    TestCaseWithFactory,
    WebServiceTestCase,
    admin_logged_in,
    api_url,
    launchpadlib_for,
    login,
    login_person,
    person_logged_in,
    verifyObject,
    ws_object,
)
from lp.testing.dbuser import dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
)
from lp.testing.pages import webservice_for_person


class WithVCSScenarios(WithScenarios):
    scenarios = [
        ("bzr", {"git": False}),
        ("git", {"git": True}),
    ]

    def makeBranch(
        self,
        same_target_as=None,
        product=None,
        stacked_on=None,
        information_type=None,
        owner=None,
        name=None,
    ):
        # Create the product pillar and its access policy if information
        # type is "PROPRIETARY".
        if product is None and same_target_as is None:
            product = self.factory.makeProduct()
            if information_type == InformationType.PROPRIETARY:
                self.factory.makeAccessPolicy(product)
        elif product is None:
            same_target_as = removeSecurityProxy(same_target_as)
            product = (
                same_target_as.target if self.git else same_target_as.product
            )

        kwargs = {"information_type": information_type, "owner": owner}
        if self.git:
            kwargs["target"] = product
            paths = [name] if name else None
            return self.factory.makeGitRefs(paths=paths, **kwargs)[0]
        else:
            kwargs["product"] = product
            kwargs["stacked_on"] = stacked_on
            kwargs["name"] = name
            return self.factory.makeProductBranch(**kwargs)

    def makeBranchMergeProposal(
        self, source=None, target=None, prerequisite=None, **kwargs
    ):
        if self.git:
            return self.factory.makeBranchMergeProposalForGit(
                target_ref=target,
                source_ref=source,
                prerequisite_ref=prerequisite,
                **kwargs,
            )
        else:
            return self.factory.makeBranchMergeProposal(
                source_branch=source,
                target_branch=target,
                prerequisite_branch=prerequisite,
                **kwargs,
            )


class TestBranchMergeProposalInterface(TestCaseWithFactory):
    """Ensure that BranchMergeProposal implements its interface."""

    layer = DatabaseFunctionalLayer

    def test_BranchMergeProposal_implements_interface(self):
        """Ensure that BranchMergeProposal implements its interface."""
        bmp = self.factory.makeBranchMergeProposal()
        verifyObject(IBranchMergeProposal, bmp)


class TestBranchMergeProposalCanonicalUrl(
    WithVCSScenarios, TestCaseWithFactory
):
    """Tests canonical_url for merge proposals."""

    layer = DatabaseFunctionalLayer

    def test_BranchMergeProposal_canonical_url_base(self):
        # The URL for a merge proposal starts with the parent (source branch
        # or source Git repository).
        bmp = self.makeBranchMergeProposal()
        url = canonical_url(bmp)
        parent_url = canonical_url(bmp.parent)
        self.assertTrue(url.startswith(parent_url))

    def test_BranchMergeProposal_canonical_url_rest(self):
        # The rest of the URL for a merge proposal is +merge followed by the
        # db id.
        bmp = self.makeBranchMergeProposal()
        url = canonical_url(bmp)
        parent_url = canonical_url(bmp.parent)
        rest = url[len(parent_url) :]
        self.assertEqual("/+merge/%s" % bmp.id, rest)


class TestBranchMergeProposalPrivacy(TestCaseWithFactory):
    """Ensure that BranchMergeProposal implements privacy."""

    layer = DatabaseFunctionalLayer

    def test_BranchMergeProposal_implements_interface(self):
        """Ensure that BranchMergeProposal implements privacy."""
        bmp = self.factory.makeBranchMergeProposal()
        verifyObject(IPrivacy, bmp)

    @staticmethod
    def setPrivate(branch):
        """Force a branch to be private."""
        login_person(branch.owner)
        branch.setPrivate(True, branch.owner)

    def test_private(self):
        """Private flag should be True if True for any involved branch."""
        bmp = self.factory.makeBranchMergeProposal()
        self.assertFalse(bmp.private)
        self.setPrivate(bmp.source_branch)
        self.assertTrue(bmp.private)
        bmp.source_branch.setPrivate(False, bmp.source_branch.owner)
        self.setPrivate(bmp.target_branch)
        self.assertTrue(bmp.private)
        bmp.target_branch.setPrivate(False, bmp.target_branch.owner)
        removeSecurityProxy(bmp).prerequisite_branch = self.factory.makeBranch(
            product=bmp.source_branch.product
        )
        self.setPrivate(bmp.prerequisite_branch)
        self.assertTrue(bmp.private)

    def test_open_reviewer_with_private_branch(self):
        """If the reviewer is an open team, and either of the branches are
        private, they are not subscribed."""
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        trunk = self.factory.makeBranch(product=product, owner=owner)
        team = self.factory.makeTeam()
        branch = self.factory.makeBranch(
            information_type=InformationType.USERDATA,
            owner=owner,
            product=product,
        )
        with person_logged_in(owner):
            trunk.reviewer = team
            self.factory.makeBranchMergeProposal(
                source_branch=branch, target_branch=trunk
            )
            subscriptions = [bsub.person for bsub in branch.subscriptions]
            self.assertEqual([owner], subscriptions)

    def test_closed_reviewer_with_private_branch(self):
        """If the reviewer is a exclusive team, they are subscribed."""
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        trunk = self.factory.makeBranch(product=product, owner=owner)
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )
        branch = self.factory.makeBranch(
            information_type=InformationType.USERDATA,
            owner=owner,
            product=product,
        )
        with person_logged_in(owner):
            trunk.reviewer = team
            self.factory.makeBranchMergeProposal(
                source_branch=branch, target_branch=trunk
            )
            subscriptions = [bsub.person for bsub in branch.subscriptions]
            self.assertContentEqual([owner, team], subscriptions)


class TestBranchMergeProposalTransitions(TestCaseWithFactory):
    """Test the state transitions of branch merge proposals."""

    layer = DatabaseFunctionalLayer

    # All transitions between states are handled my method calls
    # on the proposal.
    transition_functions = {
        BranchMergeProposalStatus.WORK_IN_PROGRESS: "setAsWorkInProgress",
        BranchMergeProposalStatus.NEEDS_REVIEW: "requestReview",
        BranchMergeProposalStatus.CODE_APPROVED: "approveBranch",
        BranchMergeProposalStatus.REJECTED: "rejectBranch",
        BranchMergeProposalStatus.MERGED: "markAsMerged",
        BranchMergeProposalStatus.SUPERSEDED: "resubmit",
    }

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.target_branch = self.factory.makeProductBranch()
        login_person(self.target_branch.owner)

    def assertProposalState(self, proposal, state):
        """Assert that the `queue_status` of the `proposal` is `state`."""
        self.assertEqual(
            state,
            proposal.queue_status,
            "Wrong state, expected %s, got %s"
            % (state.title, proposal.queue_status.title),
        )

    def _attemptTransition(self, proposal, to_state):
        """Try to transition the proposal into the state `to_state`."""
        kwargs = {}
        method = getattr(proposal, self.transition_functions[to_state])
        if to_state in (
            BranchMergeProposalStatus.CODE_APPROVED,
            BranchMergeProposalStatus.REJECTED,
        ):
            args = [proposal.target_branch.owner, "some_revision_id"]
        elif to_state in (BranchMergeProposalStatus.SUPERSEDED,):
            args = [proposal.registrant]
        else:
            args = []
        method(*args, **kwargs)

    def assertGoodTransition(self, from_state, to_state):
        """Assert that we can go from `from_state` to `to_state`."""
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch, set_state=from_state
        )
        self.assertProposalState(proposal, from_state)
        self._attemptTransition(proposal, to_state)
        self.assertProposalState(proposal, to_state)

    def prepareDupeTransition(self, from_state):
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch, set_state=from_state
        )
        if from_state == BranchMergeProposalStatus.SUPERSEDED:
            # Setting a proposal SUPERSEDED has the side effect of creating
            # an active duplicate proposal, so make it inactive.
            proposal.superseded_by.rejectBranch(self.target_branch.owner, None)
        self.assertProposalState(proposal, from_state)
        self.factory.makeBranchMergeProposal(
            target_branch=proposal.target_branch,
            source_branch=proposal.source_branch,
        )
        return proposal

    def assertBadDupeTransition(self, from_state, to_state):
        """Assert that trying to go from `from_state` to `to_state` fails."""
        proposal = self.prepareDupeTransition(from_state)
        self.assertRaises(
            BadStateTransition, self._attemptTransition, proposal, to_state
        )

    def assertGoodDupeTransition(self, from_state, to_state):
        """Trying to go from `from_state` to `to_state` succeeds."""
        proposal = self.prepareDupeTransition(from_state)
        self._attemptTransition(proposal, to_state)
        self.assertProposalState(proposal, to_state)

    def assertAllTransitionsGood(self, from_state):
        """Assert that we can go from `from_state` to any state."""
        for status in BranchMergeProposalStatus.items:
            if status in OBSOLETE_STATES:
                # We don't need to permit transitions to obsolete states.
                continue
            self.assertGoodTransition(from_state, status)

    def test_transitions_from_wip(self):
        """We can go from work in progress to any other state."""
        self.assertAllTransitionsGood(
            BranchMergeProposalStatus.WORK_IN_PROGRESS
        )

    def test_transitions_from_needs_review(self):
        """We can go from needs review to any other state."""
        self.assertAllTransitionsGood(BranchMergeProposalStatus.NEEDS_REVIEW)

    def test_transitions_from_code_approved(self):
        """We can go from code_approved to any other state."""
        self.assertAllTransitionsGood(BranchMergeProposalStatus.CODE_APPROVED)

    def test_transitions_from_rejected(self):
        """Rejected proposals can only be resubmitted."""
        # Test the transitions from rejected.
        self.assertAllTransitionsGood(BranchMergeProposalStatus.REJECTED)

    def test_transition_from_final_with_dupes(self):
        """Proposals cannot be set active if there are similar active ones.

        So transitioning from a final state to an active one should cause
        an exception, but transitioning from a final state to a different
        final state should be fine.
        """
        for from_status in FINAL_STATES:
            for to_status in BranchMergeProposalStatus.items:
                if to_status in OBSOLETE_STATES:
                    # We don't need to permit transitions to obsolete states.
                    continue
                if to_status == BranchMergeProposalStatus.SUPERSEDED:
                    continue
                if to_status in FINAL_STATES:
                    self.assertGoodDupeTransition(from_status, to_status)
                else:
                    self.assertBadDupeTransition(from_status, to_status)

    def assertValidTransitions(self, expected, proposal, to_state, by_user):
        # Check the valid transitions for the merge proposal by the specified
        # user.
        valid = set()
        for state in BranchMergeProposalStatus.items:
            if is_valid_transition(proposal, state, to_state, by_user):
                valid.add(state)
        self.assertEqual(expected, valid)

    def test_transition_to_rejected_by_reviewer(self):
        # A proposal should be able to go from any states to rejected if the
        # user is a reviewer.
        valid_transitions = set(BranchMergeProposalStatus.items)
        proposal = self.factory.makeBranchMergeProposal()
        self.assertValidTransitions(
            valid_transitions,
            proposal,
            BranchMergeProposalStatus.REJECTED,
            proposal.target_branch.owner,
        )

    def test_transition_to_rejected_by_non_reviewer(self):
        # A non-reviewer should not be able to set a proposal as rejected.
        proposal = self.factory.makeBranchMergeProposal()
        # It is always valid to go to the same state.
        self.assertValidTransitions(
            {BranchMergeProposalStatus.REJECTED},
            proposal,
            BranchMergeProposalStatus.REJECTED,
            proposal.source_branch.owner,
        )

    def test_transitions_to_wip_resets_reviewer(self):
        # When a proposal was approved and is moved back into work in progress
        # the reviewer, date reviewed, and reviewed revision are all reset.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.CODE_APPROVED,
        )
        self.assertIsNot(None, proposal.reviewer)
        self.assertIsNot(None, proposal.date_reviewed)
        self.assertIsNot(None, proposal.reviewed_revision_id)
        proposal.setAsWorkInProgress()
        self.assertIs(None, proposal.reviewer)
        self.assertIs(None, proposal.date_reviewed)
        self.assertIs(None, proposal.reviewed_revision_id)

    def test_transitions_from_rejected_to_merged_resets_reviewer(self):
        # When a rejected proposal ends up being merged anyway, reset the
        # reviewer details as they did not approve as is otherwise assumed.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.REJECTED,
        )
        self.assertIsNot(None, proposal.reviewer)
        self.assertIsNot(None, proposal.date_reviewed)
        self.assertIsNot(None, proposal.reviewed_revision_id)
        proposal.markAsMerged()
        self.assertIs(None, proposal.reviewer)
        self.assertIs(None, proposal.date_reviewed)
        self.assertIs(None, proposal.reviewed_revision_id)


class TestBranchMergeProposalSetStatus(TestCaseWithFactory):
    """Test the setStatus method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.target_branch = self.factory.makeProductBranch()
        login_person(self.target_branch.owner)

    def test_set_status_approved_to_work_in_progress(self):
        # setState can change an approved merge proposal to Work In Progress.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.CODE_APPROVED,
        )
        proposal.setStatus(BranchMergeProposalStatus.WORK_IN_PROGRESS)
        self.assertEqual(
            proposal.queue_status, BranchMergeProposalStatus.WORK_IN_PROGRESS
        )

    def test_set_status_wip_to_needs_review(self):
        # setState can change the merge proposal to Needs Review.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS,
        )
        proposal.setStatus(BranchMergeProposalStatus.NEEDS_REVIEW)
        self.assertEqual(
            proposal.queue_status, BranchMergeProposalStatus.NEEDS_REVIEW
        )

    def test_set_status_wip_to_code_approved(self):
        # setState can change the merge proposal to Approved, which will
        # also set the reviewed_revision_id to the approved revision id.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS,
        )
        proposal.setStatus(
            BranchMergeProposalStatus.CODE_APPROVED,
            user=self.target_branch.owner,
            revision_id="500",
        )
        self.assertEqual(
            proposal.queue_status, BranchMergeProposalStatus.CODE_APPROVED
        )
        self.assertEqual(proposal.reviewed_revision_id, "500")

    def test_set_status_wip_to_rejected(self):
        # setState can change the merge proposal to Rejected, which also
        # marks the reviewed_revision_id to the rejected revision id.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS,
        )
        proposal.setStatus(
            BranchMergeProposalStatus.REJECTED,
            user=self.target_branch.owner,
            revision_id="1000",
        )
        self.assertEqual(
            proposal.queue_status, BranchMergeProposalStatus.REJECTED
        )
        self.assertEqual(proposal.reviewed_revision_id, "1000")

    def test_set_status_wip_to_merged(self):
        # setState can change the merge proposal to Merged.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS,
        )
        proposal.setStatus(
            BranchMergeProposalStatus.MERGED,
            user=self.target_branch.owner,
            revision_id="1000",
        )
        self.assertEqual(
            proposal.queue_status, BranchMergeProposalStatus.MERGED
        )
        self.assertEqual(proposal.merged_revision_id, "1000")
        self.assertEqual(proposal.merge_type, MergeType.UNKNOWN)

    def test_set_status_invalid_status(self):
        # IBranchMergeProposal.setStatus doesn't work in the case of
        # superseded branches since a superseded branch requires more than
        # just changing a few settings.  Because it's unknown, it should
        # raise an AssertionError.
        proposal = self.factory.makeBranchMergeProposal(
            target_branch=self.target_branch,
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS,
        )
        self.assertRaises(
            AssertionError,
            proposal.setStatus,
            BranchMergeProposalStatus.SUPERSEDED,
        )


class TestBranchMergeProposalRequestReview(TestCaseWithFactory):
    """Test the resetting of date_review_reqeuested."""

    layer = DatabaseFunctionalLayer

    def _createMergeProposal(self, needs_review):
        # Create and return a merge proposal.
        source_branch = self.factory.makeProductBranch()
        target_branch = self.factory.makeProductBranch(
            product=source_branch.product
        )
        login_person(target_branch.owner)
        return source_branch.addLandingTarget(
            source_branch.owner,
            target_branch,
            date_created=datetime(2000, 1, 1, 12, tzinfo=timezone.utc),
            needs_review=needs_review,
        )

    def test_date_set_on_change(self):
        # When the proposal changes to needs review state the date is
        # recoreded.
        proposal = self._createMergeProposal(needs_review=False)
        self.assertEqual(
            BranchMergeProposalStatus.WORK_IN_PROGRESS, proposal.queue_status
        )
        self.assertIs(None, proposal.date_review_requested)
        # Requesting the merge then sets the date review requested.
        proposal.requestReview()
        self.assertSqlAttributeEqualsDate(
            proposal, "date_review_requested", UTC_NOW
        )

    def test_date_not_reset_on_rerequest(self):
        # When the proposal changes to needs review state the date is
        # recoreded.
        proposal = self._createMergeProposal(needs_review=True)
        self.assertEqual(
            BranchMergeProposalStatus.NEEDS_REVIEW, proposal.queue_status
        )
        self.assertEqual(proposal.date_created, proposal.date_review_requested)
        # Requesting the merge again will not reset the date review requested.
        proposal.requestReview()
        self.assertEqual(proposal.date_created, proposal.date_review_requested)

    def test_date_not_reset_on_wip(self):
        # If a proposal has been in needs review state, and is moved back into
        # work in progress, the date_review_requested is not reset.
        proposal = self._createMergeProposal(needs_review=True)
        proposal.setAsWorkInProgress()
        self.assertIsNot(None, proposal.date_review_requested)


class TestCreateCommentNotifications(TestCaseWithFactory):
    """Test the notifications are raised at the right times."""

    layer = DatabaseFunctionalLayer

    def test_notify_on_nominate(self):
        # Ensure that a notification is emitted when a new comment is added.
        merge_proposal = self.factory.makeBranchMergeProposal()
        commenter = self.factory.makePerson()
        login_person(commenter)
        result, events = self.assertNotifies(
            ObjectCreatedEvent,
            False,
            merge_proposal.createComment,
            owner=commenter,
            subject="A review.",
        )
        self.assertEqual(result, events[0].object)

    def test_notify_on_nominate_suppressed_if_requested(self):
        # Ensure that the notification is suppressed if the notify listeners
        # parameger is set to False.
        merge_proposal = self.factory.makeBranchMergeProposal()
        commenter = self.factory.makePerson()
        login_person(commenter)
        self.assertNoNotification(
            merge_proposal.createComment,
            owner=commenter,
            subject="A review.",
            _notify_listeners=False,
        )


class TestMergeProposalAllComments(TestCase):
    """Tester for `BranchMergeProposal.all_comments`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        # Testing behaviour, not permissions here.
        login("foo.bar@canonical.com")
        self.factory = LaunchpadObjectFactory()
        self.merge_proposal = self.factory.makeBranchMergeProposal()

    def test_all_comments(self):
        """Ensure all comments associated with the proposal are returned."""
        comment1 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject"
        )
        comment2 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject"
        )
        comment3 = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject"
        )
        self.assertEqual(
            {comment1, comment2, comment3},
            set(self.merge_proposal.all_comments),
        )


class TestMergeProposalGetComment(TestCase):
    """Tester for `BranchMergeProposal.getComment`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        # Testing behaviour, not permissions here.
        login("foo.bar@canonical.com")
        self.factory = LaunchpadObjectFactory()
        self.merge_proposal = self.factory.makeBranchMergeProposal()
        self.merge_proposal2 = self.factory.makeBranchMergeProposal()
        self.comment = self.merge_proposal.createComment(
            self.merge_proposal.registrant, "Subject"
        )

    def test_getComment(self):
        """Tests that we can get a comment."""
        self.assertEqual(
            self.comment, self.merge_proposal.getComment(self.comment.id)
        )

    def test_getCommentWrongBranchMergeProposal(self):
        """Tests that we can get a comment."""
        self.assertRaises(
            WrongBranchMergeProposal,
            self.merge_proposal2.getComment,
            self.comment.id,
        )


class TestMergeProposalSetCommentVisibility(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_anonymous(self):
        comment = self.factory.makeCodeReviewComment()
        self.assertRaisesWithContent(
            Unauthorized,
            "User <anonymous> cannot hide or show code review comments.",
            comment.branch_merge_proposal.setCommentVisibility,
            user=None,
            comment_number=comment.id,
            visible=False,
        )

    def test_random_user(self):
        comment = self.factory.makeCodeReviewComment()
        person = self.factory.makePerson()
        self.assertRaisesWithContent(
            Unauthorized,
            "User %s cannot hide or show code review comments." % person.name,
            comment.branch_merge_proposal.setCommentVisibility,
            user=person,
            comment_number=comment.id,
            visible=False,
        )

    def test_comment_author(self):
        comment = self.factory.makeCodeReviewComment()
        another_comment = self.factory.makeCodeReviewComment(
            merge_proposal=comment.branch_merge_proposal
        )
        comment.branch_merge_proposal.setCommentVisibility(
            user=comment.author, comment_number=comment.id, visible=False
        )
        self.assertFalse(comment.visible)
        self.assertTrue(another_comment.visible)

    def test_registry_expert(self):
        comment = self.factory.makeCodeReviewComment()
        another_comment = self.factory.makeCodeReviewComment(
            merge_proposal=comment.branch_merge_proposal
        )
        comment.branch_merge_proposal.setCommentVisibility(
            user=self.factory.makeRegistryExpert(),
            comment_number=comment.id,
            visible=False,
        )
        self.assertFalse(comment.visible)
        self.assertTrue(another_comment.visible)

    def test_admin(self):
        comment = self.factory.makeCodeReviewComment()
        another_comment = self.factory.makeCodeReviewComment(
            merge_proposal=comment.branch_merge_proposal
        )
        comment.branch_merge_proposal.setCommentVisibility(
            user=self.factory.makeAdministrator(),
            comment_number=comment.id,
            visible=False,
        )
        self.assertFalse(comment.visible)
        self.assertTrue(another_comment.visible)


class TestMergeProposalGetVoteReference(TestCaseWithFactory):
    """Tester for `BranchMergeProposal.getComment`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        # Testing behaviour, not permissions here.
        login("foo.bar@canonical.com")
        self.merge_proposal = self.factory.makeBranchMergeProposal()
        self.merge_proposal2 = self.factory.makeBranchMergeProposal()
        self.vote = self.merge_proposal.nominateReviewer(
            reviewer=self.merge_proposal.registrant,
            registrant=self.merge_proposal.registrant,
        )

    def test_getVoteReference(self):
        """Tests that we can get a comment."""
        self.assertEqual(
            self.vote, self.merge_proposal.getVoteReference(self.vote.id)
        )

    def test_getVoteReferenceWrongBranchMergeProposal(self):
        """Tests that we can get a comment."""
        self.assertRaises(
            WrongBranchMergeProposal,
            self.merge_proposal2.getVoteReference,
            self.vote.id,
        )


class TestMergeProposalGetPreviewDiff(TestCaseWithFactory):
    """Tests for `BranchMergeProposal.getPreviewDiff`."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user="foo.bar@canonical.com")
        self.mp_one = self.factory.makeBranchMergeProposal()
        self.mp_two = self.factory.makeBranchMergeProposal()
        self.preview_diff = self.mp_one.updatePreviewDiff(
            "Some diff", "source_id", "target_id"
        )
        transaction.commit()

    def test_getPreviewDiff(self):
        """We can get a preview-diff."""
        self.assertEqual(
            self.preview_diff, self.mp_one.getPreviewDiff(self.preview_diff.id)
        )

    def test_getPreviewDiff_NotFound(self):
        """DiffNotFound is raised if a PreviewDiff cannot be found."""
        self.assertRaises(DiffNotFound, self.mp_one.getPreviewDiff, 1000)

    def test_getPreviewDiffWrongBranchMergeProposal(self):
        """An error is raised if the given id does not match the MP."""
        self.assertRaises(
            WrongBranchMergeProposal,
            self.mp_two.getPreviewDiff,
            self.preview_diff.id,
        )


class TestMergeProposalNotification(WithVCSScenarios, TestCaseWithFactory):
    """Test that events are created when merge proposals are manipulated"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user="test@canonical.com")

    def test_notifyOnCreate_needs_review(self):
        # When a merge proposal is created needing review, the
        # BranchMergeProposalNeedsReviewEvent is raised as well as the usual
        # ObjectCreatedEvent.
        source = self.makeBranch()
        target = self.makeBranch(same_target_as=source)
        registrant = self.factory.makePerson()
        result, events = self.assertNotifies(
            [ObjectCreatedEvent, BranchMergeProposalNeedsReviewEvent],
            False,
            source.addLandingTarget,
            registrant,
            target,
            needs_review=True,
        )
        self.assertEqual(result, events[0].object)

    def test_notifyOnCreate_work_in_progress(self):
        # When a merge proposal is created as work in progress, the
        # BranchMergeProposalNeedsReviewEvent is not raised.
        source = self.makeBranch()
        target = self.makeBranch(same_target_as=source)
        registrant = self.factory.makePerson()
        result, events = self.assertNotifies(
            [ObjectCreatedEvent],
            False,
            source.addLandingTarget,
            registrant,
            target,
        )
        self.assertEqual(result, events[0].object)

    def test_needs_review_from_work_in_progress(self):
        # Transitioning from work in progress to needs review raises the
        # BranchMergeProposalNeedsReviewEvent event.
        bmp = self.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.WORK_IN_PROGRESS
        )
        with person_logged_in(bmp.registrant):
            self.assertNotifies(
                [BranchMergeProposalNeedsReviewEvent],
                False,
                bmp.setStatus,
                BranchMergeProposalStatus.NEEDS_REVIEW,
            )

    def test_needs_review_no_op(self):
        # Calling needs review when in needs review does not notify.
        bmp = self.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.NEEDS_REVIEW
        )
        with person_logged_in(bmp.registrant):
            self.assertNoNotification(
                bmp.setStatus, BranchMergeProposalStatus.NEEDS_REVIEW
            )

    def test_needs_review_from_approved(self):
        # Calling needs review when approved does not notify either.
        bmp = self.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.CODE_APPROVED
        )
        with person_logged_in(bmp.registrant):
            self.assertNoNotification(
                bmp.setStatus, BranchMergeProposalStatus.NEEDS_REVIEW
            )

    def test_getNotificationRecipients(self):
        """Ensure that recipients can be added/removed with subscribe"""
        bmp = self.makeBranchMergeProposal()
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.merge_source.owner
        target_owner = bmp.merge_target.owner
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        subscriber_set = {source_owner, target_owner}
        self.assertEqual(subscriber_set, set(recipients.keys()))
        source_subscriber = self.factory.makePerson()
        bmp.merge_source.subscribe(
            source_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            source_subscriber,
        )
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        subscriber_set.add(source_subscriber)
        self.assertEqual(subscriber_set, set(recipients.keys()))
        bmp.merge_source.subscribe(
            source_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.NOEMAIL,
            source_subscriber,
        )
        # By specifying no email, they will no longer get email.
        subscriber_set.remove(source_subscriber)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        self.assertEqual(subscriber_set, set(recipients.keys()))

    def test_getNotificationRecipientLevels(self):
        """Ensure that only recipients with the right level are returned"""
        bmp = self.makeBranchMergeProposal()
        full_subscriber = self.factory.makePerson()
        bmp.merge_source.subscribe(
            full_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            full_subscriber,
        )
        status_subscriber = self.factory.makePerson()
        bmp.merge_source.subscribe(
            status_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.STATUS,
            status_subscriber,
        )
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.merge_source.owner
        target_owner = bmp.merge_target.owner
        self.assertEqual(
            {full_subscriber, status_subscriber, source_owner, target_owner},
            set(recipients.keys()),
        )
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.FULL
        )
        self.assertEqual(
            {full_subscriber, source_owner, target_owner},
            set(recipients.keys()),
        )

    def test_getNotificationRecipientsAnyBranch(self):
        prerequisite = self.makeBranch()
        bmp = self.makeBranchMergeProposal(prerequisite=prerequisite)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.NOEMAIL
        )
        source_owner = bmp.merge_source.owner
        target_owner = bmp.merge_target.owner
        prerequisite_owner = bmp.merge_prerequisite.owner
        self.assertEqual(
            {source_owner, target_owner, prerequisite_owner},
            set(recipients.keys()),
        )
        source_subscriber = self.factory.makePerson()
        bmp.merge_source.subscribe(
            source_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            source_subscriber,
        )
        target_subscriber = self.factory.makePerson()
        bmp.merge_target.subscribe(
            target_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            target_subscriber,
        )
        prerequisite_subscriber = self.factory.makePerson()
        bmp.merge_prerequisite.subscribe(
            prerequisite_subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            prerequisite_subscriber,
        )
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.FULL
        )
        self.assertEqual(
            {
                source_subscriber,
                target_subscriber,
                prerequisite_subscriber,
                source_owner,
                target_owner,
                prerequisite_owner,
            },
            set(recipients.keys()),
        )

    def test_getNotificationRecipientsIncludesReviewers(self):
        bmp = self.makeBranchMergeProposal()
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.merge_source.owner
        target_owner = bmp.merge_target.owner
        login_person(source_owner)
        reviewer = self.factory.makePerson()
        bmp.nominateReviewer(reviewer, registrant=source_owner)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        subscriber_set = {source_owner, target_owner, reviewer}
        self.assertEqual(subscriber_set, set(recipients.keys()))

    def test_getNotificationRecipientsIncludesTeamReviewers(self):
        # If the reviewer is a team, the team gets the email.
        bmp = self.makeBranchMergeProposal()
        # Both of the branch owners are now subscribed to their own
        # branches with full code review notification level set.
        source_owner = bmp.merge_source.owner
        target_owner = bmp.merge_target.owner
        login_person(source_owner)
        reviewer = self.factory.makeTeam()
        bmp.nominateReviewer(reviewer, registrant=source_owner)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        subscriber_set = {source_owner, target_owner, reviewer}
        self.assertEqual(subscriber_set, set(recipients.keys()))

    def test_getNotificationRecipients_Registrant(self):
        # If the registrant of the proposal is being notified of the
        # proposals, they get their rationale set to "Registrant".
        registrant = self.factory.makePerson()
        bmp = self.makeBranchMergeProposal(registrant=registrant)
        # Make sure that the registrant is subscribed.
        bmp.merge_source.subscribe(
            registrant,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            registrant,
        )
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        reason = recipients[registrant]
        self.assertEqual("Registrant", reason.mail_header)
        self.assertEqual(
            "You proposed %s for merging." % bmp.merge_source.identity,
            reason.getReason(),
        )

    def test_getNotificationRecipients_Registrant_not_subscribed(self):
        # If the registrant of the proposal is not subscribed, we don't send
        # them any email.
        registrant = self.factory.makePerson()
        bmp = self.makeBranchMergeProposal(registrant=registrant)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        self.assertFalse(registrant in recipients)

    def test_getNotificationRecipients_Owner(self):
        # If the owner of the source branch is subscribed (which is the
        # default), then they get a rationale telling them they are the Owner.
        bmp = self.makeBranchMergeProposal()
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        reason = recipients[bmp.merge_source.owner]
        self.assertEqual("Owner", reason.mail_header)
        self.assertEqual(
            "You are the owner of %s." % bmp.merge_source.identity,
            reason.getReason(),
        )

    def test_getNotificationRecipients_team_owner(self):
        # If the owner of the source branch is subscribed (which is the
        # default), but the owner is a team, then none of the headers will say
        # Owner.
        team = self.factory.makeTeam()
        branch = self.makeBranch(owner=team)
        bmp = self.makeBranchMergeProposal(source=branch)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        headers = {reason.mail_header for reason in recipients.values()}
        self.assertFalse("Owner" in headers)

    def test_getNotificationRecipients_Owner_not_subscribed(self):
        # If the owner of the source branch has unsubscribed themselves, then
        # we don't send them email.
        bmp = self.makeBranchMergeProposal()
        owner = bmp.merge_source.owner
        bmp.merge_source.unsubscribe(owner, owner)
        recipients = bmp.getNotificationRecipients(
            CodeReviewNotificationLevel.STATUS
        )
        self.assertFalse(owner in recipients)

    def test_getNotificationRecipients_privacy(self):
        # If a user can see only one of the source and target branches, then
        # they do not get email about the proposal.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        source = self.makeBranch(owner=owner, product=product)
        target = self.makeBranch(owner=owner, product=product)
        bmp = self.makeBranchMergeProposal(source=source, target=target)
        # Subscribe eric to the source branch only.
        eric = self.factory.makePerson()
        source.subscribe(
            eric,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            eric,
        )
        # Subscribe bob to the target branch only.
        bob = self.factory.makePerson()
        target.subscribe(
            bob,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            bob,
        )
        # Subscribe charlie to both.
        charlie = self.factory.makePerson()
        source.subscribe(
            charlie,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            charlie,
        )
        target.subscribe(
            charlie,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.FULL,
            charlie,
        )
        # Make both branches private.
        for branch in (source, target):
            removeSecurityProxy(branch).transitionToInformationType(
                InformationType.USERDATA, branch.owner, verify_policy=False
            )
        with person_logged_in(owner):
            recipients = bmp.getNotificationRecipients(
                CodeReviewNotificationLevel.FULL
            )
        self.assertNotIn(bob, recipients)
        self.assertNotIn(eric, recipients)
        self.assertIn(charlie, recipients)


class TestMergeProposalWebhooks(WithVCSScenarios, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def getWebhookTarget(self, branch):
        if self.git:
            return branch.repository
        else:
            return branch

    @staticmethod
    def getURL(obj):
        if obj is not None:
            return canonical_url(obj, force_local_path=True)
        else:
            return None

    @classmethod
    def getExpectedPayload(cls, proposal, redact=False):
        payload = {
            "registrant": "/~%s" % proposal.registrant.name,
            "source_branch": cls.getURL(proposal.source_branch),
            "source_git_repository": cls.getURL(
                proposal.source_git_repository
            ),
            "source_git_path": proposal.source_git_path,
            "target_branch": cls.getURL(proposal.target_branch),
            "target_git_repository": cls.getURL(
                proposal.target_git_repository
            ),
            "target_git_path": proposal.target_git_path,
            "prerequisite_branch": cls.getURL(proposal.prerequisite_branch),
            "prerequisite_git_repository": cls.getURL(
                proposal.prerequisite_git_repository
            ),
            "prerequisite_git_path": proposal.prerequisite_git_path,
            "queue_status": proposal.queue_status.title,
            "commit_message": (
                "<redacted>" if redact else proposal.commit_message
            ),
            "whiteboard": "<redacted>" if redact else proposal.whiteboard,
            "description": "<redacted>" if redact else proposal.description,
            "preview_diff": cls.getURL(proposal.preview_diff),
        }
        return {k: Equals(v) for k, v in payload.items()}

    def assertCorrectDelivery(
        self, expected_payload, hook, delivery, event_type
    ):
        self.assertThat(
            delivery,
            MatchesStructure(
                event_type=Equals(event_type),
                payload=MatchesDict(expected_payload),
            ),
        )
        with dbuser(config.IWebhookDeliveryJobSource.dbuser):
            self.assertEqual(
                "<WebhookDeliveryJob for webhook %d on %r>"
                % (hook.id, hook.target),
                repr(delivery),
            )

    def assertCorrectLogging(
        self, expected_redacted_payload, hook, logger, event_type
    ):
        with dbuser(config.IWebhookDeliveryJobSource.dbuser):
            self.assertThat(
                logger.output,
                LogsScheduledWebhooks(
                    [
                        (
                            hook,
                            event_type,
                            MatchesDict(expected_redacted_payload),
                        )
                    ]
                ),
            )

    def test_create_private_repo_triggers_webhooks(self):
        # When a merge proposal is created, any relevant webhooks are
        # triggered even if the repository is proprietary.
        logger = self.useFixture(FakeLogger())
        source = self.makeBranch(information_type=InformationType.PROPRIETARY)
        target = self.makeBranch(
            same_target_as=source, information_type=InformationType.PROPRIETARY
        )

        with admin_logged_in():
            # Create the web hook and the proposal.
            registrant = self.factory.makePerson()
            hook = self.factory.makeWebhook(
                target=self.getWebhookTarget(target),
                event_types=["merge-proposal:0.1::create"],
            )
            proposal = source.addLandingTarget(
                registrant, target, needs_review=True
            )
            target_owner = target.owner

        login_person(target_owner)
        delivery = hook.deliveries.one()
        expected_payload = {
            "merge_proposal": Equals(self.getURL(proposal)),
            "action": Equals("created"),
            "new": MatchesDict(self.getExpectedPayload(proposal)),
        }
        expected_redacted_payload = dict(
            expected_payload,
            new=MatchesDict(self.getExpectedPayload(proposal, redact=True)),
        )
        expected_event = "merge-proposal:0.1"
        self.assertCorrectDelivery(
            expected_payload, hook, delivery, expected_event
        )
        self.assertCorrectLogging(
            expected_redacted_payload, hook, logger, expected_event
        )

    def test_create_triggers_webhooks(self):
        # When a merge proposal is created, any relevant webhooks are
        # triggered.
        logger = self.useFixture(FakeLogger())
        source = self.makeBranch()
        target = self.makeBranch(same_target_as=source)
        registrant = self.factory.makePerson()
        hook = self.factory.makeWebhook(
            target=self.getWebhookTarget(target),
            event_types=["merge-proposal:0.1::create"],
        )
        proposal = source.addLandingTarget(
            registrant, target, needs_review=True
        )
        login_person(target.owner)
        delivery = hook.deliveries.one()
        expected_payload = {
            "merge_proposal": Equals(self.getURL(proposal)),
            "action": Equals("created"),
            "new": MatchesDict(self.getExpectedPayload(proposal)),
        }
        expected_redacted_payload = dict(
            expected_payload,
            new=MatchesDict(self.getExpectedPayload(proposal, redact=True)),
        )
        expected_event = "merge-proposal:0.1"
        self.assertCorrectDelivery(
            expected_payload, hook, delivery, expected_event
        )
        self.assertCorrectLogging(
            expected_redacted_payload, hook, logger, expected_event
        )

    def test_modify_triggers_webhooks(self):
        logger = self.useFixture(FakeLogger())
        # When an existing merge proposal is modified, any relevant webhooks
        # are triggered.
        source = self.makeBranch()
        target = self.makeBranch(same_target_as=source)
        registrant = self.factory.makePerson()
        proposal = source.addLandingTarget(
            registrant, target, needs_review=True
        )
        hook = self.factory.makeWebhook(
            target=self.getWebhookTarget(target),
            event_types=["merge-proposal:0.1::status-change"],
        )
        login_person(target.owner)
        expected_payload = {
            "merge_proposal": Equals(self.getURL(proposal)),
            "action": Equals("modified"),
            "old": MatchesDict(self.getExpectedPayload(proposal)),
        }
        expected_redacted_payload = dict(
            expected_payload,
            old=MatchesDict(self.getExpectedPayload(proposal, redact=True)),
        )
        with BranchMergeProposalNoPreviewDiffDelta.monitor(proposal):
            proposal.setStatus(
                BranchMergeProposalStatus.CODE_APPROVED, user=target.owner
            )
            proposal.description = "An excellent proposal."
        expected_payload["new"] = MatchesDict(
            self.getExpectedPayload(proposal)
        )
        expected_redacted_payload["new"] = MatchesDict(
            self.getExpectedPayload(proposal, redact=True)
        )
        expected_event = "merge-proposal:0.1"
        delivery = hook.deliveries.one()
        self.assertCorrectDelivery(
            expected_payload, hook, delivery, expected_event
        )
        self.assertCorrectLogging(
            expected_redacted_payload, hook, logger, expected_event
        )

    def test_delete_triggers_webhooks(self):
        # When an existing merge proposal is deleted, any relevant webhooks
        # are triggered.
        logger = self.useFixture(FakeLogger())
        source = self.makeBranch()
        target = self.makeBranch(same_target_as=source)
        registrant = self.factory.makePerson()
        proposal = source.addLandingTarget(
            registrant, target, needs_review=True
        )
        hook = self.factory.makeWebhook(
            target=self.getWebhookTarget(target),
            event_types=["merge-proposal:0.1::delete"],
        )
        login_person(target.owner)
        expected_payload = {
            "merge_proposal": Equals(self.getURL(proposal)),
            "action": Equals("deleted"),
            "old": MatchesDict(self.getExpectedPayload(proposal)),
        }
        expected_redacted_payload = dict(
            expected_payload,
            old=MatchesDict(self.getExpectedPayload(proposal, redact=True)),
        )
        proposal.deleteProposal()
        delivery = hook.deliveries.one()
        expected_event = "merge-proposal:0.1"
        self.assertCorrectDelivery(
            expected_payload, hook, delivery, expected_event
        )
        self.assertCorrectLogging(
            expected_redacted_payload, hook, logger, expected_event
        )

    def _create_for_webhook_with_git_ref_pattern(
        self, git_ref_pattern, expect_delivery
    ):
        source = self.makeBranch()
        target = self.makeBranch(
            same_target_as=source, name="refs/heads/foo-bar"
        )
        registrant = self.factory.makePerson()
        hook = self.factory.makeWebhook(
            target=self.getWebhookTarget(target),
            event_types=["merge-proposal:0.1::create"],
            git_ref_pattern=git_ref_pattern,
        )
        source.addLandingTarget(registrant, target, needs_review=True)
        login_person(target.owner)
        delivery = hook.deliveries.one()

        if expect_delivery:
            self.assertIsNotNone(delivery)
        else:
            self.assertIsNone(delivery)

    def test_create_triggers_webhooks_with_matching_ref_pattern(self):
        if not self.git:
            self.skipTest("Only relevant for Git.")

        self._create_for_webhook_with_git_ref_pattern(
            git_ref_pattern="refs/heads/*", expect_delivery=True
        )

    def test_create_doesnt_trigger_webhooks_without_matching_ref_pattern(self):
        if not self.git:
            self.skipTest("Only relevant for Git.")

        self._create_for_webhook_with_git_ref_pattern(
            git_ref_pattern="not-matching-test", expect_delivery=False
        )

    def _modify_for_webhook_with_git_ref_pattern(
        self, git_ref_pattern, expect_delivery
    ):
        source = self.makeBranch()
        target = self.makeBranch(
            same_target_as=source, name="refs/heads/foo-bar"
        )
        registrant = self.factory.makePerson()
        proposal = source.addLandingTarget(
            registrant, target, needs_review=True
        )
        hook = self.factory.makeWebhook(
            target=self.getWebhookTarget(target),
            event_types=["merge-proposal:0.1::status-change"],
            git_ref_pattern=git_ref_pattern,
        )

        with person_logged_in(
            target.owner
        ), BranchMergeProposalNoPreviewDiffDelta.monitor(proposal):
            proposal.setStatus(
                BranchMergeProposalStatus.CODE_APPROVED, user=target.owner
            )
            proposal.description = "An excellent proposal."
        with admin_logged_in():
            delivery = hook.deliveries.one()

        if expect_delivery:
            self.assertIsNotNone(delivery)
        else:
            self.assertIsNone(delivery)

    def test_modify_triggers_webhooks_with_matching_ref_pattern(self):
        if not self.git:
            self.skipTest("Only relevant for Git.")

        self._modify_for_webhook_with_git_ref_pattern(
            git_ref_pattern="refs/heads/*", expect_delivery=True
        )

    def test_modify_doesnt_trigger_webhooks_without_matching_ref_pattern(self):
        if not self.git:
            self.skipTest("Only relevant for Git.")

        self._modify_for_webhook_with_git_ref_pattern(
            git_ref_pattern="not-matching-test", expect_delivery=False
        )

    def _delete_for_webhook_with_git_ref_pattern(
        self, git_ref_pattern, expect_delivery
    ):
        source = self.makeBranch()
        target = self.makeBranch(
            same_target_as=source, name="refs/heads/foo-bar"
        )
        registrant = self.factory.makePerson()
        proposal = source.addLandingTarget(
            registrant, target, needs_review=True
        )
        hook = self.factory.makeWebhook(
            target=self.getWebhookTarget(target),
            event_types=["merge-proposal:0.1::delete"],
            git_ref_pattern=git_ref_pattern,
        )
        with person_logged_in(target.owner):
            proposal.deleteProposal()
            delivery = hook.deliveries.one()

        if expect_delivery:
            self.assertIsNotNone(delivery)
        else:
            self.assertIsNone(delivery)

    def test_delete_triggers_webhooks_with_matching_ref_pattern(self):
        if not self.git:
            self.skipTest("Only relevant for Git.")

        self._delete_for_webhook_with_git_ref_pattern(
            git_ref_pattern="refs/heads/*", expect_delivery=True
        )

    def test_delete_doesnt_trigger_webhooks_without_matching_ref_pattern(self):
        if not self.git:
            self.skipTest("Only relevant for Git.")

        self._delete_for_webhook_with_git_ref_pattern(
            git_ref_pattern="not-matching-test", expect_delivery=False
        )


class TestMergeProposalWebhookGranularity(
    WithVCSScenarios,
    DiffTestCase,
):
    """Webhook subscopes behaviour for merge-proposals."""

    layer = LaunchpadZopelessLayer

    valid_diff = (
        "diff --git a/foo b/foo\n"
        "new file mode 100644\n"
        "index 0000000..e69de29\n"
        "--- /dev/null\n"
        "+++ b/foo\n"
        "@@ -0,0 +1 @@\n"
        "+dummy\n"
    )

    def _make_mp_and_hook(self, event_types):
        source = self.makeBranch()
        target = self.makeBranch(same_target_as=source)
        mp = source.addLandingTarget(
            self.factory.makePerson(), target, needs_review=True
        )
        hook = self.factory.makeWebhook(
            target=target.repository if self.git else target,
            event_types=event_types,
        )
        return mp, hook, target

    def _latest_delivery(self, hook):
        with admin_logged_in():
            return hook.deliveries.one()

    def test_edit_description_triggers_webhook(self):
        """Updating the description triggers the merge proposal webhook
        with subscope ::edit."""
        mp, hook, target = self._make_mp_and_hook(["merge-proposal:0.1::edit"])

        login_person(target.owner)
        with BranchMergeProposalNoPreviewDiffDelta.monitor(mp):
            mp.description = "New description"

        self.assertEqual(
            "merge-proposal:0.1", self._latest_delivery(hook).event_type
        )
        self.assertEqual(1, hook.deliveries.count())
        delivery = self._latest_delivery(hook)
        self.assertEqual("modified", delivery.payload["action"])

    def test_edit_commit_message_triggers_webhook(self):
        """Updating the commit message triggers the merge proposal webhook
        with subscope ::edit."""
        mp, hook, target = self._make_mp_and_hook(["merge-proposal:0.1::edit"])

        login_person(target.owner)
        with BranchMergeProposalNoPreviewDiffDelta.monitor(mp):
            mp.commit_message = "New description"

        self.assertEqual(
            "merge-proposal:0.1", self._latest_delivery(hook).event_type
        )
        self.assertEqual(1, hook.deliveries.count())
        delivery = self._latest_delivery(hook)
        self.assertEqual("modified", delivery.payload["action"])

    def test_review_without_inlines_always_triggers(self):
        """A main comment without inline comments triggers exactly once
        ::review webhook."""
        mp, hook, target = self._make_mp_and_hook(
            ["merge-proposal:0.1::review"]
        )

        login_person(target.owner)
        preview = mp.updatePreviewDiff(self.valid_diff, "a", "b")
        transaction.commit()

        author = self.factory.makePerson()
        login_person(author)
        mp.createComment(
            author,
            subject="LGTM",
            content="All good!",
            previewdiff_id=preview.id,
            vote=CodeReviewVote.APPROVE,
            inline_comments={},
        )
        transaction.commit()

        with admin_logged_in():
            self.assertEqual(1, hook.deliveries.count())
            self.assertEqual(
                "merge-proposal:0.1",
                self._latest_delivery(hook).event_type,
            )
            delivery = self._latest_delivery(hook)
            self.assertEqual("reviewed", delivery.payload["action"])

    def test_review_with_main_and_inline_comments_trigger_once(self):
        """A main comment and inline comments triggers exactly one
        ::review webhook."""
        mp, hook, target = self._make_mp_and_hook(
            ["merge-proposal:0.1::review"]
        )
        login_person(target.owner)

        preview = mp.updatePreviewDiff(self.valid_diff, "a", "b")
        transaction.commit()

        author = self.factory.makePerson()
        login_person(author)
        mp.createComment(
            author,
            subject="LGTM-with-inline",
            content="Looks fine with a couple of remarks.",
            previewdiff_id=preview.id,
            vote=CodeReviewVote.APPROVE,
            inline_comments={"10": "one remark", "20": "another remark"},
        )
        transaction.commit()

        with admin_logged_in():
            self.assertEqual(1, hook.deliveries.count())
            self.assertEqual(
                "merge-proposal:0.1",
                self._latest_delivery(hook).event_type,
            )
            delivery = self._latest_delivery(hook)
            self.assertEqual("reviewed", delivery.payload["action"])

    def test_parent_scope_still_receives_create(self):
        """A hook with only 'merge-proposal:0.1' event type still triggers
        when a merge proposal is created."""
        target = self.makeBranch()
        hook = self.factory.makeWebhook(
            target=target.repository if self.git else target,
            event_types=["merge-proposal:0.1"],
        )

        # Creating the MP should schedule the webhook.
        login_person(target.owner)
        source = self.makeBranch(same_target_as=target)
        source.addLandingTarget(
            self.factory.makePerson(), target, needs_review=True
        )
        self.assertEqual(1, hook.deliveries.count())
        self.assertEqual(
            "merge-proposal:0.1", self._latest_delivery(hook).event_type
        )
        delivery = self._latest_delivery(hook)
        payload = delivery.payload
        self.assertEqual("created", payload["action"])

    def test_subscope_does_not_leak_to_other_subscope(self):
        """A hook for ::status-change is not triggered by ::edit."""
        mp, hook, target = self._make_mp_and_hook(
            ["merge-proposal:0.1::status-change"]
        )

        # Change something that is not the status (description).
        login_person(target.owner)
        mp.description = "just a wording tweak"
        transaction.commit()
        with admin_logged_in():
            self.assertEqual(0, hook.deliveries.count())

    def test_push_webhook_triggered_git(self):
        """UpdatePreviewDiffJob triggers a 'push' webhook with
        action 'modified'."""
        if not self.git:
            self.skipTest("Only relevant for Git MPs.")

        # Create merge proposal and hook
        mp = self.createExampleGitMerge()[0]
        hook = self.factory.makeWebhook(
            target=mp.target_git_repository,
            event_types=[
                "merge-proposal:0.1::push",
            ],
        )
        # Simulate the push
        job = UpdatePreviewDiffJob.create(mp)
        with dbuser("merge-proposal-jobs"):
            JobRunner([job]).runAll()
        transaction.commit()

        # Assert webhook triggered
        with admin_logged_in():
            self.assertEqual(1, hook.deliveries.count())
            delivery = self._latest_delivery(hook)
            self.assertEqual("merge-proposal:0.1", delivery.event_type)
            self.assertEqual("modified", delivery.payload["action"])
            self.assertIsNotNone(mp.preview_diff)

    def test_push_webhook_triggered_bzr(self):
        """UpdatePreviewDiffJob triggers a 'push' webhook with
        action 'modified' for Bzr MPs."""
        if self.git:
            self.skipTest("Only relevant for Bzr MPs.")

        # Create merge proposal and hook
        mp = self.createExampleBzrMerge()[0]
        hook = self.factory.makeWebhook(
            target=mp.target_branch,
            event_types=["merge-proposal:0.1::push"],
        )

        # Add revisions
        self.factory.makeRevisionsForBranch(mp.source_branch, count=1)
        mp.source_branch.next_mirror_time = None
        transaction.commit()

        # Simulate the push
        job = UpdatePreviewDiffJob.create(mp)
        with dbuser("merge-proposal-jobs"):
            JobRunner([job]).runAll()
        transaction.commit()

        # Assert webhook triggered
        with admin_logged_in():
            self.assertEqual(1, hook.deliveries.count())
            delivery = self._latest_delivery(hook)
            self.assertEqual("merge-proposal:0.1", delivery.event_type)
            self.assertEqual("modified", delivery.payload["action"])
            self.assertIsNotNone(mp.preview_diff)

    def test_create_webhook_triggered(self):
        """Creating a merge proposal triggers only one webhook
        with action 'created'."""
        target = self.makeBranch()
        hook = self.factory.makeWebhook(
            target=target.repository if self.git else target,
            event_types=[
                "merge-proposal:0.1::create",
                "merge-proposal:0.1::push",
                "merge-proposal:0.1::edit",
                "merge-proposal:0.1::review",
                "merge-proposal:0.1::status-change",
            ],
        )

        login_person(target.owner)
        source = self.makeBranch(same_target_as=target)
        source.addLandingTarget(
            self.factory.makePerson(), target, needs_review=True
        )

        with admin_logged_in():
            self.assertEqual(1, hook.deliveries.count())
            delivery = self._latest_delivery(hook)
            self.assertEqual("merge-proposal:0.1", delivery.event_type)
            self.assertEqual("created", delivery.payload["action"])


class TestGetAddress(TestCaseWithFactory):
    """Test that the address property gives expected results."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user="test@canonical.com")

    def test_address(self):
        merge_proposal = self.factory.makeBranchMergeProposal()
        expected = "mp+%d@code.launchpad.test" % merge_proposal.id
        self.assertEqual(expected, merge_proposal.address)


class TestBranchMergeProposalGetter(TestCaseWithFactory):
    """Test that the BranchMergeProposalGetter behaves as expected."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user="test@canonical.com")

    def test_get(self):
        """Ensure the correct merge proposal is returned."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        self.assertEqual(
            merge_proposal, BranchMergeProposalGetter().get(merge_proposal.id)
        )

    def test_get_as_utility(self):
        """Ensure the correct merge proposal is returned."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        utility = getUtility(IBranchMergeProposalGetter)
        retrieved = utility.get(merge_proposal.id)
        self.assertEqual(merge_proposal, retrieved)

    def test_getVotesForProposals(self):
        # Check the resulting format of the dict.  getVotesForProposals
        # returns a dict mapping merge proposals to a list of votes for that
        # proposal.
        mp_no_reviews = make_merge_proposal_without_reviewers(self.factory)
        reviewer = self.factory.makePerson()
        mp_with_reviews = self.factory.makeBranchMergeProposal(
            reviewer=reviewer
        )
        login_person(mp_with_reviews.registrant)
        [vote_reference] = list(mp_with_reviews.votes)
        self.assertEqual(
            {mp_no_reviews: [], mp_with_reviews: [vote_reference]},
            getUtility(IBranchMergeProposalGetter).getVotesForProposals(
                [mp_with_reviews, mp_no_reviews]
            ),
        )

    def test_activeProposalsForBranches_different_branches(self):
        """Only proposals for the correct branches are returned."""
        mp = self.factory.makeBranchMergeProposal()
        mp2 = self.factory.makeBranchMergeProposal()
        active = BranchMergeProposalGetter.activeProposalsForBranches(
            mp.source_branch, mp.target_branch
        )
        self.assertEqual([mp], list(active))
        active2 = BranchMergeProposalGetter.activeProposalsForBranches(
            mp2.source_branch, mp2.target_branch
        )
        self.assertEqual([mp2], list(active2))

    def test_activeProposalsForBranches_different_states(self):
        """Only proposals for active states are returned."""
        for state in BranchMergeProposalStatus.items:
            if state in OBSOLETE_STATES:
                continue
            mp = self.factory.makeBranchMergeProposal(set_state=state)
            active = BranchMergeProposalGetter.activeProposalsForBranches(
                mp.source_branch, mp.target_branch
            )
            # If a proposal is superseded, there is an active proposal which
            # supersedes it.
            if state == BranchMergeProposalStatus.SUPERSEDED:
                self.assertEqual([mp.superseded_by], list(active))
            elif state in FINAL_STATES:
                self.assertEqual([], list(active))
            else:
                self.assertEqual([mp], list(active))


class TestBranchMergeProposalGetterGetProposals(TestCaseWithFactory):
    """Test the getProposalsForContext method."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an administrator so the permission checks for things
        # like adding landing targets and setting privacy on the branches
        # are allowed.
        TestCaseWithFactory.setUp(self, user="foo.bar@canonical.com")

    def _make_merge_proposal(
        self,
        owner_name,
        product_name,
        branch_name,
        needs_review=False,
        registrant=None,
    ):
        # A helper method to make the tests readable.
        owner = getUtility(IPersonSet).getByName(owner_name)
        if owner is None:
            owner = self.factory.makePerson(name=owner_name)
        product = getUtility(IProductSet).getByName(product_name)
        if product is None:
            product = self.factory.makeProduct(name=product_name)
        stacked_on_branch = self.factory.makeProductBranch(
            product=product, owner=owner, registrant=registrant
        )
        branch = self.factory.makeProductBranch(
            product=product,
            owner=owner,
            registrant=registrant,
            name=branch_name,
            stacked_on=stacked_on_branch,
        )
        if registrant is None:
            registrant = owner
        bmp = branch.addLandingTarget(
            registrant=registrant,
            merge_target=self.factory.makeProductBranch(
                product=product, owner=owner
            ),
        )
        if needs_review:
            bmp.requestReview()
        return bmp

    def _get_merge_proposals(self, context, status=None, visible_by_user=None):
        # Helper method to return tuples of source branch details.
        results = BranchMergeProposalGetter.getProposalsForContext(
            context, status, visible_by_user
        )
        return sorted(bmp.source_branch.unique_name for bmp in results)

    def test_getProposalsForParticipant(self):
        # It's possible to get all the merge proposals for a single
        # participant.
        wally = self.factory.makePerson(name="wally")
        beaver = self.factory.makePerson(name="beaver")

        bmp1 = self._make_merge_proposal("wally", "gokart", "turbo", True)
        bmp1.nominateReviewer(beaver, wally)
        self._make_merge_proposal("beaver", "gokart", "brakes", True)

        getter = BranchMergeProposalGetter
        wally_proposals = getter.getProposalsForParticipant(
            wally, [BranchMergeProposalStatus.NEEDS_REVIEW], wally
        )
        self.assertEqual(wally_proposals.count(), 1)

        beave_proposals = getter.getProposalsForParticipant(
            beaver, [BranchMergeProposalStatus.NEEDS_REVIEW], beaver
        )
        self.assertEqual(beave_proposals.count(), 2)

        bmp1.rejectBranch(wally, "1")

        beave_proposals = getter.getProposalsForParticipant(
            beaver, [BranchMergeProposalStatus.NEEDS_REVIEW], beaver
        )
        self.assertEqual(beave_proposals.count(), 1)

        beave_proposals = getter.getProposalsForParticipant(
            beaver, [BranchMergeProposalStatus.REJECTED], beaver
        )
        self.assertEqual(beave_proposals.count(), 1)

    def test_created_proposal_default_status(self):
        # When we create a merge proposal using the helper method, the default
        # status of the proposal is work in progress.
        in_progress = self._make_merge_proposal("albert", "november", "work")
        self.assertEqual(
            BranchMergeProposalStatus.WORK_IN_PROGRESS,
            in_progress.queue_status,
        )

    def test_created_proposal_review_status(self):
        # If needs_review is set to True, the created merge proposal is set in
        # the needs review state.
        needs_review = self._make_merge_proposal(
            "bob", "november", "work", needs_review=True
        )
        self.assertEqual(
            BranchMergeProposalStatus.NEEDS_REVIEW, needs_review.queue_status
        )

    def test_all_for_product_restrictions(self):
        # Queries on product should limit results to that product.
        self._make_merge_proposal("albert", "november", "work")
        self._make_merge_proposal("bob", "november", "work")
        # And make a proposal for another product to make sure that it doesn't
        # appear
        self._make_merge_proposal("charles", "mike", "work")

        self.assertEqual(
            ["~albert/november/work", "~bob/november/work"],
            self._get_merge_proposals(
                getUtility(IProductSet).getByName("november")
            ),
        )

    def test_wip_for_product_restrictions(self):
        # Check queries on product limited on status.
        self._make_merge_proposal("albert", "november", "work")
        self._make_merge_proposal("bob", "november", "work", needs_review=True)
        self.assertEqual(
            ["~albert/november/work"],
            self._get_merge_proposals(
                getUtility(IProductSet).getByName("november"),
                status=[BranchMergeProposalStatus.WORK_IN_PROGRESS],
            ),
        )

    def test_all_for_person_restrictions(self):
        # Queries on person should limit results to that person.
        self._make_merge_proposal("albert", "november", "work")
        self._make_merge_proposal("albert", "mike", "work")
        # And make a proposal for another product to make sure that it doesn't
        # appear
        self._make_merge_proposal("charles", "mike", "work")

        self.assertEqual(
            ["~albert/mike/work", "~albert/november/work"],
            self._get_merge_proposals(
                getUtility(IPersonSet).getByName("albert")
            ),
        )

    def test_wip_for_person_restrictions(self):
        # If looking for the merge proposals for a person, and the status is
        # specified, then the resulting proposals will have one of the states
        # specified.
        self._make_merge_proposal("albert", "november", "work")
        self._make_merge_proposal(
            "albert", "november", "review", needs_review=True
        )
        self.assertEqual(
            ["~albert/november/work"],
            self._get_merge_proposals(
                getUtility(IPersonSet).getByName("albert"),
                status=[BranchMergeProposalStatus.WORK_IN_PROGRESS],
            ),
        )

    def test_private_branches(self):
        # The resulting list of merge proposals is filtered by the actual
        # proposals that the logged in user is able to see.
        proposal = self._make_merge_proposal("albert", "november", "work")
        # Mark the source branch private.
        proposal.source_branch.transitionToInformationType(
            InformationType.USERDATA,
            proposal.source_branch.owner,
            verify_policy=False,
        )
        self._make_merge_proposal("albert", "mike", "work")

        albert = getUtility(IPersonSet).getByName("albert")
        # Albert can see his private branch.
        self.assertEqual(
            ["~albert/mike/work", "~albert/november/work"],
            self._get_merge_proposals(albert, visible_by_user=albert),
        )
        # Anonymous people can't.
        self.assertEqual(
            ["~albert/mike/work"], self._get_merge_proposals(albert)
        )
        # Other people can't.
        self.assertEqual(
            ["~albert/mike/work"],
            self._get_merge_proposals(
                albert, visible_by_user=self.factory.makePerson()
            ),
        )
        # A branch subscribers can.
        subscriber = self.factory.makePerson()
        proposal.source_branch.subscribe(
            subscriber,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.NOEMAIL,
            subscriber,
        )
        self.assertEqual(
            ["~albert/mike/work", "~albert/november/work"],
            self._get_merge_proposals(albert, visible_by_user=subscriber),
        )

    def test_team_private_branches(self):
        # If both charles and albert are a member team xray, and albert
        # creates a branch in the team namespace, charles will be able to see
        # it.
        albert = self.factory.makePerson(name="albert")
        charles = self.factory.makePerson(name="charles")
        xray = self.factory.makeTeam(name="xray", owner=albert)
        xray.addMember(person=charles, reviewer=albert)

        proposal = self._make_merge_proposal(
            "xray", "november", "work", registrant=albert
        )
        # Mark the source branch private.
        proposal.source_branch.transitionToInformationType(
            InformationType.USERDATA,
            proposal.source_branch.owner,
            verify_policy=False,
        )

        november = getUtility(IProductSet).getByName("november")
        # The proposal is visible to charles.
        self.assertEqual(
            ["~xray/november/work"],
            self._get_merge_proposals(november, visible_by_user=charles),
        )
        # Not visible to anonymous people.
        self.assertEqual([], self._get_merge_proposals(november))
        # Not visible to non team members.
        self.assertEqual(
            [],
            self._get_merge_proposals(
                november, visible_by_user=self.factory.makePerson()
            ),
        )


class TestBranchMergeProposalDeletion(TestCaseWithFactory):
    """Deleting a branch merge proposal deletes relevant objects."""

    layer = DatabaseFunctionalLayer

    def test_deleteProposal_deletes_job(self):
        """Deleting a branch merge proposal deletes all related jobs."""
        proposal = self.factory.makeBranchMergeProposal()
        store = Store.of(proposal)
        job = MergeProposalNeedsReviewEmailJob.create(proposal)
        job_id = job.context.id
        login_person(proposal.registrant)
        proposal.deleteProposal()
        store.flush()
        store.invalidate()
        self.assertRaises(NotFoundError, BranchMergeProposalJob.get, job_id)


class TestBranchMergeProposalBugs(WithVCSScenarios, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.user = self.factory.makePerson()
        login_person(self.user)
        if self.git:
            self.hosting_fixture = self.useFixture(GitHostingFixture())

    def test_bugs(self):
        # bugs includes all linked bugs.
        bmp = self.makeBranchMergeProposal()
        self.assertEqual([], bmp.bugs)
        bugs = [self.factory.makeBug() for _ in range(2)]
        bmp.linkBug(bugs[0], bmp.registrant)
        self.assertEqual([bugs[0]], bmp.bugs)
        bmp.linkBug(bugs[1], bmp.registrant)
        self.assertContentEqual(bugs, bmp.bugs)
        bmp.unlinkBug(bugs[0], bmp.registrant)
        self.assertEqual([bugs[1]], bmp.bugs)
        bmp.unlinkBug(bugs[1], bmp.registrant)
        self.assertEqual([], bmp.bugs)

    def test_related_bugtasks_includes_source_bugtasks(self):
        # related_bugtasks includes bugtasks linked to the source branch in
        # the Bazaar case, or directly to the MP in the Git case.
        bmp = self.makeBranchMergeProposal()
        bug = self.factory.makeBug()
        bmp.linkBug(bug, bmp.registrant)
        self.assertEqual(bug.bugtasks, list(bmp.getRelatedBugTasks(self.user)))

    def test_related_bugtasks_excludes_private_bugs(self):
        # related_bugtasks ignores private bugs for non-authorised users.
        bmp = self.makeBranchMergeProposal()
        bug = self.factory.makeBug()
        bmp.linkBug(bug, bmp.registrant)
        person = self.factory.makePerson()
        with person_logged_in(person):
            private_bug = self.factory.makeBug(
                owner=person, information_type=InformationType.USERDATA
            )
            bmp.linkBug(private_bug, person)
            private_tasks = private_bug.bugtasks
        self.assertEqual(bug.bugtasks, list(bmp.getRelatedBugTasks(self.user)))
        all_bugtasks = list(bug.bugtasks)
        all_bugtasks.extend(private_tasks)
        self.assertEqual(all_bugtasks, list(bmp.getRelatedBugTasks(person)))

    def test_related_bugtasks_excludes_target_bugs(self):
        # related_bugtasks ignores bugs linked to the target branch.
        if self.git:
            self.skipTest("Only relevant for Bazaar.")
        bmp = self.makeBranchMergeProposal()
        bug = self.factory.makeBug()
        bmp.target_branch.linkBug(bug, bmp.registrant)
        self.assertEqual([], list(bmp.getRelatedBugTasks(self.user)))

    def test_related_bugtasks_excludes_mutual_bugs(self):
        # related_bugtasks ignores bugs linked to both branches.
        if self.git:
            self.skipTest("Only relevant for Bazaar.")
        bmp = self.makeBranchMergeProposal()
        bug = self.factory.makeBug()
        bmp.source_branch.linkBug(bug, bmp.registrant)
        bmp.target_branch.linkBug(bug, bmp.registrant)
        self.assertEqual([], list(bmp.getRelatedBugTasks(self.user)))

    def test__fetchRelatedBugIDsFromSource(self):
        # _fetchRelatedBugIDsFromSource makes a reasonable backend call and
        # parses commit messages.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        bugs = [self.factory.makeBug() for _ in range(3)]
        bmp = self.makeBranchMergeProposal()
        self.hosting_fixture.getLog.result = [
            {
                "sha1": bmp.source_git_commit_sha1,
                "message": "Commit 1\n\nLP: #%d" % bugs[0].id,
            },
            {
                "sha1": hashlib.sha1(b"1").hexdigest(),
                # Will not be matched.
                "message": "Commit 2; see LP #%d" % bugs[1].id,
            },
            {
                "sha1": hashlib.sha1(b"2").hexdigest(),
                "message": "Commit 3; LP: #%d" % bugs[2].id,
            },
            {
                "sha1": hashlib.sha1(b"3").hexdigest(),
                # Non-existent bug ID will not be returned.
                "message": "Non-existent bug; LP: #%d" % (bugs[2].id + 100),
            },
        ]
        related_bugs = removeSecurityProxy(bmp)._fetchRelatedBugIDsFromSource()
        path = "%s:%s" % (
            bmp.target_git_repository.getInternalPath(),
            bmp.source_git_repository.getInternalPath(),
        )
        self.assertEqual(
            [
                (
                    (path, bmp.source_git_commit_sha1),
                    {
                        "limit": 10,
                        "stop": bmp.target_git_commit_sha1,
                        "logger": None,
                    },
                )
            ],
            self.hosting_fixture.getLog.calls,
        )
        self.assertContentEqual([bugs[0].id, bugs[2].id], related_bugs)

    def _setUpLog(self, bugs):
        """Set up a fake log response referring to the given bugs."""
        self.hosting_fixture.getLog.result = [
            {
                "sha1": hashlib.sha1(str(i).encode()).hexdigest(),
                "message": "LP: #%d" % bug.id,
            }
            for i, bug in enumerate(bugs)
        ]
        self.hosting_fixture.memcache_fixture.clear()

    def test_updateRelatedBugsFromSource_no_links(self):
        # updateRelatedBugsFromSource does nothing if there are no related
        # bugs in either the database or the source branch.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        bmp = self.makeBranchMergeProposal()
        self._setUpLog([])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([], bmp.bugs)

    def test_updateRelatedBugsFromSource_new_links(self):
        # If the source branch has related bugs not yet reflected in the
        # database, updateRelatedBugsFromSource creates the links.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        bugs = [self.factory.makeBug() for _ in range(3)]
        bmp = self.makeBranchMergeProposal()
        self._setUpLog([bugs[0]])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([bugs[0]], bmp.bugs)
        self._setUpLog(bugs)
        bmp.updateRelatedBugsFromSource()
        self.assertContentEqual(bugs, bmp.bugs)

    def test_updateRelatedBugsFromSource_same_links(self):
        # If the database and the source branch list the same related bugs,
        # updateRelatedBugsFromSource does nothing.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        bug = self.factory.makeBug()
        bmp = self.makeBranchMergeProposal()
        self._setUpLog([bug])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([bug], bmp.bugs)
        # The second run is a no-op.
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([bug], bmp.bugs)

    def test_updateRelatedBugsFromSource_removes_old_links(self):
        # If the database records a source-branch-originating related bug
        # that is no longer listed by the source branch,
        # updateRelatedBugsFromSource removes the link.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        bug = self.factory.makeBug()
        bmp = self.makeBranchMergeProposal()
        self._setUpLog([bug])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([bug], bmp.bugs)
        self._setUpLog([])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([], bmp.bugs)

    def test_updateRelatedBugsFromSource_leaves_manual_links(self):
        # If a bug was linked to the merge proposal manually,
        # updateRelatedBugsFromSource leaves the link alone regardless of
        # whether it is listed by the source branch.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        bug = self.factory.makeBug()
        bmp = self.makeBranchMergeProposal()
        bmp.linkBug(bug)
        self._setUpLog([])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([bug], bmp.bugs)
        matches_expected_xref = MatchesDict(
            {("bug", str(bug.id)): ContainsDict({"metadata": Is(None)})}
        )
        self.assertThat(
            getUtility(IXRefSet).findFrom(
                ("merge_proposal", str(bmp.id)), types=["bug"]
            ),
            matches_expected_xref,
        )
        self._setUpLog([bug])
        self.assertThat(
            getUtility(IXRefSet).findFrom(
                ("merge_proposal", str(bmp.id)), types=["bug"]
            ),
            matches_expected_xref,
        )

    def test_updateRelatedBugsFromSource_honours_limit(self):
        # If the number of bugs to be linked exceeds the configured limit,
        # updateRelatedBugsFromSource only links that many bugs and logs an
        # OOPS.
        if not self.git:
            self.skipTest("Only relevant for Git.")
        self.pushConfig("codehosting", related_bugs_from_source_limit=3)
        bugs = [self.factory.makeBug() for _ in range(5)]
        bmp = self.makeBranchMergeProposal()
        self._setUpLog([bugs[0]])
        bmp.updateRelatedBugsFromSource()
        self.assertEqual([bugs[0]], bmp.bugs)
        self.assertEqual([], self.oopses)
        self._setUpLog(bugs)
        bmp.updateRelatedBugsFromSource()
        self.assertContentEqual(bugs[:3], bmp.bugs)
        self.assertEqual(1, len(self.oopses))
        self.assertEqual("TooManyRelatedBugs", self.oopses[0]["type"])


class TestBranchMergeProposalNominateReviewer(
    WithVCSScenarios, TestCaseWithFactory
):
    """Test that the appropriate vote references get created."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, user="test@canonical.com")
        if self.git:
            self.hosting_fixture = self.useFixture(GitHostingFixture())

    def test_notify_on_nominate(self):
        # Ensure that a notification is emitted on nomination.
        merge_proposal = self.makeBranchMergeProposal()
        login_person(merge_proposal.merge_source.owner)
        reviewer = self.factory.makePerson()
        result, events = self.assertNotifies(
            ReviewerNominatedEvent,
            False,
            merge_proposal.nominateReviewer,
            reviewer=reviewer,
            registrant=merge_proposal.merge_source.owner,
        )
        self.assertEqual(result, events[0].object)

    def test_notify_on_nominate_suppressed_if_requested(self):
        # Ensure that a notification is suppressed if notify listeners is set
        # to False.
        merge_proposal = self.makeBranchMergeProposal()
        login_person(merge_proposal.merge_source.owner)
        reviewer = self.factory.makePerson()
        self.assertNoNotification(
            merge_proposal.nominateReviewer,
            reviewer=reviewer,
            registrant=merge_proposal.merge_source.owner,
            _notify_listeners=False,
        )

    def test_one_initial_votes(self):
        """A new merge proposal has one vote of the default reviewer."""
        merge_proposal = self.makeBranchMergeProposal()
        self.assertEqual(1, len(list(merge_proposal.votes)))
        [vote] = list(merge_proposal.votes)
        self.assertEqual(merge_proposal.merge_target.owner, vote.reviewer)

    def makeProposalWithReviewer(
        self, reviewer=None, review_type=None, registrant=None, **kwargs
    ):
        """Make a proposal and request a review from reviewer.

        If no reviewer is passed in, make a reviewer.
        """
        if reviewer is None:
            reviewer = self.factory.makePerson()
        if registrant is None:
            registrant = self.factory.makePerson()
        merge_proposal = make_merge_proposal_without_reviewers(
            factory=self.factory,
            for_git=self.git,
            registrant=registrant,
            **kwargs,
        )
        login_person(merge_proposal.merge_source.owner)
        merge_proposal.nominateReviewer(
            reviewer=reviewer, registrant=registrant, review_type=review_type
        )
        return merge_proposal, reviewer

    def test_pending_review_registrant(self):
        # The registrant passed into the nominateReviewer call is the
        # registrant of the vote reference.
        registrant = self.factory.makePerson()
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            registrant=registrant
        )
        vote_reference = list(merge_proposal.votes)[0]
        self.assertEqual(registrant, vote_reference.registrant)

    def assertOneReviewPending(self, merge_proposal, reviewer, review_type):
        # Check that there is one and only one review pending with the
        # specified reviewer and review_type.
        votes = list(merge_proposal.votes)
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        if review_type is None:
            self.assertIs(None, vote_reference.review_type)
        else:
            self.assertEqual(review_type, vote_reference.review_type)
        self.assertIs(None, vote_reference.comment)

    def test_nominate_creates_reference(self):
        # A new vote reference is created when a reviewer is nominated.
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            review_type="general"
        )
        self.assertOneReviewPending(merge_proposal, reviewer, "general")

    def test_nominate_with_None_review_type(self):
        # Reviews nominated with a review type of None, make vote references
        # with a review_type of None.
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            review_type=None
        )
        self.assertOneReviewPending(merge_proposal, reviewer, None)

    def test_nominate_with_whitespace_review_type(self):
        # A review nominated with a review type that just contains whitespace
        # or the empty string, makes a vote reference with a review_type of
        # None.
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            review_type=""
        )
        self.assertOneReviewPending(merge_proposal, reviewer, None)
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            review_type="    "
        )
        self.assertOneReviewPending(merge_proposal, reviewer, None)
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            review_type="\t"
        )
        self.assertOneReviewPending(merge_proposal, reviewer, None)

    def test_nominate_multiple_with_different_types(self):
        # While an individual can only be requested to do one review
        # (test_nominate_updates_reference) a team can have multiple
        # nominations for different review types.
        reviewer = self.factory.makePerson()
        review_team = self.factory.makeTeam(owner=reviewer)
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            reviewer=review_team, review_type="general-1"
        )
        merge_proposal.nominateReviewer(
            reviewer=review_team,
            registrant=merge_proposal.registrant,
            review_type="general-2",
        )

        votes = list(merge_proposal.votes)
        self.assertEqual(
            ["general-1", "general-2"],
            sorted(review.review_type for review in votes),
        )

    def test_nominate_multiple_with_same_types(self):
        # There can be multiple reviews for a team with the same review_type.
        reviewer = self.factory.makePerson()
        review_team = self.factory.makeTeam(owner=reviewer)
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            reviewer=review_team, review_type="general"
        )
        merge_proposal.nominateReviewer(
            reviewer=review_team,
            registrant=merge_proposal.registrant,
            review_type="general",
        )

        votes = list(merge_proposal.votes)
        self.assertEqual(
            [(review_team, "general"), (review_team, "general")],
            [(review.reviewer, review.review_type) for review in votes],
        )

    def test_nominate_multiple_team_reviews_with_no_type(self):
        # There can be multiple reviews for a team with no review type set.
        reviewer = self.factory.makePerson()
        review_team = self.factory.makeTeam(owner=reviewer)
        merge_proposal, reviewer = self.makeProposalWithReviewer(
            reviewer=review_team, review_type=None
        )
        merge_proposal.nominateReviewer(
            reviewer=review_team,
            registrant=merge_proposal.registrant,
            review_type=None,
        )

        votes = list(merge_proposal.votes)
        self.assertEqual(
            [(review_team, None), (review_team, None)],
            [(review.reviewer, review.review_type) for review in votes],
        )

    def test_nominate_updates_reference(self):
        """The existing reference is updated on re-nomination."""
        merge_proposal = self.makeBranchMergeProposal()
        login_person(merge_proposal.merge_source.owner)
        reviewer = self.factory.makePerson()
        reference = merge_proposal.nominateReviewer(
            reviewer=reviewer,
            registrant=merge_proposal.merge_source.owner,
            review_type="General",
        )
        self.assertEqual("general", reference.review_type)
        merge_proposal.nominateReviewer(
            reviewer=reviewer,
            registrant=merge_proposal.merge_source.owner,
            review_type="Specific",
        )
        # Note we're using the reference from the first call
        self.assertEqual("specific", reference.review_type)

    def _check_mp_branch_visibility(self, branch, reviewer):
        # The reviewer is subscribed to the branch and can see it.
        sub = branch.getSubscription(reviewer)
        self.assertEqual(
            BranchSubscriptionNotificationLevel.NOEMAIL, sub.notification_level
        )
        self.assertEqual(BranchSubscriptionDiffSize.NODIFF, sub.max_diff_lines)
        self.assertEqual(CodeReviewNotificationLevel.FULL, sub.review_level)
        # The reviewer can see the branch.
        self.assertTrue(branch.visibleByUser(reviewer))
        if IBranch.providedBy(branch) and branch.stacked_on is not None:
            self._check_mp_branch_visibility(branch.stacked_on, reviewer)

    def _test_nominate_grants_visibility(self, reviewer):
        """Nominated reviewers can see the source and target branches."""
        owner = self.factory.makePerson()
        product = self.factory.makeProduct()
        # For bzr, we make a source branch stacked on a private one.
        # For git, we make the gitref itself private.
        if self.git:
            source_branch = self.makeBranch(
                product=product,
                owner=owner,
                information_type=InformationType.USERDATA,
            )
        else:
            base_branch = self.makeBranch(
                owner=owner,
                product=product,
                information_type=InformationType.USERDATA,
            )
            source_branch = self.makeBranch(
                stacked_on=base_branch, product=product, owner=owner
            )
        target_branch = self.makeBranch(
            owner=owner,
            product=product,
            information_type=InformationType.USERDATA,
        )
        login_person(owner)
        merge_proposal = self.makeBranchMergeProposal(
            source=source_branch, target=target_branch
        )
        # The reviewer can't see the source or target branches.
        self.assertFalse(source_branch.visibleByUser(reviewer))
        self.assertFalse(target_branch.visibleByUser(reviewer))
        merge_proposal.nominateReviewer(
            reviewer=reviewer, registrant=merge_proposal.merge_source.owner
        )
        for branch in [source_branch, target_branch]:
            self._check_mp_branch_visibility(branch, reviewer)

    def test_nominate_person_grants_visibility(self):
        reviewer = self.factory.makePerson()
        self._test_nominate_grants_visibility(reviewer)

    def test_nominate_team_grants_visibility(self):
        reviewer = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )
        self._test_nominate_grants_visibility(reviewer)

    def _assertVoteReference(self, votes, reviewer, comment):
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        self.assertEqual(reviewer, vote_reference.registrant)
        self.assertIsNone(vote_reference.review_type)
        self.assertEqual(comment, vote_reference.comment)

    def test_comment_with_vote_creates_reference(self):
        """A comment with a vote creates a vote reference."""
        reviewer = self.factory.makePerson()
        merge_proposal = self.makeBranchMergeProposal(
            reviewer=reviewer, registrant=reviewer
        )
        comment = merge_proposal.createComment(
            reviewer,
            "Message subject",
            "Message content",
            vote=CodeReviewVote.APPROVE,
        )
        votes = list(merge_proposal.votes)
        self._assertVoteReference(votes, reviewer, comment)

    def test_comment_without_a_vote_does_not_create_reference(self):
        """A comment with a vote creates a vote reference."""
        reviewer = self.factory.makePerson()
        merge_proposal = make_merge_proposal_without_reviewers(
            self.factory, for_git=self.git
        )
        merge_proposal.createComment(
            reviewer, "Message subject", "Message content"
        )
        self.assertEqual([], list(merge_proposal.votes))

    def test_second_vote_by_person_just_alters_reference(self):
        """A second vote changes the comment reference only."""
        reviewer = self.factory.makePerson()
        merge_proposal = self.makeBranchMergeProposal(
            reviewer=reviewer, registrant=reviewer
        )
        merge_proposal.createComment(
            reviewer,
            "Message subject",
            "Message content",
            vote=CodeReviewVote.DISAPPROVE,
        )
        comment2 = merge_proposal.createComment(
            reviewer,
            "Message subject",
            "Message content",
            vote=CodeReviewVote.APPROVE,
        )
        votes = list(merge_proposal.votes)
        self._assertVoteReference(votes, reviewer, comment2)

    def test_vote_by_nominated_reuses_reference(self):
        """A comment with a vote for a nominated reviewer alters reference."""
        reviewer = self.factory.makePerson()
        merge_proposal, ignore = self.makeProposalWithReviewer(
            reviewer=reviewer, review_type="general"
        )
        login(merge_proposal.merge_source.owner.preferredemail.email)
        comment = merge_proposal.createComment(
            reviewer,
            "Message subject",
            "Message content",
            vote=CodeReviewVote.APPROVE,
            review_type="general",
        )

        votes = list(merge_proposal.votes)
        self.assertEqual(1, len(votes))
        vote_reference = votes[0]
        self.assertEqual(reviewer, vote_reference.reviewer)
        self.assertEqual(merge_proposal.registrant, vote_reference.registrant)
        self.assertEqual("general", vote_reference.review_type)
        self.assertEqual(comment, vote_reference.comment)

    def test_claiming_team_review(self):
        # A person in a team claims a team review of the same type.
        reviewer = self.factory.makePerson()
        team = self.factory.makeTeam(owner=reviewer)
        merge_proposal, ignore = self.makeProposalWithReviewer(
            reviewer=team, review_type="general"
        )
        login(merge_proposal.merge_source.owner.preferredemail.email)
        [vote] = list(merge_proposal.votes)
        self.assertEqual(team, vote.reviewer)
        comment = merge_proposal.createComment(
            reviewer,
            "Message subject",
            "Message content",
            vote=CodeReviewVote.APPROVE,
            review_type="general",
        )
        self.assertEqual(reviewer, vote.reviewer)
        self.assertEqual("general", vote.review_type)
        self.assertEqual(comment, vote.comment)

    def test_claiming_tagless_team_review_with_tag(self):
        # A person in a team claims a team review of the same type, or if
        # there isn't a team review with that specified type, but there is a
        # team review that doesn't have a review type set, then claim that
        # one.
        reviewer = self.factory.makePerson()
        team = self.factory.makeTeam(owner=reviewer)
        merge_proposal = self.makeBranchMergeProposal(reviewer=team)
        login(merge_proposal.merge_source.owner.preferredemail.email)
        [vote] = list(merge_proposal.votes)
        self.assertEqual(team, vote.reviewer)
        comment = merge_proposal.createComment(
            reviewer,
            "Message subject",
            "Message content",
            vote=CodeReviewVote.APPROVE,
            review_type="general",
        )
        self.assertEqual(reviewer, vote.reviewer)
        self.assertEqual("general", vote.review_type)
        self.assertEqual(comment, vote.comment)
        # Still only one vote.
        self.assertEqual(1, len(list(merge_proposal.votes)))

    def test_preloadDataForBMPs_maps_votes_to_proposals(self):
        # When called on multiple merge proposals, preloadDataForBMPs
        # assigns votes to the correct proposals.
        merge_proposal_1, reviewer_1 = self.makeProposalWithReviewer(
            set_state=BranchMergeProposalStatus.MERGED
        )
        merge_proposal_2, _ = self.makeProposalWithReviewer(
            target=merge_proposal_1.merge_target,
            source=merge_proposal_1.merge_source,
        )
        merge_proposal_2.nominateReviewer(
            reviewer=reviewer_1, registrant=merge_proposal_2.registrant
        )
        votes_1 = list(merge_proposal_1.votes)
        self.assertEqual(1, len(votes_1))
        votes_2 = list(merge_proposal_2.votes)
        self.assertEqual(2, len(votes_2))
        BranchMergeProposal.preloadDataForBMPs(
            [
                removeSecurityProxy(merge_proposal_1),
                removeSecurityProxy(merge_proposal_2),
            ],
            reviewer_1,
        )
        self.assertContentEqual(votes_1, merge_proposal_1.votes)
        self.assertContentEqual(votes_2, merge_proposal_2.votes)


class TestBranchMergeProposalResubmit(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_resubmit(self):
        """Ensure that resubmit performs its basic function.

        It should create a new merge proposal, mark the old one as superseded,
        and set its status to superseded.
        """
        bmp1 = self.factory.makeBranchMergeProposal()
        login_person(bmp1.registrant)
        bmp2 = bmp1.resubmit(bmp1.registrant)
        self.assertNotEqual(bmp1.id, bmp2.id)
        self.assertEqual(
            bmp1.queue_status, BranchMergeProposalStatus.SUPERSEDED
        )
        self.assertEqual(
            bmp2.queue_status, BranchMergeProposalStatus.NEEDS_REVIEW
        )
        self.assertEqual(bmp2, bmp1.superseded_by)
        self.assertEqual(bmp1.source_branch, bmp2.source_branch)
        self.assertEqual(bmp1.target_branch, bmp2.target_branch)
        self.assertEqual(bmp1.prerequisite_branch, bmp2.prerequisite_branch)

    def test_resubmit_re_requests_review(self):
        """Resubmit should request new reviews.

        Both those who have already reviewed and those who have been nominated
        to review should be requested to review the new proposal.
        """
        bmp1 = self.factory.makeBranchMergeProposal()
        nominee = self.factory.makePerson()
        login_person(bmp1.registrant)
        bmp1.nominateReviewer(nominee, bmp1.registrant, "nominee")
        reviewer = self.factory.makePerson()
        bmp1.createComment(
            reviewer,
            "I like",
            vote=CodeReviewVote.APPROVE,
            review_type="specious",
        )
        bmp2 = bmp1.resubmit(bmp1.registrant)
        self.assertEqual(
            {
                (bmp1.target_branch.owner, None),
                (nominee, "nominee"),
                (reviewer, "specious"),
            },
            {(vote.reviewer, vote.review_type) for vote in bmp2.votes},
        )

    def test_resubmit_no_reviewers(self):
        """Resubmitting a proposal with no reviewers should work."""
        bmp = make_merge_proposal_without_reviewers(self.factory)
        with person_logged_in(bmp.registrant):
            bmp.resubmit(bmp.registrant)

    def test_resubmit_changes_branches(self):
        """Resubmit changes branches, if specified."""
        original = self.factory.makeBranchMergeProposal()
        self.useContext(person_logged_in(original.registrant))
        branch_target = original.source_branch.target
        new_source = self.factory.makeBranchTargetBranch(branch_target)
        new_target = self.factory.makeBranchTargetBranch(branch_target)
        new_prerequisite = self.factory.makeBranchTargetBranch(branch_target)
        revised = original.resubmit(
            original.registrant, new_source, new_target, new_prerequisite
        )
        self.assertEqual(new_source, revised.source_branch)
        self.assertEqual(new_target, revised.target_branch)
        self.assertEqual(new_prerequisite, revised.prerequisite_branch)

    def test_resubmit_changes_description(self):
        """Resubmit changes description, if specified."""
        original = self.factory.makeBranchMergeProposal()
        self.useContext(person_logged_in(original.registrant))
        revised = original.resubmit(original.registrant, description="foo")
        self.assertEqual("foo", revised.description)

    def test_resubmit_preserves_commit(self):
        """Resubmit preserves commit message."""
        original = self.factory.makeBranchMergeProposal()
        self.useContext(person_logged_in(original.registrant))
        revised = original.resubmit(original.registrant)
        self.assertEqual(original.commit_message, revised.commit_message)

    def test_resubmit_breaks_link(self):
        """Resubmit breaks link, if specified."""
        original = self.factory.makeBranchMergeProposal()
        self.useContext(person_logged_in(original.registrant))
        original.resubmit(original.registrant, break_link=True)
        self.assertIs(None, original.superseded_by)

    def test_resubmit_with_active_retains_state(self):
        """Resubmit does not change proposal if an active proposal exists."""
        first_mp = self.factory.makeBranchMergeProposal()
        with person_logged_in(first_mp.registrant):
            first_mp.rejectBranch(first_mp.target_branch.owner, "a")
            second_mp = self.factory.makeBranchMergeProposal(
                source_branch=first_mp.source_branch,
                target_branch=first_mp.target_branch,
            )
            expected_exc = ExpectedException(
                BranchMergeProposalExists,
                "There is already a branch merge"
                " proposal registered for branch .* to land on .* that is"
                " still active.",
            )
            with expected_exc:
                first_mp.resubmit(first_mp.registrant)
            self.assertEqual(
                second_mp, expected_exc.caught_exc.existing_proposal
            )
            self.assertEqual(
                BranchMergeProposalStatus.REJECTED, first_mp.queue_status
            )

    def test_resubmit_on_inactive_retains_state_new_branches(self):
        """Resubmit with branches doesn't change proposal."""
        first_mp = self.factory.makeBranchMergeProposal()
        with person_logged_in(first_mp.registrant):
            first_mp.rejectBranch(first_mp.target_branch.owner, "a")
            second_mp = self.factory.makeBranchMergeProposal()
            with ExpectedException(BranchMergeProposalExists, ""):
                first_mp.resubmit(
                    first_mp.registrant,
                    second_mp.source_branch,
                    second_mp.target_branch,
                )
            self.assertEqual(
                BranchMergeProposalStatus.REJECTED, first_mp.queue_status
            )


class TestUpdatePreviewDiff(TestCaseWithFactory):
    """Test the updatePreviewDiff method of BranchMergeProposal."""

    layer = LaunchpadFunctionalLayer

    def _updatePreviewDiff(self, merge_proposal):
        # Update the preview diff for the merge proposal.
        diff_text = (
            "=== modified file 'sample.py'\n"
            "--- sample\t2009-01-15 23:44:22 +0000\n"
            "+++ sample\t2009-01-29 04:10:57 +0000\n"
            "@@ -19,7 +19,7 @@\n"
            " from zope.interface import implementer\n"
            "\n"
            " from storm.expr import Desc, Join, LeftJoin\n"
            "-from storm.references import Reference\n"
            "+from storm.locals import Int, Reference\n"
            " from sqlobject import ForeignKey, IntCol\n"
            "\n"
            " from lp.services.config import config\n"
        )
        diff_stat = {"sample": (1, 1)}
        login_person(merge_proposal.registrant)
        merge_proposal.updatePreviewDiff(diff_text, "source_id", "target_id")
        # Have to commit the transaction to make the Librarian file
        # available.
        transaction.commit()
        return diff_text, diff_stat

    def test_new_diff(self):
        # Test that both the PreviewDiff and the Diff get created.
        merge_proposal = self.factory.makeBranchMergeProposal()
        diff_text, diff_stat = self._updatePreviewDiff(merge_proposal)
        self.assertEqual(diff_text, merge_proposal.preview_diff.text)
        self.assertEqual(diff_stat, merge_proposal.preview_diff.diffstat)

    def test_update_diff(self):
        # Test that both the PreviewDiff and the Diff get updated.
        merge_proposal = self.factory.makeBranchMergeProposal()
        login_person(merge_proposal.registrant)
        diff_bytes = "".join(unified_diff("", "random text"))
        merge_proposal.updatePreviewDiff(diff_bytes, "a", "b")
        transaction.commit()
        # Extract the primary key ids for the preview diff and the diff to
        # show that we are not reusing the objects.
        preview_diff_id = removeSecurityProxy(merge_proposal.preview_diff).id
        diff_id = removeSecurityProxy(merge_proposal.preview_diff).diff_id
        diff_text, diff_stat = self._updatePreviewDiff(merge_proposal)
        self.assertEqual(diff_text, merge_proposal.preview_diff.text)
        self.assertEqual(diff_stat, merge_proposal.preview_diff.diffstat)
        self.assertNotEqual(
            preview_diff_id,
            removeSecurityProxy(merge_proposal.preview_diff).id,
        )
        self.assertNotEqual(
            diff_id, removeSecurityProxy(merge_proposal.preview_diff).diff_id
        )


class TestScheduleDiffUpdates(TestCaseWithFactory):
    """Test scheduling of diff updates."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.job_source = removeSecurityProxy(
            getUtility(IBranchMergeProposalJobSource)
        )

    def test_scheduleDiffUpdates_bzr(self):
        bmp = self.factory.makeBranchMergeProposal()
        self.factory.makeRevisionsForBranch(bmp.source_branch)
        self.factory.makeRevisionsForBranch(bmp.target_branch)
        [job] = self.job_source.iterReady()
        removeSecurityProxy(job).job._status = JobStatus.COMPLETED
        self.assertEqual([], list(self.job_source.iterReady()))
        with person_logged_in(bmp.merge_target.owner):
            bmp.scheduleDiffUpdates()
        [job] = self.job_source.iterReady()
        self.assertIsInstance(job, UpdatePreviewDiffJob)

    def test_scheduleDiffUpdates_git(self):
        bmp = self.factory.makeBranchMergeProposalForGit()
        [job] = self.job_source.iterReady()
        removeSecurityProxy(job).job._status = JobStatus.COMPLETED
        self.assertEqual([], list(self.job_source.iterReady()))
        with person_logged_in(bmp.merge_target.owner):
            bmp.scheduleDiffUpdates()
        [job] = self.job_source.iterReady()
        self.assertIsInstance(job, UpdatePreviewDiffJob)

    def test_getLatestDiffUpdateJob(self):
        complete_date = datetime.now(timezone.utc)

        bmp = self.factory.makeBranchMergeProposal()
        failed_job = removeSecurityProxy(bmp.getLatestDiffUpdateJob())
        failed_job.job._status = JobStatus.FAILED
        failed_job.job.date_finished = complete_date
        completed_job = UpdatePreviewDiffJob.create(bmp)
        completed_job.job._status = JobStatus.COMPLETED
        completed_job.job.date_finished = complete_date - timedelta(seconds=10)
        result = removeSecurityProxy(bmp.getLatestDiffUpdateJob())
        self.assertEqual(failed_job.job_id, result.job_id)

    def test_ggetLatestDiffUpdateJob_correct_branch(self):
        complete_date = datetime.now(timezone.utc)

        main_bmp = self.factory.makeBranchMergeProposal()
        second_bmp = self.factory.makeBranchMergeProposal()
        failed_job = removeSecurityProxy(second_bmp.getLatestDiffUpdateJob())
        failed_job.job._status = JobStatus.FAILED
        failed_job.job.date_finished = complete_date
        completed_job = removeSecurityProxy(main_bmp.getLatestDiffUpdateJob())
        completed_job.job._status = JobStatus.COMPLETED
        completed_job.job.date_finished = complete_date - timedelta(seconds=10)
        result = removeSecurityProxy(main_bmp.getLatestDiffUpdateJob())
        self.assertEqual(completed_job.job_id, result.job_id)

    def test_getLatestDiffUpdateJob_without_completion_date(self):
        bmp = self.factory.makeBranchMergeProposal()
        failed_job = removeSecurityProxy(bmp.getLatestDiffUpdateJob())
        failed_job.job._status = JobStatus.FAILED
        result = bmp.getLatestDiffUpdateJob()
        self.assertTrue(result)
        self.assertIsNone(result.job.date_finished)


class TestNextPreviewDiffJob(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_returns_none_if_job_not_pending(self):
        """Jobs are shown while pending."""
        bmp = self.factory.makeBranchMergeProposal()
        job = bmp.next_preview_diff_job
        self.assertEqual(job, bmp.next_preview_diff_job)
        job.start()
        self.assertEqual(job, bmp.next_preview_diff_job)
        job.fail()
        self.assertIs(None, bmp.next_preview_diff_job)

    def makeBranchMergeProposalNoPending(self):
        bmp = self.factory.makeBranchMergeProposal()
        bmp.next_preview_diff_job.start()
        bmp.next_preview_diff_job.complete()
        return bmp

    def test_returns_update_preview_diff_job(self):
        """UpdatePreviewDiffJobs can be returned."""
        bmp = self.makeBranchMergeProposalNoPending()
        updatejob = UpdatePreviewDiffJob.create(bmp)
        Store.of(updatejob.context).flush()
        self.assertEqual(updatejob, bmp.next_preview_diff_job)

    def test_returns_first_job(self):
        """First-created job is returned."""
        bmp = self.makeBranchMergeProposalNoPending()
        updatejob = UpdatePreviewDiffJob.create(bmp)
        UpdatePreviewDiffJob.create(bmp)
        self.assertEqual(updatejob, bmp.next_preview_diff_job)

    def test_does_not_return_jobs_for_other_proposals(self):
        """Jobs for other merge proposals are not returned."""
        bmp = self.factory.makeBranchMergeProposal()
        bmp.next_preview_diff_job.start()
        bmp.next_preview_diff_job.complete()
        self.factory.makeBranchMergeProposal()
        self.assertIs(None, bmp.next_preview_diff_job)


class TestRevisionEndDate(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_revision_end_date_active(self):
        # An active merge proposal will have None as an end date.
        bmp = self.factory.makeBranchMergeProposal()
        self.assertIs(None, bmp.revision_end_date)

    def test_revision_end_date_merged(self):
        # An merged proposal will have the date merged as an end date.
        bmp = self.factory.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.MERGED
        )
        self.assertEqual(bmp.date_merged, bmp.revision_end_date)

    def test_revision_end_date_rejected(self):
        # An rejected proposal will have the date reviewed as an end date.
        bmp = self.factory.makeBranchMergeProposal(
            set_state=BranchMergeProposalStatus.REJECTED
        )
        self.assertEqual(bmp.date_reviewed, bmp.revision_end_date)


class TestGetRevisionsSinceReviewStart(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def assertRevisionGroups(self, bmp, expected_groups):
        """Get the groups for the merge proposal and check them."""
        revision_groups = list(bmp.getRevisionsSinceReviewStart())
        self.assertEqual(expected_groups, revision_groups)

    def test_getRevisionsSinceReviewStart_no_revisions(self):
        # If there have been no revisions pushed since the start of the
        # review, the method returns an empty list.
        bmp = self.factory.makeBranchMergeProposal()
        self.assertRevisionGroups(bmp, [])

    def test_getRevisionsSinceReviewStart_groups(self):
        # Revisions that were scanned at the same time have the same
        # date_created.  These revisions are grouped together.
        review_date = datetime(2009, 9, 10, tzinfo=timezone.utc)
        bmp = self.factory.makeBranchMergeProposal(date_created=review_date)
        with person_logged_in(bmp.registrant):
            bmp.requestReview(review_date)
        revision_date = review_date + timedelta(days=1)
        revisions = []
        for _ in range(2):
            revisions.append(
                add_revision_to_branch(
                    self.factory, bmp.source_branch, revision_date
                )
            )
            revisions.append(
                add_revision_to_branch(
                    self.factory, bmp.source_branch, revision_date
                )
            )
            revision_date += timedelta(days=1)
        expected_groups = [
            [revisions[0], revisions[1], revisions[2], revisions[3]]
        ]
        self.assertRevisionGroups(bmp, expected_groups)

    def test_getRevisionsSinceReviewStart_groups_with_comments(self):
        # Revisions that were scanned at the same time have the same
        # date_created.  These revisions are grouped together.
        bmp = self.factory.makeBranchMergeProposal(
            date_created=self.factory.getUniqueDate()
        )
        revisions = []
        revisions.append(
            add_revision_to_branch(
                self.factory, bmp.source_branch, self.factory.getUniqueDate()
            )
        )
        revisions.append(
            add_revision_to_branch(
                self.factory, bmp.source_branch, self.factory.getUniqueDate()
            )
        )
        with person_logged_in(self.factory.makePerson()):
            self.factory.makeCodeReviewComment(
                merge_proposal=bmp, date_created=self.factory.getUniqueDate()
            )
        revisions.append(
            add_revision_to_branch(
                self.factory, bmp.source_branch, self.factory.getUniqueDate()
            )
        )

        expected_groups = [[revisions[0], revisions[1]], [revisions[2]]]
        self.assertRevisionGroups(bmp, expected_groups)


class TestBranchMergeProposalGetIncrementalDiffs(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_getIncrementalDiffs(self):
        """getIncrementalDiffs returns the requested values or None.

        None is returned if there is no IncrementalDiff for the requested
        revision pair and branch_merge_proposal.
        """
        bmp = self.factory.makeBranchMergeProposal()
        diff1 = self.factory.makeIncrementalDiff(merge_proposal=bmp)
        diff2 = self.factory.makeIncrementalDiff(merge_proposal=bmp)
        diff3 = self.factory.makeIncrementalDiff()
        result = bmp.getIncrementalDiffs(
            [
                (diff1.old_revision, diff1.new_revision),
                (diff2.old_revision, diff2.new_revision),
                # Wrong merge proposal
                (diff3.old_revision, diff3.new_revision),
                # Mismatched revisions
                (diff1.old_revision, diff2.new_revision),
            ]
        )
        self.assertEqual([diff1, diff2, None, None], result)

    def test_getIncrementalDiffs_respects_input_order(self):
        """The order of the output follows the input order."""
        bmp = self.factory.makeBranchMergeProposal()
        diff1 = self.factory.makeIncrementalDiff(merge_proposal=bmp)
        diff2 = self.factory.makeIncrementalDiff(merge_proposal=bmp)
        result = bmp.getIncrementalDiffs(
            [
                (diff1.old_revision, diff1.new_revision),
                (diff2.old_revision, diff2.new_revision),
            ]
        )
        self.assertEqual([diff1, diff2], result)
        result = bmp.getIncrementalDiffs(
            [
                (diff2.old_revision, diff2.new_revision),
                (diff1.old_revision, diff1.new_revision),
            ]
        )
        self.assertEqual([diff2, diff1], result)


class TestGetUnlandedSourceBranchRevisions(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_getUnlandedSourceBranchRevisions(self):
        # Revisions in the source branch but not in the target are shown
        # as unlanded.
        bmp = self.factory.makeBranchMergeProposal()
        self.factory.makeRevisionsForBranch(bmp.source_branch, count=5)
        r1 = bmp.source_branch.getBranchRevision(sequence=1)
        initial_revisions = list(bmp.getUnlandedSourceBranchRevisions())
        self.assertEqual(5, len(initial_revisions))
        self.assertIn(r1, initial_revisions)
        # If we push one of the revisions into the target, it disappears
        # from the unlanded list.
        bmp.target_branch.createBranchRevision(1, r1.revision)
        partial_revisions = list(bmp.getUnlandedSourceBranchRevisions())
        self.assertEqual(4, len(partial_revisions))
        self.assertNotIn(r1, partial_revisions)


class TestBranchMergeProposalInlineComments(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        # Create a testing IPerson, IPreviewDiff and IBranchMergeProposal
        # for tests. Log in as the testing IPerson.
        self.person = self.factory.makePerson()
        self.bmp = self.factory.makeBranchMergeProposal(registrant=self.person)
        self.previewdiff = self.factory.makePreviewDiff(
            merge_proposal=self.bmp
        )
        login_person(self.person)

    def getInlineComments(self, previewdiff_id=None):
        # Return all published inline comments for the context BMP
        if previewdiff_id is None:
            previewdiff_id = self.previewdiff.id

        return self.bmp.getInlineComments(previewdiff_id)

    def getDraft(self, previewdiff_id=None, person=None):
        # Return all draft inline comments for the context BMP
        if previewdiff_id is None:
            previewdiff_id = self.previewdiff.id
        if person is None:
            person = self.person

        return self.bmp.getDraftInlineComments(previewdiff_id, person)

    def test_save_drafts(self):
        # Draft inline comments, passed as a dictionary keyed by diff line
        # number, can be stored for the current user using
        # `IBranchMergeProposal.saveDraftInlineComment`.
        # see `ICoreReviewInlineCommentSet.ensureDraft` for details.
        self.bmp.saveDraftInlineComment(
            previewdiff_id=self.previewdiff.id,
            person=self.person,
            comments={"10": "DrAfT", "15": "CoMmEnTs"},
        )
        self.assertEqual(2, len(self.getDraft()))

    def test_save_drafts_no_previewdiff(self):
        # `saveDraftInlineComment` raises `DiffNotFound` if there is
        # no context `PreviewDiff` created on the given timestamp.
        kwargs = {
            "person": self.person,
            "comments": {"10": "No diff"},
            "previewdiff_id": 1000,
        }
        self.assertRaises(
            DiffNotFound, self.bmp.saveDraftInlineComment, **kwargs
        )

    def test_publish(self):
        # Existing (draft) inline comments can be published associated
        # with an `ICodeReviewComment`.
        self.bmp.createComment(
            owner=self.bmp.registrant,
            subject="Testing!",
            previewdiff_id=self.previewdiff.id,
            inline_comments={"11": "foo"},
        )
        self.assertEqual(1, len(self.getInlineComments()))
        self.assertEqual(1, self.bmp.all_comments.count())

    def test_publish_no_subject_on_comment(self):
        # Not passing in a Subject when creating a comment
        # does not fail and the MP comment is created
        # with the default subject.
        self.bmp.createComment(
            owner=self.bmp.registrant,
            previewdiff_id=self.previewdiff.id,
            inline_comments=None,
            content="Test comment",
        )
        self.assertEqual(1, self.bmp.all_comments.count())
        comment = self.bmp.all_comments[0]
        self.assertEqual("Test comment", comment.message.chunks[0].content)
        self.assertEqual(
            "Re: [Merge] %s into %s"
            % (
                self.bmp.source_branch.bzr_identity,
                self.bmp.target_branch.bzr_identity,
            ),
            comment.message.subject,
        )

    def test_publish_no_inlines(self):
        # Suppressing 'inline_comments' does not result in any inline
        # comments, but the MP comment itself is created.
        self.bmp.createComment(
            owner=self.bmp.registrant,
            subject="Testing!",
            previewdiff_id=self.previewdiff.id,
            inline_comments=None,
        )
        self.assertEqual(0, len(self.getInlineComments()))
        self.assertEqual(1, self.bmp.all_comments.count())

    def test_publish_empty(self):
        # Passing an empty 'inline_comments' dictionary does not result
        # in any inline comments published.
        self.bmp.createComment(
            owner=self.bmp.registrant,
            subject="Testing!",
            previewdiff_id=self.previewdiff.id,
            inline_comments={},
        )
        self.assertEqual(0, len(self.getInlineComments()))
        self.assertEqual(1, self.bmp.all_comments.count())

    def test_publish_no_previewdiff_id(self):
        # If previewdiff ID is not given and there are
        # inline comments to publish, an `AssertioError` is raised
        kwargs = {
            "owner": self.bmp.registrant,
            "subject": "Testing!",
            "previewdiff_id": None,
            "inline_comments": {"10": "foo"},
        }
        self.assertRaises(AssertionError, self.bmp.createComment, **kwargs)

    def test_publish_no_diff_found(self):
        # If previewdiff ID does not correspond to
        # a context `PreviewDiff`, an `DiffNotFound` is raised.
        kwargs = {
            "owner": self.bmp.registrant,
            "subject": "Testing!",
            "previewdiff_id": 1000,
            "inline_comments": {"10": "foo"},
        }
        self.assertRaises(DiffNotFound, self.bmp.createComment, **kwargs)

    def test_get_inlinecomments(self):
        # Published inline comments for an specific `PreviewDiff` can
        # be retrieved via `getInlineComments`.
        comment = self.bmp.createComment(
            owner=self.bmp.registrant,
            subject="Testing!",
            previewdiff_id=self.previewdiff.id,
            inline_comments={"11": "eleven"},
        )

        published_comments = self.bmp.getInlineComments(self.previewdiff.id)
        self.assertEqual(1, len(published_comments))
        [published_comment] = published_comments

        # A 'published' inline comment is represented by a list of 4
        # elements (line_number, author, comment, timestamp).
        self.assertEqual(
            {
                "line_number": "11",
                "person": self.person,
                "text": "eleven",
                "date": comment.date_created,
            },
            published_comment,
        )

    def test_get_draft(self):
        # Draft inline comments for an specific `PreviewDiff` and
        # `IPerson` (author) can be retrieved via `getDraftInlineComments`.
        self.bmp.saveDraftInlineComment(
            previewdiff_id=self.previewdiff.id,
            person=self.person,
            comments={"10": "ten"},
        )

        draft_comments = self.bmp.getDraftInlineComments(
            self.previewdiff.id, self.person
        )

        # A 'draft' inline comment is represented by a dictionary (object)
        # with keyed by line numbers (as text) and the corresponding
        # comment as value, exactly as it was sent to LP.
        self.assertEqual({"10": "ten"}, draft_comments)

    def test_get_draft_different_users(self):
        #  Different users have different draft comments.
        self.bmp.saveDraftInlineComment(
            previewdiff_id=self.previewdiff.id,
            person=self.person,
            comments={"1": "zoing!"},
        )

        someone_else = self.factory.makePerson()
        self.bmp.saveDraftInlineComment(
            previewdiff_id=self.previewdiff.id,
            person=someone_else,
            comments={"1": "boing!"},
        )

        self.assertEqual({"1": "zoing!"}, self.getDraft())
        self.assertEqual({"1": "boing!"}, self.getDraft(person=someone_else))

    def test_get_diff_not_found(self):
        # Trying to fetch inline comments (draft or published) with a
        # ID that does not correspond to a context `PreviewDiff`
        # raises `DiffNotFound`.
        self.assertRaises(DiffNotFound, self.bmp.getInlineComments, 1000)

        self.assertRaises(
            DiffNotFound, self.bmp.getDraftInlineComments, 1000, self.person
        )


class TestWebservice(WebServiceTestCase):
    """Tests for the webservice."""

    def test_getMergeProposals_with_merged_revnos(self):
        """Specifying merged revnos selects the correct merge proposal."""
        registrant = self.factory.makePerson()
        mp = self.factory.makeBranchMergeProposal(registrant=registrant)
        launchpad = launchpadlib_for(
            "test",
            registrant,
            service_root=self.layer.appserver_root_url("api"),
        )

        with person_logged_in(registrant):
            mp.markAsMerged(merged_revno=123)
            transaction.commit()
            target = ws_object(launchpad, mp.target_branch)
            mp = ws_object(launchpad, mp)
        self.assertEqual(
            [mp],
            list(
                target.getMergeProposals(
                    status=["Merged"], merged_revnos=[123]
                )
            ),
        )

    def test_getRelatedBugTasks_bzr(self):
        """Test the getRelatedBugTasks API for Bazaar."""
        db_bmp = self.factory.makeBranchMergeProposal()
        db_bug = self.factory.makeBug()
        db_bmp.source_branch.linkBug(db_bug, db_bmp.registrant)
        transaction.commit()
        bmp = self.wsObject(db_bmp)
        bugtask = self.wsObject(db_bug.default_bugtask)
        self.assertEqual([bugtask], list(bmp.getRelatedBugTasks()))

    def test_getRelatedBugTasks_git(self):
        """Test the getRelatedBugTasks API for Git."""
        db_bmp = self.factory.makeBranchMergeProposalForGit()
        db_bug = self.factory.makeBug()
        db_bmp.linkBug(db_bug, db_bmp.registrant)
        transaction.commit()
        bmp = self.wsObject(db_bmp)
        bugtask = self.wsObject(db_bug.default_bugtask)
        self.assertEqual([bugtask], list(bmp.getRelatedBugTasks()))

    def test_setStatus_invalid_transition(self):
        """Emit BadRequest when an invalid transition is requested."""
        bmp = self.factory.makeBranchMergeProposal()
        with person_logged_in(bmp.registrant):
            bmp.resubmit(bmp.registrant)
        transaction.commit()
        ws_bmp = self.wsObject(bmp, user=bmp.target_branch.owner)
        with ExpectedException(
            BadRequest,
            "(.|\n)*Invalid state transition for merge proposal(.|\n)*",
        ):
            ws_bmp.setStatus(status="Approved")

    def test_previewdiff_with_null_diffstat(self):
        # A previewdiff with an empty diffstat doesn't crash when fetched.
        previewdiff = self.factory.makePreviewDiff()
        removeSecurityProxy(previewdiff).diff.diffstat = None
        user = previewdiff.branch_merge_proposal.target_branch.owner
        ws_previewdiff = self.wsObject(previewdiff, user=user)
        self.assertIsNone(ws_previewdiff.diffstat)

    def test_saveDraftInlineComment_with_no_previewdiff(self):
        # Failure on context diff mismatch.
        bmp = self.factory.makeBranchMergeProposal()
        ws_bmp = self.wsObject(bmp, user=bmp.target_branch.owner)

        self.assertRaises(
            BadRequest,
            ws_bmp.saveDraftInlineComment,
            previewdiff_id=1000,
            comments={},
        )

    def test_saveDraftInlineComment(self):
        # Creating and retrieving draft inline comments.
        # These operations require an logged in user with permission
        # to view the BMP.
        previewdiff = self.factory.makePreviewDiff()
        proposal = previewdiff.branch_merge_proposal

        ws_bmp = self.wsObject(proposal, user=proposal.target_branch.owner)
        ws_bmp.saveDraftInlineComment(
            previewdiff_id=previewdiff.id, comments={"2": "foo"}
        )
        transaction.commit()

        draft_comments = ws_bmp.getDraftInlineComments(
            previewdiff_id=previewdiff.id
        )
        self.assertEqual({"2": "foo"}, draft_comments)

    def test_getInlineComment(self):
        # Publishing and retrieving inline comments.
        previewdiff = self.factory.makePreviewDiff()
        proposal = previewdiff.branch_merge_proposal
        user = proposal.target_branch.owner

        # Publishing inline-comments requires an logged in user with
        # lp.Edit permission on the MP, in this case, the branch owner.
        ws_bmp = self.wsObject(proposal, user=user)
        review_comment = ws_bmp.createComment(
            subject="Testing!",
            previewdiff_id=previewdiff.id,
            inline_comments={"2": "foo"},
        )
        transaction.commit()

        # Retrieving published inline comments requires only lp.View
        # permission on the MP, since the testing MP is public, even
        # an anonymous user can view published inline comments.
        launchpad = launchpadlib_for(
            "test", None, service_root=self.layer.appserver_root_url("api")
        )
        anon_bmp = ws_object(launchpad, proposal)
        inline_comments = anon_bmp.getInlineComments(
            previewdiff_id=previewdiff.id
        )

        self.assertEqual(1, len(inline_comments))
        [inline_comment] = inline_comments

        self.assertEqual("2", inline_comment.get("line_number"))
        self.assertEqual(user.name, inline_comment.get("person").get("name"))
        self.assertEqual("foo", inline_comment.get("text"))
        comment_date = review_comment.date_created.isoformat()
        self.assertEqual(comment_date, inline_comment.get("date"))


class TestBranchMergeProposalApproval(WithVCSScenarios, TestCaseWithFactory):
    """Test the isApproved method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        team = self.factory.makeTeam()
        target = self.makeBranch(owner=team)

        self.registrant = self.factory.makePerson(member_of=[team])
        self.reviewer = self.factory.makePerson(member_of=[team])

        self.proposal = self.makeBranchMergeProposal(
            target=target, registrant=self.registrant
        )

    def test_isApproved_no_votes(self):
        # A proposal with no votes is not approved
        self.assertFalse(self.proposal.isApproved())

    def test_isApproved_with_untrusted_approval(self):
        # A proposal with one untrusted approval is not approved
        untrusted_reviewer = self.factory.makePerson()
        with person_logged_in(untrusted_reviewer):
            self.proposal.createComment(
                owner=untrusted_reviewer,
                vote=CodeReviewVote.APPROVE,
            )
        self.assertFalse(self.proposal.isApproved())

    def test_isApproved_with_trusted_approval(self):
        # A proposal with one trusted approval is approved
        with person_logged_in(self.reviewer):
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.APPROVE,
            )
        self.assertTrue(self.proposal.isApproved())

    def test_isApproved_approval_after_disapproval(self):
        # If a person approves after disapproving a proposal, it counts having
        # approved it
        with person_logged_in(self.reviewer):
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.DISAPPROVE,
            )
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.APPROVE,
            )
        self.assertTrue(self.proposal.isApproved())

    def test_isApproved_disapproval_after_approval(self):
        # If a person disapproves after approving a proposal, it counts having
        # disapproved it
        with person_logged_in(self.reviewer):
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.APPROVE,
            )
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.DISAPPROVE,
            )
        self.assertFalse(self.proposal.isApproved())


class TestBranchMergeProposalCIChecks(TestCaseWithFactory):
    """Test the CIChecksPassed method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.proposal = self.factory.makeBranchMergeProposalForGit()

    def test_CIChecksPassed_bazaar_repo(self):
        # No CI checks on bazaar repos
        proposal = self.factory.makeBranchMergeProposal()
        self.assertTrue(proposal.CIChecksPassed())

    def test_CIChecksPassed_no_reports(self):
        # If there are no CI reports, checks are considered passed
        self.assertTrue(self.proposal.CIChecksPassed())

    def test_CIChecksPassed_success(self):
        # If the latest CI report is successful, checks are passed
        self.factory.makeRevisionStatusReport(
            git_repository=self.proposal.source_git_repository,
            commit_sha1=self.proposal.source_git_commit_sha1,
            result=RevisionStatusResult.SUCCEEDED,
        )
        self.assertTrue(self.proposal.CIChecksPassed())

    def test_CIChecksPassed_failure(self):
        # If the latest CI report is a failure, checks are not passed
        self.factory.makeRevisionStatusReport(
            git_repository=self.proposal.source_git_repository,
            commit_sha1=self.proposal.source_git_commit_sha1,
            result=RevisionStatusResult.FAILED,
        )
        self.assertFalse(self.proposal.CIChecksPassed())

    def test_CIChecksPassed_running(self):
        # If the latest CI report is a failure, checks are not passed
        self.factory.makeRevisionStatusReport(
            git_repository=self.proposal.source_git_repository,
            commit_sha1=self.proposal.source_git_commit_sha1,
            result=RevisionStatusResult.RUNNING,
        )
        self.assertFalse(self.proposal.CIChecksPassed())


class TestBranchMergeProposalConflicts(WithVCSScenarios, TestCaseWithFactory):
    """Test the hasNoConflicts method of BranchMergeProposal."""

    # layer = DatabaseFunctionalLayer
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.proposal = self.makeBranchMergeProposal()

    def test_hasNoConflicts_no_diff(self):
        # If there is no preview diff, there are no conflicts
        self.assertTrue(self.proposal.hasNoConflicts())

    def test_hasNoConflicts_no_conflicts(self):
        # If the preview diff has no conflicts, hasNoConflicts returns False
        self.factory.makePreviewDiff(merge_proposal=self.proposal)
        transaction.commit()
        self.assertTrue(self.proposal.hasNoConflicts())

    def test_hasNoConflicts_with_conflicts(self):
        # If the preview diff has conflicts, hasNoConflicts returns False
        self.factory.makePreviewDiff(
            merge_proposal=self.proposal,
            conflicts="Merge conflicts found",
        )
        transaction.commit()
        self.assertFalse(self.proposal.hasNoConflicts())


class TestBranchMergeProposalPrerequisites(TestCaseWithFactory):
    """Test hasNoPendingPrerequisite method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()

    def test_hasNoPendingPrerequisite_no_prerequisite(self):
        # If there is no prerequisite branch, there are no pending
        # prerequisites
        proposal = self.factory.makeBranchMergeProposalForGit()
        self.assertTrue(proposal.hasNoPendingPrerequisite())

    def test_hasNoPendingPrerequisite_merged(self):
        # If the prerequisite has been merged, there are no pending
        # prerequisites
        merged_prerequisite = self.factory.makeGitRefs()[0]
        proposal = self.factory.makeBranchMergeProposalForGit(
            prerequisite_ref=merged_prerequisite
        )

        mock_requestMergesResponse = {
            proposal.target_git_commit_sha1: merged_prerequisite.commit_sha1
        }
        self.useFixture(GitHostingFixture(merges=mock_requestMergesResponse))
        self.assertTrue(proposal.hasNoPendingPrerequisite())

    def test_hasNoPendingPrerequisite_not_merged(self):
        # If the prerequisite has not been merged, there are pending
        # prerequisites
        prerequisite = self.factory.makeGitRefs()[0]
        proposal = self.factory.makeBranchMergeProposalForGit(
            prerequisite_ref=prerequisite
        )

        self.useFixture(GitHostingFixture())
        self.assertFalse(proposal.hasNoPendingPrerequisite())

    def test_hasNoPendingPrerequisite_no_prerequisits_bazaar(self):
        # If there is no prerequisite branch, there are no pending
        # prerequisites
        proposal = self.factory.makeBranchMergeProposal()
        self.assertTrue(proposal.hasNoPendingPrerequisite())

    def test_hasNoPendingPrerequisite_bazaar(self):
        # If there is a prerequisite branch in a bazaar MP, raise not
        # Implemented
        prerequisite = self.factory.makeBranch()
        proposal = self.factory.makeBranchMergeProposal(
            prerequisite_branch=prerequisite
        )
        self.assertIsNone(proposal.hasNoPendingPrerequisite())


class TestBranchMergeProposalDiffStatus(WithVCSScenarios, TestCaseWithFactory):
    """Test the diffIsUpToDate method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.proposal = self.makeBranchMergeProposal()

    def test_diffIsUpToDate_no_job(self):
        # If there is no pending diff job, the diff is up to date
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.assertTrue(self.proposal.diffIsUpToDate())

    def test_diffIsUpToDate_with_job(self):
        # If there is a pending diff job, the diff is not up to date
        self.assertFalse(self.proposal.diffIsUpToDate())


class TestBranchMergeProposalMergeCriteria(
    WithVCSScenarios, TestCaseWithFactory
):
    """Test the checkMergeCriteria method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()

        team = self.factory.makeTeam()
        self.target = self.makeBranch(owner=team)
        self.reviewer = self.factory.makePerson(member_of=[team])

        self.proposal = self.makeBranchMergeProposal(target=self.target)
        self.useFixture(GitHostingFixture())

        self.expected_criteria = {
            "is_in_progress": {"passed": True, "is_required": False},
            "has_no_conflicts": {"passed": True, "is_required": True},
            "diff_is_up_to_date": {"passed": True, "is_required": False},
            "is_approved": {"passed": True, "is_required": False},
            "CI_checks_passed": {"passed": True, "is_required": False},
            "has_no_pending_prerequisite": {
                "passed": True,
                "is_required": False,
            },
        }

    def test_checkMergeCriteria_all_passed(self):
        # If all criteria are met, checkMergeCriteria returns a tuple with True
        # and a dict stating which criteria checks ran and all passed
        with person_logged_in(self.reviewer):
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.APPROVE,
            )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        can_merge, can_force, criteria = self.proposal.checkMergeCriteria()
        self.assertTrue(can_merge)
        self.assertTrue(can_force)
        self.assertDictEqual(self.expected_criteria, criteria)

    def test_checkMergeCriteria_some_failed(self):
        # If some criteria are not met, checkMergeCriteria returns a tuple with
        # False, and a dict stating which criteria failed.
        can_merge, can_force, criteria = self.proposal.checkMergeCriteria()
        self.assertFalse(can_merge)
        self.assertTrue(can_force)
        expected_criteria = self.expected_criteria
        expected_criteria["diff_is_up_to_date"] = {
            "passed": False,
            "is_required": False,
            "error": "New changes were pushed too recently",
        }
        expected_criteria["is_approved"] = {
            "passed": False,
            "is_required": False,
            "error": "Proposal has not been approved",
        }
        self.assertDictEqual(expected_criteria, criteria)

    def test_checkMergeCriteria_with_prerequisite(self):
        # When there is a prerequisite branch, its criteria is included

        prerequisite = self.makeBranch(
            same_target_as=self.proposal.merge_target
        )
        proposal = self.makeBranchMergeProposal(
            target=self.proposal.merge_target,
            prerequisite=prerequisite,
        )

        with person_logged_in(self.reviewer):
            proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.APPROVE,
            )
        proposal.next_preview_diff_job.start()
        proposal.next_preview_diff_job.complete()

        # Different response for git and bazaar
        expected_criteria = self.expected_criteria
        if self.git:
            expected_can_merge = False
            expected_can_force = True
            expected_criteria["has_no_pending_prerequisite"] = {
                "passed": False,
                "is_required": False,
                "error": "Prerequisite branch not merged",
            }
        else:
            expected_can_merge = True
            expected_can_force = True
            expected_criteria["has_no_pending_prerequisite"] = {
                "passed": None,
                "is_required": False,
                "error": "Not implemented",
            }
        can_merge, can_force, criteria = proposal.checkMergeCriteria()
        self.assertEqual(expected_can_merge, can_merge)
        self.assertEqual(expected_can_force, can_force)
        self.assertDictEqual(expected_criteria, criteria)

    def test_getMergeCriteria_initial_state(self):
        # The getMergeCriteria method returns a dict with can_be_merged and
        # the merge criteria statuses
        expected_criteria = {
            "can_be_merged": False,
            "can_be_force_merged": True,
            "criteria": {
                "is_in_progress": {"passed": True, "is_required": False},
                "has_no_conflicts": {"passed": True, "is_required": True},
                "diff_is_up_to_date": {
                    "passed": False,
                    "is_required": False,
                    "error": "New changes were pushed too recently",
                },
                "is_approved": {
                    "passed": False,
                    "is_required": False,
                    "error": "Proposal has not been approved",
                },
                "CI_checks_passed": {"passed": True, "is_required": False},
                "has_no_pending_prerequisite": {
                    "passed": True,
                    "is_required": False,
                },
            },
        }

        criteria = self.proposal.getMergeCriteria()
        self.assertDictEqual(expected_criteria, criteria)

    def test_getMergeCriteria_all_passed(self):
        # When all criteria are met, can_be_merged is True
        with person_logged_in(self.reviewer):
            self.proposal.createComment(
                owner=self.reviewer,
                vote=CodeReviewVote.APPROVE,
            )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()

        response = self.proposal.getMergeCriteria()
        expected_response = {
            "can_be_merged": True,
            "can_be_force_merged": True,
            "criteria": self.expected_criteria,
        }
        self.assertDictEqual(expected_response, response)

    def test_getMergeCriteria_with_prerequisite(self):
        # When there is a prerequisite branch, its criteria is included

        prerequisite = self.makeBranch(
            same_target_as=self.proposal.merge_target
        )
        proposal = self.makeBranchMergeProposal(
            target=self.proposal.merge_target,
            prerequisite=prerequisite,
        )

        expected_response = {
            "can_be_merged": False,
            "can_be_force_merged": True,
            "criteria": {
                "is_in_progress": {"passed": True, "is_required": False},
                "has_no_conflicts": {"passed": True, "is_required": True},
                "diff_is_up_to_date": {
                    "passed": False,
                    "is_required": False,
                    "error": "New changes were pushed too recently",
                },
                "is_approved": {
                    "passed": False,
                    "is_required": False,
                    "error": "Proposal has not been approved",
                },
                "CI_checks_passed": {"passed": True, "is_required": False},
                "has_no_pending_prerequisite": {
                    "passed": False,
                    "is_required": False,
                    "error": "Prerequisite branch not merged",
                },
            },
        }

        if not self.git:
            expected_response["criteria"]["has_no_pending_prerequisite"] = {
                "passed": None,
                "is_required": False,
                "error": "Not implemented",
            }

        response = proposal.getMergeCriteria()
        self.assertDictEqual(expected_response, response)


class TestBranchMergeProposalMergePermissions(TestCaseWithFactory):
    """Test the personCanMerge method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        self.proposal = self.factory.makeBranchMergeProposalForGit()
        self.useFixture(GitHostingFixture())

    def test_personCanMerge_no_permission(self):
        # A person without push permission cannot merge
        proposal = removeSecurityProxy(self.proposal)
        self.assertFalse(proposal.personCanMerge(self.person))

    def test_personCanMerge_with_permission(self):
        # A person with push permission can merge
        proposal = removeSecurityProxy(self.proposal)
        rule = removeSecurityProxy(
            self.factory.makeGitRule(repository=proposal.target_git_repository)
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=self.person, can_create=True, can_push=True
        )
        self.assertTrue(proposal.personCanMerge(self.person))

    def test_personCanMerge_bazaar(self):
        # Check checking permissions for merging bazaar repo raises error
        proposal = removeSecurityProxy(self.factory.makeBranchMergeProposal())
        self.assertRaises(
            NotImplementedError,
            proposal.personCanMerge,
            self.person,
        )

    def test_canIMerge_no_permission(self):
        # Check that canIMerge endpoint is exposed and returns False if user
        # has no merge permissions

        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PUBLIC
        )
        with person_logged_in(self.person):
            proposal_url = api_url(self.proposal)

        response = self.webservice.named_get(
            proposal_url,
            "canIMerge",
            api_version="devel",
        )
        self.assertEqual(200, response.status)
        self.assertFalse(response.jsonBody())

    def test_canIMerge_with_permission(self):
        # Check that canIMerge endpoint is exposed and returns True if user
        # has merge permissions

        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PUBLIC
        )
        with person_logged_in(self.person):
            proposal_url = api_url(self.proposal)

        rule = removeSecurityProxy(
            self.factory.makeGitRule(
                repository=removeSecurityProxy(
                    self.proposal
                ).target_git_repository
            )
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=self.person, can_create=True, can_push=True
        )

        response = self.webservice.named_get(
            proposal_url,
            "canIMerge",
            api_version="devel",
        )
        self.assertEqual(200, response.status)
        self.assertTrue(response.jsonBody())


class TestBranchMergeProposalMerge(TestCaseWithFactory):
    """Test the requestMerge method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.hosting_fixture = self.useFixture(GitHostingFixture())
        self.useFixture(
            FeatureFixture({PROPOSAL_MERGE_ENABLED_FEATURE_FLAG: "on"})
        )

        self.proposal = removeSecurityProxy(
            self.factory.makeBranchMergeProposalForGit()
        )

        self.person = self.factory.makePerson()
        self.reviewer = self.proposal.target_git_repository.owner

        rule = removeSecurityProxy(
            self.factory.makeGitRule(
                repository=self.proposal.target_git_repository
            )
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=self.person, can_create=True, can_push=True
        )

    def test_merge_feature_flag(self):
        # Without feature flag enabled, merge fails

        self.useFixture(
            FeatureFixture({PROPOSAL_MERGE_ENABLED_FEATURE_FLAG: ""})
        )

        self.assertRaises(
            BranchMergeProposalFeatureDisabled,
            self.proposal.merge,
            self.person,
        )

    def test_merge_success(self):
        # Same repo merges work similarly to cross-repo merges

        repository = self.proposal.target_git_repository
        [source_ref, target_ref] = self.factory.makeGitRefs(
            paths=["refs/heads/source", "refs/heads/target"],
            repository=repository,
        )
        proposal = removeSecurityProxy(
            self.factory.makeBranchMergeProposalForGit(
                source_ref=source_ref,
                target_ref=target_ref,
            )
        )

        proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        proposal.next_preview_diff_job.start()
        proposal.next_preview_diff_job.complete()

        with person_logged_in(self.person):
            proposal.merge(self.person)
            self.assertEqual(
                BranchMergeProposalStatus.MERGED,
                proposal.queue_status,
            )

        self.assertIsNotNone(proposal.target_git_repository.getLatestScanJob())

    def test_cross_repo_merge_success(self):
        # A successful merge request updates the proposal status

        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()

        with person_logged_in(self.person):
            self.proposal.merge(self.person)
            self.assertEqual(
                BranchMergeProposalStatus.MERGED,
                self.proposal.queue_status,
            )

    def test_force_merge(self):
        # Force merge skips checking for certain criteria (e.g. approval)
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()

        with person_logged_in(self.person):
            # Fails without force=True
            self.assertRaises(
                BranchMergeProposalNotMergeable,
                self.proposal.merge,
                self.person,
            )

            # Succeeds with force=True
            self.proposal.merge(self.person, force=True)
            self.assertEqual(
                BranchMergeProposalStatus.MERGED,
                self.proposal.queue_status,
            )

    def test_merge_success_commit_message(self):
        # Successful merge with an commit message

        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.proposal.commit_message = "Old commit message"

        with person_logged_in(self.person):
            self.proposal.merge(
                self.person,
                commit_message="New commit message",
            )
            self.assertEqual(
                BranchMergeProposalStatus.MERGED,
                self.proposal.queue_status,
            )

        # Refresh from the database to ensure we are checking the latest state
        self.proposal = Store.of(self.proposal).get(
            BranchMergeProposal, self.proposal.id
        )
        self.assertEqual("New commit message", self.proposal.commit_message)

    def test_merge_unsuccessful_commit_message(self):
        # Unsuccessful merge with an commit message doesn't override message

        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.proposal.commit_message = "Old commit message"

        self.hosting_fixture.merge.failure = BranchMergeProposalMergeFailed(
            "Merge proposal failed to merge"
        )

        with person_logged_in(self.person):
            self.assertRaises(
                BranchMergeProposalMergeFailed,
                self.proposal.merge,
                self.person,
                commit_message="New commit message",
            )

        # Refresh from the database to ensure we are checking the latest state
        self.proposal = Store.of(self.proposal).get(
            BranchMergeProposal, self.proposal.id
        )
        self.assertEqual(self.proposal.commit_message, "Old commit message")

    def test_merge_no_permission(self):
        # A person without permission cannot request a merge
        person = self.factory.makePerson()
        self.assertRaises(
            Unauthorized,
            self.proposal.merge,
            person,
        )

    def test_merge_not_mergeable(self):
        # A proposal that doesn't meet merge criteria cannot be merged
        self.assertRaises(
            BranchMergeProposalNotMergeable,
            self.proposal.merge,
            self.person,
        )

    def test_merge_bazaar_not_supported(self):
        # Bazaar branches are not supported
        proposal = removeSecurityProxy(self.factory.makeBranchMergeProposal())
        self.assertRaises(
            NotImplementedError,
            proposal.merge,
            self.person,
        )

    def test_merge_turnip_failure(self):
        # Test merge failed from git hosting system

        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()

        self.hosting_fixture.merge.failure = BranchMergeProposalMergeFailed(
            "Merge proposal failed to merge"
        )

        with person_logged_in(self.person):
            self.assertRaises(
                BranchMergeProposalMergeFailed,
                self.proposal.merge,
                self.person,
            )

    def test_merge_already_merged(self):
        # Test if proposal had already been merged previously, we still mark
        # it as merged with the correct merge_revsision_id and merge_type

        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()

        self.hosting_fixture.merge.result = {
            "merge_commit": "fake-sha1",
            "previously_merged": True,
        }

        with person_logged_in(self.person):
            self.proposal.merge(self.person)
            self.assertEqual(
                BranchMergeProposalStatus.MERGED,
                self.proposal.queue_status,
            )
            self.assertEqual("fake-sha1", self.proposal.merged_revision_id)
            self.assertEqual(MergeType.UNKNOWN, self.proposal.merge_type)

    def test_merge_already_merged_with_merge_commit(self):
        # Test that if proposal had already been merged previously, we don't
        # overwrite the merge_revision_id or the merge_type

        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()

        with person_logged_in(self.person):
            self.proposal.merge(self.person)
            self.assertEqual("fake-sha1", self.proposal.merged_revision_id)

        self.proposal.setAsWorkInProgress()

        self.hosting_fixture.merge.result = {
            "merge_commit": "new-sha1",
            "previously_merged": True,
        }

        with person_logged_in(self.person):
            self.proposal.merge(self.person)
            self.assertEqual(
                BranchMergeProposalStatus.MERGED,
                self.proposal.queue_status,
            )
            self.assertEqual("fake-sha1", self.proposal.merged_revision_id)
            self.assertEqual(MergeType.REGULAR_MERGE, self.proposal.merge_type)


class TestBranchMergeProposalRequestMerge(TestCaseWithFactory):
    """Test the request_merge method of BranchMergeProposal."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.hosting_fixture = self.useFixture(GitHostingFixture())
        self.useFixture(
            FeatureFixture({PROPOSAL_MERGE_ENABLED_FEATURE_FLAG: "on"})
        )

        self.proposal = removeSecurityProxy(
            self.factory.makeBranchMergeProposalForGit()
        )

        self.person = self.factory.makePerson()
        self.reviewer = self.proposal.target_git_repository.owner

        rule = removeSecurityProxy(
            self.factory.makeGitRule(
                repository=self.proposal.target_git_repository
            )
        )
        self.factory.makeGitRuleGrant(
            rule=rule, grantee=self.person, can_create=True, can_push=True
        )

    def test_request_merge_feature_flag(self):
        self.useFixture(
            FeatureFixture({PROPOSAL_MERGE_ENABLED_FEATURE_FLAG: ""})
        )
        self.assertRaises(
            BranchMergeProposalFeatureDisabled,
            self.proposal.request_merge,
            self.person,
        )

    def test_request_merge_success(self):
        repository = self.proposal.target_git_repository
        [source_ref, target_ref] = self.factory.makeGitRefs(
            paths=["refs/heads/source", "refs/heads/target"],
            repository=repository,
        )
        proposal = removeSecurityProxy(
            self.factory.makeBranchMergeProposalForGit(
                source_ref=source_ref,
                target_ref=target_ref,
            )
        )
        proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        proposal.next_preview_diff_job.start()
        proposal.next_preview_diff_job.complete()
        with person_logged_in(self.person):
            result = proposal.request_merge(self.person)
            self.assertEqual("Merge successfully queued", result)

    def test_request_cross_repo_merge_success(self):
        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        with person_logged_in(self.person):
            result = self.proposal.request_merge(self.person)
            self.assertEqual("Merge successfully queued", result)

    def test_request_force_merge(self):
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        with person_logged_in(self.person):
            self.assertRaises(
                BranchMergeProposalNotMergeable,
                self.proposal.request_merge,
                self.person,
            )
            result = self.proposal.request_merge(self.person, force=True)
            self.assertEqual("Merge successfully queued", result)

    def test_request_merge_success_commit_message(self):
        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.proposal.commit_message = "Old commit message"
        with person_logged_in(self.person):
            result = self.proposal.request_merge(
                self.person,
                commit_message="New commit message",
            )
            self.assertEqual("Merge successfully queued", result)
        self.proposal = Store.of(self.proposal).get(
            BranchMergeProposal, self.proposal.id
        )
        self.assertEqual("Old commit message", self.proposal.commit_message)

    def test_request_merge_unsuccessful_commit_message(self):
        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.proposal.commit_message = "Old commit message"
        self.hosting_fixture.request_merge.failure = (
            BranchMergeProposalMergeFailed("Merge proposal failed to merge")
        )
        with person_logged_in(self.person):
            self.assertRaises(
                BranchMergeProposalMergeFailed,
                self.proposal.request_merge,
                self.person,
                commit_message="New commit message",
            )
        self.proposal = Store.of(self.proposal).get(
            BranchMergeProposal, self.proposal.id
        )
        self.assertEqual(self.proposal.commit_message, "Old commit message")

    def test_request_merge_no_permission(self):
        person = self.factory.makePerson()
        self.assertRaises(
            Unauthorized,
            self.proposal.request_merge,
            person,
        )

    def test_request_merge_not_mergeable(self):
        self.assertRaises(
            BranchMergeProposalNotMergeable,
            self.proposal.request_merge,
            self.person,
        )

    def test_request_merge_bazaar_not_supported(self):
        proposal = removeSecurityProxy(self.factory.makeBranchMergeProposal())
        self.assertRaises(
            NotImplementedError,
            proposal.request_merge,
            self.person,
        )

    def test_request_merge_turnip_failure(self):
        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.hosting_fixture.request_merge.failure = (
            BranchMergeProposalMergeFailed("Merge proposal failed to merge")
        )
        with person_logged_in(self.person):
            self.assertRaises(
                BranchMergeProposalMergeFailed,
                self.proposal.request_merge,
                self.person,
            )

    def test_request_merge_already_merged(self):
        self.proposal.createComment(
            owner=self.reviewer,
            vote=CodeReviewVote.APPROVE,
        )
        self.proposal.next_preview_diff_job.start()
        self.proposal.next_preview_diff_job.complete()
        self.hosting_fixture.request_merge.result = {
            "queued": False,
            "already_merged": True,
        }
        with person_logged_in(self.person):
            result = self.proposal.request_merge(self.person)
            self.assertEqual(
                "Proposal already merged, waiting for rescan",
                result,
            )


load_tests = load_tests_apply_scenarios
