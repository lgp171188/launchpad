# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for rock recipe jobs."""

from lp.rocks.interfaces.rockrecipe import ROCK_RECIPE_ALLOW_CREATE
from lp.rocks.interfaces.rockrecipejob import (
    IRockRecipeJob,
    IRockRecipeRequestBuildsJob,
)
from lp.rocks.model.rockrecipejob import (
    RockRecipeJob,
    RockRecipeJobType,
    RockRecipeRequestBuildsJob,
)
from lp.services.features.testing import FeatureFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestRockRecipeJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `RockRecipeJob` objects provide `IRockRecipeJob`.
        recipe = self.factory.makeRockRecipe()
        self.assertProvides(
            RockRecipeJob(recipe, RockRecipeJobType.REQUEST_BUILDS, {}),
            IRockRecipeJob,
        )


class TestRockRecipeRequestBuildsJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `RockRecipeRequestBuildsJob` objects provide
        # `IRockRecipeRequestBuildsJob`."""
        recipe = self.factory.makeRockRecipe()
        job = RockRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertProvides(job, IRockRecipeRequestBuildsJob)

    def test___repr__(self):
        # `RockRecipeRequestBuildsJob` objects have an informative __repr__.
        recipe = self.factory.makeRockRecipe()
        job = RockRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertEqual(
            "<RockRecipeRequestBuildsJob for ~%s/%s/+rock/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(job),
        )
