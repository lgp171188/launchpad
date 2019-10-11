# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `OCIProject` and `OCIProjectSet`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility

from lp.registry.interfaces.ociproject import (
    IOCIProject,
    IOCIProjectSet,
    )
from lp.testing import (
    admin_logged_in,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIProject(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        recipe_target = self.factory.makeOCIProject()
        with admin_logged_in():
            self.assertProvides(recipe_target, IOCIProject)


class TestOCIProjectSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target_set = getUtility(IOCIProjectSet)
        with admin_logged_in():
            self.assertProvides(target_set, IOCIProjectSet)

    def test_new_recipe_target(self):
        registrant = self.factory.makePerson()
        distribution = self.factory.makeDistribution(owner=registrant)
        recipe_name = self.factory.makeOCIProjectName()
        target = getUtility(IOCIProjectSet).new(
            registrant,
            distribution,
            recipe_name
        )
        with person_logged_in(registrant):
            self.assertEqual(target.registrant, registrant)
            self.assertEqual(target.distribution, distribution)
            self.assertEqual(target.pillar, distribution)
            self.assertEqual(target.ociprojectname, recipe_name)

    def test_getByDistributionAndName(self):
        registrant = self.factory.makePerson()
        distribution = self.factory.makeDistribution(owner=registrant)
        recipe_target = self.factory.makeOCIProject(
            registrant=registrant, pillar=distribution)

        # Make sure there's more than one to get the result from
        self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution())

        with person_logged_in(registrant):
            fetched_result = getUtility(
                IOCIProjectSet).getByDistributionAndName(
                    distribution, recipe_target.ociprojectname.name)
            self.assertEqual(recipe_target, fetched_result)
