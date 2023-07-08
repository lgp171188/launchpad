# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for handling of channels in Canonical's stores."""

from lp.services.channels import channel_list_to_string, channel_string_to_list
from lp.testing import TestCase
from lp.testing.layers import BaseLayer


class TestChannels(TestCase):
    layer = BaseLayer

    def test_channel_string_to_list_no_track_or_branch(self):
        self.assertEqual((None, "edge", None), channel_string_to_list("edge"))

    def test_channel_string_to_list_with_track(self):
        self.assertEqual(
            ("track", "edge", None), channel_string_to_list("track/edge")
        )

    def test_channel_string_to_list_with_branch(self):
        self.assertEqual(
            (None, "edge", "fix-123"), channel_string_to_list("edge/fix-123")
        )

    def test_channel_string_to_list_with_track_and_branch(self):
        self.assertEqual(
            ("track", "edge", "fix-123"),
            channel_string_to_list("track/edge/fix-123"),
        )

    def test_channel_string_to_list_no_risk(self):
        self.assertRaisesWithContent(
            ValueError,
            "No valid risk provided: 'track/fix-123'",
            channel_string_to_list,
            "track/fix-123",
        )

    def test_channel_string_to_list_ambiguous_risk(self):
        self.assertRaisesWithContent(
            ValueError,
            "Branch name cannot match a risk name: 'edge/stable'",
            channel_string_to_list,
            "edge/stable",
        )

    def test_channel_string_to_list_too_many_components(self):
        self.assertRaisesWithContent(
            ValueError,
            "Invalid channel name: 'track/edge/invalid/too-long'",
            channel_string_to_list,
            "track/edge/invalid/too-long",
        )

    def test_channel_list_to_string_no_track_or_branch(self):
        self.assertEqual("edge", channel_list_to_string(None, "edge", None))

    def test_channel_list_to_string_with_track(self):
        self.assertEqual(
            "track/edge", channel_list_to_string("track", "edge", None)
        )

    def test_channel_list_to_string_with_branch(self):
        self.assertEqual(
            "edge/fix-123", channel_list_to_string(None, "edge", "fix-123")
        )

    def test_channel_list_to_string_with_track_and_branch(self):
        self.assertEqual(
            "track/edge/fix-123",
            channel_list_to_string("track", "edge", "fix-123"),
        )
