# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for craft recipe jobs."""

from lp.crafts.interfaces.craftrecipe import CRAFT_RECIPE_ALLOW_CREATE
from lp.crafts.interfaces.craftrecipejob import (
    ICraftRecipeJob,
    ICraftRecipeRequestBuildsJob,
)
from lp.crafts.model.craftrecipejob import (
    CraftRecipeJob,
    CraftRecipeJobType,
    CraftRecipeRequestBuildsJob,
)
from lp.services.features.testing import FeatureFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestCraftRecipeJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CraftRecipeJob` objects provide `ICraftRecipeJob`.
        recipe = self.factory.makeCraftRecipe()
        self.assertProvides(
            CraftRecipeJob(recipe, CraftRecipeJobType.REQUEST_BUILDS, {}),
            ICraftRecipeJob,
        )


class TestCraftRecipeRequestBuildsJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CraftRecipeRequestBuildsJob` objects provide
        # `ICraftRecipeRequestBuildsJob`."""
        recipe = self.factory.makeCraftRecipe()
        job = CraftRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertProvides(job, ICraftRecipeRequestBuildsJob)

    def test___repr__(self):
        # `CraftRecipeRequestBuildsJob` objects have an informative __repr__.
        recipe = self.factory.makeCraftRecipe()
        job = CraftRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertEqual(
            "<CraftRecipeRequestBuildsJob for ~%s/%s/+craft/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(job),
        )
