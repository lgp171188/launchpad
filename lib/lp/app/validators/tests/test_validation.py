# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for field validators"""

from lp.app.validators.validation import validate_oci_branch_name
from lp.testing import TestCase
from lp.testing.layers import BaseLayer


class TestOCIBranchValidator(TestCase):
    layer = BaseLayer

    def test_validate_oci_branch_name_with_leading_slash(self):
        self.assertFalse(validate_oci_branch_name("/refs/heads/v2.1.0-20.04"))

    def test_validate_oci_branch_name_full(self):
        self.assertTrue(validate_oci_branch_name("refs/heads/v2.1.0-20.04"))

    def test_validate_oci_branch_name_just_branch_name(self):
        self.assertTrue(validate_oci_branch_name("v2.1.0-20.04"))

    def test_validate_oci_branch_name_failure(self):
        self.assertFalse(validate_oci_branch_name("notvalidbranch"))

    def test_validate_oci_branch_name_invalid_ubuntu_version(self):
        self.assertFalse(validate_oci_branch_name("v2.1.0-ubuntu20.04"))

    def test_validate_oci_branch_name_invalid_delimiter(self):
        self.assertFalse(validate_oci_branch_name("v2/1.0-20.04"))

    def test_validate_oci_branch_name_tag(self):
        self.assertTrue(validate_oci_branch_name("refs/tags/v2-1.0-20.04"))

    def test_validate_oci_branch_name_heads_and_tags(self):
        self.assertFalse(
            validate_oci_branch_name("refs/heads/refs/tags/v1.0-20.04")
        )
