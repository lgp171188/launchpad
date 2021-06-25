# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for charm recipe jobs."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.charms.interfaces.charmrecipejob import (
    ICharmRecipeJob,
    ICharmRecipeRequestBuildsJob,
    )
from lp.charms.model.charmrecipejob import (
    CharmRecipeJob,
    CharmRecipeJobType,
    CharmRecipeRequestBuildsJob,
    )
from lp.services.features.testing import FeatureFixture
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestCharmRecipeJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestCharmRecipeJob, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CharmRecipeJob` objects provide `ICharmRecipeJob`.
        recipe = self.factory.makeCharmRecipe()
        self.assertProvides(
            CharmRecipeJob(recipe, CharmRecipeJobType.REQUEST_BUILDS, {}),
            ICharmRecipeJob)


class TestCharmRecipeRequestBuildsJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super(TestCharmRecipeRequestBuildsJob, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CharmRecipeRequestBuildsJob` objects provide
        # `ICharmRecipeRequestBuildsJob`."""
        recipe = self.factory.makeCharmRecipe()
        job = CharmRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertProvides(job, ICharmRecipeRequestBuildsJob)

    def test___repr__(self):
        # `CharmRecipeRequestBuildsJob` objects have an informative __repr__.
        recipe = self.factory.makeCharmRecipe()
        job = CharmRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertEqual(
            "<CharmRecipeRequestBuildsJob for ~%s/%s/+charm/%s>" % (
                recipe.owner.name, recipe.project.name, recipe.name),
            repr(job))
