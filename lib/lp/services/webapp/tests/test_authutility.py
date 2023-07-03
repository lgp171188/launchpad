# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import base64

from zope.authentication.interfaces import ILoginPassword
from zope.component import getUtility
from zope.interface import implementer
from zope.principalregistry.principalregistry import UnauthenticatedPrincipal
from zope.publisher.browser import TestRequest
from zope.publisher.http import BasicAuthAdapter
from zope.publisher.interfaces.http import IHTTPCredentials
from zope.security.testing import addCheckerPublic

from lp.registry.interfaces.person import IPerson
from lp.services.config import config
from lp.services.identity.interfaces.account import IAccount
from lp.services.webapp.authentication import (
    LaunchpadPrincipal,
    PlacelessAuthUtility,
)
from lp.services.webapp.interfaces import (
    IPlacelessAuthUtility,
    IPlacelessLoginSource,
)
from lp.testing import TestCase
from lp.testing.fixture import ZopeAdapterFixture, ZopeUtilityFixture
from lp.testing.layers import FunctionalLayer


@implementer(IPerson)
class FakePerson:
    is_valid_person = True


@implementer(IAccount)
class FakeAccount:
    person = FakePerson()


Bruce = LaunchpadPrincipal(42, "bruce", "Bruce", FakeAccount())
Bruce.person = Bruce.account.person


@implementer(IPlacelessLoginSource)
class FakePlacelessLoginSource:
    def getPrincipalByLogin(self, id):
        return Bruce

    getPrincipal = getPrincipalByLogin

    def getPrincipals(self, name):
        return [Bruce]


class TestPlacelessAuth(TestCase):
    layer = FunctionalLayer

    def setUp(self):
        super().setUp()
        addCheckerPublic()
        self.useFixture(
            ZopeUtilityFixture(
                FakePlacelessLoginSource(), IPlacelessLoginSource
            )
        )
        self.useFixture(
            ZopeUtilityFixture(PlacelessAuthUtility(), IPlacelessAuthUtility)
        )
        self.useFixture(
            ZopeAdapterFixture(
                BasicAuthAdapter, (IHTTPCredentials,), ILoginPassword
            )
        )

    def _make(self, login, pwd):
        auth = base64.b64encode(
            ("%s:%s" % (login, pwd)).encode("ASCII")
        ).decode("ASCII")
        dict = {"HTTP_AUTHORIZATION": "Basic %s" % auth}
        request = TestRequest(**dict)
        return getUtility(IPlacelessAuthUtility), request

    def test_authenticate_ok(self):
        authsvc, request = self._make("bruce", "test")
        self.assertEqual(authsvc.authenticate(request), Bruce)

    def test_authenticate_notok(self):
        authsvc, request = self._make("bruce", "nottest")
        self.assertEqual(authsvc.authenticate(request), None)

    def test_unauthenticatedPrincipal(self):
        authsvc, request = self._make(None, None)
        self.assertTrue(
            isinstance(
                authsvc.unauthenticatedPrincipal(), UnauthenticatedPrincipal
            )
        )

    def test_unauthorized(self):
        authsvc, request = self._make("bruce", "test")
        self.assertEqual(authsvc.unauthorized("bruce", request), None)
        self.assertEqual(request._response._status, 401)

    def test_basic_auth_disabled(self):
        # Basic auth uses a single password for every user, so it must
        # never be used on production. authenticate() will skip basic
        # auth unless it's enabled.
        authsvc, request = self._make("bruce", "test")
        self.assertEqual(authsvc.authenticate(request), Bruce)
        try:
            config.push("no-basic", "[launchpad]\nbasic_auth_password: none")
            self.assertEqual(authsvc.authenticate(request), None)
        finally:
            config.pop("no-basic")

    def test_direct_basic_call_fails_when_disabled(self):
        # Basic auth uses a single password for every user, so it must
        # never be used on production. authenticate() won't call the
        # underlying method unless it's enabled, but even if it somehow
        # does it will fail.
        authsvc, request = self._make("bruce", "test")
        credentials = ILoginPassword(request, None)
        self.assertEqual(
            authsvc._authenticateUsingBasicAuth(credentials, request), Bruce
        )
        try:
            config.push("no-basic", "[launchpad]\nbasic_auth_password: none")
            exception = self.assertRaises(
                AssertionError,
                authsvc._authenticateUsingBasicAuth,
                credentials,
                request,
            )
            self.assertEqual(
                "Attempted to use basic auth when it is disabled",
                str(exception),
            )
        finally:
            config.pop("no-basic")

    def test_getPrincipal(self):
        authsvc, request = self._make("bruce", "test")
        self.assertEqual(authsvc.getPrincipal("bruce"), Bruce)

    def test_getPrincipals(self):
        authsvc, request = self._make("bruce", "test")
        self.assertEqual(authsvc.getPrincipals("bruce"), [Bruce])

    def test_getPrincipalByLogin(self):
        authsvc, request = self._make("bruce", "test")
        self.assertEqual(authsvc.getPrincipalByLogin("bruce"), Bruce)
