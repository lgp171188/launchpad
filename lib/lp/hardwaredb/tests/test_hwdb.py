# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the hardware database model."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

from lp.hardwaredb.interfaces.hwdb import (
    HWDB_SUBMISSIONS_DISABLED_FEATURE_FLAG,
    HWSubmissionsDisabledError,
    )
from lp.services.features.testing import FeatureFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestHWDBFeatureFlag(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def test_feature_flag_disables_submissions(self):
        # Launchpad's hardware database is obsolescent.  We have a feature
        # flag to stage the removal of support for new submissions.
        with FeatureFixture({HWDB_SUBMISSIONS_DISABLED_FEATURE_FLAG: "on"}):
            self.assertRaises(
                HWSubmissionsDisabledError, self.factory.makeHWSubmission)
