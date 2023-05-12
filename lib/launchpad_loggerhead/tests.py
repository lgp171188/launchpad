# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from urllib.parse import urlencode, urlsplit

import requests
import soupmatchers
from paste.httpexceptions import HTTPExceptionHandler
from testtools.content import Content
from testtools.content_type import UTF8_TEXT
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.wsgi import Browser

from launchpad_loggerhead.app import RootApp
from launchpad_loggerhead.session import SessionHandler
from launchpad_loggerhead.testing import LoggerheadFixture
from lp.app import versioninfo
from lp.app.enums import InformationType
from lp.services.config import config
from lp.services.webapp.vhosts import allvhosts
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import AppServerLayer, DatabaseFunctionalLayer

SESSION_VAR = "lh.session"

# See lib/launchpad_loggerhead/wsgi.py for the production mechanism for
# getting the secret.
SECRET = b"secret"


def session_scribbler(app, test):
    """Squirrel away the session variable."""

    def scribble(environ, start_response):
        test.session = environ[SESSION_VAR]  # Yay for mutables.
        return app(environ, start_response)

    return scribble


class SimpleLogInRootApp(RootApp):
    """A mock root app that doesn't require open id."""

    def _complete_login(self, environ, start_response):
        environ[SESSION_VAR]["user"] = "bob"
        start_response("200 OK", [("Content-type", "text/plain")])
        return [b"\n"]

    def __call__(self, environ, start_response):
        codebrowse_netloc = urlsplit(
            config.codehosting.secure_codebrowse_root
        ).netloc
        if environ["HTTP_HOST"] == codebrowse_netloc:
            return RootApp.__call__(self, environ, start_response)
        else:
            # Return a fake response.
            start_response("200 OK", [("Content-type", "text/plain")])
            return [b"This is a dummy destination.\n"]


class TestLogout(TestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCase.setUp(self)
        self.session = None
        app = SimpleLogInRootApp(SESSION_VAR)
        app = session_scribbler(app, self)
        app = HTTPExceptionHandler(app)
        app = SessionHandler(app, SESSION_VAR, SECRET)
        self.cookie_name = app.cookie_name
        self.browser = Browser(wsgi_app=app)
        self.browser.open(config.codehosting.secure_codebrowse_root + "+login")

    def testLoggerheadLogout(self):
        # We start logged in as 'bob'.
        self.assertEqual(self.session["user"], "bob")
        self.browser.open(
            config.codehosting.secure_codebrowse_root + "favicon.ico"
        )
        self.assertEqual(self.session["user"], "bob")
        self.assertTrue(self.browser.cookies.get(self.cookie_name))

        # When we visit +logout, our session is gone.
        self.browser.open(
            config.codehosting.secure_codebrowse_root + "+logout"
        )
        self.assertEqual(self.session, {})

        # By default, we have been redirected to the Launchpad root.
        self.assertEqual(
            self.browser.url, allvhosts.configs["mainsite"].rooturl
        )

        # The user has an empty session now.
        self.browser.open(
            config.codehosting.secure_codebrowse_root + "favicon.ico"
        )
        self.assertEqual(self.session, {})

    def testLoggerheadLogoutRedirect(self):
        # When we visit +logout with a 'next_to' value in the query string,
        # the logout page will redirect to the given URI.  As of this
        # writing, this is used by Launchpad to redirect to our OpenId
        # provider (see lp.testing.tests.test_login.
        # TestLoginAndLogout.test_CookieLogoutPage).

        # Here, we will have a more useless example of the basic machinery.
        dummy_root = "http://launchpad.test/"
        self.browser.open(
            config.codehosting.secure_codebrowse_root
            + "+logout?"
            + urlencode(dict(next_to=dummy_root + "+logout"))
        )

        # We are logged out, as before.
        self.assertEqual(self.session, {})

        # Now, though, we are redirected to the ``next_to`` destination.
        self.assertEqual(self.browser.url, dummy_root + "+logout")
        self.assertEqual(
            self.browser.contents, b"This is a dummy destination.\n"
        )

    def testLoggerheadLogoutRedirectCookieLogoutMimic(self):
        # When we visit +logout with a 'next_to' value in the query string,
        # the logout page will redirect to the given URI.  As of this
        # writing, this is used by Launchpad to redirect to our OpenId
        # provider (see lp.testing.tests.test_login.
        # TestLoginAndLogout.test_CookieLogoutPage).

        # CookieLogout behaviour mimic
        self.browser.open(
            config.codehosting.secure_codebrowse_root
            + "+logout?"
            + urlencode(
                dict(next_to=config.launchpad.openid_provider_root + "+logout")
            )
        )

        # We are logged out, as before.
        self.assertEqual(self.session, {})

        # Now, though, we are redirected to the ``next_to`` destination.
        self.assertEqual(
            self.browser.url, config.launchpad.openid_provider_root + "+logout"
        )
        self.assertEqual(
            self.browser.contents, b"This is a dummy destination.\n"
        )

    def testLoggerheadLogoutRedirectFailure(self):
        # When we visit +logout with a 'next_to' value in the query string,
        # the logout page will redirect to the given URI only if
        # the url belongs to well known domains

        # Here, we will have an example of open redirect attack
        dummy_root = "http://launchpad.phishing.test/"
        self.browser.open(
            config.codehosting.secure_codebrowse_root
            + "+logout?"
            + urlencode(dict(next_to=dummy_root + "+logout"))
        )

        # We are logged out, as before.
        self.assertEqual(self.session, {})

        # We are redirected to the default homepage because
        # the next_to is unknown
        self.assertEqual(self.browser.url, "http://launchpad.test/")


class TestWSGI(TestCaseWithFactory):
    """Smoke tests for Launchpad's loggerhead WSGI server."""

    layer = AppServerLayer

    def setUp(self):
        super().setUp()
        self.useBzrBranches()
        loggerhead_fixture = self.useFixture(LoggerheadFixture())

        def get_debug_log_bytes():
            try:
                with open(loggerhead_fixture.logfile, "rb") as logfile:
                    return [logfile.read()]
            except OSError:
                return [b""]

        self.addDetail(
            "loggerhead-debug", Content(UTF8_TEXT, get_debug_log_bytes)
        )

    def test_robots(self):
        response = requests.get(
            "http://127.0.0.1:%d/robots.txt" % config.codebrowse.port
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual(b"User-agent: *\nDisallow: /\n", response.content)

    def test_public_port_public_branch(self):
        # Requests for public branches on the public port are allowed.
        db_branch, _ = self.create_branch_and_tree()
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.port,
            db_branch.unique_name,
        )
        response = requests.get(branch_url)
        self.assertEqual(200, response.status_code)
        title_tag = soupmatchers.Tag(
            "page title", "title", text="%s : changes" % db_branch.unique_name
        )
        self.assertThat(response.text, soupmatchers.HTMLContains(title_tag))

    def test_public_port_private_branch(self):
        # Requests for private branches on the public port send the user
        # through the login workflow.
        db_branch, _ = self.create_branch_and_tree(
            information_type=InformationType.USERDATA
        )
        naked_branch = removeSecurityProxy(db_branch)
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.port,
            naked_branch.unique_name,
        )
        response = requests.get(
            branch_url,
            headers={"X-Forwarded-Scheme": "https"},
            allow_redirects=False,
        )
        self.assertEqual(301, response.status_code)
        self.assertEqual(
            "testopenid.test:8085",
            urlsplit(response.headers["Location"]).netloc,
        )

    def test_private_port_public_branch(self):
        # Requests for public branches on the private port are allowed.
        db_branch, _ = self.create_branch_and_tree()
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.private_port,
            db_branch.unique_name,
        )
        response = requests.get(branch_url)
        self.assertEqual(200, response.status_code)
        title_tag = soupmatchers.Tag(
            "page title", "title", text="%s : changes" % db_branch.unique_name
        )
        self.assertThat(response.text, soupmatchers.HTMLContains(title_tag))

    def test_private_port_private_branch(self):
        # Requests for private branches on the private port are allowed.
        db_branch, _ = self.create_branch_and_tree(
            information_type=InformationType.USERDATA
        )
        naked_branch = removeSecurityProxy(db_branch)
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.private_port,
            naked_branch.unique_name,
        )
        response = requests.get(branch_url)
        self.assertEqual(200, response.status_code)
        title_tag = soupmatchers.Tag(
            "page title",
            "title",
            text="%s : changes" % naked_branch.unique_name,
        )
        self.assertThat(response.text, soupmatchers.HTMLContains(title_tag))

    def test_revision_header_present(self):
        db_branch, _ = self.create_branch_and_tree()
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.port,
            db_branch.unique_name,
        )
        response = requests.get(branch_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            versioninfo.revision, response.headers["X-Launchpad-Revision"]
        )

    def test_vary_header_present(self):
        db_branch, _ = self.create_branch_and_tree()
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.port,
            db_branch.unique_name,
        )
        response = requests.get(branch_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual("Cookie, Authorization", response.headers["Vary"])

    def test_security_headers_present(self):
        db_branch, _ = self.create_branch_and_tree()
        branch_url = "http://127.0.0.1:%d/%s" % (
            config.codebrowse.port,
            db_branch.unique_name,
        )
        response = requests.get(branch_url)
        self.assertEqual(200, response.status_code)
        self.assertEqual(
            "frame-ancestors 'self';",
            response.headers["Content-Security-Policy"],
        )
        self.assertEqual("SAMEORIGIN", response.headers["X-Frame-Options"])
        self.assertEqual("nosniff", response.headers["X-Content-Type-Options"])
        self.assertEqual("1; mode=block", response.headers["X-XSS-Protection"])
