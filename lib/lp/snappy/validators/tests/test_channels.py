# Copyright 2017-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from lp.app.validators import LaunchpadValidationError
from lp.snappy.validators.channels import channels_validator
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadFunctionalLayer


class TestChannelsValidator(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_channels_validator_valid(self):
        self.assertTrue(
            channels_validator(["1.1/beta/fix-123", "1.1/edge/fix-123"])
        )
        self.assertTrue(channels_validator(["1.1/beta", "1.1/edge"]))
        self.assertTrue(channels_validator(["beta/fix-123", "edge/fix-123"]))
        self.assertTrue(channels_validator(["beta", "edge"]))

    def test_channels_validator_multiple_tracks(self):
        self.assertTrue(channels_validator(["1.1/stable", "2.1/edge"]))

    def test_channels_validator_multiple_branches(self):
        self.assertTrue(channels_validator(["stable/fix-123", "edge/fix-124"]))

    def test_channels_validator_invalid_channel(self):
        self.assertRaises(
            LaunchpadValidationError,
            channels_validator,
            ["1.1/stable/invalid/too-long"],
        )
