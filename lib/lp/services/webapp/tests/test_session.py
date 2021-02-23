# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import datetime
import hashlib
import hmac

from testtools import TestCase
from testtools.matchers import Contains
from zope.session.session import digestEncode

from lp.services.webapp.login import (
    isFreshLogin,
    OpenIDCallbackView,
    )
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.services.webapp.session import (
    get_cookie_domain,
    LaunchpadCookieClientIdManager,
    )
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class GetCookieDomainTestCase(TestCase):

    def test_base_domain(self):
        # Test that the base Launchpad domain gives a domain parameter
        # that is visible to the virtual hosts.
        self.assertEqual(get_cookie_domain('launchpad.net'), '.launchpad.net')

    def test_vhost_domain(self):
        # Test Launchpad subdomains give the same domain parameter
        self.assertEqual(get_cookie_domain('bugs.launchpad.net'),
                         '.launchpad.net')

    def test_other_domain(self):
        # Other domains do not return a cookie domain.
        self.assertEqual(get_cookie_domain('example.com'), None)

    def test_other_instances(self):
        # Test that requests to other launchpad instances are scoped right
        self.assertEqual(get_cookie_domain('demo.launchpad.net'),
                         '.demo.launchpad.net')
        self.assertEqual(get_cookie_domain('bugs.demo.launchpad.net'),
                         '.demo.launchpad.net')

        self.assertEqual(get_cookie_domain('staging.launchpad.net'),
                         '.staging.launchpad.net')
        self.assertEqual(get_cookie_domain('bugs.staging.launchpad.net'),
                         '.staging.launchpad.net')

        self.assertEqual(get_cookie_domain('launchpad.test'),
                         '.launchpad.test')
        self.assertEqual(get_cookie_domain('bugs.launchpad.test'),
                         '.launchpad.test')


class TestLaunchpadCookieClientIdManager(TestCase):

    def test_httponly(self):
        # Authentication cookies are marked as httponly, so JavaScript
        # can't read them directly.
        request = LaunchpadTestRequest()
        LaunchpadCookieClientIdManager().setRequestId(request, 'some-id')
        self.assertThat(
            dict(request.response.getHeaders())['Set-Cookie'].lower(),
            Contains('; httponly;'))

    def test_stable_client_id(self):
        # Changing the HMAC algorithm used for client IDs would invalidate
        # existing sessions, so be careful that that doesn't happen
        # accidentally across upgrades.
        request = LaunchpadTestRequest()
        idmanager = LaunchpadCookieClientIdManager()
        idmanager._secret = 'secret'
        data = b'random'
        s = digestEncode(hashlib.sha1(data).digest())
        mac = hmac.new(
            s, idmanager.secret.encode(), digestmod=hashlib.sha1).digest()
        sid = (s + digestEncode(mac)).decode()
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
        when = datetime.datetime.utcnow() - datetime.timedelta(seconds=180)
        self.setupLoggedInRequest(user, request, when)
        self.assertFalse(isFreshLogin(request))
