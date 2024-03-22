# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests of the branch interface."""

from breezy.branch import format_registry as branch_format_registry
from breezy.bzr import BzrProber
from breezy.repository import format_registry as repo_format_registry

import lp.codehosting  # noqa: F401  # For plugins.
from lp.code.bzr import BranchFormat, ControlFormat, RepositoryFormat
from lp.testing import TestCase


class TestFormatSupport(TestCase):
    """Ensure the launchpad format list is up-to-date.

    While ideally we would ensure that the lists of markers were the same,
    early branch and repo formats did not use markers.  (The branch/repo
    was implied by the control dir format.)
    """

    def test_control_format_complement(self):
        self.breezy_is_subset(BzrProber.formats.keys(), ControlFormat)

    def test_branch_format_complement(self):
        self.breezy_is_subset(branch_format_registry.keys(), BranchFormat)

    def test_repository_format_complement(self):
        self.breezy_is_subset(repo_format_registry.keys(), RepositoryFormat)

    def breezy_is_subset(self, breezy_formats, launchpad_enum):
        """Ensure the Breezy format marker list is a subset of Launchpad."""
        breezy_format_strings = set(breezy_formats)
        launchpad_format_strings = {
            format.title.encode() for format in launchpad_enum.items
        }
        self.assertEqual(
            set(), breezy_format_strings.difference(launchpad_format_strings)
        )

    def test_repositoryDescriptions(self):
        self.checkDescriptions(RepositoryFormat)

    def test_branchDescriptions(self):
        self.checkDescriptions(BranchFormat)

    def test_controlDescriptions(self):
        self.checkDescriptions(ControlFormat)

    def checkDescriptions(self, format_enums):
        for item in format_enums.items:
            description = item.description
            if description.endswith("\n"):
                description = description[:-1]
            self.assertTrue(
                len(description.split("\n")) == 1, item.description
            )
