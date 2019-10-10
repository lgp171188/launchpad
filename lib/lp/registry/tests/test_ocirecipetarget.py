# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `OCIRecipeTarget` and `OCIRecipeTargetSet`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility

from lp.registry.interfaces.ocirecipetarget import IOCIRecipeTargetSet
from lp.registry.model.ocirecipename import OCIRecipeName
from lp.registry.model.ocirecipetarget import OCIRecipeTarget
from lp.services.database.interfaces import IStore
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class OCIRecipeTargetTest(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        recipe_target = self.factory.makeOCIRecipeTarget()
        self.assertTrue(recipe_target)

    def test_getByDistribution(self):
        distribution = self.factory.makeDistribution()
        recipe_target = self.factory.makeOCIRecipeTarget(
            pillar=distribution)

        # Make sure there's more than one to get the result from
        self.factory.makeOCIRecipeTarget(
            pillar=self.factory.makeDistribution())

        fetched_targets = getUtility(
            IOCIRecipeTargetSet).findByDistribution(distribution)
        self.assertEqual(1, fetched_targets.count())
        self.assertEqual(recipe_target, fetched_targets.first())
