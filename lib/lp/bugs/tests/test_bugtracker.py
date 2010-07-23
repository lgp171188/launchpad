# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from doctest import NORMALIZE_WHITESPACE, ELLIPSIS
from doctest import DocTestSuite

import unittest
from urllib2 import HTTPError, Request
from datetime import datetime, timedelta
from pytz import utc

from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lazr.lifecycle.snapshot import Snapshot

from canonical.launchpad.ftests import login_person
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.testing import LaunchpadFunctionalLayer

from lp.bugs.externalbugtracker import (
    BugTrackerConnectError, Mantis, MantisLoginHandler)
from lp.bugs.interfaces.bugtracker import BugTrackerType, IBugTracker
from lp.bugs.tests.externalbugtracker import Urlib2TransportTestHandler
from lp.registry.interfaces.person import IPersonSet
from lp.testing import login, login_person, TestCaseWithFactory
from lp.testing.sampledata import ADMIN_EMAIL


class BugTrackerTestCase(TestCaseWithFactory):
    """Unit tests for the `BugTracker` class."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(BugTrackerTestCase, self).setUp()
        self.bug_tracker = self.factory.makeBugTracker()
        for i in range(5):
            self.factory.makeBugWatch(bugtracker=self.bug_tracker)

        self.now = datetime.now(utc)

    def test_multi_product_constraints_observed(self):
        """BugTrackers for which multi_product=True should return None
        when no remote product is passed to getBugFilingURL().

        BugTrackers for which multi_product=False should still return a
        URL even when getBugFilingURL() is passed no remote product.
        """
        for type in BugTrackerType.items:
            bugtracker = self.factory.makeBugTracker(bugtrackertype=type)

            bugtracker_urls = bugtracker.getBugFilingAndSearchLinks(None)
            bug_filing_url = bugtracker_urls['bug_filing_url']
            bug_search_url = bugtracker_urls['bug_search_url']

            if bugtracker.multi_product:
                self.assertTrue(
                    bug_filing_url is None,
                    "getBugFilingAndSearchLinks() should return a "
                    "bug_filing_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)
                self.assertTrue(
                    bug_search_url is None,
                    "getBugFilingAndSearchLinks() should return a "
                    "bug_search_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)
            else:
                self.assertTrue(
                    bug_filing_url is not None,
                    "getBugFilingAndSearchLinks() should not return a "
                    "bug_filing_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)
                self.assertTrue(
                    bug_search_url is not None,
                    "getBugFilingAndSearchLinks() should not return a "
                    "bug_search_url of None for BugTrackers of type %s when "
                    "no remote product is passed." %
                    type.title)

    def test_attributes_not_in_snapshot(self):
        # A snapshot of an IBugTracker will not contain a copy of
        # several attributes.
        marker = object()
        original = self.factory.makeBugTracker()
        attributes = [
            'watches',
            'watches_needing_update',
            'watches_ready_to_check',
            'watches_with_unpushed_comments',
            ]
        for attribute in attributes:
            self.failUnless(
                getattr(original, attribute, marker) is not marker,
                "Attribute %s missing from bug tracker." % attribute)
        snapshot = Snapshot(original, providing=IBugTracker)
        for attribute in attributes:
            self.failUnless(
                getattr(snapshot, attribute, marker) is marker,
                "Attribute %s not missing from snapshot." % attribute)

    def test_watches_ready_to_check(self):
        bug_tracker = self.factory.makeBugTracker()
        # Initially there are no watches, so none need to be checked.
        self.failUnless(bug_tracker.watches_ready_to_check.is_empty())
        # A bug watch without a next_check set is not ready either.
        bug_watch = self.factory.makeBugWatch(bugtracker=bug_tracker)
        removeSecurityProxy(bug_watch).next_check = None
        self.failUnless(bug_tracker.watches_ready_to_check.is_empty())
        # If we set its next_check date, it will be ready.
        removeSecurityProxy(bug_watch).next_check = (
            datetime.now(utc) - timedelta(hours=1))
        self.failUnless(1, bug_tracker.watches_ready_to_check.count())
        self.failUnlessEqual(
            bug_watch, bug_tracker.watches_ready_to_check.one())

    def test_watches_with_unpushed_comments(self):
        bug_tracker = self.factory.makeBugTracker()
        # Initially there are no watches, so there are no unpushed
        # comments.
        self.failUnless(bug_tracker.watches_with_unpushed_comments.is_empty())
        # A new bug watch has no comments, so the same again.
        bug_watch = self.factory.makeBugWatch(bugtracker=bug_tracker)
        self.failUnless(bug_tracker.watches_with_unpushed_comments.is_empty())
        # A comment linked to the bug watch will be found.
        login_person(bug_watch.bug.owner)
        message = self.factory.makeMessage(owner=bug_watch.owner)
        bug_message = bug_watch.bug.linkMessage(message, bug_watch)
        self.failUnless(1, bug_tracker.watches_with_unpushed_comments.count())
        self.failUnlessEqual(
            bug_watch, bug_tracker.watches_with_unpushed_comments.one())
        # Once the comment has been pushed, it will no longer be found.
        removeSecurityProxy(bug_message).remote_comment_id = 'brains'
        self.failUnless(bug_tracker.watches_with_unpushed_comments.is_empty())

    def _assertBugWatchesAreCheckedInTheFuture(self):
        """Check the dates of all self.bug_tracker.watches.

        Raise an error if:
         * The next_check dates aren't in the future.
         * The next_check dates aren't <= 1 day in the future.
         * The lastcheck dates are not None
         * The last_error_types are not None.
        """
        for watch in self.bug_tracker.watches:
            self.assertTrue(
                watch.next_check is not None,
                "BugWatch next_check time should not be None.")
            self.assertTrue(
                watch.next_check >= self.now,
                "BugWatch next_check time should be in the future.")
            self.assertTrue(
                watch.next_check <= self.now + timedelta(days=1),
                "BugWatch next_check time should be one day or less in "
                "the future.")
            self.assertTrue(
                watch.lastchecked is None,
                "BugWatch lastchecked should be None.")
            self.assertTrue(
                watch.last_error_type is None,
                "BugWatch last_error_type should be None.")

    def test_unprivileged_user_cant_reset_watches(self):
        # It isn't possible for a user who isn't an admin or a member of
        # the Launchpad Developers team to reset the watches for a bug
        # tracker.
        unprivileged_user = self.factory.makePerson()
        login_person(unprivileged_user)
        self.assertRaises(
            Unauthorized, self.bug_tracker.resetWatches,
            user=unprivileged_user)

    def test_admin_can_reset_watches(self):
        # Launchpad admins can reset the watches on a bugtracker.
        admin_user = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        login_person(admin_user)
        self.bug_tracker.resetWatches(user=admin_user)
        self._assertBugWatchesAreCheckedInTheFuture()

    def test_lp_dev_can_reset_watches(self):
        # Launchpad developers can reset the watches on a bugtracker.
        login(ADMIN_EMAIL)
        admin = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        launchpad_developers = getUtility(
            ILaunchpadCelebrities).launchpad_developers
        lp_dev = self.factory.makePerson()
        launchpad_developers.addMember(lp_dev, admin)
        login_person(lp_dev)
        self.bug_tracker.resetWatches(user=lp_dev)
        self._assertBugWatchesAreCheckedInTheFuture()

    def test_janitor_can_reset_watches(self):
        # The Janitor can reset the watches on a bug tracker.
        janitor = getUtility(ILaunchpadCelebrities).janitor
        login_person(janitor)
        self.bug_tracker.resetWatches(user=janitor)


class TestMantis(TestCaseWithFactory):
    """Tests for the Mantis-specific bug tracker code."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestMantis, self).setUp()

    def test_mantis_login_redirects(self):
        # The Mantis bug tracker needs a special HTTP redirect handler
        # in order to login in. Ensure that redirects to the page with
        # the login form are indeed changed to redirects the form submit
        # URL.
        handler = MantisLoginHandler()
        request = Request('http://mantis.example.com/some/path')
        # Let's pretend that Mantis sent a redirect request to the
        # login page.
        new_request = handler.redirect_request(
            request, None, 302, None, None,
            'http://mantis.example.com/login_page.php'
            '?return=%2Fview.php%3Fid%3D3301')
        self.assertEqual(
            'http://mantis.example.com/login.php?'
            'username=guest&password=guest&return=%2Fview.php%3Fid%3D3301',
            new_request.get_full_url())

    def test_mantis_login_redirect_handler_is_used(self):
        # Ensure that the special Mantis login handler is used
        # by the Mantis tracker
        tracker = Mantis('http://mantis.example.com')
        test_handler = Urlib2TransportTestHandler()
        test_handler.setRedirect('http://mantis.example.com/login_page.php'
            '?return=%2Fsome%2Fpage')
        opener = tracker._opener
        opener.add_handler(test_handler)
        opener.open('http://mantis.example.com/some/page')
        # We should now have two entries in the test handler's list
        # of visited URLs: The original URL we wanted to visit and the
        # URL changed by the MantisLoginHandler.
        self.assertEqual(
            ['http://mantis.example.com/some/page',
             'http://mantis.example.com/login.php?'
             'username=guest&password=guest&return=%2Fsome%2Fpage'],
            test_handler.accessed_urls)

    def test_mantis_opener_can_handle_cookies(self):
        # Ensure that the OpenerDirector of the Mantis bug tracker
        # handles cookies.
        tracker = Mantis('http://mantis.example.com')
        test_handler = Urlib2TransportTestHandler()
        opener = tracker._opener
        opener.add_handler(test_handler)
        opener.open('http://mantis.example.com', '')
        cookies = list(tracker._cookie_handler.cookiejar)
        self.assertEqual(1, len(cookies))
        self.assertEqual('foo', cookies[0].name)
        self.assertEqual('bar', cookies[0].value)

    def test_mantis_csv_file_http_500_error(self):
        # If a Mantis bug tracker returns a HTTP 500 error when the
        # URL for CSV data is accessed, we treat this as an
        # indication that we should screen scrape the bug data and
        # thus set csv_data to None.
        tracker = Mantis('http://mantis.example.com')
        test_handler = Urlib2TransportTestHandler()
        opener = tracker._opener
        opener.add_handler(test_handler)
        test_handler.setError(
            HTTPError(
                'http://mantis.example.com/csv_export.php', 500,
                'Internal Error', {}, None),
            'http://mantis.example.com/csv_export.php')
        self.assertIs(None, tracker.csv_data)

    def test_mantis_csv_file_other_http_errors(self):
        # If the Mantis server returns other HTTP errors than 500,
        # they appear as BugTrackerConnectErrors.
        tracker = Mantis('http://mantis.example.com')
        test_handler = Urlib2TransportTestHandler()
        opener = tracker._opener
        opener.add_handler(test_handler)
        test_handler.setError(
            HTTPError(
                'http://mantis.example.com/csv_export.php', 503,
                'Service Unavailable', {}, None),
            'http://mantis.example.com/csv_export.php')
        self.assertRaises(BugTrackerConnectError, tracker._csv_data)

        test_handler.setError(
            HTTPError(
                'http://mantis.example.com/csv_export.php', 404,
                'Not Found', {}, None),
            'http://mantis.example.com/csv_export.php')
        self.assertRaises(BugTrackerConnectError, tracker._csv_data)


def test_suite():
    suite = unittest.TestLoader().loadTestsFromName(__name__)
    doctest_suite = DocTestSuite(
        'lp.bugs.model.bugtracker',
        optionflags=NORMALIZE_WHITESPACE|ELLIPSIS)
    suite.addTest(doctest_suite)
    return suite
