# Copyright 2012-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for core services infrastructure."""

import json
from urllib.parse import urlparse

from fixtures import FakeLogger
from lazr.restful.interfaces._rest import IHTTPResource
from zope.component import getUtility
from zope.interface import implementer
from zope.interface.interfaces import ComponentLookupError

from lp.app.interfaces.services import IService, IServiceFactory
from lp.services.webapp.interaction import ANONYMOUS
from lp.testing import FakeAdapterMixin, TestCaseWithFactory, login
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.publication import test_traverse


class IFakeService(IService):
    """Fake service interface."""


@implementer(IFakeService, IHTTPResource)
class FakeService:
    name = "fake_service"


class TestServiceFactory(TestCaseWithFactory, FakeAdapterMixin):
    """Tests for the ServiceFactory"""

    layer = DatabaseFunctionalLayer

    def test_service_traversal(self):
        # Test that traversal to the named service works.
        login(ANONYMOUS)
        fake_service = FakeService()
        self.registerUtility(fake_service, IService, "fake")
        context, view, request = test_traverse(
            "https://launchpad.test/api/devel/+services/fake"
        )
        self.assertEqual(getUtility(IServiceFactory), context)
        self.assertEqual(fake_service, view)

    def test_service_factory_traversal(self):
        # Test that traversal to the service factory works.
        context, view, request = test_traverse(
            "https://launchpad.test/api/devel/+services"
        )
        self.assertEqual(getUtility(IServiceFactory), context)
        view_text = view().decode("UTF-8")
        self.assertEqual(
            "service_factory",
            urlparse(json.loads(view_text)["resource_type_link"]).fragment,
        )

    def test_invalid_service(self):
        # Test that traversal to an invalid service name fails.
        self.useFixture(FakeLogger())
        self.assertRaises(
            ComponentLookupError,
            test_traverse,
            "https://launchpad.test/api/devel/+services/invalid",
        )
