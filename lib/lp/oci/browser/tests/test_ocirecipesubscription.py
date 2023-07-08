# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI recipe subscription views."""

from fixtures import FakeLogger
from zope.security.interfaces import Unauthorized

from lp.app.enums import InformationType
from lp.oci.tests.helpers import OCIConfigHelperMixin
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


class BaseTestOCIRecipeView(OCIConfigHelperMixin, BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.setConfig()
        self.useFixture(FakeLogger())
        self.person = self.factory.makePerson(name="recipe-owner")

    def makeOCIRecipe(self, oci_project=None, **kwargs):
        [ref] = self.factory.makeGitRefs(
            owner=self.person,
            target=self.person,
            name="recipe-repository",
            paths=["refs/heads/v1.0-20.04"],
        )
        if oci_project is None:
            project = self.factory.makeProduct(
                owner=self.person, registrant=self.person
            )
            oci_project = self.factory.makeOCIProject(
                registrant=self.person,
                pillar=project,
                ociprojectname="my-oci-project",
            )
        return self.factory.makeOCIRecipe(
            registrant=self.person,
            owner=self.person,
            name="recipe-name",
            git_ref=ref,
            oci_project=oci_project,
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


class TestPublicOCIRecipeSubscriptionViews(BaseTestOCIRecipeView):
    def test_subscribe_self(self):
        recipe = self.makeOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")
        browser = self.getViewBrowser(recipe, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe yourself
            Subscribe someone else
            Subscribers
            Recipe-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

        # Go to "subscribe myself" page, and click the button.
        browser = self.getViewBrowser(
            recipe, view_name="+subscribe", user=another_user
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe to OCI recipe
            recipe-name
            Subscribe to OCI recipe or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Subscribe").click()

        # We should be redirected back to OCI page.
        with admin_logged_in():
            self.assertEqual(canonical_url(recipe), browser.url)

        # And the new user should be listed in the subscribers list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Another-user
            Recipe-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

    def test_unsubscribe_self(self):
        recipe = self.makeOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(recipe.owner):
            recipe.subscribe(another_user, recipe.owner)
        subscription = recipe.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit subscription to OCI recipe for Another-user
            If you unsubscribe from an OCI recipe it will no longer show up on
            your personal pages. or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Another-user has been unsubscribed from this OCI recipe.
            """,
            self.extractInfoMessageContent(browser),
        )
        with person_logged_in(self.person):
            self.assertIsNone(recipe.getSubscription(another_user))

    def test_subscribe_someone_else(self):
        recipe = self.makeOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")
        browser = self.getViewBrowser(recipe, user=recipe.owner)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Recipe-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

        # Go to "subscribe" page, and click the button.
        browser = self.getViewBrowser(
            recipe, view_name="+addsubscriber", user=another_user
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe to OCI recipe
            Person:
            .*
            The person subscribed to the related OCI recipe.
            or
            Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl(name="field.person").value = "another-user"
        browser.getControl("Subscribe").click()

        # We should be redirected back to OCI recipe page.
        with admin_logged_in():
            self.assertEqual(canonical_url(recipe), browser.url)

        # And the new user should be listed in the subscribers list.
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Another-user
            Recipe-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

    def test_unsubscribe_someone_else(self):
        recipe = self.makeOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(recipe.owner):
            recipe.subscribe(another_user, recipe.owner)

        subscription = recipe.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=recipe.owner)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit subscription to OCI recipe for Another-user
            If you unsubscribe from an OCI recipe it will no longer show up on
            your personal pages. or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Another-user has been unsubscribed from this OCI recipe.
            """,
            self.extractInfoMessageContent(browser),
        )
        with person_logged_in(self.person):
            self.assertIsNone(recipe.getSubscription(another_user))


class TestPrivateOCIRecipeSubscriptionViews(BaseTestOCIRecipeView):
    def makePrivateOCIRecipe(self, **kwargs):
        project = self.factory.makeProduct(
            owner=self.person,
            registrant=self.person,
            information_type=InformationType.PROPRIETARY,
            branch_sharing_policy=BranchSharingPolicy.PROPRIETARY,
        )
        oci_project = self.factory.makeOCIProject(
            ociprojectname="my-oci-project", pillar=project
        )
        return self.makeOCIRecipe(
            information_type=InformationType.PROPRIETARY,
            oci_project=oci_project,
        )

    def test_cannot_subscribe_to_private_snap(self):
        recipe = self.makePrivateOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")
        # Unsubscribed user should not see the OCI recipe page.
        self.assertRaises(
            Unauthorized, self.getViewBrowser, recipe, user=another_user
        )
        # Nor the subscribe pages.
        self.assertRaises(
            Unauthorized,
            self.getViewBrowser,
            recipe,
            view_name="+subscribe",
            user=another_user,
        )
        self.assertRaises(
            Unauthorized,
            self.getViewBrowser,
            recipe,
            view_name="+addsubscriber",
            user=another_user,
        )

    def test_recipe_owner_can_subscribe_someone_to_private_recipe(self):
        recipe = self.makePrivateOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")

        # Go to "subscribe" page, and click the button.
        browser = self.getViewBrowser(
            recipe, view_name="+addsubscriber", user=self.person
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Subscribe to OCI recipe
            Person:
            .*
            The person subscribed to the related OCI recipe.
            or
            Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl(name="field.person").value = "another-user"
        browser.getControl("Subscribe").click()

        # Now the new user should be listed in the subscribers list,
        # and have access to the recipe page.
        browser = self.getViewBrowser(recipe, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit your subscription
            Subscribe someone else
            Subscribers
            Another-user
            Recipe-owner
            """,
            self.getSubscriptionPortletText(browser),
        )

    def test_unsubscribe_self(self):
        recipe = self.makePrivateOCIRecipe()
        another_user = self.factory.makePerson(name="another-user")
        with person_logged_in(self.person):
            recipe.subscribe(another_user, self.person)
            subscription = recipe.getSubscription(another_user)
        browser = self.getViewBrowser(subscription, user=another_user)
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Edit subscription to OCI recipe for Another-user
            If you unsubscribe from an OCI  recipe it will no longer show up on
            your personal pages. or Cancel
            """,
            self.extractMainText(browser),
        )
        browser.getControl("Unsubscribe").click()
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r"""
            Another-user has been unsubscribed from this OCI recipe.
            """,
            self.extractInfoMessageContent(browser),
        )
        with person_logged_in(self.person):
            self.assertIsNone(recipe.getSubscription(another_user))
