# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Tests for foreign branch support."""

__metaclass__ = type

import os
import time
import unittest

import CVS
import pysvn

from bzrlib.tests import TestCaseWithTransport

from lp.codehosting.codeimport.foreigntree import (
    CVSWorkingTree, SubversionWorkingTree)
from lp.codehosting.codeimport.tests.servers import (
    CVSServer, SubversionServer)
from canonical.testing import BaseLayer


class TestSubversionWorkingTree(TestCaseWithTransport):

    layer = BaseLayer

    def assertIsUpToDate(self, original_url, new_path):
        """Assert that a Subversion working tree is up to date.

        :param original_url: The URL of the Subversion branch.
        :param new_path: The path of the checkout.
        """
        client = pysvn.Client()
        [(path, local_info)] = client.info2(new_path, recurse=False)
        [(path, remote_info)] = client.info2(original_url, recurse=False)
        self.assertEqual(original_url, local_info['URL'])
        self.assertEqual(remote_info['rev'].number, local_info['rev'].number)

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        svn_server = SubversionServer('repository_path')
        svn_server.setUp()
        self.addCleanup(svn_server.tearDown)
        self.svn_branch_url = svn_server.makeBranch(
            'trunk', [('README', 'original')])

    def test_path(self):
        # The local path is passed to the constructor is available as
        # 'local_path'.
        tree = SubversionWorkingTree('url', 'path')
        self.assertEqual(tree.local_path, 'path')

    def test_url(self):
        # The URL of the repository is available as 'remote_url'.
        tree = SubversionWorkingTree('url', 'path')
        self.assertEqual(tree.remote_url, 'url')

    def test_checkout(self):
        # checkout() checks out an up-to-date working tree to the local path.
        tree = SubversionWorkingTree(self.svn_branch_url, 'tree')
        tree.checkout()
        self.assertIsUpToDate(self.svn_branch_url, tree.local_path)

    def test_update(self):
        # update() fetches any changes to the branch from the remote branch.
        # We test this by checking out the same branch twice, making
        # modifications in one, then updating the other. If the modifications
        # appear, then update() works.
        tree = SubversionWorkingTree(self.svn_branch_url, 'tree')
        tree.checkout()

        tree2 = SubversionWorkingTree(self.svn_branch_url, 'tree2')
        tree2.checkout()

        # Make a change.
        # XXX: JonathanLange 2008-02-19: "README" is a mystery guest.
        new_content = 'Comfort ye\n'
        self.build_tree_contents([('tree/README', new_content)])
        tree.commit()

        tree2.update()
        readme_path = os.path.join(tree2.local_path, 'README')
        self.assertFileEqual(new_content, readme_path)

    def test_update_ignores_externals(self):
        # update() ignores svn:externals.
        # We test this in a similar way to test_update, by getting two trees,
        # mutating one and checking its effect on the other tree -- though
        # here we are hoping for no effect.
        tree = SubversionWorkingTree(self.svn_branch_url, 'tree')
        tree.checkout()

        tree2 = SubversionWorkingTree(self.svn_branch_url, 'tree2')
        tree2.checkout()

        client = pysvn.Client()
        client.propset(
            'svn:externals', 'external http://foo.invalid/svn/something',
            tree.local_path)
        tree.commit()

        tree2.update()


class TestCVSWorkingTree(TestCaseWithTransport):

    layer = BaseLayer

    def assertHasCheckout(self, cvs_working_tree):
        """Assert that `cvs_working_tree` has a checkout of its CVS module."""
        tree = CVS.tree(os.path.abspath(cvs_working_tree.local_path))
        repository = tree.repository()
        self.assertEqual(repository.root, cvs_working_tree.root)
        self.assertEqual(tree.module().name(), cvs_working_tree.module)

    def makeCVSWorkingTree(self, local_path):
        """Make a CVS working tree for testing."""
        return CVSWorkingTree(
            self.cvs_server.getRoot(), self.module_name, local_path)

    def setUp(self):
        TestCaseWithTransport.setUp(self)
        self.cvs_server = CVSServer('repository_path')
        self.cvs_server.setUp()
        self.module_name = 'test_module'
        self.cvs_server.makeModule(
            self.module_name, [('README', 'Random content\n')])
        self.addCleanup(self.cvs_server.tearDown)

    def test_path(self):
        # The local path is passed to the constructor and available as
        # 'local_path'.
        tree = CVSWorkingTree('root', 'module', 'path')
        self.assertEqual(tree.local_path, os.path.abspath('path'))

    def test_module(self):
        # The module is passed to the constructor and available as 'module'.
        tree = CVSWorkingTree('root', 'module', 'path')
        self.assertEqual(tree.module, 'module')

    def test_root(self):
        # The root is passed to the constructor and available as 'root'.
        tree = CVSWorkingTree('root', 'module', 'path')
        self.assertEqual(tree.root, 'root')

    def test_checkout(self):
        # checkout() checks out an up-to-date working tree.
        tree = self.makeCVSWorkingTree('working_tree')
        tree.checkout()
        self.assertHasCheckout(tree)

    def test_commit(self):
        # commit() makes local changes available to other checkouts.
        tree = self.makeCVSWorkingTree('working_tree')
        tree.checkout()

        # If you write to a file in the same second as the previous commit,
        # CVS will not think that it has changed.
        time.sleep(1)

        # Make a change.
        new_content = 'Comfort ye\n'
        readme = open(os.path.join(tree.local_path, 'README'), 'w')
        readme.write(new_content)
        readme.close()
        self.assertFileEqual(new_content, 'working_tree/README')

        # Commit the change.
        tree.commit()

        tree2 = self.makeCVSWorkingTree('working_tree2')
        tree2.checkout()

        self.assertFileEqual(new_content, 'working_tree2/README')


    def test_update(self):
        # update() fetches any changes to the branch from the remote branch.
        # We test this by checking out the same branch twice, making
        # modifications in one, then updating the other. If the modifications
        # appear, then update() works.
        tree = self.makeCVSWorkingTree('working_tree')
        tree.checkout()

        tree2 = self.makeCVSWorkingTree('working_tree2')
        tree2.checkout()

        # If you write to a file in the same second as the previous commit,
        # CVS will not think that it has changed.
        time.sleep(1)

        # Make a change.
        new_content = 'Comfort ye\n'
        self.build_tree_contents([('working_tree/README', new_content)])

        # Commit the change.
        tree.commit()

        # Update.
        tree2.update()
        readme_path = os.path.join(tree2.local_path, 'README')
        self.assertFileEqual(new_content, readme_path)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
