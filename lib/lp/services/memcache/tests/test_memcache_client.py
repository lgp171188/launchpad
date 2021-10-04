# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the IMemcacheClient utility."""

from lazr.restful.utils import get_current_browser_request
from zope.component import getUtility

from lp.services.memcache.client import memcache_client_factory
from lp.services.memcache.interfaces import IMemcacheClient
from lp.services.timeline.requesttimeline import get_request_timeline
from lp.testing import TestCase
from lp.testing.layers import LaunchpadZopelessLayer


class MemcacheClientTestCase(TestCase):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(MemcacheClientTestCase, self).setUp()
        self.client = getUtility(IMemcacheClient)

    def test_basics(self):
        self.assertTrue(self.client.set('somekey', 'somevalue'))
        self.assertEqual(self.client.get('somekey'), 'somevalue')

    def test_bug_452092(self):
        """Memcache 1.44 allowed spaces in keys, which was incorrect. This
        would break things badly enough that we are running a patched version.
        This test ensures that spaces are correctly flagged as errors at
        the callsite rather than causing chaos later, ensuring that if
        we upgrade we upgrade to a version with correct validation.
        """
        self.assertRaises(
            self.client.MemcachedKeyCharacterError,
            self.client.set, 'key with spaces', 'some value')

    def test_set_recorded_to_timeline(self):
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        self.client.set('foo', 'bar')
        action = timeline.actions[-1]
        self.assertEqual('memcache-set', action.category)
        self.assertEqual('foo', action.detail)

    def test_get_recorded_to_timeline(self):
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        self.client.set('foo', 'bar')
        self.client.get('foo')
        action = timeline.actions[-1]
        self.assertEqual('memcache-get', action.category)
        self.assertEqual('foo', action.detail)


class MemcacheClientFactoryTestCase(TestCase):

    layer = LaunchpadZopelessLayer

    def test_with_timeline(self):
        # memcache_client_factory defaults to returning a client that
        # records events to a timeline.
        client = memcache_client_factory()
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        base_action_count = len(timeline.actions)
        client.set('foo', 'bar')
        self.assertEqual('bar', client.get('foo'))
        self.assertEqual(base_action_count + 2, len(timeline.actions))

    def test_without_timeline(self):
        # We can explicitly request a client that does not record events to
        # a timeline.
        client = memcache_client_factory(timeline=False)
        request = get_current_browser_request()
        timeline = get_request_timeline(request)
        base_action_count = len(timeline.actions)
        client.set('foo', 'bar')
        self.assertEqual('bar', client.get('foo'))
        self.assertEqual(base_action_count, len(timeline.actions))
