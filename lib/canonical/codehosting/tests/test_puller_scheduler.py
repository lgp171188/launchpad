import logging
import os
import shutil
import tempfile
import unittest

import bzrlib

from canonical.config import config
from canonical.launchpad.interfaces import BranchType
from canonical.codehosting import branch_id_to_path
from canonical.codehosting.puller.branchtomirror import BranchToMirror
from canonical.codehosting.tests.helpers import create_branch
from canonical.codehosting.puller import jobmanager
from canonical.authserver.client.branchstatus import BranchStatusClient
from canonical.authserver.tests.harness import AuthserverTacTestSetup
from canonical.testing import LaunchpadFunctionalLayer, reset_logging


class TestJobManager(unittest.TestCase):

    def setUp(self):
        self.masterlock = 'master.lock'
        # We set the log level to CRITICAL so that the log messages
        # are suppressed.
        logging.basicConfig(level=logging.CRITICAL)

    def tearDown(self):
        reset_logging()

    def makeFakeClient(self, hosted, mirrored, imported):
        return FakeBranchStatusClient(
            {'HOSTED': hosted, 'MIRRORED': mirrored, 'IMPORTED': imported})

    def testEmptyAddBranches(self):
        fakeclient = self.makeFakeClient([], [], [])
        manager = jobmanager.JobManager(BranchType.HOSTED)
        manager.addBranches(fakeclient)
        self.assertEqual([], manager.branches_to_mirror)

    def testSingleAddBranches(self):
        # Get a list of branches and ensure that it can add a branch object.
        expected_branch = BranchToMirror(
            src='managersingle',
            dest=config.supermirror.branchesdest + '/00/00/00/00',
            branch_status_client=None, branch_id=None, unique_name=None,
            branch_type=None)
        fakeclient = self.makeFakeClient(
            [(0, 'managersingle', u'name//trunk')], [], [])
        manager = jobmanager.JobManager(BranchType.HOSTED)
        manager.addBranches(fakeclient)
        self.assertEqual([expected_branch], manager.branches_to_mirror)

    def testManagerCreatesLocks(self):
        try:
            manager = jobmanager.JobManager(BranchType.HOSTED)
            manager.lockfilename = self.masterlock
            manager.lock()
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def testManagerEnforcesLocks(self):
        try:
            manager = jobmanager.JobManager(BranchType.HOSTED)
            manager.lockfilename = self.masterlock
            manager.lock()
            anothermanager = jobmanager.JobManager(BranchType.HOSTED)
            anothermanager.lockfilename = self.masterlock
            self.assertRaises(jobmanager.LockError, anothermanager.lock)
            self.failUnless(os.path.exists(self.masterlock))
            manager.unlock()
        finally:
            self._removeLockFile()

    def _removeLockFile(self):
        if os.path.exists(self.masterlock):
            os.unlink(self.masterlock)

    def testImportAddBranches(self):
        client = self.makeFakeClient(
            [], [],
            [(14, 'http://escudero.ubuntu.com:680/0000000e',
              'vcs-imports//main')])
        import_manager = jobmanager.JobManager(BranchType.IMPORTED)
        import_manager.addBranches(client)
        expected_branch = BranchToMirror(
            src='http://escudero.ubuntu.com:680/0000000e',
            dest=config.supermirror.branchesdest + '/00/00/00/0e',
            branch_status_client=None, branch_id=None, unique_name=None,
            branch_type=None)
        self.assertEqual(import_manager.branches_to_mirror, [expected_branch])
        branch_types = [branch.branch_type
                        for branch in import_manager.branches_to_mirror]
        self.assertEqual(branch_types, [BranchType.IMPORTED])

    def testUploadAddBranches(self):
        client = self.makeFakeClient(
            [(25, '/tmp/sftp-test/branches/00/00/00/19', u'name12//pushed')],
            [], [])
        upload_manager = jobmanager.JobManager(BranchType.HOSTED)
        upload_manager.addBranches(client)
        expected_branch = BranchToMirror(
            src='/tmp/sftp-test/branches/00/00/00/19',
            dest=config.supermirror.branchesdest + '/00/00/00/19',
            branch_status_client=None, branch_id=None, unique_name=None,
            branch_type=None)
        self.assertEqual(upload_manager.branches_to_mirror, [expected_branch])
        branch_types = [branch.branch_type
                        for branch in upload_manager.branches_to_mirror]
        self.assertEqual(branch_types, [BranchType.HOSTED])

    def testMirrorAddBranches(self):
        client = self.makeFakeClient(
            [],
            [(15, 'http://example.com/gnome-terminal/main', u'name12//main')],
            [])
        mirror_manager = jobmanager.JobManager(BranchType.MIRRORED)
        mirror_manager.addBranches(client)
        expected_branch = BranchToMirror(
            src='http://example.com/gnome-terminal/main',
            dest=config.supermirror.branchesdest + '/00/00/00/0f',
            branch_status_client=None, branch_id=None, unique_name=None,
            branch_type=None)
        self.assertEqual(mirror_manager.branches_to_mirror, [expected_branch])
        branch_types = [branch.branch_type
                        for branch in mirror_manager.branches_to_mirror]
        self.assertEqual(branch_types, [BranchType.MIRRORED])


class TestJobManagerInLaunchpad(unittest.TestCase):
    layer = LaunchpadFunctionalLayer

    testdir = None

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        # Change the HOME environment variable in order to ignore existing
        # user config files.
        os.environ.update({'HOME': self.test_dir})
        self.authserver = AuthserverTacTestSetup()
        self.authserver.setUp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        self.authserver.tearDown()

    def _getBranchDir(self, branchname):
        return os.path.join(self.test_dir, branchname)

    def assertMirrored(self, branch_to_mirror):
        """Assert that branch_to_mirror's source and destinations have the same
        revisions.

        :param branch_to_mirror: a BranchToMirror instance.
        """
        source_branch = bzrlib.branch.Branch.open(branch_to_mirror.source)
        dest_branch = bzrlib.branch.Branch.open(branch_to_mirror.dest)
        self.assertEqual(source_branch.last_revision(),
                         dest_branch.last_revision())

    def testJobRunner(self):
        manager = jobmanager.JobManager(BranchType.HOSTED)
        self.assertEqual(len(manager.branches_to_mirror), 0)

        client = BranchStatusClient()
        branches = [
            self._makeBranch("brancha", 1, client),
            self._makeBranch("branchb", 2, client),
            self._makeBranch("branchc", 3, client),
            self._makeBranch("branchd", 4, client),
            self._makeBranch("branche", 5, client)]

        manager.branches_to_mirror.extend(branches)

        manager.run(logging.getLogger())

        self.assertEqual(len(manager.branches_to_mirror), 0)
        for branch in branches:
            self.assertMirrored(branch)

    def _makeBranch(self, relative_dir, target, branch_status_client,
                    unique_name=None):
        """Given a relative directory, make a strawman branch and return it.

        @param relativedir - The directory to make the branch
        @output BranchToMirror - A branch object representing the strawman
                                    branch
        """
        branch_dir = os.path.join(self.test_dir, relative_dir)
        create_branch(branch_dir)
        if target == None:
            target_dir = None
        else:
            target_dir = os.path.join(
                self.test_dir, branch_id_to_path(target))
        return BranchToMirror(
                branch_dir, target_dir, branch_status_client, target,
                unique_name, branch_type=None)


class FakeBranchStatusClient:
    """A dummy branch status client implementation for testing getBranches()"""

    def __init__(self, branch_queues):
        self.branch_queues = branch_queues

    def getBranchPullQueue(self, branch_type):
        return self.branch_queues[branch_type]


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

