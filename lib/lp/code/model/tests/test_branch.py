# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Branches."""

from datetime import datetime, timedelta, timezone

import transaction
from breezy.branch import Branch
from breezy.bzr.bzrdir import BzrDir
from breezy.revision import NULL_REVISION
from breezy.url_policy_open import BadUrl
from storm.exceptions import LostObjectError
from storm.locals import Store
from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools import ExpectedException
from testtools.matchers import Not, PathExists
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp import _
from lp.app.enums import (
    PRIVATE_INFORMATION_TYPES,
    PUBLIC_INFORMATION_TYPES,
    InformationType,
)
from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.blueprints.enums import NewSpecificationDefinitionStatus
from lp.blueprints.interfaces.specification import ISpecificationSet
from lp.blueprints.model.specificationbranch import SpecificationBranch
from lp.bugs.interfaces.bug import CreateBugParams, IBugSet
from lp.bugs.model.bugbranch import BugBranch
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.bzr import BranchFormat, ControlFormat, RepositoryFormat
from lp.code.enums import (
    BranchLifecycleStatus,
    BranchSubscriptionNotificationLevel,
    BranchType,
    CodeReviewNotificationLevel,
)
from lp.code.errors import (
    AlreadyLatestFormat,
    BranchCreatorNotMemberOfOwnerTeam,
    BranchCreatorNotOwner,
    BranchFileNotFound,
    BranchTargetError,
    CannotDeleteBranch,
    CannotUpgradeNonHosted,
    InvalidBranchMergeProposal,
    UpgradePending,
)
from lp.code.interfaces.branch import DEFAULT_BRANCH_STATUS_IN_LISTING, IBranch
from lp.code.interfaces.branchjob import (
    IBranchScanJobSource,
    IBranchUpgradeJobSource,
)
from lp.code.interfaces.branchlookup import IBranchLookup
from lp.code.interfaces.branchmergeproposal import (
    BRANCH_MERGE_PROPOSAL_FINAL_STATES as FINAL_STATES,
)
from lp.code.interfaces.branchmergeproposal import IBranchMergeProposalGetter
from lp.code.interfaces.branchnamespace import (
    IBranchNamespacePolicy,
    IBranchNamespaceSet,
)
from lp.code.interfaces.branchrevision import IBranchRevision
from lp.code.interfaces.codehosting import branch_id_alias
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.linkedbranch import ICanHasLinkedBranch
from lp.code.interfaces.seriessourcepackagebranch import (
    IFindOfficialBranchLinks,
)
from lp.code.model.branch import (
    BranchSet,
    ClearDependentBranch,
    ClearOfficialPackageBranch,
    ClearSeriesBranch,
    DeleteCodeImport,
    DeletionCallable,
    DeletionOperation,
    update_trigger_modified_fields,
)
from lp.code.model.branchjob import (
    BranchJob,
    BranchJobType,
    BranchScanJob,
    ReclaimBranchSpaceJob,
)
from lp.code.model.branchrevision import BranchRevision
from lp.code.model.codereviewcomment import CodeReviewComment
from lp.code.model.revision import Revision
from lp.code.tests.helpers import BranchHostingFixture, add_revision_to_branch
from lp.codehosting.vfs.branchfs import get_real_branch_path
from lp.registry.enums import (
    BranchSharingPolicy,
    PersonVisibility,
    TeamMembershipPolicy,
)
from lp.registry.errors import CannotChangeInformationType
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactSource,
    IAccessPolicyArtifactSource,
    IAccessPolicySource,
)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.sourcepackage import SourcePackage
from lp.registry.tests.test_accesspolicy import get_policies_for_artifact
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.job.tests import block_on_job, monitor_celery
from lp.services.osutils import override_environ
from lp.services.propertycache import clear_property_cache
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import IOpenLaunchBag, OAuthPermission
from lp.testing import (
    ANONYMOUS,
    TestCase,
    TestCaseWithFactory,
    WebServiceTestCase,
    admin_logged_in,
    api_url,
    celebrity_logged_in,
    login,
    login_person,
    logout,
    person_logged_in,
    run_with_login,
)
from lp.testing.dbuser import dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import (
    CeleryBranchWriteJobLayer,
    CeleryBzrsyncdJobLayer,
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
    ZopelessAppServerLayer,
)
from lp.testing.pages import webservice_for_person


def create_knit(test_case):
    db_branch, tree = test_case.create_branch_and_tree(format="knit")
    with person_logged_in(db_branch.owner):
        db_branch.branch_format = BranchFormat.BZR_BRANCH_5
        db_branch.repository_format = RepositoryFormat.BZR_KNIT_1
    return db_branch, tree


class TestCodeImport(TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        login("test@canonical.com")
        self.factory = LaunchpadObjectFactory()

    def test_branchCodeImport(self):
        """Ensure the codeImport property works correctly."""
        code_import = self.factory.makeCodeImport()
        branch = code_import.branch
        self.assertEqual(code_import, branch.code_import)
        getUtility(ICodeImportSet).delete(code_import)
        clear_property_cache(branch)
        self.assertIsNone(branch.code_import)


class TestBranchChanged(TestCaseWithFactory):
    """Tests for `IBranch.branchChanged`."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.arbitrary_formats = (
            ControlFormat.BZR_METADIR_1,
            BranchFormat.BZR_BRANCH_6,
            RepositoryFormat.BZR_CHK_2A,
        )

    def test_branchChanged_sets_last_mirrored_id(self):
        # branchChanged sets the last_mirrored_id attribute on the branch.
        revid = self.factory.getUniqueString()
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.branchChanged("", revid, *self.arbitrary_formats)
        self.assertEqual(revid, branch.last_mirrored_id)

    def test_branchChanged_sets_stacked_on(self):
        # branchChanged sets the stacked_on attribute based on the unique_name
        # passed in.
        branch = self.factory.makeAnyBranch()
        stacked_on = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.branchChanged(
            stacked_on.unique_name, "", *self.arbitrary_formats
        )
        self.assertEqual(stacked_on, branch.stacked_on)

    def test_branchChanged_sets_stacked_on_branch_id_alias(self):
        # branchChanged sets the stacked_on attribute based on the id of the
        # branch if it is valid.
        branch = self.factory.makeAnyBranch()
        stacked_on = self.factory.makeAnyBranch()
        login_person(branch.owner)
        stacked_on_location = branch_id_alias(stacked_on)
        branch.branchChanged(stacked_on_location, "", *self.arbitrary_formats)
        self.assertEqual(stacked_on, branch.stacked_on)

    def test_branchChanged_unsets_stacked_on(self):
        # branchChanged clears the stacked_on attribute on the branch if '' is
        # passed in as the stacked_on location.
        branch = self.factory.makeAnyBranch()
        removeSecurityProxy(branch).stacked_on = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.branchChanged("", "", *self.arbitrary_formats)
        self.assertIs(None, branch.stacked_on)

    def test_branchChanged_sets_last_mirrored(self):
        # branchChanged sets the last_mirrored attribute on the branch to the
        # current time.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.branchChanged("", "", *self.arbitrary_formats)
        self.assertSqlAttributeEqualsDate(branch, "last_mirrored", UTC_NOW)

    def test_branchChanged_records_bogus_stacked_on_url(self):
        # If a bogus location is passed in as the stacked_on parameter,
        # mirror_status_message is set to indicate the problem and stacked_on
        # set to None.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.branchChanged("~does/not/exist", "", *self.arbitrary_formats)
        self.assertIs(None, branch.stacked_on)
        self.assertTrue("~does/not/exist" in branch.mirror_status_message)

    def test_branchChanged_clears_mirror_status_message_if_no_error(self):
        # branchChanged() clears any error that's currently mentioned in
        # mirror_status_message.
        branch = self.factory.makeAnyBranch()
        removeSecurityProxy(branch).mirror_status_message = "foo"
        login_person(branch.owner)
        branch.branchChanged("", "", *self.arbitrary_formats)
        self.assertIs(None, branch.mirror_status_message)

    def test_branchChanged_creates_scan_job(self):
        # branchChanged() creates a scan job for the branch.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))
        branch.branchChanged("", "rev1", *self.arbitrary_formats)
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(1, len(jobs))

    def test_branchChanged_doesnt_create_scan_job_for_noop_change(self):
        # branchChanged() doesn't create a scan job if the tip revision id
        # hasn't changed.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        removeSecurityProxy(branch).last_mirrored_id = "rev1"
        removeSecurityProxy(branch).last_scanned_id = "rev1"
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))
        branch.branchChanged("", "rev1", *self.arbitrary_formats)
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))

    def test_branchChanged_creates_scan_job_for_broken_scan(self):
        # branchChanged() if the last_scanned_id is different to the newly
        # changed revision, then a scan job is created.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        removeSecurityProxy(branch).last_mirrored_id = "rev1"
        removeSecurityProxy(branch).last_scanned_id = "old"
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(0, len(jobs))
        branch.branchChanged("", "rev1", *self.arbitrary_formats)
        jobs = list(getUtility(IBranchScanJobSource).iterReady())
        self.assertEqual(1, len(jobs))

    def test_branchChanged_packs_format(self):
        # branchChanged sets the branch_format etc attributes to the passed in
        # values.
        branch = self.factory.makeAnyBranch()
        login_person(branch.owner)
        branch.branchChanged(
            "",
            "rev1",
            ControlFormat.BZR_METADIR_1,
            BranchFormat.BZR_BRANCH_6,
            RepositoryFormat.BZR_KNITPACK_1,
        )
        login(ANONYMOUS)
        self.assertEqual(
            (
                ControlFormat.BZR_METADIR_1,
                BranchFormat.BZR_BRANCH_6,
                RepositoryFormat.BZR_KNITPACK_1,
            ),
            (
                branch.control_format,
                branch.branch_format,
                branch.repository_format,
            ),
        )


class TestBranchJobViaCelery(TestCaseWithFactory):
    layer = CeleryBzrsyncdJobLayer

    def test_branchChanged_via_celery(self):
        """Running a job via Celery succeeds and emits expected output."""
        # Delay importing anything that uses Celery until RabbitMQLayer is
        # running, so that config.rabbitmq.broker_urls is defined when
        # lp.services.job.celeryconfig is loaded.
        self.useFixture(
            FeatureFixture({"jobs.celery.enabled_classes": "BranchScanJob"})
        )
        self.useBzrBranches()
        db_branch, bzr_tree = self.create_branch_and_tree()
        bzr_tree.commit(
            "First commit", rev_id=b"rev1", committer="me@example.org"
        )
        with person_logged_in(db_branch.owner):
            db_branch.branchChanged(None, "rev1", None, None, None)
        with block_on_job():
            transaction.commit()
        self.assertEqual(db_branch.revision_count, 1)

    def test_branchChanged_via_celery_no_enabled(self):
        """With no feature flag, no task is created."""
        self.useBzrBranches()
        db_branch, bzr_tree = self.create_branch_and_tree()
        bzr_tree.commit(
            "First commit", rev_id=b"rev1", committer="me@example.org"
        )
        with person_logged_in(db_branch.owner):
            db_branch.branchChanged(None, "rev1", None, None, None)
        with monitor_celery() as responses:
            transaction.commit()
            self.assertEqual([], responses)


class TestBranchWriteJobViaCelery(TestCaseWithFactory):
    layer = CeleryBranchWriteJobLayer

    def test_destroySelf_via_celery(self):
        """Calling destroySelf causes Celery to delete the branch."""
        self.useFixture(
            FeatureFixture(
                {"jobs.celery.enabled_classes": "ReclaimBranchSpaceJob"}
            )
        )
        self.useBzrBranches()
        db_branch, tree = self.create_branch_and_tree()
        branch_path = get_real_branch_path(db_branch.id)
        self.assertThat(branch_path, PathExists())
        store = Store.of(db_branch)
        with person_logged_in(db_branch.owner):
            db_branch.destroySelf()
        job = store.find(
            BranchJob, BranchJob.job_type == BranchJobType.RECLAIM_BRANCH_SPACE
        ).one()
        job.job.scheduled_start = datetime.now(timezone.utc)
        with block_on_job():
            transaction.commit()
        self.assertThat(branch_path, Not(PathExists()))

    def test_requestUpgradeUsesCelery(self):
        self.useFixture(
            FeatureFixture({"jobs.celery.enabled_classes": "BranchUpgradeJob"})
        )
        self.useBzrBranches()
        db_branch, tree = create_knit(self)
        self.assertEqual(
            tree.branch.repository._format.get_format_string(),
            b"Bazaar-NG Knit Repository Format 1",
        )

        with person_logged_in(db_branch.owner):
            db_branch.requestUpgrade(db_branch.owner)
        with block_on_job():
            transaction.commit()
        new_branch = Branch.open(tree.branch.base)
        self.assertEqual(
            new_branch.repository._format.get_format_string(),
            b"Bazaar repository format 2a (needs bzr 1.16 or later)\n",
        )
        self.assertFalse(db_branch.needs_upgrading)


class TestBranchRevisionMethods(TestCaseWithFactory):
    """Test the branch methods for adding and removing branch revisions."""

    layer = DatabaseFunctionalLayer

    def _getBranchRevision(self, branch, rev_id):
        """Get the branch revision for the specified branch and rev_id."""
        resultset = IStore(BranchRevision).find(
            BranchRevision,
            BranchRevision.branch == branch,
            BranchRevision.revision == Revision.id,
            Revision.revision_id == rev_id,
        )
        return resultset.one()

    def test_createBranchRevision(self):
        # createBranchRevision adds the link for the revision to the branch.
        branch = self.factory.makeBranch()
        rev = self.factory.makeRevision()
        # Nothing there to start with.
        self.assertIs(None, self._getBranchRevision(branch, rev.revision_id))
        branch.createBranchRevision(1, rev)
        # Now there is one.
        br = self._getBranchRevision(branch, rev.revision_id)
        self.assertEqual(branch, br.branch)
        self.assertEqual(rev, br.revision)

    def test_removeBranchRevisions(self):
        # removeBranchRevisions can remove a single linked revision.
        branch = self.factory.makeBranch()
        rev = self.factory.makeRevision()
        branch.createBranchRevision(1, rev)
        # Now remove the branch revision.
        branch.removeBranchRevisions(rev.revision_id)
        # Revision not there now.
        self.assertIs(None, self._getBranchRevision(branch, rev.revision_id))

    def test_removeBranchRevisions_multiple(self):
        # removeBranchRevisions can remove multiple revision links at once.
        branch = self.factory.makeBranch()
        rev1 = self.factory.makeRevision()
        rev2 = self.factory.makeRevision()
        rev3 = self.factory.makeRevision()
        branch.createBranchRevision(1, rev1)
        branch.createBranchRevision(2, rev2)
        branch.createBranchRevision(3, rev3)
        # Now remove the branch revision.
        branch.removeBranchRevisions(
            [rev1.revision_id, rev2.revision_id, rev3.revision_id]
        )
        # No mainline revisions there now.
        # The revision_history attribute is tested above.
        self.assertEqual([], list(branch.revision_history))


class TestBranchGetRevision(TestCaseWithFactory):
    """Make sure that `Branch.getBranchRevision` works as expected."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.branch = self.factory.makeAnyBranch()

    def _makeRevision(self, revno):
        # Make a revision and add it to the branch.
        rev = self.factory.makeRevision()
        self.branch.createBranchRevision(revno, rev)
        return rev

    def testGetBySequenceNumber(self):
        rev1 = self._makeRevision(1)
        branch_revision = self.branch.getBranchRevision(sequence=1)
        self.assertEqual(rev1, branch_revision.revision)
        self.assertEqual(1, branch_revision.sequence)

    def testGetByRevision(self):
        rev1 = self._makeRevision(1)
        branch_revision = self.branch.getBranchRevision(revision=rev1)
        self.assertEqual(rev1, branch_revision.revision)
        self.assertEqual(1, branch_revision.sequence)

    def testGetByRevisionId(self):
        rev1 = self._makeRevision(1)
        branch_revision = self.branch.getBranchRevision(
            revision_id=rev1.revision_id
        )
        self.assertEqual(rev1, branch_revision.revision)
        self.assertEqual(1, branch_revision.sequence)

    def testNonExistant(self):
        self._makeRevision(1)
        self.assertTrue(self.branch.getBranchRevision(sequence=2) is None)
        rev2 = self.factory.makeRevision()
        self.assertTrue(self.branch.getBranchRevision(revision=rev2) is None)
        self.assertTrue(
            self.branch.getBranchRevision(revision_id="not found") is None
        )

    def testInvalidParams(self):
        self.assertRaises(AssertionError, self.branch.getBranchRevision)
        rev1 = self._makeRevision(1)
        self.assertRaises(
            AssertionError,
            self.branch.getBranchRevision,
            sequence=1,
            revision=rev1,
            revision_id=rev1.revision_id,
        )
        self.assertRaises(
            AssertionError,
            self.branch.getBranchRevision,
            sequence=1,
            revision=rev1,
        )
        self.assertRaises(
            AssertionError,
            self.branch.getBranchRevision,
            revision=rev1,
            revision_id=rev1.revision_id,
        )
        self.assertRaises(
            AssertionError,
            self.branch.getBranchRevision,
            sequence=1,
            revision_id=rev1.revision_id,
        )


class TestBranch(TestCaseWithFactory):
    """Test basic properties about Launchpad database branches."""

    layer = DatabaseFunctionalLayer

    def test_pullURLMirrored(self):
        # Mirrored branches are pulled from their actual URLs -- that's the
        # point.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        self.assertEqual(branch.url, branch.getPullURL())

    def test_pullURLImported(self):
        # Imported branches are pulled from the import servers at locations
        # corresponding to the hex id of the branch being mirrored.
        import_server = config.launchpad.bzr_imports_root_url
        branch = self.factory.makeAnyBranch(branch_type=BranchType.IMPORTED)
        self.assertEqual(
            "%s/%08x" % (import_server, branch.id), branch.getPullURL()
        )

    def test_pullURLRemote(self):
        # We cannot mirror remote branches. getPullURL raises an
        # AssertionError.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.REMOTE)
        self.assertRaises(AssertionError, branch.getPullURL)

    def test_owner_name(self):
        # The owner_name attribute is set to be the name of the branch owner
        # through a db trigger.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            branch.owner.name, removeSecurityProxy(branch).owner_name
        )

    def test_owner_name_updated(self):
        # When the owner of a branch is changed, the denormalised owner_name
        # attribute is updated too.
        branch = self.factory.makeAnyBranch()
        new_owner = self.factory.makePerson()
        removeSecurityProxy(branch).owner = new_owner
        # Call the function that is normally called through the event system
        # to auto reload the fields updated by the db triggers.
        update_trigger_modified_fields(branch)
        self.assertEqual(
            new_owner.name, removeSecurityProxy(branch).owner_name
        )

    def test_target_suffix_product(self):
        # The target_suffix for a product branch is the name of the product.
        branch = self.factory.makeProductBranch()
        self.assertEqual(
            branch.product.name, removeSecurityProxy(branch).target_suffix
        )

    def test_target_suffix_junk(self):
        # The target_suffix for a junk branch is None.
        branch = self.factory.makePersonalBranch()
        self.assertIs(None, removeSecurityProxy(branch).target_suffix)

    def test_target_suffix_package(self):
        # A package branch has the target_suffix set to the name of the source
        # package.
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            branch.sourcepackagename.name,
            removeSecurityProxy(branch).target_suffix,
        )

    def test_unique_name_product(self):
        branch = self.factory.makeProductBranch()
        self.assertEqual(
            "~%s/%s/%s"
            % (branch.owner.name, branch.product.name, branch.name),
            branch.unique_name,
        )

    def test_unique_name_junk(self):
        branch = self.factory.makePersonalBranch()
        self.assertEqual(
            "~%s/+junk/%s" % (branch.owner.name, branch.name),
            branch.unique_name,
        )

    def test_unique_name_source_package(self):
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            "~%s/%s/%s/%s/%s"
            % (
                branch.owner.name,
                branch.distribution.name,
                branch.distroseries.name,
                branch.sourcepackagename.name,
                branch.name,
            ),
            branch.unique_name,
        )

    def test_target_name_junk(self):
        branch = self.factory.makePersonalBranch()
        self.assertEqual("+junk", branch.target.name)

    def test_target_name_product(self):
        branch = self.factory.makeProductBranch()
        self.assertEqual(branch.product.name, branch.target.name)

    def test_target_name_package(self):
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            "%s/%s/%s"
            % (
                branch.distribution.name,
                branch.distroseries.name,
                branch.sourcepackagename.name,
            ),
            branch.target.name,
        )

    def makeLaunchBag(self):
        return getUtility(IOpenLaunchBag)

    def test_addToLaunchBag_product(self):
        # Branches are not added directly to the launchbag. Instead,
        # information about their target is added.
        branch = self.factory.makeProductBranch()
        launchbag = self.makeLaunchBag()
        branch.addToLaunchBag(launchbag)
        self.assertEqual(branch.product, launchbag.product)

    def test_addToLaunchBag_personal(self):
        # Junk branches may also be added to the launchbag.
        branch = self.factory.makePersonalBranch()
        launchbag = self.makeLaunchBag()
        branch.addToLaunchBag(launchbag)
        self.assertIs(None, launchbag.product)

    def test_addToLaunchBag_package(self):
        # Package branches can be added to the launchbag.
        branch = self.factory.makePackageBranch()
        launchbag = self.makeLaunchBag()
        branch.addToLaunchBag(launchbag)
        self.assertEqual(branch.distroseries, launchbag.distroseries)
        self.assertEqual(branch.distribution, launchbag.distribution)
        self.assertEqual(branch.sourcepackage, launchbag.sourcepackage)
        self.assertIs(None, branch.product)

    def test_distribution_personal(self):
        # The distribution property of a branch is None for personal branches.
        branch = self.factory.makePersonalBranch()
        self.assertIs(None, branch.distribution)

    def test_distribution_product(self):
        # The distribution property of a branch is None for product branches.
        branch = self.factory.makeProductBranch()
        self.assertIs(None, branch.distribution)

    def test_distribution_package(self):
        # The distribution property of a branch is the distribution of the
        # distroseries for package branches.
        branch = self.factory.makePackageBranch()
        self.assertEqual(branch.distroseries.distribution, branch.distribution)

    def test_sourcepackage_personal(self):
        # The sourcepackage property of a branch is None for personal
        # branches.
        branch = self.factory.makePersonalBranch()
        self.assertIs(None, branch.sourcepackage)

    def test_sourcepackage_product(self):
        # The sourcepackage property of a branch is None for product branches.
        branch = self.factory.makeProductBranch()
        self.assertIs(None, branch.sourcepackage)

    def test_sourcepackage_package(self):
        # The sourcepackage property of a branch is the ISourcePackage built
        # from the distroseries and sourcepackagename of the branch.
        branch = self.factory.makePackageBranch()
        self.assertEqual(
            SourcePackage(branch.sourcepackagename, branch.distroseries),
            branch.sourcepackage,
        )

    def test_implements_IBranch(self):
        # Instances of Branch provide IBranch.
        branch = self.factory.makeBranch()
        # We don't care about security, we just want to check that it
        # implements the interface.
        self.assertProvides(removeSecurityProxy(branch), IBranch)

    def test_associatedProductSeries_initial(self):
        # By default, a branch has no associated product series.
        branch = self.factory.makeBranch()
        self.assertEqual([], list(branch.associatedProductSeries()))

    def test_associatedProductSeries_linked(self):
        # When a branch is linked to a product series, that product series is
        # included in associatedProductSeries.
        branch = self.factory.makeProductBranch()
        product = removeSecurityProxy(branch.product)
        ICanHasLinkedBranch(product).setBranch(branch)
        self.assertEqual(
            [product.development_focus], list(branch.associatedProductSeries())
        )

    def test_getMergeProposals(self):
        target_branch = self.factory.makeProductBranch()
        bmp = self.factory.makeBranchMergeProposal(target_branch=target_branch)
        self.factory.makeBranchMergeProposal()
        self.assertEqual([bmp], list(target_branch.getMergeProposals()))

    def test_getDependentMergeProposals(self):
        prerequisite_branch = self.factory.makeProductBranch()
        bmp = self.factory.makeBranchMergeProposal(
            prerequisite_branch=prerequisite_branch
        )
        self.factory.makeBranchMergeProposal()
        self.assertEqual(
            [bmp], list(prerequisite_branch.getDependentMergeProposals())
        )


class TestBranchUpgrade(TestCaseWithFactory):
    """Test the upgrade functionalities of branches."""

    layer = ZopelessAppServerLayer

    def test_needsUpgrading_empty_formats(self):
        branch = self.factory.makePersonalBranch()
        self.assertFalse(branch.needs_upgrading)

    def test_checkUpgrade_empty_formats(self):
        branch = self.factory.makePersonalBranch()
        with ExpectedException(
            AlreadyLatestFormat,
            "Branch lp://dev/~person-name.*junk/branch.* is in the latest"
            " format, so it cannot be upgraded.",
        ):
            branch.checkUpgrade()

    def test_needsUpgrade_mirrored_branch(self):
        branch = self.factory.makeBranch(
            branch_type=BranchType.MIRRORED,
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_REPOSITORY_4,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_checkUpgrade_mirrored_branch(self):
        branch = self.factory.makeBranch(
            branch_type=BranchType.MIRRORED,
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_REPOSITORY_4,
        )
        with ExpectedException(
            CannotUpgradeNonHosted,
            "Cannot upgrade non-hosted branch %s" % branch.bzr_identity,
        ):
            branch.checkUpgrade()

    def test_needsUpgrade_remote_branch(self):
        branch = self.factory.makeBranch(
            branch_type=BranchType.REMOTE,
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_REPOSITORY_4,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrade_import_branch(self):
        branch = self.factory.makeBranch(
            branch_type=BranchType.IMPORTED,
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_REPOSITORY_4,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_already_requested(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If the format is
        # unrecognized, we don't try to upgrade it.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        branch.requestUpgrade(branch.owner)

        self.assertFalse(branch.needs_upgrading)

    def test_checkUpgrade_already_requested(self):
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        branch.requestUpgrade(branch.owner)
        with ExpectedException(
            UpgradePending,
            "An upgrade is already in progress for branch"
            " lp://dev/~person-name.*junk/branch.*.",
        ):
            branch.checkUpgrade()

    def test_needsUpgrading_branch_format_unrecognized(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If the format is
        # unrecognized, we don't try to upgrade it.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.UNRECOGNIZED,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_branch_format_upgrade_not_needed(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If a branch is up-to-date, it
        # doesn't need to be upgraded.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_8,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_checkUpgrade_branch_format_upgrade_not_needed(self):
        # If a branch is up-to-date, checkUpgrade raises AlreadyLatestFormat
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_8,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        with ExpectedException(
            AlreadyLatestFormat,
            "Branch lp://dev/~person-name.*junk/branch.* is in the latest"
            " format, so it cannot be upgraded.",
        ):
            branch.checkUpgrade()

    def test_needsUpgrading_branch_format_upgrade_needed(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  If a branch doesn't support
        # stacking, it needs to be upgraded.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_6,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        self.assertTrue(branch.needs_upgrading)

    def test_needsUpgrading_repository_format_unrecognized(self):
        # A branch has a needs_upgrading attribute that returns whether or not
        # a branch needs to be upgraded or not.  In the repo format is
        # unrecognized, we don't try to upgrade it.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_8,
            repository_format=RepositoryFormat.UNRECOGNIZED,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_repository_format_upgrade_not_needed(self):
        # A branch has a needs_upgrading method that returns whether or not a
        # branch needs to be upgraded or not.  If the repo format is up to
        # date, there's no need to upgrade it.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_8,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        self.assertFalse(branch.needs_upgrading)

    def test_needsUpgrading_repository_format_upgrade_needed(self):
        # A branch has a needs_upgrading method that returns whether or not a
        # branch needs to be upgraded or not.  If the format doesn't support
        # stacking, it needs to be upgraded.
        branch = self.factory.makePersonalBranch(
            branch_format=BranchFormat.BZR_BRANCH_8,
            repository_format=RepositoryFormat.BZR_REPOSITORY_4,
        )
        self.assertTrue(branch.needs_upgrading)

    def test_requestUpgrade(self):
        # A BranchUpgradeJob can be created by calling IBranch.requestUpgrade.
        branch = self.factory.makeAnyBranch(
            branch_format=BranchFormat.BZR_BRANCH_6
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        job = removeSecurityProxy(branch.requestUpgrade(branch.owner))

        jobs = list(getUtility(IBranchUpgradeJobSource).iterReady())
        self.assertEqual(
            jobs,
            [
                job,
            ],
        )

    def test_requestUpgrade_no_upgrade_needed(self):
        # If a branch doesn't need to be upgraded, requestUpgrade raises an
        # AlreadyLatestFormat.
        branch = self.factory.makeAnyBranch(
            branch_format=BranchFormat.BZR_BRANCH_8,
            repository_format=RepositoryFormat.BZR_CHK_2A,
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        self.assertRaises(
            AlreadyLatestFormat, branch.requestUpgrade, branch.owner
        )

    def test_requestUpgrade_upgrade_pending(self):
        # If there is a pending upgrade already requested, requestUpgrade
        # raises an UpgradePending.
        branch = self.factory.makeAnyBranch(
            branch_format=BranchFormat.BZR_BRANCH_6
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        branch.requestUpgrade(branch.owner)

        self.assertRaises(UpgradePending, branch.requestUpgrade, branch.owner)

    def test_upgradePending(self):
        # If there is a BranchUpgradeJob pending for the branch, return True.
        branch = self.factory.makeAnyBranch(
            branch_format=BranchFormat.BZR_BRANCH_6
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        branch.requestUpgrade(branch.owner)

        self.assertTrue(branch.upgrade_pending)

    def test_upgradePending_no_upgrade_requested(self):
        # If the branch never had an upgrade requested, return False.
        branch = self.factory.makeAnyBranch()

        self.assertFalse(branch.upgrade_pending)

    def test_upgradePending_old_job_exists(self):
        # If the branch had an upgrade pending, but then the job was
        # completed, then upgrade_pending should return False.
        branch = self.factory.makeAnyBranch(
            branch_format=BranchFormat.BZR_BRANCH_6
        )
        owner = removeSecurityProxy(branch).owner
        login_person(owner)
        self.addCleanup(logout)
        branch_job = removeSecurityProxy(branch.requestUpgrade(branch.owner))
        branch_job.job.start()
        branch_job.job.complete()

        self.assertFalse(branch.upgrade_pending)


class TestBzrIdentityMixin(TestCaseWithFactory):
    """Test the defaults and identities provided by BzrIdentityMixin."""

    layer = DatabaseFunctionalLayer

    def assertBzrIdentity(self, branch, identity_path):
        """Assert that the bzr identity of 'branch' is 'identity_path'.

        Actually, it'll be lp://dev/<identity_path>.
        """
        self.assertEqual(
            identity_path, branch.shortened_path, "shortened path"
        )
        self.assertEqual(
            "lp://dev/%s" % identity_path, branch.bzr_identity, "bzr identity"
        )

    def test_bzr_identity_default(self):
        # By default, the bzr identity is an lp URL with the branch's unique
        # name.
        branch = self.factory.makeAnyBranch()
        self.assertBzrIdentity(branch, branch.unique_name)

    def test_bzr_identity_linked_to_product(self):
        # If a branch is the development focus branch for a product, then it's
        # bzr identity is lp:product.
        branch = self.factory.makeProductBranch()
        product = removeSecurityProxy(branch.product)
        linked_branch = ICanHasLinkedBranch(product)
        linked_branch.setBranch(branch)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_bzr_identity_linked_to_product_series(self):
        # If a branch is the development focus branch for a product series,
        # then it's bzr identity is lp:product/series.
        branch = self.factory.makeProductBranch()
        product = branch.product
        series = self.factory.makeProductSeries(product=product)
        linked_branch = ICanHasLinkedBranch(series)
        login_person(series.owner)
        linked_branch.setBranch(branch)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_bzr_identity_private_linked_to_product(self):
        # Private branches also have a short lp:url.
        branch = self.factory.makeProductBranch(
            information_type=InformationType.USERDATA
        )
        with celebrity_logged_in("admin"):
            product = branch.product
            ICanHasLinkedBranch(product).setBranch(branch)
            self.assertBzrIdentity(branch, product.name)

    def test_bzr_identity_linked_to_series_and_dev_focus(self):
        # If a branch is the development focus branch for a product and the
        # branch for a series, the bzr identity will be the storter of the two
        # URLs.
        branch = self.factory.makeProductBranch()
        series = self.factory.makeProductSeries(product=branch.product)
        product_link = ICanHasLinkedBranch(removeSecurityProxy(branch.product))
        series_link = ICanHasLinkedBranch(series)
        product_link.setBranch(branch)
        login_person(series.owner)
        series_link.setBranch(branch)
        self.assertBzrIdentity(branch, product_link.bzr_path)

    def test_bzr_identity_junk_branch_always_unique_name(self):
        # For junk branches, the bzr identity is always based on the unique
        # name of the branch, even if it's linked to a product, product series
        # or whatever.
        branch = self.factory.makePersonalBranch()
        product = removeSecurityProxy(self.factory.makeProduct())
        ICanHasLinkedBranch(product).setBranch(branch)
        self.assertBzrIdentity(branch, branch.unique_name)

    def test_bzr_identity_linked_to_package(self):
        # If a branch is linked to a pocket of a package, then the
        # bzr identity is the path to that package.
        branch = self.factory.makePackageBranch()
        # Have to pick something that's not RELEASE in order to guarantee that
        # it's not the dev focus source package.
        pocket = PackagePublishingPocket.BACKPORTS
        linked_branch = ICanHasLinkedBranch(
            branch.sourcepackage.getSuiteSourcePackage(pocket)
        )
        registrant = branch.sourcepackage.distribution.owner
        login_person(registrant)
        linked_branch.setBranch(branch, registrant)
        login(ANONYMOUS)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_bzr_identity_linked_to_dev_package(self):
        # If a branch is linked to the development focus version of a package
        # then the bzr identity is distro/package.
        sourcepackage = self.factory.makeSourcePackage()
        distro_package = sourcepackage.distribution_sourcepackage
        branch = self.factory.makePackageBranch(
            sourcepackage=distro_package.development_version
        )
        linked_branch = ICanHasLinkedBranch(distro_package)
        registrant = sourcepackage.distribution.owner
        run_with_login(registrant, linked_branch.setBranch, branch, registrant)
        self.assertBzrIdentity(branch, linked_branch.bzr_path)

    def test_identities_no_links(self):
        # If there are no links, the only branch identity is the unique name.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            [(branch.unique_name, branch)], branch.getBranchIdentities()
        )

    def test_linked_to_product(self):
        # If a branch is linked to the product, it is also by definition
        # linked to the development focus of the product.
        fooix = removeSecurityProxy(self.factory.makeProduct(name="fooix"))
        fooix.development_focus.name = "devel"
        eric = self.factory.makePerson(name="eric")
        branch = self.factory.makeProductBranch(
            product=fooix, owner=eric, name="trunk"
        )
        linked_branch = ICanHasLinkedBranch(fooix)
        linked_branch.setBranch(branch)
        self.assertEqual(
            [linked_branch, ICanHasLinkedBranch(fooix.development_focus)],
            branch.getBranchLinks(),
        )
        self.assertEqual(
            [
                ("fooix", fooix),
                ("fooix/devel", fooix.development_focus),
                ("~eric/fooix/trunk", branch),
            ],
            branch.getBranchIdentities(),
        )

    def test_linked_to_product_series(self):
        # If a branch is linked to a non-development series of a product and
        # not linked to the product itself, then only the product series is
        # returned in the links.
        fooix = removeSecurityProxy(self.factory.makeProduct(name="fooix"))
        future = self.factory.makeProductSeries(product=fooix, name="future")
        eric = self.factory.makePerson(name="eric")
        branch = self.factory.makeProductBranch(
            product=fooix, owner=eric, name="trunk"
        )
        linked_branch = ICanHasLinkedBranch(future)
        login_person(fooix.owner)
        linked_branch.setBranch(branch)
        self.assertEqual([linked_branch], branch.getBranchLinks())
        self.assertEqual(
            [("fooix/future", future), ("~eric/fooix/trunk", branch)],
            branch.getBranchIdentities(),
        )

    def test_linked_to_package(self):
        # If a branch is linked to a suite source package where the
        # distroseries is the current series for the distribution, there is a
        # link for both the distribution source package and the suite source
        # package.
        mint = self.factory.makeDistribution(name="mint")
        dev = self.factory.makeDistroSeries(
            distribution=mint, version="1.0", name="dev"
        )
        eric = self.factory.makePerson(name="eric")
        branch = self.factory.makePackageBranch(
            distroseries=dev, sourcepackagename="choc", name="tip", owner=eric
        )
        dsp = self.factory.makeDistributionSourcePackage("choc", mint)
        distro_link = ICanHasLinkedBranch(dsp)
        development_package = dsp.development_version
        suite_sourcepackage = development_package.getSuiteSourcePackage(
            PackagePublishingPocket.RELEASE
        )
        suite_sp_link = ICanHasLinkedBranch(suite_sourcepackage)

        registrant = suite_sourcepackage.distribution.owner
        run_with_login(registrant, suite_sp_link.setBranch, branch, registrant)

        self.assertEqual([distro_link, suite_sp_link], branch.getBranchLinks())
        self.assertEqual(
            [
                ("mint/choc", dsp),
                ("mint/dev/choc", suite_sourcepackage),
                ("~eric/mint/dev/choc/tip", branch),
            ],
            branch.getBranchIdentities(),
        )

    def test_linked_to_package_not_release_pocket(self):
        # If a branch is linked to a suite source package where the
        # distroseries is the current series for the distribution, but the
        # pocket is not the RELEASE pocket, then there is only the link for
        # the suite source package.
        mint = self.factory.makeDistribution(name="mint")
        dev = self.factory.makeDistroSeries(
            distribution=mint, version="1.0", name="dev"
        )
        eric = self.factory.makePerson(name="eric")
        branch = self.factory.makePackageBranch(
            distroseries=dev, sourcepackagename="choc", name="tip", owner=eric
        )
        dsp = self.factory.makeDistributionSourcePackage("choc", mint)
        development_package = dsp.development_version
        suite_sourcepackage = development_package.getSuiteSourcePackage(
            PackagePublishingPocket.BACKPORTS
        )
        suite_sp_link = ICanHasLinkedBranch(suite_sourcepackage)

        registrant = suite_sourcepackage.distribution.owner
        run_with_login(registrant, suite_sp_link.setBranch, branch, registrant)

        self.assertEqual([suite_sp_link], branch.getBranchLinks())
        self.assertEqual(
            [
                ("mint/dev-backports/choc", suite_sourcepackage),
                ("~eric/mint/dev/choc/tip", branch),
            ],
            branch.getBranchIdentities(),
        )

    def test_linked_to_package_not_current_series(self):
        # If the branch is linked to a suite source package where the distro
        # series is not the current series, only the suite source package is
        # returned in the links.
        mint = self.factory.makeDistribution(name="mint")
        self.factory.makeDistroSeries(
            distribution=mint, version="1.0", name="dev"
        )
        supported = self.factory.makeDistroSeries(
            distribution=mint, version="0.9", name="supported"
        )
        eric = self.factory.makePerson(name="eric")
        branch = self.factory.makePackageBranch(
            distroseries=supported,
            sourcepackagename="choc",
            name="tip",
            owner=eric,
        )
        suite_sp = self.factory.makeSuiteSourcePackage(
            distroseries=supported,
            sourcepackagename="choc",
            pocket=PackagePublishingPocket.RELEASE,
        )
        suite_sp_link = ICanHasLinkedBranch(suite_sp)

        registrant = suite_sp.distribution.owner
        run_with_login(registrant, suite_sp_link.setBranch, branch, registrant)

        self.assertEqual([suite_sp_link], branch.getBranchLinks())
        self.assertEqual(
            [
                ("mint/supported/choc", suite_sp),
                ("~eric/mint/supported/choc/tip", branch),
            ],
            branch.getBranchIdentities(),
        )

    def test_linked_across_project_to_package(self):
        # If a product branch is linked to a suite source package, the links
        # are the same as if it was a source package branch.
        mint = self.factory.makeDistribution(name="mint")
        self.factory.makeDistroSeries(
            distribution=mint, version="1.0", name="dev"
        )
        eric = self.factory.makePerson(name="eric")
        fooix = self.factory.makeProduct(name="fooix")
        branch = self.factory.makeProductBranch(
            product=fooix, owner=eric, name="trunk"
        )
        dsp = self.factory.makeDistributionSourcePackage("choc", mint)
        distro_link = ICanHasLinkedBranch(dsp)
        development_package = dsp.development_version
        suite_sourcepackage = development_package.getSuiteSourcePackage(
            PackagePublishingPocket.RELEASE
        )
        suite_sp_link = ICanHasLinkedBranch(suite_sourcepackage)

        registrant = suite_sourcepackage.distribution.owner
        run_with_login(registrant, suite_sp_link.setBranch, branch, registrant)

        self.assertEqual([distro_link, suite_sp_link], branch.getBranchLinks())
        self.assertEqual(
            [
                ("mint/choc", dsp),
                ("mint/dev/choc", suite_sourcepackage),
                ("~eric/fooix/trunk", branch),
            ],
            branch.getBranchIdentities(),
        )

    def test_junk_branch_links(self):
        # If a junk branch has links, those links are returned by
        # getBranchLinks, but getBranchIdentities just returns the branch
        # unique name.
        eric = self.factory.makePerson(name="eric")
        branch = self.factory.makePersonalBranch(owner=eric, name="foo")
        fooix = removeSecurityProxy(self.factory.makeProduct())
        linked_branch = ICanHasLinkedBranch(fooix)
        linked_branch.setBranch(branch)
        self.assertEqual(
            [linked_branch, ICanHasLinkedBranch(fooix.development_focus)],
            branch.getBranchLinks(),
        )
        self.assertEqual(
            [("~eric/+junk/foo", branch)], branch.getBranchIdentities()
        )


class TestBranchDeletion(TestCaseWithFactory):
    """Test the different cases that makes a branch deletable or not."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()
        self.product = self.factory.makeProduct(owner=self.user)
        self.branch = self.factory.makeProductBranch(
            name="to-delete", owner=self.user, product=self.product
        )
        # The owner of the branch is subscribed to the branch when it is
        # created.  The tests here assume no initial connections, so
        # unsubscribe the branch owner here.
        self.branch.unsubscribe(self.branch.owner, self.branch.owner)
        # Make sure that the tests all flush the database changes.
        self.addCleanup(Store.of(self.branch).flush)
        login_person(self.user)

    def test_deletable(self):
        """A newly created branch can be deleted without any problems."""
        self.assertEqual(
            self.branch.canBeDeleted(),
            True,
            "A newly created branch should be able to be " "deleted.",
        )
        branch_id = self.branch.id
        branch_set = getUtility(IBranchLookup)
        self.branch.destroySelf()
        self.assertIsNone(
            branch_set.get(branch_id), "The branch has not been deleted."
        )

    def test_stackedBranchDisablesDeletion(self):
        # A branch that is stacked upon cannot be deleted.
        self.factory.makeAnyBranch(stacked_on=self.branch)
        self.assertFalse(self.branch.canBeDeleted())

    def test_subscriptionDoesntDisableDeletion(self):
        """A branch that has a subscription can be deleted."""
        self.branch.subscribe(
            self.user,
            BranchSubscriptionNotificationLevel.NOEMAIL,
            None,
            CodeReviewNotificationLevel.NOEMAIL,
            self.user,
        )
        self.assertEqual(True, self.branch.canBeDeleted())

    def test_codeImportCanStillBeDeleted(self):
        """A branch that has an attached code import can be deleted."""
        code_import = LaunchpadObjectFactory().makeCodeImport()
        branch = code_import.branch
        self.assertEqual(
            branch.canBeDeleted(),
            True,
            "A branch that has a import is deletable.",
        )

    def test_bugBranchLinkDisablesDeletion(self):
        """A branch linked to a bug cannot be deleted."""
        params = CreateBugParams(
            owner=self.user,
            title="Firefox bug",
            comment="blah",
            target=self.product,
        )
        bug = getUtility(IBugSet).createBug(params)
        bug.linkBranch(self.branch, self.user)
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch linked to a bug is not deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_specBranchLinkDisablesDeletion(self):
        """A branch linked to a spec cannot be deleted."""
        spec = getUtility(ISpecificationSet).new(
            name="some-spec",
            title="Some spec",
            target=self.product,
            owner=self.user,
            summary="",
            specurl=None,
            definition_status=NewSpecificationDefinitionStatus.NEW,
        )
        spec.linkBranch(self.branch, self.user)
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch linked to a spec is not deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_associatedProductSeriesBranchDisablesDeletion(self):
        """A branch linked as a branch to a product series cannot be
        deleted.
        """
        self.product.development_focus.branch = self.branch
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch that is a user branch for a product series"
            " is not deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_productSeriesTranslationsBranchDisablesDeletion(self):
        self.product.development_focus.translations_branch = self.branch
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch that is a translations branch for a "
            "product series is not deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_revisionsDeletable(self):
        """A branch that has some revisions can be deleted."""
        revision = self.factory.makeRevision()
        self.branch.createBranchRevision(0, revision)
        # Need to commit the addition to make sure that the branch revisions
        # are recorded as there and that the appropriate deferred foreign keys
        # are set up.
        transaction.commit()
        self.assertEqual(
            self.branch.canBeDeleted(),
            True,
            "A branch that has a revision is deletable.",
        )
        unique_name = self.branch.unique_name
        self.branch.destroySelf()
        # Commit again to trigger the deferred indices.
        transaction.commit()
        branch_lookup = getUtility(IBranchLookup)
        self.assertEqual(
            branch_lookup.getByUniqueName(unique_name),
            None,
            "Branch was not deleted.",
        )

    def test_landingTargetDisablesDeletion(self):
        """A branch with a landing target cannot be deleted."""
        target_branch = self.factory.makeProductBranch(
            name="landing-target", owner=self.user, product=self.product
        )
        self.branch.addLandingTarget(self.user, target_branch)
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch with a landing target is not deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_landingCandidateDisablesDeletion(self):
        """A branch with a landing candidate cannot be deleted."""
        source_branch = self.factory.makeProductBranch(
            name="landing-candidate", owner=self.user, product=self.product
        )
        source_branch.addLandingTarget(self.user, self.branch)
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch with a landing candidate is not" " deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_prerequisiteBranchDisablesDeletion(self):
        """A branch that is a prerequisite branch cannot be deleted."""
        source_branch = self.factory.makeProductBranch(
            name="landing-candidate", owner=self.user, product=self.product
        )
        target_branch = self.factory.makeProductBranch(
            name="landing-target", owner=self.user, product=self.product
        )
        source_branch.addLandingTarget(self.user, target_branch, self.branch)
        self.assertEqual(
            self.branch.canBeDeleted(),
            False,
            "A branch with a prerequisite target is not " "deletable.",
        )
        self.assertRaises(CannotDeleteBranch, self.branch.destroySelf)

    def test_relatedBranchJobsDeleted(self):
        # A branch with an associated branch job will delete those jobs.
        branch = self.factory.makeBranch(
            branch_format=BranchFormat.BZR_BRANCH_6
        )
        removeSecurityProxy(branch).requestUpgrade(branch.owner)
        branch.destroySelf()
        # Need to commit the transaction to fire off the constraint checks.
        transaction.commit()

    def test_linked_translations_branch_cleared(self):
        # The translations_branch of a series that is linked to the branch
        # should be cleared.
        dev_focus = self.branch.product.development_focus
        dev_focus.translations_branch = self.branch
        self.branch.destroySelf(break_references=True)

    def test_related_TranslationTemplatesBuild_cleaned_out(self):
        # A TranslationTemplatesBuild may come with a BuildQueue entry.
        # Deleting the branch cleans up the BuildQueue before it can
        # remove the TTB.
        build = self.factory.makeTranslationTemplatesBuild()
        build.queueBuild()
        build.branch.destroySelf(break_references=True)

    def test_unrelated_TranslationTemplatesBuild_intact(self):
        # No innocent BuildQueue entries are harmed in deleting a
        # branch.
        build = self.factory.makeTranslationTemplatesBuild()
        bq = build.queueBuild()
        other_build = self.factory.makeTranslationTemplatesBuild()
        other_bq = other_build.queueBuild()

        build.branch.destroySelf(break_references=True)

        store = Store.of(build)
        # The BuildQueue for the job whose branch we deleted is gone.
        self.assertEqual(0, store.find(BuildQueue, id=bq.id).count())

        # The other job's BuildQueue entry is still there.
        self.assertEqual(1, store.find(BuildQueue, id=other_bq.id).count())

    def test_createsJobToReclaimSpace(self):
        # When a branch is deleted from the database, a job to remove the
        # branch from disk as well.
        branch = self.factory.makeAnyBranch()
        branch_id = branch.id
        store = Store.of(branch)
        branch.destroySelf()
        jobs = store.find(
            BranchJob, BranchJob.job_type == BranchJobType.RECLAIM_BRANCH_SPACE
        )
        self.assertEqual(
            [branch_id], [ReclaimBranchSpaceJob(job).branch_id for job in jobs]
        )

    def test_destroySelf_with_SourcePackageRecipe(self):
        """If branch is a base_branch in a recipe, it is deleted."""
        recipe = self.factory.makeSourcePackageRecipe()
        recipe.base_branch.destroySelf(break_references=True)

    def test_destroySelf_with_SourcePackageRecipe_as_non_base(self):
        """If branch is referred to by a recipe, it is deleted."""
        branch1 = self.factory.makeAnyBranch()
        branch2 = self.factory.makeAnyBranch()
        self.factory.makeSourcePackageRecipe(branches=[branch1, branch2])
        branch2.destroySelf(break_references=True)

    def test_destroySelf_with_inline_comments_draft(self):
        # Draft inline comments related to a deleted branch (source
        # or target MP branch) also get removed.
        merge_proposal = self.factory.makeBranchMergeProposal(
            registrant=self.user, target_branch=self.branch
        )
        preview_diff = self.factory.makePreviewDiff(
            merge_proposal=merge_proposal
        )
        transaction.commit()
        merge_proposal.saveDraftInlineComment(
            previewdiff_id=preview_diff.id,
            person=self.user,
            comments={"1": "Should vanish."},
        )
        self.branch.destroySelf(break_references=True)

    def test_destroySelf_with_inline_comments_published(self):
        # Published inline comments related to a deleted branch (source
        # or target MP branch) also get removed.
        merge_proposal = self.factory.makeBranchMergeProposal(
            registrant=self.user, target_branch=self.branch
        )
        preview_diff = self.factory.makePreviewDiff(
            merge_proposal=merge_proposal
        )
        transaction.commit()
        merge_proposal.createComment(
            owner=self.user,
            subject="Delete me!",
            previewdiff_id=preview_diff.id,
            inline_comments={"1": "Must disappear."},
        )
        self.branch.destroySelf(break_references=True)

    def test_related_webhooks_deleted(self):
        webhook = self.factory.makeWebhook(target=self.branch)
        webhook.ping()
        self.branch.destroySelf()
        transaction.commit()
        self.assertRaises(LostObjectError, getattr, webhook, "target")


class TestBranchDeletionConsequences(TestCase):
    """Test determination and application of branch deletion consequences."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        login("test@canonical.com")
        self.factory = LaunchpadObjectFactory()
        # Has to be a product branch because of merge proposals.
        self.branch = self.factory.makeProductBranch()
        # The owner of the branch is subscribed to the branch when it is
        # created.  The tests here assume no initial connections, so
        # unsubscribe the branch owner here.
        self.branch.unsubscribe(self.branch.owner, self.branch.owner)

    def test_plainBranch(self):
        """Ensure that a fresh branch has no deletion requirements."""
        self.assertEqual({}, self.branch.deletionRequirements())

    def makeMergeProposals(self):
        """Produce a merge proposal for testing purposes."""
        target_branch = self.factory.makeProductBranch(
            product=self.branch.product
        )
        prerequisite_branch = self.factory.makeProductBranch(
            product=self.branch.product
        )
        # Remove the implicit subscriptions.
        target_branch.unsubscribe(target_branch.owner, target_branch.owner)
        prerequisite_branch.unsubscribe(
            prerequisite_branch.owner, prerequisite_branch.owner
        )
        merge_proposal1 = self.branch.addLandingTarget(
            self.branch.owner, target_branch, prerequisite_branch
        )
        # Disable this merge proposal, to allow creating a new identical one
        lp_admins = getUtility(ILaunchpadCelebrities).admin
        merge_proposal1.rejectBranch(lp_admins, "null:")
        merge_proposal2 = self.branch.addLandingTarget(
            self.branch.owner, target_branch, prerequisite_branch
        )
        return merge_proposal1, merge_proposal2

    def test_branchWithMergeProposal(self):
        """Ensure that deletion requirements with a merge proposal are right.

        Each branch related to the merge proposal is tested to ensure it
        produces a unique, correct result.
        """
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        self.assertEqual(
            {
                merge_proposal1: (
                    "delete",
                    _(
                        "This branch is the source branch of this merge"
                        " proposal."
                    ),
                ),
                merge_proposal2: (
                    "delete",
                    _(
                        "This branch is the source branch of this merge"
                        " proposal."
                    ),
                ),
            },
            self.branch.deletionRequirements(),
        )
        self.assertEqual(
            {
                merge_proposal1: (
                    "delete",
                    _(
                        "This branch is the target branch of this merge"
                        " proposal."
                    ),
                ),
                merge_proposal2: (
                    "delete",
                    _(
                        "This branch is the target branch of this merge"
                        " proposal."
                    ),
                ),
            },
            merge_proposal1.target_branch.deletionRequirements(),
        )
        self.assertEqual(
            {
                merge_proposal1: (
                    "alter",
                    _(
                        "This branch is the prerequisite branch of this merge"
                        " proposal."
                    ),
                ),
                merge_proposal2: (
                    "alter",
                    _(
                        "This branch is the prerequisite branch of this merge"
                        " proposal."
                    ),
                ),
            },
            merge_proposal1.prerequisite_branch.deletionRequirements(),
        )

    def test_deleteMergeProposalSource(self):
        """Merge proposal source branches can be deleted with break_links."""
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        merge_proposal1_id = merge_proposal1.id
        getUtility(IBranchMergeProposalGetter).get(merge_proposal1_id)
        self.branch.destroySelf(break_references=True)
        self.assertRaises(
            NotFoundError,
            getUtility(IBranchMergeProposalGetter).get,
            merge_proposal1_id,
        )

    def test_deleteMergeProposalTarget(self):
        """Merge proposal target branches can be deleted with break_links."""
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        merge_proposal1_id = merge_proposal1.id
        getUtility(IBranchMergeProposalGetter).get(merge_proposal1_id)
        merge_proposal1.target_branch.destroySelf(break_references=True)
        self.assertRaises(
            NotFoundError,
            getUtility(IBranchMergeProposalGetter).get,
            merge_proposal1_id,
        )

    def test_deleteMergeProposalDependent(self):
        """break_links enables deleting merge proposal dependent branches."""
        merge_proposal1, merge_proposal2 = self.makeMergeProposals()
        merge_proposal1.prerequisite_branch.destroySelf(break_references=True)
        self.assertEqual(None, merge_proposal1.prerequisite_branch)

    def test_deleteSourceCodeReviewComment(self):
        """Deletion of branches that have CodeReviewComments works."""
        comment = self.factory.makeCodeReviewComment()
        comment_id = comment.id
        branch = comment.branch_merge_proposal.source_branch
        branch.destroySelf(break_references=True)
        self.assertIsNone(
            IStore(CodeReviewComment).get(CodeReviewComment, comment_id)
        )

    def test_deleteTargetCodeReviewComment(self):
        """Deletion of branches that have CodeReviewComments works."""
        comment = self.factory.makeCodeReviewComment()
        comment_id = comment.id
        branch = comment.branch_merge_proposal.target_branch
        branch.destroySelf(break_references=True)
        self.assertIsNone(
            IStore(CodeReviewComment).get(CodeReviewComment, comment_id)
        )

    def test_branchWithBugRequirements(self):
        """Deletion requirements for a branch with a bug are right."""
        bug = self.factory.makeBug()
        bug.linkBranch(self.branch, self.branch.owner)
        self.assertEqual(
            {
                bug.default_bugtask: (
                    "delete",
                    _("This bug is linked to this branch."),
                )
            },
            self.branch.deletionRequirements(),
        )

    def test_branchWithBugDeletion(self):
        """break_links allows deleting a branch with a bug."""
        bug1 = self.factory.makeBug()
        bug1.linkBranch(self.branch, self.branch.owner)
        bug_branch1 = bug1.linked_bugbranches.first()
        bug_branch1_id = removeSecurityProxy(bug_branch1).id
        self.branch.destroySelf(break_references=True)
        self.assertIsNone(IStore(BugBranch).get(BugBranch, bug_branch1_id))

    def test_branchWithSpecRequirements(self):
        """Deletion requirements for a branch with a spec are right."""
        spec = self.factory.makeSpecification()
        spec.linkBranch(self.branch, self.branch.owner)
        self.assertEqual(
            {
                self.branch.spec_links[0]: (
                    "delete",
                    _("This blueprint is linked to this branch."),
                )
            },
            self.branch.deletionRequirements(),
        )

    def test_branchWithSpecDeletion(self):
        """break_links allows deleting a branch with a spec."""
        spec1 = self.factory.makeSpecification()
        spec1.linkBranch(self.branch, self.branch.owner)
        spec1_branch_id = self.branch.spec_links[0].id
        spec2 = self.factory.makeSpecification()
        spec2.linkBranch(self.branch, self.branch.owner)
        spec2_branch_id = self.branch.spec_links[1].id
        self.branch.destroySelf(break_references=True)
        self.assertIsNone(
            IStore(SpecificationBranch).get(
                SpecificationBranch, spec1_branch_id
            )
        )
        self.assertIsNone(
            IStore(SpecificationBranch).get(
                SpecificationBranch, spec2_branch_id
            )
        )

    def test_branchWithSeriesRequirements(self):
        """Deletion requirements for a series' branch are right."""
        series = self.factory.makeProductSeries(branch=self.branch)
        self.assertEqual(
            {series: ("alter", _("This series is linked to this branch."))},
            self.branch.deletionRequirements(),
        )

    def test_branchWithSeriesDeletion(self):
        """break_links allows deleting a series' branch."""
        series1 = self.factory.makeProductSeries(branch=self.branch)
        series2 = self.factory.makeProductSeries(branch=self.branch)
        self.branch.destroySelf(break_references=True)
        self.assertEqual(None, series1.branch)
        self.assertEqual(None, series2.branch)

    def test_official_package_requirements(self):
        # If a branch is officially linked to a source package, then the
        # deletion requirements indicate the fact.
        branch = self.factory.makePackageBranch()
        package = branch.sourcepackage
        pocket = PackagePublishingPocket.RELEASE
        run_with_login(
            package.distribution.owner,
            package.development_version.setBranch,
            pocket,
            branch,
            package.distribution.owner,
        )
        self.assertEqual(
            {
                package: (
                    "alter",
                    _("Branch is officially linked to a source package."),
                )
            },
            branch.deletionRequirements(),
        )

    def test_official_package_branch_deleted(self):
        # A branch that's an official package branch can be deleted if you are
        # allowed to modify package branch links, and you pass in
        # break_references.
        branch = self.factory.makePackageBranch()
        package = branch.sourcepackage
        pocket = PackagePublishingPocket.RELEASE
        run_with_login(
            package.distribution.owner,
            package.development_version.setBranch,
            pocket,
            branch,
            package.distribution.owner,
        )
        self.assertEqual(False, branch.canBeDeleted())
        branch.destroySelf(break_references=True)
        self.assertIs(None, package.getBranch(pocket))

    def test_branchWithCodeImportRequirements(self):
        """Deletion requirements for a code import branch are right"""
        code_import = self.factory.makeCodeImport()
        # Remove the implicit branch subscription first.
        code_import.branch.unsubscribe(
            code_import.branch.owner, code_import.branch.owner
        )
        self.assertEqual({}, code_import.branch.deletionRequirements())

    def test_branchWithCodeImportDeletion(self):
        """break_references allows deleting a code import branch."""
        code_import = self.factory.makeCodeImport()
        code_import_id = code_import.id
        code_import.branch.destroySelf(break_references=True)
        self.assertRaises(
            NotFoundError, getUtility(ICodeImportSet).get, code_import_id
        )

    def test_sourceBranchWithCodeReviewVoteReference(self):
        """Break_references handles CodeReviewVoteReference source branch."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        merge_proposal.nominateReviewer(
            self.factory.makePerson(), self.factory.makePerson()
        )
        merge_proposal.source_branch.destroySelf(break_references=True)

    def test_targetBranchWithCodeReviewVoteReference(self):
        """Break_references handles CodeReviewVoteReference target branch."""
        merge_proposal = self.factory.makeBranchMergeProposal()
        merge_proposal.nominateReviewer(
            self.factory.makePerson(), self.factory.makePerson()
        )
        merge_proposal.target_branch.destroySelf(break_references=True)

    def test_snap_requirements(self):
        # If a branch is used by a snap package, the deletion requirements
        # indicate this.
        self.factory.makeSnap(branch=self.branch)
        self.assertEqual(
            {None: ("alter", _("Some snap packages build from this branch."))},
            self.branch.deletionRequirements(),
        )

    def test_snap_deletion(self):
        # break_references allows deleting a branch used by a snap package.
        snap1 = self.factory.makeSnap(branch=self.branch)
        snap2 = self.factory.makeSnap(branch=self.branch)
        self.branch.destroySelf(break_references=True)
        transaction.commit()
        self.assertIsNone(snap1.branch)
        self.assertIsNone(snap2.branch)

    def test_ClearDependentBranch(self):
        """ClearDependent.__call__ must clear the prerequisite branch."""
        merge_proposal = removeSecurityProxy(self.makeMergeProposals()[0])
        with person_logged_in(merge_proposal.prerequisite_branch.owner):
            ClearDependentBranch(merge_proposal)()
        self.assertEqual(None, merge_proposal.prerequisite_branch)

    def test_ClearOfficialPackageBranch(self):
        # ClearOfficialPackageBranch.__call__ clears the official package
        # branch.
        branch = self.factory.makePackageBranch()
        package = branch.sourcepackage
        pocket = PackagePublishingPocket.RELEASE
        run_with_login(
            package.distribution.owner,
            package.development_version.setBranch,
            pocket,
            branch,
            package.distribution.owner,
        )
        series_set = getUtility(IFindOfficialBranchLinks)
        [link] = list(series_set.findForBranch(branch))
        ClearOfficialPackageBranch(link)()
        self.assertIs(None, package.getBranch(pocket))

    def test_ClearSeriesBranch(self):
        """ClearSeriesBranch.__call__ must clear the user branch."""
        series = removeSecurityProxy(
            self.factory.makeProductSeries(branch=self.branch)
        )
        ClearSeriesBranch(series, self.branch)()
        self.assertEqual(None, series.branch)

    def test_DeletionOperation(self):
        """DeletionOperation.__call__ is not implemented."""
        self.assertRaises(NotImplementedError, DeletionOperation("a", "b"))

    def test_DeletionCallable(self):
        """DeletionCallable must invoke the callable."""
        spec = self.factory.makeSpecification()
        spec_link = spec.linkBranch(self.branch, self.branch.owner)
        spec_link_id = spec_link.id
        DeletionCallable(spec, "blah", spec_link.destroySelf)()
        self.assertIsNone(
            IStore(SpecificationBranch).get(SpecificationBranch, spec_link_id)
        )

    def test_DeleteCodeImport(self):
        """DeleteCodeImport.__call__ must delete the CodeImport."""
        code_import = self.factory.makeCodeImport()
        code_import_id = code_import.id
        DeleteCodeImport(code_import)()
        self.assertRaises(
            NotFoundError, getUtility(ICodeImportSet).get, code_import_id
        )

    def test_deletionRequirements_with_SourcePackageRecipe(self):
        """Recipes are listed as deletion requirements."""
        recipe = self.factory.makeSourcePackageRecipe()
        self.assertEqual(
            {recipe: ("delete", "This recipe uses this branch.")},
            recipe.base_branch.deletionRequirements(),
        )


class StackedBranches(TestCaseWithFactory):
    """Tests for showing branches stacked on another."""

    layer = DatabaseFunctionalLayer

    def testNoBranchesStacked(self):
        # getStackedBranches returns an empty collection if there are no
        # branches stacked on it.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(set(), set(branch.getStackedBranches()))

    def testSingleBranchStacked(self):
        # some_branch.getStackedBranches returns a collection of branches
        # stacked on some_branch.
        branch = self.factory.makeAnyBranch()
        stacked_branch = self.factory.makeAnyBranch(stacked_on=branch)
        self.assertEqual({stacked_branch}, set(branch.getStackedBranches()))

    def testMultipleBranchesStacked(self):
        # some_branch.getStackedBranches returns a collection of branches
        # stacked on some_branch.
        branch = self.factory.makeAnyBranch()
        stacked_a = self.factory.makeAnyBranch(stacked_on=branch)
        stacked_b = self.factory.makeAnyBranch(stacked_on=branch)
        self.assertEqual(
            {stacked_a, stacked_b}, set(branch.getStackedBranches())
        )

    def testNoBranchesStackedOn(self):
        # getStackedBranches returns an empty collection if there are no
        # branches stacked on it.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(set(), set(branch.getStackedOnBranches()))

    def testSingleBranchStackedOn(self):
        # some_branch.getStackedOnBranches returns a collection of branches
        # on which some_branch is stacked.
        branch = self.factory.makeAnyBranch()
        stacked_branch = self.factory.makeAnyBranch(stacked_on=branch)
        self.assertEqual({branch}, set(stacked_branch.getStackedOnBranches()))

    def testMultipleBranchesStackedOn(self):
        # some_branch.getStackedOnBranches returns a collection of branches
        # on which some_branch is stacked.
        stacked_a = self.factory.makeAnyBranch()
        stacked_b = self.factory.makeAnyBranch(stacked_on=stacked_a)
        branch = self.factory.makeAnyBranch(stacked_on=stacked_b)
        self.assertEqual(
            {stacked_a, stacked_b}, set(branch.getStackedOnBranches())
        )


class BranchAddLandingTarget(TestCaseWithFactory):
    """Exercise all the code paths for adding a landing target."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp("admin@canonical.com")
        self.product = self.factory.makeProduct()

        self.user = self.factory.makePerson()
        self.reviewer = self.factory.makePerson(name="johndoe")
        self.source = self.factory.makeProductBranch(
            name="source-branch", owner=self.user, product=self.product
        )
        self.target = self.factory.makeProductBranch(
            name="target-branch", owner=self.user, product=self.product
        )
        self.prerequisite = self.factory.makeProductBranch(
            name="prerequisite-branch", owner=self.user, product=self.product
        )

    def tearDown(self):
        logout()
        super().tearDown()

    def assertOnePendingReview(self, proposal, reviewer, review_type=None):
        # There should be one pending vote for the reviewer with the specified
        # review type.
        [vote] = list(proposal.votes)
        self.assertEqual(reviewer, vote.reviewer)
        self.assertEqual(self.user, vote.registrant)
        self.assertIs(None, vote.comment)
        if review_type is None:
            self.assertIs(None, vote.review_type)
        else:
            self.assertEqual(review_type, vote.review_type)

    def test_junkSource(self):
        """Junk branches cannot be used as a source for merge proposals."""
        self.source.setTarget(user=self.source.owner)
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
        )

    def test_targetProduct(self):
        """The product of the target branch must match the product of the
        source branch.
        """
        self.target.setTarget(user=self.target.owner)
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
        )

        project = self.factory.makeProduct()
        self.target.setTarget(user=self.target.owner, project=project)
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
        )

    def test_targetMustNotBeTheSource(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.source,
        )

    def test_prerequisiteBranchSameProduct(self):
        """The prerequisite branch, if any, must be for the same product."""
        self.prerequisite.setTarget(user=self.prerequisite.owner)
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
            self.prerequisite,
        )

        project = self.factory.makeProduct()
        self.prerequisite.setTarget(
            user=self.prerequisite.owner, project=project
        )
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
            self.prerequisite,
        )

    def test_prerequisiteMustNotBeTheSource(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
            self.source,
        )

    def test_prerequisiteMustNotBeTheTarget(self):
        """The target and source branch cannot be the same."""
        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
            self.target,
        )

    def test_existingMergeProposal(self):
        """If there is an existing merge proposal for the source and target
        branch pair, then another landing target specifying the same pair
        raises.
        """
        self.source.addLandingTarget(self.user, self.target, self.prerequisite)

        self.assertRaises(
            InvalidBranchMergeProposal,
            self.source.addLandingTarget,
            self.user,
            self.target,
            self.prerequisite,
        )

    def test_existingRejectedMergeProposal(self):
        """If there is an existing rejected merge proposal for the source and
        target branch pair, then another landing target specifying the same
        pair is fine.
        """
        proposal = self.source.addLandingTarget(
            self.user, self.target, self.prerequisite
        )
        proposal.rejectBranch(self.user, "some_revision")
        self.source.addLandingTarget(self.user, self.target, self.prerequisite)

    def test_default_reviewer(self):
        """If the target branch has a default reviewer set, this reviewer
        should be assigned to the merge proposal.
        """
        target_with_default_reviewer = self.factory.makeProductBranch(
            name="target-branch-with-reviewer",
            owner=self.user,
            product=self.product,
            reviewer=self.reviewer,
        )
        proposal = self.source.addLandingTarget(
            self.user, target_with_default_reviewer
        )
        self.assertOnePendingReview(proposal, self.reviewer)

    def test_default_reviewer_when_owner(self):
        """If the target branch has a no default reviewer set, the branch
        owner should be assigned as the reviewer for the merge proposal.
        """
        proposal = self.source.addLandingTarget(self.user, self.target)
        self.assertOnePendingReview(proposal, self.source.owner)

    def test_attributeAssignment(self):
        """Smoke test to make sure the assignments are there."""
        commit_message = "Some commit message"
        proposal = self.source.addLandingTarget(
            self.user,
            self.target,
            self.prerequisite,
            commit_message=commit_message,
        )
        self.assertEqual(proposal.registrant, self.user)
        self.assertEqual(proposal.source_branch, self.source)
        self.assertEqual(proposal.target_branch, self.target)
        self.assertEqual(proposal.prerequisite_branch, self.prerequisite)
        self.assertEqual(proposal.commit_message, commit_message)

    def test__createMergeProposal_with_reviewers(self):
        person1 = self.factory.makePerson()
        person2 = self.factory.makePerson()
        e = self.assertRaises(
            ValueError,
            self.source._createMergeProposal,
            self.user,
            self.target,
            reviewers=[person1, person2],
        )
        self.assertEqual(
            "reviewers and review_types must be equal length.", str(e)
        )
        e = self.assertRaises(
            ValueError,
            self.source._createMergeProposal,
            self.user,
            self.target,
            reviewers=[person1, person2],
            review_types=["review1"],
        )
        self.assertEqual(
            "reviewers and review_types must be equal length.", str(e)
        )
        bmp = self.source._createMergeProposal(
            self.user,
            self.target,
            reviewers=[person1, person2],
            review_types=["review1", "review2"],
        )
        votes = {(vote.reviewer, vote.review_type) for vote in bmp.votes}
        self.assertEqual({(person1, "review1"), (person2, "review2")}, votes)


class TestLandingCandidates(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_private_branch(self):
        """landing_candidates works for private branches."""
        branch = self.factory.makeBranch(
            information_type=InformationType.USERDATA
        )
        with person_logged_in(removeSecurityProxy(branch).owner):
            mp = self.factory.makeBranchMergeProposal(target_branch=branch)
            self.assertContentEqual([mp], branch.landing_candidates)


class BranchDateLastModified(TestCaseWithFactory):
    """Exercies the situations where date_last_modifed is updated."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, "test@canonical.com")

    def test_initialValue(self):
        """Initially the date_last_modifed is the date_created."""
        branch = self.factory.makeAnyBranch()
        self.assertEqual(branch.date_last_modified, branch.date_created)

    def test_bugBranchLinkUpdates(self):
        """Linking a branch to a bug updates the last modified time."""
        date_created = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        self.assertEqual(branch.date_last_modified, date_created)

        params = CreateBugParams(
            owner=branch.owner,
            title="A bug",
            comment="blah",
            target=branch.product,
        )
        bug = getUtility(IBugSet).createBug(params)

        bug.linkBranch(branch, branch.owner)
        self.assertTrue(
            branch.date_last_modified > date_created,
            "Date last modified was not updated.",
        )

    def test_updateScannedDetails_with_null_revision(self):
        # If updateScannedDetails is called with a null revision, it
        # effectively means that there is an empty branch, so we can't use the
        # revision date, so we set the last modified time to UTC_NOW.
        date_created = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        branch.updateScannedDetails(None, 0)
        self.assertSqlAttributeEqualsDate(
            branch, "date_last_modified", UTC_NOW
        )

    def test_updateScannedDetails_with_revision(self):
        # If updateScannedDetails is called with a revision with which has a
        # revision date set in the past (the usual case), the last modified
        # time of the branch is set to be the date from the Bazaar revision
        # (Revision.revision_date).
        date_created = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        revision_date = datetime(2005, 2, 2, 12, tzinfo=timezone.utc)
        revision = self.factory.makeRevision(revision_date=revision_date)
        branch.updateScannedDetails(revision, 1)
        self.assertEqual(revision_date, branch.date_last_modified)

    def test_updateScannedDetails_with_future_revision(self):
        # If updateScannedDetails is called with a revision with which has a
        # revision date set in the future, UTC_NOW is used as the last modified
        # time.  date_created = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
        date_created = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
        branch = self.factory.makeAnyBranch(date_created=date_created)
        revision_date = datetime.now(timezone.utc) + timedelta(days=1000)
        revision = self.factory.makeRevision(revision_date=revision_date)
        branch.updateScannedDetails(revision, 1)
        self.assertSqlAttributeEqualsDate(
            branch, "date_last_modified", UTC_NOW
        )


class TestBranchLifecycleStatus(TestCaseWithFactory):
    """Exercises changes in lifecycle status."""

    layer = DatabaseFunctionalLayer

    def checkStatusAfterUpdate(self, initial_state, expected_state):
        # Make sure that the lifecycle status of the branch with the initial
        # lifecycle state to be the expected_state after a revision has been
        # scanned.
        branch = self.factory.makeAnyBranch(lifecycle_status=initial_state)
        revision = self.factory.makeRevision()
        branch.updateScannedDetails(revision, 1)
        self.assertEqual(expected_state, branch.lifecycle_status)

    def test_updateScannedDetails_active_branch(self):
        # If a new revision is scanned, and the branch is in an active state,
        # then the lifecycle status isn't changed.
        for state in DEFAULT_BRANCH_STATUS_IN_LISTING:
            self.checkStatusAfterUpdate(state, state)

    def test_updateScannedDetails_inactive_branch(self):
        # If a branch is inactive (merged or abandoned) and a new revision is
        # scanned, the branch is moved to the development state.
        for state in (
            BranchLifecycleStatus.MERGED,
            BranchLifecycleStatus.ABANDONED,
        ):
            self.checkStatusAfterUpdate(
                state, BranchLifecycleStatus.DEVELOPMENT
            )


class TestCreateBranchRevisionFromIDs(TestCaseWithFactory):
    """Tests for `Branch.createBranchRevisionFromIDs`."""

    layer = DatabaseFunctionalLayer

    def test_simple(self):
        # createBranchRevisionFromIDs when passed a single revid, sequence
        # pair, creates the appropriate BranchRevision object.
        branch = self.factory.makeAnyBranch()
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        branch.createBranchRevisionFromIDs(
            [(rev.revision_id, revision_number)]
        )
        branch_revision = branch.getBranchRevision(revision=rev)
        self.assertEqual(revision_number, branch_revision.sequence)

    def test_multiple(self):
        # createBranchRevisionFromIDs when passed multiple revid, sequence
        # pairs, creates the appropriate BranchRevision objects.
        branch = self.factory.makeAnyBranch()
        revision_to_number = {}
        revision_id_sequence_pairs = []
        for _i in range(10):
            rev = self.factory.makeRevision()
            revision_number = self.factory.getUniqueInteger()
            revision_to_number[rev] = revision_number
            revision_id_sequence_pairs.append(
                (rev.revision_id, revision_number)
            )
        branch.createBranchRevisionFromIDs(revision_id_sequence_pairs)
        for rev in revision_to_number:
            branch_revision = branch.getBranchRevision(revision=rev)
            self.assertEqual(revision_to_number[rev], branch_revision.sequence)

    def test_empty(self):
        # createBranchRevisionFromIDs does not fail when passed no pairs.
        branch = self.factory.makeAnyBranch()
        branch.createBranchRevisionFromIDs([])

    def test_call_twice_in_one_transaction(self):
        # createBranchRevisionFromIDs creates temporary tables, but cleans
        # after itself so that it can safely be called twice in one
        # transaction.
        branch = self.factory.makeAnyBranch()
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        branch.createBranchRevisionFromIDs(
            [(rev.revision_id, revision_number)]
        )
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        # This is just "assertNotRaises"
        branch.createBranchRevisionFromIDs(
            [(rev.revision_id, revision_number)]
        )

    def test_ghost(self):
        # createBranchRevisionFromIDs skips ghost revisions for which no
        # Revision rows exist.
        branch = self.factory.makeAnyBranch()
        rev = self.factory.makeRevision()
        revision_number = self.factory.getUniqueInteger()
        ghost_rev_id = self.factory.getUniqueString("revision-id")
        revision_id_sequence_pairs = [
            (rev.revision_id, revision_number),
            (ghost_rev_id, None),
        ]
        branch.createBranchRevisionFromIDs(revision_id_sequence_pairs)
        self.assertEqual(
            revision_number, branch.getBranchRevision(revision=rev).sequence
        )
        self.assertIsNone(branch.getBranchRevision(revision_id=ghost_rev_id))


class TestRevisionHistory(TestCaseWithFactory):
    """Tests for a branch's revision history."""

    layer = DatabaseFunctionalLayer

    def test_revision_count(self):
        # A branch's revision count is equal to the number of revisions that
        # are associated with it.
        branch = self.factory.makeBranch()
        some_number = 6
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        self.assertEqual(some_number, branch.revision_count)

    def test_revision_history_matches_count(self):
        branch = self.factory.makeBranch()
        some_number = 3
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        self.assertEqual(
            branch.revision_count, branch.revision_history.count()
        )

    def test_revision_history_is_made_of_revisions(self):
        # Branch.revision_history contains IBranchRevision objects.
        branch = self.factory.makeBranch()
        some_number = 6
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        for branch_revision in branch.revision_history:
            self.assertProvides(branch_revision, IBranchRevision)

    def test_continuous_sequence_numbers(self):
        # The revisions in the revision history have sequence numbers which
        # start from 1 at the oldest and don't have any gaps.
        branch = self.factory.makeBranch()
        some_number = 4
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        self.assertEqual(
            [4, 3, 2, 1], [br.sequence for br in branch.revision_history]
        )

    def test_most_recent_first(self):
        # The revisions in the revision history start with the most recent
        # first.
        branch = self.factory.makeBranch()
        some_number = 4
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        revision_history = list(branch.revision_history)
        sorted_by_date = sorted(
            revision_history,
            key=lambda x: x.revision.revision_date,
            reverse=True,
        )
        self.assertEqual(sorted_by_date, revision_history)

    def test_latest_revisions(self):
        # IBranch.latest_revisions gives only the latest revisions.
        branch = self.factory.makeBranch()
        some_number = 7
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        smaller_number = some_number / 2
        self.assertEqual(
            list(branch.revision_history[:smaller_number]),
            list(branch.latest_revisions(smaller_number)),
        )

    def test_getCodebrowseUrlForRevision(self):
        # IBranch.getCodebrowseUrlForRevision gives the URL to the browser
        # for a specific revision of the code
        branch = self.factory.makeBranch()
        revision = 42
        self.factory.makeRevisionsForBranch(branch, count=revision)
        urlByRevision = branch.getCodebrowseUrlForRevision(42)
        url = branch.getCodebrowseUrl()
        self.assertEqual(urlByRevision, "%s/revision/%s" % (url, revision))

    def test_top_ancestor_has_no_parents(self):
        # The top-most revision of a branch (i.e. the first one) has no
        # parents.
        branch = self.factory.makeBranch()
        self.factory.makeRevisionsForBranch(branch, count=1)
        revision = list(branch.revision_history)[0].revision
        self.assertEqual([], revision.parent_ids)

    def test_non_first_revisions_have_parents(self):
        # Revisions which are not the first revision of the branch have
        # parent_ids. When there are no merges present, there is only one
        # parent which is the previous revision.
        branch = self.factory.makeBranch()
        some_number = 5
        self.factory.makeRevisionsForBranch(branch, count=some_number)
        revisions = list(branch.revision_history)
        last_rev = revisions[0].revision
        second_last_rev = revisions[1].revision
        self.assertEqual(last_rev.parent_ids, [second_last_rev.revision_id])

    def test_tip_revision_when_no_bazaar_data(self):
        # When a branch has no revisions and no Bazaar data at all, its tip
        # revision is None and its last_scanned_id is None.
        branch = self.factory.makeBranch()
        self.assertIs(None, branch.last_scanned_id)
        self.assertIs(None, branch.getTipRevision())

    def test_tip_revision_when_no_revisions(self):
        # When a branch has no revisions but does have Bazaar data, its tip
        # revision is None and its last_scanned_id is
        # breezy.revision.NULL_REVISION.
        branch = self.factory.makeBranch()
        branch.updateScannedDetails(None, 0)
        self.assertEqual(NULL_REVISION.decode(), branch.last_scanned_id)
        self.assertIs(None, branch.getTipRevision())

    def test_tip_revision_is_updated(self):
        branch = self.factory.makeBranch()
        revision = self.factory.makeRevision()
        branch.updateScannedDetails(revision, 1)
        self.assertEqual(revision.revision_id, branch.last_scanned_id)
        self.assertEqual(revision, branch.getTipRevision())


class TestCodebrowse(TestCaseWithFactory):
    """Tests for branch codebrowse support."""

    layer = DatabaseFunctionalLayer

    def test_simple(self):
        # The basic codebrowse URL for a public branch is an 'https' URL.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            "https://bazaar.launchpad.test/" + branch.unique_name,
            branch.getCodebrowseUrl(),
        )

    def test_private(self):
        # The codebrowse URL for a private branch is an 'https' URL.
        owner = self.factory.makePerson()
        branch = self.factory.makeAnyBranch(
            owner=owner, information_type=InformationType.USERDATA
        )
        login_person(owner)
        self.assertEqual(
            "https://bazaar.launchpad.test/" + branch.unique_name,
            branch.getCodebrowseUrl(),
        )

    def test_extra_args(self):
        # Any arguments to getCodebrowseUrl are appended to the URL.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            "https://bazaar.launchpad.test/" + branch.unique_name + "/a/b",
            branch.getCodebrowseUrl("a", "b"),
        )

    def test_source_code_url(self):
        # The source code URL points to the codebrowse URL where you can
        # actually browse the source code.
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            branch.browse_source_url, branch.getCodebrowseUrl("files")
        )

    def test_not_browsable(self):
        # For the upcoming decommissioning of bzr codehosting on
        # Launchpad, we are disabling the codebrowse feature. So
        # code is always not browsable.
        branch = self.factory.makeBranch()
        self.assertFalse(branch.code_is_browsable)
        self.factory.makeRevisionsForBranch(branch, count=5)
        self.assertFalse(branch.code_is_browsable)


class TestBranchNamespace(TestCaseWithFactory):
    """Tests for `IBranch.namespace`."""

    layer = DatabaseFunctionalLayer

    def assertNamespaceEqual(self, namespace_one, namespace_two):
        """Assert that `namespace_one` equals `namespace_two`."""
        namespace_one = removeSecurityProxy(namespace_one)
        namespace_two = removeSecurityProxy(namespace_two)
        self.assertEqual(namespace_one.__class__, namespace_two.__class__)
        self.assertEqual(namespace_one.owner, namespace_two.owner)
        self.assertEqual(
            getattr(namespace_one, "sourcepackage", None),
            getattr(namespace_two, "sourcepackage", None),
        )
        self.assertEqual(
            getattr(namespace_one, "product", None),
            getattr(namespace_two, "product", None),
        )

    def test_namespace_personal(self):
        # The namespace attribute of a personal branch points to the namespace
        # that corresponds to ~owner/+junk.
        branch = self.factory.makePersonalBranch()
        namespace = getUtility(IBranchNamespaceSet).get(person=branch.owner)
        self.assertNamespaceEqual(namespace, branch.namespace)

    def test_namespace_package(self):
        # The namespace attribute of a package branch points to the namespace
        # that corresponds to
        # ~owner/distribution/distroseries/sourcepackagename.
        branch = self.factory.makePackageBranch()
        namespace = getUtility(IBranchNamespaceSet).get(
            person=branch.owner,
            distroseries=branch.distroseries,
            sourcepackagename=branch.sourcepackagename,
        )
        self.assertNamespaceEqual(namespace, branch.namespace)

    def test_namespace_product(self):
        # The namespace attribute of a product branch points to the namespace
        # that corresponds to ~owner/product.
        branch = self.factory.makeProductBranch()
        namespace = getUtility(IBranchNamespaceSet).get(
            person=branch.owner, product=branch.product
        )
        self.assertNamespaceEqual(namespace, branch.namespace)


class TestPendingWritesAndUpdates(TestCaseWithFactory):
    """Are there changes to this branch not reflected in the database?"""

    layer = LaunchpadFunctionalLayer

    def test_new_branch_no_writes(self):
        # New branches have no pending writes or pending updates.
        branch = self.factory.makeAnyBranch()
        self.assertFalse(branch.pending_writes)
        self.assertFalse(branch.pending_updates)

    def test_branchChanged_for_hosted(self):
        # If branchChanged has been called with a new tip revision id, there
        # are pending writes and pending updates.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.HOSTED)
        with person_logged_in(branch.owner):
            branch.branchChanged("", "new-tip", None, None, None)
        self.assertTrue(branch.pending_writes)
        self.assertTrue(branch.pending_updates)

    def test_unscanned_without_rescan(self):
        # If a branch was unscanned without requesting a rescan, then there
        # are pending writes but no pending updates.
        self.useBzrBranches(direct_database=True)
        branch, bzr_tree = self.create_branch_and_tree()
        rev_id = self.factory.getUniqueBytes("rev-id")
        bzr_tree.commit("Commit", committer="me@example.com", rev_id=rev_id)
        removeSecurityProxy(branch).branchChanged("", rev_id, None, None, None)
        transaction.commit()
        [job] = getUtility(IBranchScanJobSource).iterReady()
        with dbuser("branchscanner"):
            JobRunner([job]).runAll()
        self.assertFalse(branch.pending_writes)
        self.assertFalse(branch.pending_updates)
        removeSecurityProxy(branch).unscan(rescan=False)
        self.assertTrue(branch.pending_writes)
        self.assertFalse(branch.pending_updates)

    def test_unscanned_with_rescan(self):
        # If a branch was unscanned and a rescan was requested, then there
        # are pending writes and pending updates.
        self.useBzrBranches(direct_database=True)
        branch, bzr_tree = self.create_branch_and_tree()
        rev_id = self.factory.getUniqueBytes("rev-id")
        bzr_tree.commit("Commit", committer="me@example.com", rev_id=rev_id)
        removeSecurityProxy(branch).branchChanged("", rev_id, None, None, None)
        transaction.commit()
        [job] = getUtility(IBranchScanJobSource).iterReady()
        with dbuser("branchscanner"):
            JobRunner([job]).runAll()
        self.assertFalse(branch.pending_writes)
        self.assertFalse(branch.pending_updates)
        removeSecurityProxy(branch).unscan(rescan=True)
        self.assertTrue(branch.pending_writes)
        self.assertTrue(branch.pending_updates)

    def test_requestMirror_for_imported(self):
        # If an imported branch has a requested mirror, then we've just
        # imported new changes. Therefore, pending writes and pending
        # updates.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.IMPORTED)
        branch.requestMirror()
        self.assertTrue(branch.pending_writes)
        self.assertTrue(branch.pending_updates)

    def test_requestMirror_for_mirrored(self):
        # Mirrored branches *always* have a requested mirror. The fact that
        # a mirror is requested has no bearing on whether there are pending
        # writes or pending updates. Thus, pending_writes and
        # pending_updates are both False.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.requestMirror()
        self.assertFalse(branch.pending_writes)
        self.assertFalse(branch.pending_updates)

    def test_pulled_but_not_scanned(self):
        # If a branch has been pulled (mirrored) but not scanned, then we have
        # yet to load the revisions into the database. This means there are
        # pending writes and pending updates.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.startMirroring()
        rev_id = self.factory.getUniqueBytes("rev-id")
        removeSecurityProxy(branch).branchChanged("", rev_id, None, None, None)
        self.assertTrue(branch.pending_writes)
        self.assertTrue(branch.pending_updates)

    def test_pulled_and_scanned(self):
        # If a branch has been pulled and scanned, then there are no pending
        # writes or pending updates.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.startMirroring()
        rev_id = self.factory.getUniqueBytes("rev-id")
        removeSecurityProxy(branch).branchChanged("", rev_id, None, None, None)
        # Cheat! The actual API for marking a branch as scanned is to run
        # the BranchScanJob. That requires a revision in the database
        # though.
        removeSecurityProxy(branch).last_scanned_id = rev_id.decode()
        [job] = getUtility(IBranchScanJobSource).iterReady()
        removeSecurityProxy(job).job._status = JobStatus.COMPLETED
        self.assertFalse(branch.pending_writes)
        self.assertFalse(branch.pending_updates)

    def test_first_mirror_started(self):
        # If we have started mirroring the branch for the first time, then
        # there are probably pending writes and pending updates.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.startMirroring()
        self.assertTrue(branch.pending_writes)
        self.assertTrue(branch.pending_updates)

    def test_following_mirror_started(self):
        # If we have started mirroring the branch, then there are probably
        # pending writes and pending updates.
        branch = self.factory.makeAnyBranch(branch_type=BranchType.MIRRORED)
        branch.startMirroring()
        rev_id = self.factory.getUniqueBytes("rev-id")
        removeSecurityProxy(branch).branchChanged("", rev_id, None, None, None)
        # Cheat! We can only tell if mirroring has started if the last
        # mirrored attempt is different from the last mirrored time. To ensure
        # this, we start the second mirror in a new transaction.
        transaction.commit()
        branch.startMirroring()
        self.assertTrue(branch.pending_writes)
        self.assertTrue(branch.pending_updates)


class TestBranchPrivacy(TestCaseWithFactory):
    """Tests for branch privacy."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin user as we aren't checking edit permissions here.
        TestCaseWithFactory.setUp(self, "admin@canonical.com")

    def test_public_stacked_on_private_is_private(self):
        # A public branch stacked on a private branch is private.
        stacked_on = self.factory.makeBranch(
            information_type=InformationType.USERDATA
        )
        branch = self.factory.makeBranch(stacked_on=stacked_on)
        self.assertTrue(branch.private)
        self.assertEqual(stacked_on.information_type, branch.information_type)
        self.assertEqual(
            InformationType.USERDATA,
            removeSecurityProxy(branch).information_type,
        )

    def test_personal_branches_for_private_teams_are_private(self):
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED,
            visibility=PersonVisibility.PRIVATE,
        )
        branch = self.factory.makePersonalBranch(owner=team)
        self.assertTrue(branch.private)
        self.assertEqual(InformationType.PROPRIETARY, branch.information_type)

    def test__reconcileAccess_for_product_branch(self):
        # _reconcileAccess uses a product policy for a product branch.
        branch = self.factory.makeBranch(
            information_type=InformationType.USERDATA
        )
        [artifact] = getUtility(IAccessArtifactSource).ensure([branch])
        getUtility(IAccessPolicyArtifactSource).deleteByArtifact([artifact])
        removeSecurityProxy(branch)._reconcileAccess()
        self.assertContentEqual(
            getUtility(IAccessPolicySource).find(
                [(branch.product, InformationType.USERDATA)]
            ),
            get_policies_for_artifact(branch),
        )

    def test__reconcileAccess_for_package_branch(self):
        # _reconcileAccess uses a distribution policy for a package branch.
        branch = self.factory.makePackageBranch(
            information_type=InformationType.USERDATA
        )
        [artifact] = getUtility(IAccessArtifactSource).ensure([branch])
        getUtility(IAccessPolicyArtifactSource).deleteByArtifact([artifact])
        removeSecurityProxy(branch)._reconcileAccess()
        self.assertContentEqual(
            getUtility(IAccessPolicySource).find(
                [(branch.distribution, InformationType.USERDATA)]
            ),
            get_policies_for_artifact(branch),
        )

    def test__reconcileAccess_for_personal_branch(self):
        # _reconcileAccess uses a person policy for a personal branch.
        team_owner = self.factory.makeTeam()
        branch = self.factory.makePersonalBranch(
            owner=team_owner, information_type=InformationType.USERDATA
        )
        removeSecurityProxy(branch)._reconcileAccess()
        self.assertContentEqual(
            getUtility(IAccessPolicySource).findByTeam([team_owner]),
            get_policies_for_artifact(branch),
        )


class TestBranchGetAllowedInformationTypes(TestCaseWithFactory):
    """Test Branch.getAllowedInformationTypes."""

    layer = DatabaseFunctionalLayer

    def test_normal_user_sees_namespace_types(self):
        # An unprivileged user sees the types allowed by the namespace.
        branch = self.factory.makeBranch()
        policy = IBranchNamespacePolicy(branch.namespace)
        self.assertContentEqual(
            policy.getAllowedInformationTypes(),
            branch.getAllowedInformationTypes(branch.owner),
        )
        self.assertNotIn(
            InformationType.PROPRIETARY,
            branch.getAllowedInformationTypes(branch.owner),
        )
        self.assertNotIn(
            InformationType.EMBARGOED,
            branch.getAllowedInformationTypes(branch.owner),
        )

    def test_admin_sees_namespace_types(self):
        # An admin sees all the types, since they occasionally need to
        # override the namespace rules. This is hopefully temporary, and
        # can go away once the new sharing rules (granting
        # non-commercial projects limited use of private branches) are
        # deployed.
        branch = self.factory.makeBranch()
        admin = self.factory.makeAdministrator()
        self.assertContentEqual(
            PUBLIC_INFORMATION_TYPES + PRIVATE_INFORMATION_TYPES,
            branch.getAllowedInformationTypes(admin),
        )
        self.assertIn(
            InformationType.PROPRIETARY,
            branch.getAllowedInformationTypes(admin),
        )


class TestBranchSetPrivate(TestCaseWithFactory):
    """Test IBranch.setPrivate."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        # Use an admin user as we aren't checking edit permissions here.
        TestCaseWithFactory.setUp(self, "admin@canonical.com")

    def test_public_to_public(self):
        # Setting a public branch to be public is a no-op.
        branch = self.factory.makeProductBranch()
        self.assertFalse(branch.private)
        branch.setPrivate(False, branch.owner)
        self.assertFalse(branch.private)
        self.assertEqual(InformationType.PUBLIC, branch.information_type)

    def test_public_to_private_allowed(self):
        # If there is a privacy policy allowing the branch owner to have
        # private branches, then setting the branch private is allowed.
        branch = self.factory.makeProductBranch()
        branch.setPrivate(True, branch.owner)
        self.assertTrue(branch.private)
        self.assertEqual(InformationType.USERDATA, branch.information_type)

    def test_public_to_private_for_admins(self):
        # Admins can override the default behaviour and make any public branch
        # private.
        branch = self.factory.makeProductBranch()
        # Grab a random admin, the teamowner is good enough here.
        admins = getUtility(ILaunchpadCelebrities).admin
        branch.setPrivate(True, admins.teamowner)
        self.assertTrue(branch.private)
        self.assertEqual(
            InformationType.USERDATA,
            removeSecurityProxy(branch).information_type,
        )

    def test_private_to_private(self):
        # Setting a private branch to be private is a no-op.
        branch = self.factory.makeProductBranch(
            information_type=InformationType.USERDATA
        )
        self.assertTrue(branch.private)
        branch.setPrivate(True, branch.owner)
        self.assertTrue(branch.private)
        self.assertEqual(
            InformationType.USERDATA,
            removeSecurityProxy(branch).information_type,
        )

    def test_private_to_public_allowed(self):
        # If the namespace policy allows public branches, then changing from
        # private to public is allowed.
        branch = self.factory.makeProductBranch(
            information_type=InformationType.USERDATA
        )
        branch.setPrivate(False, branch.owner)
        self.assertFalse(branch.private)
        self.assertEqual(InformationType.PUBLIC, branch.information_type)

    def test_private_to_public_not_allowed(self):
        # If the namespace policy does not allow public branches, attempting
        # to change the branch to be public raises CannotChangeInformationType.
        product = self.factory.makeProduct(
            branch_sharing_policy=BranchSharingPolicy.PROPRIETARY
        )
        branch = self.factory.makeBranch(product=product, owner=product.owner)
        self.assertRaisesWithContent(
            CannotChangeInformationType,
            "Forbidden by project policy.",
            branch.setPrivate,
            False,
            branch.owner,
        )

    def test_cannot_transition_with_private_stacked_on(self):
        # If a public branch is stacked on a private branch, it can not
        # change its information_type to public.
        stacked_on = self.factory.makeBranch(
            information_type=InformationType.USERDATA
        )
        branch = self.factory.makeBranch(stacked_on=stacked_on)
        self.assertRaisesWithContent(
            CannotChangeInformationType,
            "Must match stacked-on branch.",
            branch.transitionToInformationType,
            InformationType.PUBLIC,
            branch.owner,
        )

    def test_can_transition_with_public_stacked_on(self):
        # If a private branch is stacked on a public branch, it can change
        # its information_type.
        stacked_on = self.factory.makeBranch()
        branch = self.factory.makeBranch(
            stacked_on=stacked_on, information_type=InformationType.USERDATA
        )
        branch.transitionToInformationType(
            InformationType.PUBLICSECURITY, branch.owner
        )
        self.assertEqual(
            InformationType.PUBLICSECURITY, branch.information_type
        )

    def test_transition_reconciles_access(self):
        # transitionToStatus calls _reconcileAccess to make the sharing
        # schema match the new value.
        branch = self.factory.makeBranch(
            information_type=InformationType.USERDATA
        )
        with admin_logged_in():
            branch.transitionToInformationType(
                InformationType.PRIVATESECURITY,
                branch.owner,
                verify_policy=False,
            )
        self.assertEqual(
            InformationType.PRIVATESECURITY,
            get_policies_for_artifact(branch)[0].type,
        )

    def test_can_transition_with_no_subscribers(self):
        # Ensure that a branch can transition to another private type when
        # there are no subscribers to the branch.
        owner = self.factory.makePerson()
        branch = self.factory.makeBranch(
            owner=owner, information_type=InformationType.USERDATA
        )
        with person_logged_in(owner):
            branch.unsubscribe(owner, owner)
        branch.transitionToInformationType(
            InformationType.PRIVATESECURITY, owner, verify_policy=False
        )
        self.assertEqual(
            InformationType.PRIVATESECURITY, branch.information_type
        )


class BranchModerateTestCase(WithScenarios, TestCaseWithFactory):
    """Test that pillar owners and commercial admins can moderate branches."""

    layer = DatabaseFunctionalLayer
    scenarios = [
        ("project", {"branch_factory_name": "makeProductBranch"}),
        ("distribution", {"branch_factory_name": "makePackageBranch"}),
    ]

    def _makeBranch(self, **kwargs):
        return getattr(self.factory, self.branch_factory_name)(**kwargs)

    def _getPillar(self, branch):
        return branch.product or branch.distribution

    def test_moderate_permission(self):
        # Test the ModerateBranch security checker.
        branch = self._makeBranch()
        pillar = self._getPillar(branch)
        with person_logged_in(pillar.owner):
            self.assertTrue(check_permission("launchpad.Moderate", branch))
        with celebrity_logged_in("commercial_admin"):
            self.assertTrue(check_permission("launchpad.Moderate", branch))

    def test_methods_smoketest(self):
        # Users with launchpad.Moderate can call transitionToInformationType.
        branch = self._makeBranch()
        pillar = self._getPillar(branch)
        with person_logged_in(pillar.owner):
            pillar.setBranchSharingPolicy(BranchSharingPolicy.PUBLIC)
            branch.transitionToInformationType(
                InformationType.PRIVATESECURITY, pillar.owner
            )
        self.assertEqual(
            InformationType.PRIVATESECURITY, branch.information_type
        )

    def test_attribute_smoketest(self):
        # Users with launchpad.Moderate can set attrs.
        branch = self._makeBranch()
        pillar = self._getPillar(branch)
        with person_logged_in(pillar.owner):
            branch.name = "not-secret"
            branch.description = "redacted"
            branch.reviewer = pillar.owner
            branch.lifecycle_status = BranchLifecycleStatus.EXPERIMENTAL
        self.assertEqual("not-secret", branch.name)
        self.assertEqual("redacted", branch.description)
        self.assertEqual(pillar.owner, branch.reviewer)
        self.assertEqual(
            BranchLifecycleStatus.EXPERIMENTAL, branch.lifecycle_status
        )


class TestBranchBugLinks(TestCaseWithFactory):
    """Tests for bug linkages in `Branch`"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()
        login_person(self.user)

    def test_bug_link(self):
        # Branches can be linked to bugs through the Branch interface.
        branch = self.factory.makeAnyBranch()
        bug = self.factory.makeBug()
        branch.linkBug(bug, self.user)

        self.assertEqual(branch.linked_bugs.count(), 1)

        linked_bug = branch.linked_bugs.first()

        self.assertEqual(linked_bug.id, bug.id)

    def test_bug_unlink(self):
        # Branches can be unlinked from the bug as well.
        branch = self.factory.makeAnyBranch()
        bug = self.factory.makeBug()
        branch.linkBug(bug, self.user)

        self.assertEqual(branch.linked_bugs.count(), 1)

        branch.unlinkBug(bug, self.user)

        self.assertEqual(branch.linked_bugs.count(), 0)


class TestBranchSpecLinks(TestCaseWithFactory):
    """Tests for bug linkages in `Branch`"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.user = self.factory.makePerson()

    def test_spec_link(self):
        # Branches can be linked to specs through the Branch interface.
        branch = self.factory.makeAnyBranch()
        spec = self.factory.makeSpecification()
        branch.linkSpecification(spec, self.user)

        self.assertEqual(branch.spec_links.count(), 1)

        spec_branch = branch.spec_links[0]

        self.assertEqual(spec_branch.specification.id, spec.id)
        self.assertEqual(spec_branch.branch.id, branch.id)

    def test_spec_unlink(self):
        # Branches can be unlinked from the spec as well.
        branch = self.factory.makeAnyBranch()
        spec = self.factory.makeSpecification()
        branch.linkSpecification(spec, self.user)

        self.assertEqual(branch.spec_links.count(), 1)

        branch.unlinkSpecification(spec, self.user)

        self.assertEqual(branch.spec_links.count(), 0)


class TestBranchIsPersonTrustedReviewer(TestCaseWithFactory):
    """Test the `IBranch.isPersonTrustedReviewer` method."""

    layer = DatabaseFunctionalLayer

    def assertTrustedReviewer(self, branch, person):
        """Assert that `person` is a trusted reviewer for the `branch`."""
        self.assertTrue(branch.isPersonTrustedReviewer(person))

    def assertNotTrustedReviewer(self, branch, person):
        """Assert that `person` is not a trusted reviewer for the `branch`."""
        self.assertFalse(branch.isPersonTrustedReviewer(person))

    def test_none_is_not_trusted(self):
        # If None is passed in as the person, the method returns false.
        branch = self.factory.makeAnyBranch()
        self.assertNotTrustedReviewer(branch, None)

    def test_branch_owner_is_trusted(self):
        # The branch owner is a trusted reviewer.
        branch = self.factory.makeAnyBranch()
        self.assertTrustedReviewer(branch, branch.owner)

    def test_non_branch_owner_is_not_trusted(self):
        # Someone other than the branch owner is not a trusted reviewer.
        branch = self.factory.makeAnyBranch()
        reviewer = self.factory.makePerson()
        self.assertNotTrustedReviewer(branch, reviewer)

    def test_lp_admins_always_trusted(self):
        # Launchpad admins are special, and as such, are trusted.
        branch = self.factory.makeAnyBranch()
        admins = getUtility(ILaunchpadCelebrities).admin
        # Grab a random admin, the teamowner is good enough here.
        self.assertTrustedReviewer(branch, admins.teamowner)

    def test_member_of_team_owned_branch(self):
        # If the branch is owned by a team, any team member is a trusted
        # reviewer.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(owner=team)
        self.assertTrustedReviewer(branch, team.teamowner)

    def test_review_team_member_is_trusted(self):
        # If the reviewer is a member of the review team, but not the owner
        # they are still trusted.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(reviewer=team)
        self.assertTrustedReviewer(branch, team.teamowner)

    def test_branch_owner_not_review_team_member_is_trusted(self):
        # If the owner of the branch is not in the review team, they are still
        # trusted.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(reviewer=team)
        self.assertFalse(branch.owner.inTeam(team))
        self.assertTrustedReviewer(branch, branch.owner)

    def test_community_reviewer(self):
        # If the reviewer is not a member of the owner, or the review team,
        # they are not trusted reviewers.
        team = self.factory.makeTeam()
        branch = self.factory.makeAnyBranch(reviewer=team)
        reviewer = self.factory.makePerson()
        self.assertNotTrustedReviewer(branch, reviewer)


class TestBranchSetOwner(TestCaseWithFactory):
    """Tests for IBranch.setOwner."""

    layer = DatabaseFunctionalLayer

    def test_owner_sets_team(self):
        # The owner of the branch can set the owner of the branch to be a team
        # they are a member of.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam(owner=branch.owner)
        login_person(branch.owner)
        branch.setOwner(team, branch.owner)
        self.assertEqual(team, branch.owner)

    def test_owner_cannot_set_nonmember_team(self):
        # The owner of the branch cannot set the owner to be a team they are
        # not a member of.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam()
        login_person(branch.owner)
        self.assertRaises(
            BranchCreatorNotMemberOfOwnerTeam,
            branch.setOwner,
            team,
            branch.owner,
        )

    def test_owner_cannot_set_other_user(self):
        # The owner of the branch cannot set the new owner to be another
        # person.
        branch = self.factory.makeAnyBranch()
        person = self.factory.makePerson()
        login_person(branch.owner)
        self.assertRaises(
            BranchCreatorNotOwner, branch.setOwner, person, branch.owner
        )

    def test_admin_can_set_any_team_or_person(self):
        # A Launchpad admin can set the branch to be owned by any team or
        # person.
        branch = self.factory.makeAnyBranch()
        team = self.factory.makeTeam()
        # To get a random administrator, choose the admin team owner.
        admin = getUtility(ILaunchpadCelebrities).admin.teamowner
        login_person(admin)
        branch.setOwner(team, admin)
        self.assertEqual(team, branch.owner)
        person = self.factory.makePerson()
        branch.setOwner(person, admin)
        self.assertEqual(person, branch.owner)


class TestBranchSetTarget(TestCaseWithFactory):
    """Tests for IBranch.setTarget."""

    layer = DatabaseFunctionalLayer

    def test_not_both_project_and_source_package(self):
        # Only one of project or source_package can be passed in, not both.
        branch = self.factory.makePersonalBranch()
        project = self.factory.makeProduct()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        self.assertRaises(
            BranchTargetError,
            branch.setTarget,
            user=branch.owner,
            project=project,
            source_package=source_package,
        )

    def test_junk_branch_to_project_branch(self):
        # A junk branch can be moved to a project.
        branch = self.factory.makePersonalBranch()
        project = self.factory.makeProduct()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, project=project)
        self.assertEqual(project, branch.target.context)

    def test_junk_branch_to_package_branch(self):
        # A junk branch can be moved to a source package.
        branch = self.factory.makePersonalBranch()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, source_package=source_package)
        self.assertEqual(source_package, branch.target.context)

    def test_project_branch_to_other_project_branch(self):
        # Move a branch from one project to another.
        branch = self.factory.makeProductBranch()
        project = self.factory.makeProduct()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, project=project)
        self.assertEqual(project, branch.target.context)

    def test_project_branch_to_package_branch(self):
        # Move a branch from a project to a package.
        branch = self.factory.makeProductBranch()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, source_package=source_package)
        self.assertEqual(source_package, branch.target.context)

    def test_project_branch_to_junk_branch(self):
        # Move a branch from a project to junk.
        branch = self.factory.makeProductBranch()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner)
        self.assertEqual(branch.owner, branch.target.context)

    def test_package_branch_to_other_package_branch(self):
        # Move a branch from one package to another.
        branch = self.factory.makePackageBranch()
        source_package = self.factory.makeSourcePackage()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, source_package=source_package)
        self.assertEqual(source_package, branch.target.context)

    def test_package_branch_to_project_branch(self):
        # Move a branch from a package to a project.
        branch = self.factory.makePackageBranch()
        project = self.factory.makeProduct()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner, project=project)
        self.assertEqual(project, branch.target.context)

    def test_package_branch_to_junk_branch(self):
        # Move a branch from a package to junk.
        branch = self.factory.makePackageBranch()
        login_person(branch.owner)
        branch.setTarget(user=branch.owner)
        self.assertEqual(branch.owner, branch.target.context)

    def test_private_junk_branches_forbidden_for_public_teams(self):
        # Only private teams can have private junk branches.
        owner = self.factory.makeTeam()
        branch = self.factory.makeBranch(
            owner=owner, information_type=InformationType.USERDATA
        )
        with admin_logged_in():
            self.assertRaises(
                BranchTargetError, branch.setTarget, branch.owner
            )

    def test_private_junk_branches_allowed_for_private_teams(self):
        # Only private teams can have private junk branches.
        owner = self.factory.makeTeam(visibility=PersonVisibility.PRIVATE)
        with person_logged_in(owner):
            branch = self.factory.makeBranch(
                owner=owner, information_type=InformationType.USERDATA
            )
            branch.setTarget(user=branch.owner)
            self.assertEqual(branch.owner, branch.target.context)

    def test_reconciles_access(self):
        # setTarget calls _reconcileAccess to make the sharing schema
        # match the new target.
        branch = self.factory.makeBranch(
            information_type=InformationType.USERDATA
        )
        new_product = self.factory.makeProduct()
        with admin_logged_in():
            branch.setTarget(user=branch.owner, project=new_product)
        self.assertEqual(
            new_product, get_policies_for_artifact(branch)[0].pillar
        )

    def test_reconciles_access_junk_branch(self):
        # setTarget calls _reconcileAccess to make the sharing schema
        # correct for a private junk branch.
        owner = self.factory.makeTeam(visibility=PersonVisibility.PRIVATE)
        with person_logged_in(owner):
            branch = self.factory.makeBranch(
                owner=owner, information_type=InformationType.USERDATA
            )
            branch.setTarget(user=branch.owner)
        self.assertEqual(owner, get_policies_for_artifact(branch)[0].person)

    def test_public_branch_to_proprietary_only_project(self):
        # A branch cannot be moved to a target where the sharing policy does
        # not allow it.
        owner = self.factory.makePerson()
        commercial_product = self.factory.makeProduct(
            owner=owner, branch_sharing_policy=BranchSharingPolicy.PROPRIETARY
        )
        branch = self.factory.makeBranch(
            owner=owner, information_type=InformationType.PUBLIC
        )
        with admin_logged_in():
            self.assertRaises(
                BranchTargetError,
                branch.setTarget,
                branch.owner,
                commercial_product,
            )


def make_proposal_and_branch_revision(
    factory, revno, revision_id, userdata_target=False
):
    if userdata_target:
        information_type = InformationType.USERDATA
    else:
        information_type = InformationType.PUBLIC
    target_branch = factory.makeAnyBranch(information_type=information_type)
    factory.makeBranchRevision(
        revision_id=revision_id, branch=target_branch, sequence=revno
    )
    return factory.makeBranchMergeProposal(
        merged_revno=revno, target_branch=target_branch
    )


class TestGetMergeProposalsWS(WebServiceTestCase):
    def test_getMergeProposals(self):
        """getMergeProposals works as expected over the API."""
        bmp = make_proposal_and_branch_revision(
            self.factory, 5, "rev-id", userdata_target=True
        )
        transaction.commit()
        user = removeSecurityProxy(bmp).target_branch.owner
        service = self.factory.makeLaunchpadService(
            user, version=self.ws_version
        )
        result = service.branches.getMergeProposals(merged_revision="rev-id")
        self.assertEqual([self.wsObject(bmp, user)], list(result))


class TestGetMergeProposals(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.branch_set = BranchSet()

    def test_getMergeProposals_with_no_merged_revno(self):
        """Merge proposals with no merged revno are not found."""
        make_proposal_and_branch_revision(self.factory, None, "rev-id")
        result = self.branch_set.getMergeProposals(merged_revision="rev-id")
        self.assertEqual([], list(result))

    def test_getMergeProposals_with_any_merged_revno(self):
        """Any arbitrary revno will connect a revid to a proposal."""
        bmp = make_proposal_and_branch_revision(
            self.factory, self.factory.getUniqueInteger(), "rev-id"
        )
        result = self.branch_set.getMergeProposals(merged_revision="rev-id")
        self.assertEqual([bmp], list(result))

    def test_getMergeProposals_correct_merged_revno(self):
        """Only proposals with the correct merged_revno match."""
        bmp1 = make_proposal_and_branch_revision(self.factory, 4, "rev-id")
        bmp2 = make_proposal_and_branch_revision(self.factory, 5, "other")
        result = self.branch_set.getMergeProposals(merged_revision="rev-id")
        self.assertEqual([bmp1], list(result))
        result = self.branch_set.getMergeProposals(merged_revision="other")
        self.assertEqual([bmp2], list(result))

    def test_getMergeProposals_correct_branch(self):
        """Only proposals with the correct branch match."""
        bmp1 = make_proposal_and_branch_revision(self.factory, 5, "rev-id")
        make_proposal_and_branch_revision(self.factory, 5, "other")
        result = self.branch_set.getMergeProposals(merged_revision="rev-id")
        self.assertEqual([bmp1], list(result))

    def test_getMergeProposals_skips_hidden(self):
        """Proposals not visible to the user are skipped."""
        make_proposal_and_branch_revision(
            self.factory, 5, "rev-id", userdata_target=True
        )
        result = self.branch_set.getMergeProposals(
            merged_revision="rev-id", visible_by_user=self.factory.makePerson()
        )
        self.assertEqual([], list(result))

    def test_getMergeProposals_shows_visible_userdata(self):
        """Proposals visible to the user are listed."""
        bmp = make_proposal_and_branch_revision(
            self.factory, 5, "rev-id", userdata_target=True
        )
        owner = removeSecurityProxy(bmp).target_branch.owner
        result = self.branch_set.getMergeProposals(
            merged_revision="rev-id", visible_by_user=owner
        )
        self.assertEqual([bmp], list(result))


class TestScheduleDiffUpdates(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_scheduleDiffUpdates(self):
        """Create jobs for all merge proposals."""
        bmp1 = self.factory.makeBranchMergeProposal()
        bmp2 = self.factory.makeBranchMergeProposal(
            source_branch=bmp1.source_branch
        )
        removeSecurityProxy(bmp1).target_branch.last_scanned_id = "rev1"
        removeSecurityProxy(bmp2).target_branch.last_scanned_id = "rev2"
        jobs = bmp1.source_branch.scheduleDiffUpdates()
        self.assertEqual(2, len(jobs))
        bmps_to_update = {
            removeSecurityProxy(job).branch_merge_proposal for job in jobs
        }
        self.assertEqual({bmp1, bmp2}, bmps_to_update)

    def test_scheduleDiffUpdates_ignores_final(self):
        """Diffs for proposals in final states aren't updated."""
        source_branch = self.factory.makeBranch()
        for state in FINAL_STATES:
            bmp = self.factory.makeBranchMergeProposal(
                source_branch=source_branch, set_state=state
            )
            removeSecurityProxy(bmp).target_branch.last_scanned_id = "rev"
        # Creating a superseded proposal has the side effect of creating a
        # second proposal.  Delete the second proposal.
        for bmp in source_branch.landing_targets:
            if bmp.queue_status not in FINAL_STATES:
                removeSecurityProxy(bmp).deleteProposal()
        jobs = source_branch.scheduleDiffUpdates()
        self.assertEqual(0, len(jobs))

    def test_scheduleDiffUpdates_ignores_unpushed_target(self):
        """Diffs aren't updated if target has no revisions."""
        bmp = self.factory.makeBranchMergeProposal()
        jobs = bmp.source_branch.scheduleDiffUpdates()
        self.assertEqual(0, len(jobs))


class TestBranchGetMainlineBranchRevisions(TestCaseWithFactory):
    """Tests for Branch.getMainlineBranchRevisions."""

    layer = DatabaseFunctionalLayer

    def test_start_date(self):
        # Revisions created before the start date are not returned.
        branch = self.factory.makeAnyBranch()
        epoch = datetime(2009, 9, 10, tzinfo=timezone.utc)
        # Add some revisions before the epoch.
        add_revision_to_branch(self.factory, branch, epoch - timedelta(days=1))
        new = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=1)
        )
        result = branch.getMainlineBranchRevisions(epoch)
        branch_revisions = [br for br, rev in result]
        self.assertEqual([new], branch_revisions)

    def test_end_date(self):
        # Revisions created after the end date are not returned.
        branch = self.factory.makeAnyBranch()
        epoch = datetime(2009, 9, 10, tzinfo=timezone.utc)
        end_date = epoch + timedelta(days=2)
        in_range = add_revision_to_branch(
            self.factory, branch, end_date - timedelta(days=1)
        )
        # Add some revisions after the end_date.
        add_revision_to_branch(
            self.factory, branch, end_date + timedelta(days=1)
        )
        result = branch.getMainlineBranchRevisions(epoch, end_date)
        branch_revisions = [br for br, rev in result]
        self.assertEqual([in_range], branch_revisions)

    def test_newest_first(self):
        # If oldest_first is False, the newest are returned first.
        branch = self.factory.makeAnyBranch()
        epoch = datetime(2009, 9, 10, tzinfo=timezone.utc)
        old = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=1)
        )
        new = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=2)
        )
        result = branch.getMainlineBranchRevisions(epoch, oldest_first=False)
        branch_revisions = [br for br, rev in result]
        self.assertEqual([new, old], branch_revisions)

    def test_oldest_first(self):
        # If oldest_first is True, the oldest are returned first.
        branch = self.factory.makeAnyBranch()
        epoch = datetime(2009, 9, 10, tzinfo=timezone.utc)
        old = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=1)
        )
        new = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=2)
        )
        result = branch.getMainlineBranchRevisions(epoch, oldest_first=True)
        branch_revisions = [br for br, rev in result]
        self.assertEqual([old, new], branch_revisions)

    def test_only_mainline_revisions(self):
        # Only mainline revisions are returned.
        branch = self.factory.makeAnyBranch()
        epoch = datetime(2009, 9, 10, tzinfo=timezone.utc)
        old = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=1)
        )
        # Add some non mainline revision.
        add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=2), mainline=False
        )
        new = add_revision_to_branch(
            self.factory, branch, epoch + timedelta(days=3)
        )
        result = branch.getMainlineBranchRevisions(epoch)
        branch_revisions = [br for br, rev in result]
        self.assertEqual([new, old], branch_revisions)


class TestGetBzrBranch(TestCaseWithFactory):
    """Tests for `IBranch.getBzrBranch`."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.useBzrBranches(direct_database=True)

    def test_simple(self):
        # open_only_scheme returns the underlying bzr branch of a database
        # branch in the simple, unstacked, case.
        db_branch, tree = self.create_branch_and_tree()
        # XXX: AaronBentley 2010-08-06 bug=614404: a bzr username is
        # required to generate the revision-id.
        with override_environ(BRZ_EMAIL="me@example.com"):
            revid = tree.commit("")
        bzr_branch = db_branch.getBzrBranch()
        self.assertEqual(revid, bzr_branch.last_revision())

    def test_acceptable_stacking(self):
        # If the underlying bzr branch of a database branch is stacked on
        # another launchpad branch open_only_scheme returns it.
        db_stacked_on, stacked_on_tree = self.create_branch_and_tree()
        db_stacked, stacked_tree = self.create_branch_and_tree()
        stacked_tree.branch.set_stacked_on_url("/" + db_stacked_on.unique_name)
        bzr_branch = db_stacked.getBzrBranch()
        self.assertEqual(
            "/" + db_stacked_on.unique_name, bzr_branch.get_stacked_on_url()
        )

    def test_unacceptable_stacking(self):
        # If the underlying bzr branch of a database branch is stacked on
        # a non-Launchpad url, it cannot be opened.
        branch = BzrDir.create_branch_convenience("local")
        db_stacked, stacked_tree = self.create_branch_and_tree()
        stacked_tree.branch.set_stacked_on_url(branch.base)
        self.assertRaises(BadUrl, db_stacked.getBzrBranch)


class TestBranchGetBlob(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_default_rev_unscanned(self):
        branch = self.factory.makeBranch()
        self.useFixture(BranchHostingFixture(blob=b"Some text"))
        blob = branch.getBlob("src/README.txt")
        self.assertEqual(b"Some text", blob)

    def test_default_rev_scanned(self):
        branch = self.factory.makeBranch()
        removeSecurityProxy(branch).last_scanned_id = "scanned-id"
        self.useFixture(BranchHostingFixture(blob=b"Some text"))
        blob = branch.getBlob("src/README.txt")
        self.assertEqual(b"Some text", blob)

    def test_with_rev(self):
        branch = self.factory.makeBranch()
        self.useFixture(BranchHostingFixture(blob=b"Some text"))
        blob = branch.getBlob("src/README.txt", revision_id="some-rev")
        self.assertEqual(b"Some text", blob)

    def test_file_at_root_of_branch(self):
        branch = self.factory.makeBranch()
        hosting_fixture = self.useFixture(
            BranchHostingFixture(blob=b"Some text")
        )
        blob = branch.getBlob("README.txt", revision_id="some-rev")
        self.assertEqual(b"Some text", blob)
        self.assertEqual(
            [((branch.id, "README.txt"), {"rev": "some-rev"})],
            hosting_fixture.getBlob.calls,
        )

    def test_missing_directory(self):
        branch = self.factory.makeBranch()
        hosting_fixture = self.useFixture(BranchHostingFixture())
        hosting_fixture.getBlob = FakeMethod(
            failure=BranchFileNotFound(
                branch.unique_name, filename="src", rev="some-rev"
            )
        )
        self.assertRaises(
            BranchFileNotFound,
            branch.getBlob,
            "src/README.txt",
            revision_id="some-rev",
        )


class TestBranchUnscan(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_unscan(self):
        # Unscanning a branch resets the scan data, including the
        # BranchRevisions, last_scanned_id and revision_count.
        branch = self.factory.makeAnyBranch()
        self.factory.makeRevisionsForBranch(branch=branch)
        head = branch.getBranchRevision(revision_id=branch.last_scanned_id)
        self.assertEqual(5, head.sequence)
        self.assertEqual(5, branch.revision_count)

        with person_logged_in(branch.owner):
            self.assertEqual(
                (head.revision.revision_id, head.revision.revision_id),
                branch.unscan(),
            )
        transaction.commit()

        self.assertIs(None, branch.last_scanned_id)
        self.assertEqual(0, branch.revision_count)
        self.assertRaises(LostObjectError, getattr, head, "sequence")

    def test_rescan(self):
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            0, Store.of(branch).find(BranchJob, branch=branch).count()
        )
        with person_logged_in(branch.owner):
            branch.unscan(rescan=True)
        self.assertEqual(
            1, Store.of(branch).find(BranchJob, branch=branch).count()
        )

    def test_no_rescan(self):
        branch = self.factory.makeAnyBranch()
        self.assertEqual(
            0, Store.of(branch).find(BranchJob, branch=branch).count()
        )
        with person_logged_in(branch.owner):
            branch.unscan(rescan=False)
        self.assertEqual(
            0, Store.of(branch).find(BranchJob, branch=branch).count()
        )

    def test_security(self):
        branch = self.factory.makeAnyBranch()

        # Random users can't unscan a branch.
        with person_logged_in(self.factory.makePerson()):
            self.assertRaises(Unauthorized, getattr, branch, "unscan")

        # But the owner can.
        with person_logged_in(branch.owner):
            branch.unscan()

        # And so can commercial-admins (and maybe registry too,
        # eventually).
        with person_logged_in(
            getUtility(ILaunchpadCelebrities).commercial_admin
        ):
            branch.unscan()

    def test_getLatestScanJob(self):
        complete_date = datetime.now(timezone.utc)

        branch = self.factory.makeAnyBranch()
        failed_job = BranchScanJob.create(branch)
        failed_job.job._status = JobStatus.FAILED
        failed_job.job.date_finished = complete_date
        completed_job = BranchScanJob.create(branch)
        completed_job.job._status = JobStatus.COMPLETED
        completed_job.job.date_finished = complete_date - timedelta(seconds=10)
        result = branch.getLatestScanJob()
        self.assertEqual(failed_job.id, result.id)

    def test_getLatestScanJob_no_scans(self):
        branch = self.factory.makeAnyBranch()
        result = branch.getLatestScanJob()
        self.assertIsNone(result)

    def test_getLatestScanJob_correct_branch(self):
        complete_date = datetime.now(timezone.utc)

        main_branch = self.factory.makeAnyBranch()
        second_branch = self.factory.makeAnyBranch()
        failed_job = BranchScanJob.create(second_branch)
        failed_job.job._status = JobStatus.FAILED
        failed_job.job.date_finished = complete_date
        completed_job = BranchScanJob.create(main_branch)
        completed_job.job._status = JobStatus.COMPLETED
        completed_job.job.date_finished = complete_date - timedelta(seconds=10)
        result = main_branch.getLatestScanJob()
        self.assertEqual(completed_job.id, result.id)

    def test_getLatestScanJob_without_completion_date(self):
        branch = self.factory.makeAnyBranch()
        failed_job = BranchScanJob.create(branch)
        failed_job.job._status = JobStatus.FAILED
        result = branch.getLatestScanJob()
        self.assertTrue(result)
        self.assertIsNone(result.job.date_finished)


class TestWebservice(TestCaseWithFactory):
    """Tests for the webservice."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.branch_db = self.factory.makeBranch()
        self.branch_url = api_url(self.branch_db)
        self.webservice = webservice_for_person(
            self.branch_db.owner, permission=OAuthPermission.WRITE_PUBLIC
        )

    def test_transitionToInformationType(self):
        """Test transitionToInformationType() API arguments."""
        self.webservice.named_post(
            self.branch_url,
            "transitionToInformationType",
            information_type="Private Security",
            api_version="devel",
        )
        with admin_logged_in():
            self.assertEqual(
                "Private Security", self.branch_db.information_type.title
            )

    def test_unscan(self):
        """Test unscan() API call."""
        with admin_logged_in():
            self.assertEqual(
                0, len(list(getUtility(IBranchScanJobSource).iterReady()))
            )
        self.webservice.named_post(
            self.branch_url, "unscan", rescan=True, api_version="devel"
        )
        with admin_logged_in():
            self.assertEqual(
                1, len(list(getUtility(IBranchScanJobSource).iterReady()))
            )


load_tests = load_tests_apply_scenarios
