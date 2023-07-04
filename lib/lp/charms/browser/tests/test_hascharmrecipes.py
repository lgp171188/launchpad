# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test views for objects that have charm recipes."""

import soupmatchers
from testscenarios import WithScenarios, load_tests_apply_scenarios
from testtools.matchers import Not

from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.code.interfaces.gitrepository import IGitRepository
from lp.code.tests.helpers import GitHostingFixture
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_initialized_view


def make_git_repository(test_case):
    return test_case.factory.makeGitRepository()


def make_git_ref(test_case):
    return test_case.factory.makeGitRefs()[0]


class TestHasCharmRecipesView(WithScenarios, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    scenarios = [
        (
            "GitRepository",
            {
                "context_type": "repository",
                "context_factory": make_git_repository,
            },
        ),
        (
            "GitRef",
            {
                "context_type": "branch",
                "context_factory": make_git_ref,
            },
        ),
    ]

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def makeCharmRecipe(self, context):
        if IGitRepository.providedBy(context):
            [context] = self.factory.makeGitRefs(repository=context)
        return self.factory.makeCharmRecipe(git_ref=context)

    def test_charm_recipes_link_no_recipes(self):
        # An object with no charm recipes does not show a charm recipes link.
        context = self.context_factory(self)
        view = create_initialized_view(context, "+index")
        self.assertEqual(
            "No charm recipes using this %s." % self.context_type,
            view.charm_recipes_link,
        )

    def test_charm_recipes_link_one_recipe(self):
        # An object with one charm recipe shows a link to that recipe.
        context = self.context_factory(self)
        recipe = self.makeCharmRecipe(context)
        view = create_initialized_view(context, "+index")
        expected_link = '<a href="%s">1 charm recipe</a> using this %s.' % (
            canonical_url(recipe),
            self.context_type,
        )
        self.assertEqual(expected_link, view.charm_recipes_link)

    def test_charm_recipes_link_more_recipes(self):
        # An object with more than one charm recipe shows a link to a listing.
        context = self.context_factory(self)
        self.makeCharmRecipe(context)
        self.makeCharmRecipe(context)
        view = create_initialized_view(context, "+index")
        expected_link = (
            '<a href="+charm-recipes">2 charm recipes</a> using this %s.'
            % self.context_type
        )
        self.assertEqual(expected_link, view.charm_recipes_link)


class TestHasCharmRecipesMenu(WithScenarios, TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    scenarios = [
        ("GitRef", {"context_factory": make_git_ref}),
    ]

    def setUp(self):
        super().setUp()
        self.useFixture(GitHostingFixture())

    def makeCharmRecipe(self, context):
        return self.factory.makeCharmRecipe(git_ref=context)

    def test_feature_flag_disabled(self):
        # If the feature flag to allow charm recipe creation is disabled, we
        # don't show a creation link.
        context = self.context_factory(self)
        view = create_initialized_view(context, "+index")
        new_charm_recipe_url = canonical_url(
            context, view_name="+new-charm-recipe"
        )
        self.assertThat(
            view(),
            Not(
                soupmatchers.HTMLContains(
                    soupmatchers.Tag(
                        "creation link",
                        "a",
                        attrs={"href": new_charm_recipe_url},
                        text="Create charm recipe",
                    )
                )
            ),
        )

    def test_creation_link_no_recipes(self):
        # An object with no charm recipes shows a creation link.
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        context = self.context_factory(self)
        view = create_initialized_view(context, "+index")
        new_charm_recipe_url = canonical_url(
            context, view_name="+new-charm-recipe"
        )
        self.assertThat(
            view(),
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "creation link",
                    "a",
                    attrs={"href": new_charm_recipe_url},
                    text="Create charm recipe",
                )
            ),
        )

    def test_creation_link_recipes(self):
        # An object with charm recipes shows a creation link.
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        context = self.context_factory(self)
        self.makeCharmRecipe(context)
        view = create_initialized_view(context, "+index")
        new_charm_recipe_url = canonical_url(
            context, view_name="+new-charm-recipe"
        )
        self.assertThat(
            view(),
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "creation link",
                    "a",
                    attrs={"href": new_charm_recipe_url},
                    text="Create charm recipe",
                )
            ),
        )


load_tests = load_tests_apply_scenarios
