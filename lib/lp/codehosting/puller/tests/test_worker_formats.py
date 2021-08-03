# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the puller's support for various Bazaar formats."""

__metaclass__ = type

from breezy.branch import Branch
from breezy.bzr.bzrdir import BzrDirMetaFormat1
from breezy.bzr.knitpack_repo import RepositoryFormatKnitPack5
from breezy.bzr.knitrepo import RepositoryFormatKnit1
from breezy.plugins.weave_fmt.bzrdir import BzrDirFormat6
from breezy.plugins.weave_fmt.repository import (
    RepositoryFormat6,
    RepositoryFormat7,
    )
from breezy.tests.per_repository import TestCaseWithRepository
from breezy.url_policy_open import BranchOpener

import lp.codehosting  # noqa: F401  # For brz plugins.
from lp.codehosting.puller.tests import PullerWorkerMixin
from lp.codehosting.tests.helpers import LoomTestMixin


class TestPullerWorkerFormats(TestCaseWithRepository, PullerWorkerMixin,
                              LoomTestMixin):

    def setUp(self):
        TestCaseWithRepository.setUp(self)
        # make_controldir relies on this being a relative filesystem path.
        self._source_branch_path = 'source-branch'
        BranchOpener.install_hook()
        self.worker = self.makePullerWorker(
            self.get_url(self._source_branch_path),
            self.get_url('dest-path'))

    def _createSourceBranch(self, repository_format, bzrdir_format,
                            branch_format=None):
        """Make a source branch with the given formats."""
        if branch_format is not None:
            bzrdir_format.set_branch_format(branch_format)
        bd = self.make_controldir(
            self._source_branch_path, format=bzrdir_format)
        repository_format.initialize(bd)
        branch = bd.create_branch()
        tree = branch.create_checkout('source-checkout')
        tree.commit('Commit message')
        self.get_transport().delete_tree('source-checkout')
        return branch

    def assertMirrored(self, source_branch, dest_branch):
        """Assert that `dest_branch` is a mirror of `src_branch`."""
        self.assertEqual(
            source_branch.last_revision(), dest_branch.last_revision())
        # Assert that the mirrored branch is in source's format
        # XXX AndrewBennetts 2006-05-18 bug=45277: comparing format objects
        # is ugly.
        self.assertEqual(
            source_branch.repository._format.get_format_description(),
            dest_branch.repository._format.get_format_description())
        self.assertEqual(
            source_branch.controldir._format.get_format_description(),
            dest_branch.controldir._format.get_format_description())

    def _testMirrorWithFormats(self, repository_format, bzrdir_format):
        """Make a branch with certain formats, mirror it and check the mirror.

        :param repository_format: The repository format.
        :param bzrdir_format: The bzrdir format.
        """
        src_branch = self._createSourceBranch(
            repository_format, bzrdir_format)
        self.worker.mirror()
        dest_branch = Branch.open(self.worker.dest)
        self.assertMirrored(src_branch, dest_branch)

    def test_loomBranch(self):
        # When we mirror a loom branch for the first time, the mirrored loom
        # branch matches the original.
        branch = self._createSourceBranch(
            RepositoryFormatKnitPack5(),
            BzrDirMetaFormat1())
        self.loomify(branch)
        self.worker.mirror()
        mirrored_branch = Branch.open(self.worker.dest)
        self.assertMirrored(branch, mirrored_branch)

    # XXX: JonathanLange 2008-06-25: These next three tests should be
    # implemented against all supported repository formats using breezy's test
    # adaptation APIs.
    def testMirrorKnitAsKnit(self):
        # Create a source branch in knit format, and check that the mirror is
        # in knit format.
        self._testMirrorWithFormats(
            RepositoryFormatKnit1(), BzrDirMetaFormat1())

    def testMirrorMetaweaveAsMetaweave(self):
        # Create a source branch in metaweave format, and check that the
        # mirror is in metaweave format.
        self._testMirrorWithFormats(RepositoryFormat7(), BzrDirMetaFormat1())

    def testMirrorWeaveAsWeave(self):
        # Create a source branch in weave format, and check that the mirror is
        # in weave format.
        self._testMirrorWithFormats(RepositoryFormat6(), BzrDirFormat6())

    def testSourceFormatChange(self):
        # If a branch that has already been mirrored changes format, then we
        # when we re-mirror the branch, the mirror will acquire the new
        # format.

        # Create and mirror a branch in weave format.
        self._createSourceBranch(RepositoryFormat7(), BzrDirMetaFormat1())
        self.worker.mirror()

        # Change the branch to knit format and mirror again.
        self.get_transport().delete_tree(self._source_branch_path)
        self._createSourceBranch(RepositoryFormatKnit1(), BzrDirMetaFormat1())
        self.worker.mirror()

        # The mirrored branch should now be in knit format.
        self.assertMirrored(
            Branch.open(self.worker.source), Branch.open(self.worker.dest))
