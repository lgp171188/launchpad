# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import hashlib
import hmac
from datetime import datetime, timedelta
from email.utils import parsedate

from testtools.matchers import Contains, ContainsDict, Equals

from lp.services.propertycache import get_property_cache
from lp.services.webapp.login import OpenIDCallbackView, isFreshLogin
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.services.webapp.session import (
    LaunchpadCookieClientIdManager,
    encode_digest,
    get_cookie_domain,
)
from lp.testing import TestCase, TestCaseWithFactory, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer


class GetCookieDomainTestCase(TestCase):
    def test_base_domain(self):
        # Test that the base Launchpad domain gives a domain parameter
        # that is visible to the virtual hosts.
        self.pushConfig("vhost.mainsite", hostname="launchpad.net")
        self.assertEqual(".launchpad.net", get_cookie_domain("launchpad.net"))

    def test_vhost_domain(self):
        # Test Launchpad subdomains give the same domain parameter
        self.pushConfig("vhost.mainsite", hostname="launchpad.net")
        self.assertEqual(
            ".launchpad.net", get_cookie_domain("bugs.launchpad.net")
        )

    def test_other_domain(self):
        # Other domains do not return a cookie domain.
        self.pushConfig("vhost.mainsite", hostname="launchpad.net")
        self.assertIsNone(get_cookie_domain("example.com"))

    def test_staging(self):
        # Requests to Launchpad staging are scoped correctly.
        self.pushConfig("vhost.mainsite", hostname="staging.launchpad.net")
        self.assertEqual(
            ".staging.launchpad.net",
            get_cookie_domain("staging.launchpad.net"),
        )
        self.assertEqual(
            ".staging.launchpad.net",
            get_cookie_domain("bugs.staging.launchpad.net"),
        )
        self.assertIsNone(get_cookie_domain("launchpad.net"))

    def test_development(self):
        # Requests to a development server are scoped correctly.
        self.pushConfig("vhost.mainsite", hostname="launchpad.test")
        self.assertEqual(
            ".launchpad.test", get_cookie_domain("launchpad.test")
        )
        self.assertEqual(
            ".launchpad.test", get_cookie_domain("bugs.launchpad.test")
        )
        self.assertIsNone(get_cookie_domain("launchpad.net"))


class TestLaunchpadCookieClientIdManager(TestCase):
    def test_generateUniqueId(self):
        idmanager = LaunchpadCookieClientIdManager()
        get_property_cache(idmanager).secret = "secret"
        self.assertNotEqual(
            idmanager.generateUniqueId(), idmanager.generateUniqueId()
        )

    def test_expires(self):
        request = LaunchpadTestRequest()
        idmanager = LaunchpadCookieClientIdManager()
        idmanager.setRequestId(request, "some-id")
        cookie = request.response.getCookie(idmanager.namespace)
        expires = datetime(*parsedate(cookie["expires"])[:7])
        self.assertLess(
            expires - datetime.now() - timedelta(days=365),
            # Allow some slack for slow tests.
            timedelta(seconds=30),
        )

    def test_httponly(self):
        # Authentication cookies are marked as httponly, so JavaScript
        # can't read them directly.
        request = LaunchpadTestRequest()
        LaunchpadCookieClientIdManager().setRequestId(request, "some-id")
        self.assertThat(
            dict(request.response.getHeaders())["Set-Cookie"].lower(),
            Contains("; httponly;"),
        )

    def test_headers(self):
        # When the cookie is set, cache headers are added to the response to
        # try to prevent the cookie header from being cached:
        request = LaunchpadTestRequest()
        LaunchpadCookieClientIdManager().setRequestId(request, "some-id")
        self.assertThat(
            dict(request.response.getHeaders()),
            ContainsDict(
                {
                    "Cache-Control": Equals(
                        'no-cache="Set-Cookie,Set-Cookie2"'
                    ),
                    "Pragma": Equals("no-cache"),
                    "Expires": Equals("Mon, 26 Jul 1997 05:00:00 GMT"),
                }
            ),
        )

    def test_stable_client_id(self):
        # Changing the HMAC algorithm used for client IDs would invalidate
        # existing sessions, so be careful that that doesn't happen
        # accidentally across upgrades.
        request = LaunchpadTestRequest()
        idmanager = LaunchpadCookieClientIdManager()
        get_property_cache(idmanager).secret = "secret"
        data = b"random"
        s = encode_digest(hashlib.sha1(data).digest())
        mac = hmac.new(
            s, idmanager.secret.encode(), digestmod=hashlib.sha1
        ).digest()
        sid = (s + encode_digest(mac)).decode()
        idmanager.setRequestId(request, sid)
        # getRequestId will only return the previously-set ID if it was
        # generated using the correct secret with the correct algorithm.
        self.assertEqual(sid, idmanager.getRequestId(request))


class TestSessionRelatedFunctions(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setupLoggedInRequest(self, user, request, when=None):
        """Test helper to login a user for a request."""
        with person_logged_in(user):
            view = OpenIDCallbackView(user, request)
            view.login(user, when)

    def test_isFreshLogin_returns_false_for_anonymous(self):
        """isFreshLogin should return False for anonymous views."""
        request = LaunchpadTestRequest()
        self.assertFalse(isFreshLogin(request))

    def test_isFreshLogin_returns_true(self):
        """isFreshLogin should return True with a fresh logged in user."""
        user = self.factory.makePerson()
        request = LaunchpadTestRequest()
        self.setupLoggedInRequest(user, request)
        self.assertTrue(isFreshLogin(request))

    def test_isFreshLogin_returns_false(self):
        """isFreshLogin should be False for users logged in over 2 minutes."""
        user = self.factory.makePerson()
        request = LaunchpadTestRequest()
        when = datetime.utcnow() - timedelta(seconds=180)
        self.setupLoggedInRequest(user, request, when)
        self.assertFalse(isFreshLogin(request))
