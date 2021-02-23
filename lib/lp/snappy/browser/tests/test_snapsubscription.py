# -*- coding: utf-8 -*-
# NOTE: The first line above must stay first; do not move the copyright
# notice to the top.  See http://www.python.org/dev/peps/pep-0263/.
#
# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test snap package views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
import json
import re

from fixtures import FakeLogger
from lp.services.database.interfaces import IStore
from pymacaroons import Macaroon
import pytz
import responses
from six.moves.urllib.parse import (
    parse_qs,
    urlsplit,
    )
import soupmatchers
from testtools.matchers import (
    AfterPreprocessing,
    Equals,
    Is,
    MatchesDict,
    MatchesListwise,
    MatchesSetwise,
    MatchesStructure,
    Not,
    )
import transaction
from zope.component import getUtility
from zope.publisher.interfaces import NotFound
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy
from zope.testbrowser.browser import LinkNotFoundError

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.code.errors import (
    BranchHostingFault,
    GitRepositoryScanFault,
    )
from lp.code.tests.helpers import (
    BranchHostingFixture,
    GitHostingFixture,
    )
from lp.registry.enums import (
    PersonVisibility,
    TeamMembershipPolicy,
    )
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import get_property_cache
from lp.services.webapp import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.snappy.browser.snap import (
    SnapAdminView,
    SnapEditView,
    SnapView,
    )
from lp.snappy.interfaces.snap import (
    CannotModifySnapProcessor,
    ISnapSet,
    SNAP_PRIVATE_FEATURE_FLAG,
    SNAP_TESTING_FLAGS,
    SnapBuildRequestStatus,
    SnapPrivateFeatureDisabled,
    )
from lp.snappy.interfaces.snappyseries import ISnappyDistroSeriesSet
from lp.snappy.interfaces.snapstoreclient import ISnapStoreClient
from lp.testing import (
    admin_logged_in,
    BrowserTestCase,
    login,
    login_admin,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    time_counter,
    )
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.matchers import (
    MatchesPickerText,
    MatchesTagText,
    )
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tag_by_id,
    find_tags_by_class,
    get_feedback_messages,
    )
from lp.testing.publication import test_traverse
from lp.testing.views import (
    create_initialized_view,
    create_view,
    )


class BaseTestSnapView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(BaseTestSnapView, self).setUp()
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))
        self.useFixture(FakeLogger())


class TestSnapSubscriptionListView(BaseTestSnapView):

    def setUp(self):
        super(TestSnapSubscriptionListView, self).setUp()
        self.person = self.factory.makePerson(name='snap-owner')

    def makeSnap(self, **kwargs):
        [ref] = self.factory.makeGitRefs(
            owner=self.person, target=self.person, name="snap-repository",
            paths=["refs/heads/master"])
        project = self.factory.makeProduct(
            owner=self.person, registrant=self.person)
        return self.factory.makeSnap(
            registrant=self.person, owner=self.person, name="snap-name",
            git_ref=ref, project=project, **kwargs)

    def getSubscriptionPortletText(self, browser):
        return extract_text(
            find_tag_by_id(browser.contents, 'portlet-subscribers'))

    def extractMainText(self, browser):
        return extract_text(find_main_content(browser.contents))

    def extractInfoMessageContent(self, browser):
        return extract_text(
            find_tags_by_class(browser.contents, 'informational message')[0])

    def test_subscribe_self(self):
        snap = self.makeSnap()
        another_user = self.factory.makePerson(name="another-user")
        browser = self.getViewBrowser(snap, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""
            Subscribe yourself
            Subscribers
            Snap-owner
            """, self.getSubscriptionPortletText(browser))

        # Go to "subscribe myself" page, and click the button.
        browser = self.getViewBrowser(
            snap, view_name="+subscribe", user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""
            Subscribe to Snap recipe
            Snap packages
            snap-name
            Subscribe to Snap recipe or Cancel
            """, self.extractMainText(browser))
        browser.getControl("Subscribe").click()

        # We should be redirected back to snap page.
        with admin_logged_in():
            self.assertEqual(canonical_url(snap), browser.url)

        # And the new user should be listed in the subscribers list.
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""
            Edit your subscription
            Subscribers
            Another-user
            Snap-owner
            """, self.getSubscriptionPortletText(browser))

    def test_unsubscribe_self(self):
        snap = self.makeSnap()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(snap.owner):
            snap.subscribe(another_user, snap.owner)
        subscription = snap.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""
            Edit subscription to Snap recipe for Another-user
            Snap packages
            snap-name
            If you unsubscribe from a snap recipe it will no longer show up on
            your personal pages. or Cancel
            """, self.extractMainText(browser))
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(r"""
            Another-user has been unsubscribed from this Snap recipe.
            """, self.extractInfoMessageContent(browser))
        with person_logged_in(self.person):
            self.assertIsNone(snap.getSubscription(another_user))
