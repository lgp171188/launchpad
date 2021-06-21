# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test charm recipe views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestCharmRecipeNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestCharmRecipeNavigation, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_canonical_url(self):
        owner = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="project")
        recipe = self.factory.makeCharmRecipe(
            registrant=owner, owner=owner, project=project, name="charm")
        self.assertEqual(
            "http://launchpad.test/~person/project/+charm/charm",
            canonical_url(recipe))
