# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for feature flag change log."""

from datetime import datetime, timezone

from lp.services.features.changelog import ChangeLog
from lp.services.features.model import FeatureFlagChangelogEntry
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer

diff = (
    "-bugs.new_feature team:testers 10 on\n"
    "+bugs.new_feature team:testers 10 off"
)


class TestFeatureFlagChangelogEntry(TestCaseWithFactory):
    """Test the FeatureFlagChangelogEntry data."""

    layer = DatabaseFunctionalLayer

    def test_FeatureFlagChangelogEntry_creation(self):
        # A FeatureFlagChangelogEntry has a diff and a date of change.
        person = self.factory.makePerson()
        before = datetime.now(timezone.utc)
        feature_flag_change = FeatureFlagChangelogEntry(
            diff, "comment", person
        )
        after = datetime.now(timezone.utc)
        self.assertEqual(diff, feature_flag_change.diff)
        self.assertEqual("comment", feature_flag_change.comment)
        self.assertEqual(person, feature_flag_change.person)
        self.assertBetween(before, feature_flag_change.date_changed, after)


class TestChangeLog(TestCaseWithFactory):
    """Test the feature flag ChangeLog utility."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()

    def test_ChangeLog_append(self):
        # The append() method creates a FeatureFlagChangelogEntry.
        feature_flag_change = ChangeLog.append(diff, "comment", self.person)
        self.assertEqual(diff, feature_flag_change.diff)
        self.assertEqual("comment", feature_flag_change.comment)
        self.assertEqual(self.person, feature_flag_change.person)

    def test_ChangeLog_get(self):
        # The get() method returns an iterator of FeatureFlagChanges from
        # newest to oldest.
        feature_flag_change_1 = ChangeLog.append(diff, "comment", self.person)
        feature_flag_change_2 = ChangeLog.append(diff, "comment", self.person)
        results = ChangeLog.get()
        self.assertEqual(
            [feature_flag_change_2, feature_flag_change_1], list(results)
        )
