# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `OCIRecipeTarget` and `OCIRecipeTargetSet`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility

from lp.registry.interfaces.ocirecipetarget import (
    IOCIRecipeTarget,
    IOCIRecipeTargetSet,
    )
from lp.registry.model.ocirecipename import OCIRecipeName
from lp.registry.model.ocirecipetarget import OCIRecipeTarget
from lp.services.database.interfaces import IStore
from lp.testing import (
    admin_logged_in,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIRecipeTarget(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        recipe_target = self.factory.makeOCIRecipeTarget()
        with admin_logged_in():
            self.assertProvides(recipe_target, IOCIRecipeTarget)

    def test_getByDistributionAndName(self):
        person = self.factory.makePerson()
        distribution = self.factory.makeDistribution(owner=person)
        recipe_target = self.factory.makeOCIRecipeTarget(
            registrant=person, pillar=distribution)

        # Make sure there's more than one to get the result from
        self.factory.makeOCIRecipeTarget(
            pillar=self.factory.makeDistribution())

        with person_logged_in(person):
            fetched_result = getUtility(
                IOCIRecipeTargetSet).getByDistributionAndName(
                    distribution, recipe_target.ocirecipename.name)
            self.assertEqual(recipe_target, fetched_result)
