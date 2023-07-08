# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the health check view for Talisker."""

from fixtures import FakeLogger
from zope.publisher.interfaces.http import IHTTPRequest

from lp.services.database.interfaces import IDatabasePolicy
from lp.services.database.policy import DatabaseBlockedPolicy
from lp.testing import TestCase
from lp.testing.fixture import ZopeAdapterFixture
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import http


class TestStatusView(TestCase):
    layer = DatabaseFunctionalLayer

    # The successful case of traversal is tested in TestStatusCheckView.
    def test_traverse_not_found(self):
        self.useFixture(FakeLogger())
        response = http("GET /_status/nonexistent HTTP/1.0")
        self.assertEqual(404, response.getStatus())

    def test_call_not_found(self):
        self.useFixture(FakeLogger())
        response = http("GET /_status HTTP/1.0")
        self.assertEqual(404, response.getStatus())


class TestStatusCheckView(TestCase):
    layer = DatabaseFunctionalLayer

    def test_ok(self):
        response = http("GET /_status/check HTTP/1.0")
        self.assertEqual(200, response.getStatus())
        self.assertEqual(b"", response.getBody())

    def test_no_database(self):
        policy = DatabaseBlockedPolicy()
        self.useFixture(
            ZopeAdapterFixture(policy, (IHTTPRequest,), IDatabasePolicy)
        )
        response = http("GET /_status/check HTTP/1.0")
        self.assertEqual(500, response.getStatus())
