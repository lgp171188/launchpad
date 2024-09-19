# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test views for objects that have rock recipes."""

from testscenarios import WithScenarios, load_tests_apply_scenarios

from lp.code.interfaces.gitrepository import IGitRepository
from lp.rocks.interfaces.rockrecipe import ROCK_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_initialized_view


def make_git_repository(test_case):
    return test_case.factory.makeGitRepository()


def make_git_ref(test_case):
    return test_case.factory.makeGitRefs()[0]


class TestHasRockRecipesView(WithScenarios, TestCaseWithFactory):

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
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def makeRockRecipe(self, context):
        if IGitRepository.providedBy(context):
            [context] = self.factory.makeGitRefs(repository=context)
        return self.factory.makeRockRecipe(git_ref=context)

    def test_rock_recipes_link_no_recipes(self):
        # An object with no rock recipes does not show a rock recipes link.
        context = self.context_factory(self)
        view = create_initialized_view(context, "+index")
        self.assertEqual(
            "No rock recipes using this %s." % self.context_type,
            view.rock_recipes_link,
        )

    def test_rock_recipes_link_one_recipe(self):
        # An object with one rock recipe shows a link to that recipe.
        context = self.context_factory(self)
        recipe = self.makeRockRecipe(context)
        view = create_initialized_view(context, "+index")
        expected_link = '<a href="%s">1 rock recipe</a> using this %s.' % (
            canonical_url(recipe),
            self.context_type,
        )
        self.assertEqual(expected_link, view.rock_recipes_link)

    def test_rock_recipes_link_more_recipes(self):
        # An object with more than one rock recipe shows a link to a listing.
        context = self.context_factory(self)
        self.makeRockRecipe(context)
        self.makeRockRecipe(context)
        view = create_initialized_view(context, "+index")
        expected_link = (
            '<a href="+rock-recipes">2 rock recipes</a> using this %s.'
            % self.context_type
        )
        self.assertEqual(expected_link, view.rock_recipes_link)


load_tests = load_tests_apply_scenarios
