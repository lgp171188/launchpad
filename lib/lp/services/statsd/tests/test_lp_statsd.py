# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the Launchpad statsd client"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from statsd import StatsClient

from lp.services.config import config
from lp.services.statsd import (
    get_statsd_client,
    UnconfiguredStatsdClient,
    )
from lp.testing import TestCase
from lp.testing.layers import BaseLayer


class TestClientConfiguration(TestCase):

    layer = BaseLayer

    def test_get_correct_instance_unconfigured(self):
        """Test that we get the correct client, depending on config values."""
        config.push(
            'statsd_test',
            "[statsd]\nhost:")
        client = get_statsd_client()
        self.assertEqual(
            type(client), UnconfiguredStatsdClient)

    def test_get_correct_instance_configured(self):
        config.push(
            'statsd_test',
            "[statsd]\nhost: 127.0.01\nport: 9999\nprefix: test\n")
        client = get_statsd_client()
        self.assertEqual(
            type(client), StatsClient)
