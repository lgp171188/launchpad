# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests publication.py"""

import sys

from fixtures import FakeLogger
from oauthlib import oauth1
from storm.database import STATE_DISCONNECTED, STATE_RECONNECT
from storm.exceptions import DisconnectionError
from testtools.matchers import Equals, GreaterThan, MatchesListwise
from zope.component import getUtility
from zope.interface import directlyProvides
from zope.publisher.interfaces import NotFound, Retry
from zope.publisher.publish import publish
from zope.security.management import thread_local as zope_security_thread_local

import lp.services.webapp.adapter as dbadapter
from lp.services.auth.interfaces import IAccessTokenVerifiedRequest
from lp.services.database.interfaces import IPrimaryStore
from lp.services.identity.model.emailaddress import EmailAddress
from lp.services.oauth.interfaces import IOAuthConsumerSet, IOAuthSignedRequest
from lp.services.statsd.tests import StatsMixin
from lp.services.webapp.interfaces import (
    NoReferrerError,
    OAuthPermission,
    OffsiteFormPostError,
)
from lp.services.webapp.publication import (
    OFFSITE_POST_WHITELIST,
    LaunchpadBrowserPublication,
    is_browser,
    maybe_block_offsite_form_post,
)
from lp.services.webapp.servers import (
    LaunchpadTestRequest,
    WebServicePublication,
)
from lp.services.webapp.vhosts import allvhosts
from lp.testing import ANONYMOUS, TestCase, TestCaseWithFactory, login
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import DatabaseFunctionalLayer


class TestLaunchpadBrowserPublication(TestCase):
    def test_callTraversalHooks_appends_to_traversed_objects(self):
        # Traversed objects are appended to request.traversed_objects in the
        # order they're traversed.
        obj1 = object()
        obj2 = object()
        request = LaunchpadTestRequest()
        publication = LaunchpadBrowserPublication(None)
        publication.callTraversalHooks(request, obj1)
        publication.callTraversalHooks(request, obj2)
        self.assertEqual(request.traversed_objects, [obj1, obj2])

    def test_callTraversalHooks_appends_only_once_to_traversed_objects(self):
        # callTraversalHooks() may be called more than once for a given
        # traversed object, but if that's the case we won't add the same
        # object twice to traversed_objects.
        obj1 = obj2 = object()
        request = LaunchpadTestRequest()
        publication = LaunchpadBrowserPublication(None)
        publication.callTraversalHooks(request, obj1)
        publication.callTraversalHooks(request, obj2)
        self.assertEqual(request.traversed_objects, [obj1])


class TestLaunchpadBrowserPublicationInteractionHandling(TestCase):
    layer = DatabaseFunctionalLayer

    def test_endRequest_removes_previous_interaction(self):
        # Zope's BrowserPublication.endRequest leaves a reference to the
        # previous interaction around in
        # zope.security.management.thread_local.previous_interaction, which
        # can complicate memory leak analysis.  Since we don't need this
        # reference, LaunchpadBrowserPublication.endRequest removes it.
        request = LaunchpadTestRequest(PATH_INFO="/")
        request.setPublication(LaunchpadBrowserPublication(None))
        publish(request)
        self.assertIsNone(
            getattr(zope_security_thread_local, "interaction", None)
        )
        self.assertIsNone(
            getattr(zope_security_thread_local, "previous_interaction", None)
        )


class TestWebServicePublication(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        login(ANONYMOUS)

    def _getRequestForPersonAndAccountWithDifferentIDs(self):
        """Return a LaunchpadTestRequest with the correct OAuth parameters in
        its form.
        """
        # Create a lone account followed by an account-with-person just to
        # make sure in the second one the ID of the account and the person are
        # different.
        self.factory.makeAccount("Personless account")
        person = self.factory.makePerson()
        self.assertNotEqual(person.id, person.account.id)

        # Create an OAuth access token for our new person.
        consumer = getUtility(IOAuthConsumerSet).new("test-consumer")
        request_token, _ = consumer.newRequestToken()
        request_token.review(
            person, permission=OAuthPermission.READ_PUBLIC, context=None
        )
        access_token, access_secret = request_token.createAccessToken()

        # Make an OAuth signature using the access token we just created for
        # our new person.
        client = oauth1.Client(
            consumer.key,
            resource_owner_key=access_token.key,
            resource_owner_secret=access_secret,
            signature_method=oauth1.SIGNATURE_PLAINTEXT,
        )
        _, headers, _ = client.sign("/dummy")
        return LaunchpadTestRequest(
            environ={"HTTP_AUTHORIZATION": headers["Authorization"]}
        )

    def test_getPrincipal_for_person_and_account_with_different_ids(self):
        # WebServicePublication.getPrincipal() does not rely on accounts
        # having the same IDs as their associated person entries to work.
        request = self._getRequestForPersonAndAccountWithDifferentIDs()
        principal = WebServicePublication(None).getPrincipal(request)
        self.assertIsNotNone(principal)

    def test_disconnect_logs_oops(self):
        # Ensure that OOPS reports are generated for database
        # disconnections, as per Bug #373837.
        request = LaunchpadTestRequest()
        publication = WebServicePublication(None)
        dbadapter.set_request_started()
        try:
            raise DisconnectionError("Fake")
        except DisconnectionError:
            self.assertRaises(
                Retry,
                publication.handleException,
                None,
                request,
                sys.exc_info(),
                True,
            )
        dbadapter.clear_request_started()
        self.assertEqual(1, len(self.oopses))
        oops = self.oopses[0]

        # Ensure the OOPS mentions the correct exception
        self.assertEqual(oops["type"], "DisconnectionError")

    def test_store_disconnected_after_request_handled_logs_oops(self):
        # Bug #504291 was that a Store was being left in a disconnected
        # state after a request, causing subsequent requests handled by that
        # thread to fail. We detect this state in endRequest and log an
        # OOPS to help track down the trigger.
        request = LaunchpadTestRequest()
        publication = WebServicePublication(None)
        dbadapter.set_request_started()

        # Disconnect a store
        store = IPrimaryStore(EmailAddress)
        store._connection._state = STATE_DISCONNECTED

        # Invoke the endRequest hook.
        publication.endRequest(request, None)

        self.assertEqual(1, len(self.oopses))
        oops = self.oopses[0]

        # Ensure the OOPS mentions the correct exception
        self.assertStartsWith(oops["value"], "Bug #504291")

        # Ensure the store has been rolled back and in a usable state.
        self.assertEqual(store._connection._state, STATE_RECONNECT)
        store.find(EmailAddress).first()  # Confirms Store is working.

    def test_is_browser(self):
        # No User-Agent: header.
        request = LaunchpadTestRequest()
        self.assertFalse(is_browser(request))

        # Browser User-Agent: header.
        request = LaunchpadTestRequest(
            environ={"USER_AGENT": "Mozilla/42 Extreme Edition"}
        )
        self.assertTrue(is_browser(request))

        # Robot User-Agent: header.
        request = LaunchpadTestRequest(environ={"USER_AGENT": "BottyBot"})
        self.assertFalse(is_browser(request))


class TestBlockingOffsitePosts(TestCase):
    """We are very particular about what form POSTs we will accept."""

    def test_NoReferrerError(self):
        # If this request is a POST and there is no referrer, an exception is
        # raised.
        request = LaunchpadTestRequest(
            method="POST", environ=dict(PATH_INFO="/")
        )
        self.assertRaises(
            NoReferrerError, maybe_block_offsite_form_post, request
        )

    def test_nonPOST_requests(self):
        # If the request isn't a POST it is always allowed.
        request = LaunchpadTestRequest(method="SOMETHING")
        maybe_block_offsite_form_post(request)

    def test_whitelisted_paths(self):
        # There are a few whitelisted POST targets that don't require the
        # referrer be LP.  See comments in the code as to why and for related
        # bug reports.
        for path in OFFSITE_POST_WHITELIST:
            request = LaunchpadTestRequest(
                method="POST", environ=dict(PATH_INFO=path)
            )
            # this call shouldn't raise an exception
            maybe_block_offsite_form_post(request)

    def test_OAuth_signed_requests(self):
        # Requests that are OAuth signed are allowed.
        request = LaunchpadTestRequest(
            method="POST", environ=dict(PATH_INFO="/")
        )
        directlyProvides(request, IOAuthSignedRequest)
        # this call shouldn't raise an exception
        maybe_block_offsite_form_post(request)

    def test_access_token_verified_requests(self):
        # Requests that are verified with an access token are allowed.
        request = LaunchpadTestRequest(
            method="POST", environ=dict(PATH_INFO="/")
        )
        directlyProvides(request, IAccessTokenVerifiedRequest)
        # this call shouldn't raise an exception
        maybe_block_offsite_form_post(request)

    def test_nonbrowser_requests(self):
        # Requests that are from non-browsers are allowed.
        class FakeNonBrowserRequest:
            method = "SOMETHING"

        # this call shouldn't raise an exception
        maybe_block_offsite_form_post(FakeNonBrowserRequest)

    def test_onsite_posts(self):
        # Other than the explicit exceptions, all POSTs have to come from a
        # known LP virtual host.
        for hostname in allvhosts.hostnames:
            referer = "http://" + hostname + "/foo"
            request = LaunchpadTestRequest(
                method="POST", environ=dict(PATH_INFO="/", REFERER=referer)
            )
            # this call shouldn't raise an exception
            maybe_block_offsite_form_post(request)

    def test_offsite_posts(self):
        # If a post comes from an unknown host an exception is raised.
        disallowed_hosts = ["example.com", "not-subdomain.launchpad.net"]
        for hostname in disallowed_hosts:
            referer = "http://" + hostname + "/foo"
            request = LaunchpadTestRequest(
                method="POST", environ=dict(PATH_INFO="/", REFERER=referer)
            )
            self.assertRaises(
                OffsiteFormPostError, maybe_block_offsite_form_post, request
            )

    def test_unparsable_referer(self):
        # If a post has a referer that is unparsable as a URI an exception is
        # raised.
        referer = "this is not a URI"
        request = LaunchpadTestRequest(
            method="POST", environ=dict(PATH_INFO="/", REFERER=referer)
        )
        self.assertRaises(
            OffsiteFormPostError, maybe_block_offsite_form_post, request
        )

    def test_openid_callback_with_query_string(self):
        # An OpenId provider (OP) may post to the +openid-callback URL with a
        # query string and without a referer.  These posts need to be allowed.
        path_info = "/+openid-callback?starting_url=..."
        request = LaunchpadTestRequest(
            method="POST", environ=dict(PATH_INFO=path_info)
        )
        # this call shouldn't raise an exception
        maybe_block_offsite_form_post(request)


class TestEncodedReferer(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_not_found(self):
        # No oopses are reported when accessing the referer while rendering
        # the page.
        self.useFixture(FakeLogger())
        browser = self.getUserBrowser()
        browser.addHeader("Referer", "/whut\xe7foo")
        self.assertRaises(
            NotFound, browser.open, "http://launchpad.test/missing"
        )
        self.assertEqual(0, len(self.oopses))


class TestUnicodePath(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_non_ascii_url(self):
        # No oopses are reported when accessing the URL while rendering the
        # page.
        self.useFixture(FakeLogger())
        browser = self.getUserBrowser()
        self.assertRaises(
            NotFound, browser.open, "http://launchpad.test/%EC%B4%B5"
        )
        self.assertEqual(0, len(self.oopses))


class TestPublisherStats(StatsMixin, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setUpStats()

    def test_traversal_stats(self):
        self.useFixture(FakeLogger())
        browser = self.getUserBrowser()
        browser.open("http://launchpad.test")
        self.assertEqual(2, self.stats_client.timing.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.timing.call_args_list],
            MatchesListwise(
                [
                    MatchesListwise(
                        (
                            Equals(
                                "traversal_duration,env=test,"
                                "pageid=RootObject-index-html,success=True"
                            ),
                            GreaterThan(0),
                        )
                    ),
                    MatchesListwise(
                        (
                            Equals(
                                "publication_duration,env=test,"
                                "pageid=RootObject-index-html,success=True"
                            ),
                            GreaterThan(0),
                        )
                    ),
                ]
            ),
        )

    def test_traversal_failure_stats(self):
        self.useFixture(FakeLogger())
        browser = self.getUserBrowser()
        self.patch(
            LaunchpadBrowserPublication,
            "afterTraversal",
            FakeMethod(failure=Exception),
        )
        self.assertRaises(Exception, browser.open, "http://launchpad.test/")
        self.assertEqual(1, self.stats_client.timing.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.timing.call_args_list],
            MatchesListwise(
                [
                    MatchesListwise(
                        (
                            Equals(
                                "traversal_duration,env=test,"
                                "pageid=None,success=False"
                            ),
                            GreaterThan(0),
                        )
                    )
                ]
            ),
        )

    def test_publication_failure_stats(self):
        self.useFixture(FakeLogger())
        browser = self.getUserBrowser()
        self.patch(
            dbadapter,
            "set_permit_timeout_from_features",
            FakeMethod(failure=Exception),
        )
        self.assertRaises(Exception, browser.open, "http://launchpad.test/")
        self.assertEqual(2, self.stats_client.timing.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.timing.call_args_list],
            MatchesListwise(
                [
                    MatchesListwise(
                        (
                            Equals(
                                "traversal_duration,env=test,"
                                "pageid=RootObject-index-html,success=True"
                            ),
                            GreaterThan(0),
                        )
                    ),
                    MatchesListwise(
                        (
                            Equals(
                                "publication_duration,env=test,"
                                "pageid=RootObject-index-html,success=False"
                            ),
                            GreaterThan(0),
                        )
                    ),
                ]
            ),
        )

    def test_prepPageIDForMetrics_none(self):
        # Sometimes we have no pageid
        publication = LaunchpadBrowserPublication(None)
        self.assertIsNone(publication._prepPageIDForMetrics(None))

    def test_prepPageIDForMetrics_pageid(self):
        # Pageids have characters that are invalid in statsd protocol
        publication = LaunchpadBrowserPublication(None)
        self.assertEqual(
            "RootObject-index-html",
            publication._prepPageIDForMetrics("RootObject:index.html"),
        )

    def test_no_context_pageid(self):
        # request context may not exist in redirect scenarios
        owner = self.factory.makePerson()
        ppa = self.factory.makeArchive(owner=owner)
        redirect_url = (
            "http://launchpad.test/api/devel/~{}/"
            "+archive/{}/testpackage".format(owner.name, ppa.name)
        )
        self.useFixture(FakeLogger())
        browser = self.getUserBrowser()
        # This shouldn't raise ValueError
        self.assertRaises(NotFound, browser.open, redirect_url)
