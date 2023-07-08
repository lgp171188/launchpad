# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the IMemcacheClient utility."""

from unittest.mock import patch

from lazr.restful.utils import get_current_browser_request
from pymemcache.exceptions import MemcacheError, MemcacheIllegalInputError
from zope.component import getUtility

from lp.services.log.logger import BufferLogger
from lp.services.memcache.client import memcache_client_factory
from lp.services.memcache.interfaces import IMemcacheClient
from lp.services.memcache.testing import MemcacheFixture
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.testing import TestCase
from lp.testing.layers import LaunchpadZopelessLayer


class MemcacheClientTestCase(TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.client = getUtility(IMemcacheClient)

    def test_basics(self):
        self.assertTrue(self.client.set("somekey", "somevalue"))
        self.assertEqual(self.client.get("somekey"), "somevalue")

    def test_key_with_spaces_are_illegal(self):
        """Memcache 1.44 allowed spaces in keys, which was incorrect."""
        self.assertRaises(
            MemcacheIllegalInputError,
            self.client.set,
            "key with spaces",
            "some value",
        )

    def test_set_recorded_to_timeline(self):
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        self.client.set("foo", "bar")
        action = timeline.actions[-1]
        self.assertEqual("memcache-set", action.category)
        self.assertEqual("foo", action.detail)

    def test_get_recorded_to_timeline(self):
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        self.client.set("foo", "bar")
        self.client.get("foo")
        action = timeline.actions[-1]
        self.assertEqual("memcache-get", action.category)
        self.assertEqual("foo", action.detail)

    def test_get_failure(self):
        logger = BufferLogger()
        with patch.object(self.client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = MemcacheError("All servers down")
            self.assertIsNone(self.client.get("foo"))
            self.assertIsNone(self.client.get("foo", logger=logger))
            self.assertEqual(
                "ERROR Cannot get foo from memcached: All servers down\n",
                logger.content.as_text(),
            )

    def test_get_connection_refused(self):
        logger = BufferLogger()
        with patch.object(self.client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = ConnectionRefusedError(
                "Connection refused"
            )
            self.assertIsNone(self.client.get("foo"))
            self.assertIsNone(self.client.get("foo", logger=logger))
            self.assertEqual(
                "ERROR Cannot get foo from memcached: Connection refused\n",
                logger.content.as_text(),
            )

    def test_set_failure(self):
        logger = BufferLogger()
        with patch.object(self.client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = MemcacheError("All servers down")
            self.assertFalse(self.client.set("foo", "bar"))
            self.assertFalse(self.client.set("foo", "bar", logger=logger))
            self.assertEqual(
                "ERROR Cannot set foo in memcached: All servers down\n",
                logger.content.as_text(),
            )

    def test_set_connection_refused(self):
        logger = BufferLogger()
        with patch.object(self.client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = ConnectionRefusedError(
                "Connection refused"
            )
            self.assertFalse(self.client.set("foo", "bar"))
            self.assertFalse(self.client.set("foo", "bar", logger=logger))
            self.assertEqual(
                "ERROR Cannot set foo in memcached: Connection refused\n",
                logger.content.as_text(),
            )

    def test_delete_failure(self):
        logger = BufferLogger()
        with patch.object(self.client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = MemcacheError("All servers down")
            self.assertFalse(self.client.delete("foo"))
            self.assertFalse(self.client.delete("foo", logger=logger))
            self.assertEqual(
                "ERROR Cannot delete foo from memcached: All servers down\n",
                logger.content.as_text(),
            )

    def test_delete_connection_refused(self):
        logger = BufferLogger()
        with patch.object(self.client, "_get_client") as mock_get_client:
            mock_get_client.side_effect = ConnectionRefusedError(
                "Connection refused"
            )
            self.assertFalse(self.client.delete("foo"))
            self.assertFalse(self.client.delete("foo", logger=logger))
            self.assertEqual(
                "ERROR Cannot delete foo from memcached: Connection refused\n",
                logger.content.as_text(),
            )


class MemcacheClientFactoryTestCase(TestCase):
    layer = LaunchpadZopelessLayer

    def test_with_timeline(self):
        # memcache_client_factory defaults to returning a client that
        # records events to a timeline.
        client = memcache_client_factory()
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        base_action_count = len(timeline.actions)
        client.set("foo", "bar")
        self.assertEqual("bar", client.get("foo"))
        self.assertEqual(base_action_count + 2, len(timeline.actions))

    def test_without_timeline(self):
        # We can explicitly request a client that does not record events to
        # a timeline.
        client = memcache_client_factory(timeline=False)
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        base_action_count = len(timeline.actions)
        client.set("foo", "bar")
        self.assertEqual("bar", client.get("foo"))
        self.assertEqual(base_action_count, len(timeline.actions))


class MemcacheClientJSONTestCase(TestCase):
    def setUp(self):
        super().setUp()
        self.client = self.useFixture(MemcacheFixture())
        self.logger = BufferLogger()

    def test_handle_invalid_data(self):
        self.client.set("key", b"invalid_data")
        description = "binary data"

        self.client.get_json("key", self.logger, description)

        self.assertEqual(
            "ERROR Cannot load cached binary data; deleting\n",
            self.logger.content.as_text(),
        )
