# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test snap package views."""

from fixtures import FakeLogger
from zope.security.interfaces import Unauthorized

from lp.app.enums import InformationType
from lp.registry.enums import BranchSharingPolicy
from lp.services.webapp import canonical_url
from lp.testing import BrowserTestCase, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tag_by_id,
    find_tags_by_class,
)


class BaseTestSnapView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FakeLogger())
        self.person = self.factory.makePerson(name="snap-owner")

    def makeSnap(self, project=None, **kwargs):
        [ref] = self.factory.makeGitRefs(
            owner=self.person,
            target=self.person,
            name="snap-repository",
            paths=["refs/heads/master"],
        )
        if project is None:
            project = self.factory.makeProduct(
                owner=self.person, registrant=self.person
            )
        return self.factory.makeSnap(
            registrant=self.person,
            owner=self.person,
            name="snap-name",
            git_ref=ref,
            project=project,
            **kwargs,
        )

    def getSubscriptionPortletText(self, browser):
        return extract_text(
            find_tag_by_id(browser.contents, "portlet-subscribers")
        )

    def extractMainText(self, browser):
        return extract_text(find_main_content(browser.contents))

    def extractInfoMessageContent(self, browser):
        return extract_text(
            find_tags_by_class(browser.contents, "informational message")[0]
        )


class TestPublicSnapSubscriptionViews(BaseTestSnapView):
    def test_subscribe_self(self):
        snap = self.makeSnap()
        another_user = self.factory.makePerson(name="another-user")
        browser = self.getViewBrowser(snap, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe yourself
            Subscribe someone else
            Subscribers
            Snap-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

        # Go to "subscribe myself" page, and click the button.
        browser = self.getViewBrowser(
            snap, view_name="+subscribe", user=another_user
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe to snap recipe
            Snap packages
            snap-name
            Subscribe to snap recipe or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Subscribe").click()

        # We should be redirected back to snap page.
        with admin_logged_in():
            self.assertEqual(canonical_url(snap), browser.url)

        # And the new user should be listed in the subscribers list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Another-user
            Snap-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

    def test_unsubscribe_self(self):
        snap = self.makeSnap()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(snap.owner):
            snap.subscribe(another_user, snap.owner)
        subscription = snap.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit subscription to snap recipe for Another-user
            Snap packages
            snap-name
            If you unsubscribe from a snap recipe it will no longer show up on
            your personal pages. or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Another-user has been unsubscribed from this snap recipe.
            """,
            self.extractInfoMessageContent(browser),
        )
        with person_logged_in(self.person):
            self.assertIsNone(snap.getSubscription(another_user))

    def test_subscribe_someone_else(self):
        snap = self.makeSnap()
        another_user = self.factory.makePerson(name="another-user")
        browser = self.getViewBrowser(snap, user=snap.owner)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Snap-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

        # Go to "subscribe" page, and click the button.
        browser = self.getViewBrowser(
            snap, view_name="+addsubscriber", user=another_user
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe to snap recipe
            Snap packages
            snap-name
            Subscribe to snap recipe
            Person:
            .*
            The person subscribed to the related snap recipe.
            or
            Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl(name="field.person").value = "another-user"
        browser.getControl("Subscribe").click()

        # We should be redirected back to snap page.
        with admin_logged_in():
            self.assertEqual(canonical_url(snap), browser.url)

        # And the new user should be listed in the subscribers list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Another-user
            Snap-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

    def test_unsubscribe_someone_else(self):
        snap = self.makeSnap()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(snap.owner):
            snap.subscribe(another_user, snap.owner)

        subscription = snap.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=snap.owner)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit subscription to snap recipe for Another-user
            Snap packages
            snap-name
            If you unsubscribe from a snap recipe it will no longer show up on
            your personal pages. or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Another-user has been unsubscribed from this snap recipe.
            """,
            self.extractInfoMessageContent(browser),
        )
        with person_logged_in(self.person):
            self.assertIsNone(snap.getSubscription(another_user))


class TestPrivateSnapSubscriptionViews(BaseTestSnapView):
    def makePrivateSnap(self, **kwargs):
        project = self.factory.makeProduct(
            owner=self.person,
            registrant=self.person,
            information_type=InformationType.PROPRIETARY,
            branch_sharing_policy=BranchSharingPolicy.PROPRIETARY,
        )
        return self.makeSnap(
            information_type=InformationType.PROPRIETARY, project=project
        )

    def test_cannot_subscribe_to_private_snap(self):
        snap = self.makePrivateSnap()
        another_user = self.factory.makePerson(name="another-user")
        # Unsubscribed user should not see the snap page.
        self.assertRaises(
            Unauthorized, self.getViewBrowser, snap, user=another_user
        )
        # Nor the subscribe pages.
        self.assertRaises(
            Unauthorized,
            self.getViewBrowser,
            snap,
            view_name="+subscribe",
            user=another_user,
        )
        self.assertRaises(
            Unauthorized,
            self.getViewBrowser,
            snap,
            view_name="+addsubscriber",
            user=another_user,
        )

    def test_snap_owner_can_subscribe_someone_to_private_snap(self):
        snap = self.makePrivateSnap()
        another_user = self.factory.makePerson(name="another-user")

        # Go to "subscribe" page, and click the button.
        browser = self.getViewBrowser(
            snap, view_name="+addsubscriber", user=self.person
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe to snap recipe
            Snap packages
            snap-name
            Subscribe to snap recipe
            Person:
            .*
            The person subscribed to the related snap recipe.
            or
            Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl(name="field.person").value = "another-user"
        browser.getControl("Subscribe").click()

        # Now the new user should be listed in the subscribers list,
        # and have access to the snap page.
        browser = self.getViewBrowser(snap, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Another-user
            Snap-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

    def test_unsubscribe_self(self):
        snap = self.makePrivateSnap()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(self.person):
            snap.subscribe(another_user, self.person)
            subscription = snap.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit subscription to snap recipe for Another-user
            Snap packages
            snap-name
            If you unsubscribe from a snap recipe it will no longer show up on
            your personal pages. or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Another-user has been unsubscribed from this snap recipe.
            """,
            self.extractInfoMessageContent(browser),
        )
        with person_logged_in(self.person):
            self.assertIsNone(snap.getSubscription(another_user))
