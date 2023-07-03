# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the Launchpad statsd client"""

from statsd import StatsClient
from zope.component import getUtility

from lp.services.config import config
from lp.services.statsd.interfaces.statsd_client import IStatsdClient
from lp.testing import TestCase
from lp.testing.layers import ZopelessLayer


class TestClientConfiguration(TestCase):
    layer = ZopelessLayer

    def test_accessible_via_utility(self):
        """Test that we can access the class via a zope utility."""
        client = getUtility(IStatsdClient)
        self.addCleanup(client.reload)
        config.push(
            "statsd_test",
            "[statsd]\nhost: 127.0.01\n"
            "port: 9999\nprefix: test\nenvironment: test\n",
        )
        client.reload()
        self.assertIsInstance(client._client, StatsClient)

    def test_get_correct_instance_unconfigured(self):
        """Test that we get the correct client, depending on config values."""
        client = getUtility(IStatsdClient)
        self.addCleanup(client.reload)
        config.push("statsd_test", "[statsd]\nhost:")
        client.reload()
        self.assertIsNone(client._client)

    def test_get_correct_instance_configured(self):
        client = getUtility(IStatsdClient)
        self.addCleanup(client.reload)
        config.push(
            "statsd_test",
            "[statsd]\nhost: 127.0.01\n"
            "port: 9999\nprefix: test\nenvironment: test\n",
        )
        client.reload()
        self.assertIsInstance(client._client, StatsClient)
