# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIRecipeName."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.testcase import ExpectedException
from zope.component import getUtility

from lp.registry.errors import (
    InvalidName,
    NoSuchOCIRecipeName,
    )
from lp.registry.interfaces.ocirecipename import (
    IOCIRecipeName,
    IOCIRecipeNameSet,
    )
from lp.registry.model.ocirecipename import (
    OCIRecipeName,
    OCIRecipeNameSet,
    )
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIRecipeName(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        recipe_name = self.factory.makeOCIRecipeName()
        self.assertTrue(recipe_name.name.startswith('oci-recipe-name'))

    def test_invalid_name(self):
        self.assertRaises(InvalidName, OCIRecipeName, name='invalid%20name')

    def test_implements_interface(self):
        recipe_name = OCIRecipeName('test-name')
        self.assertProvides(recipe_name, IOCIRecipeName)


class TestOCIRecipeNameSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_invalid_name(self):
        recipe_name_set = OCIRecipeNameSet()
        self.assertRaises(
            InvalidName, recipe_name_set.new, name='invalid%20name')

    def test_getByName_missing(self):
        self.factory.makeOCIRecipeName(name='first')
        self.factory.makeOCIRecipeName(name='second')

        recipe_name_set = OCIRecipeNameSet()
        self.assertRaises(
            NoSuchOCIRecipeName, recipe_name_set.getByName, 'invalid')

    def test_getitem(self):
        self.factory.makeOCIRecipeName(name='first')
        self.factory.makeOCIRecipeName(name='second')

        created = self.factory.makeOCIRecipeName()
        fetched = getUtility(IOCIRecipeNameSet)[created.name]
        self.assertEqual(fetched, created)

    def test_getByName(self):
        self.factory.makeOCIRecipeName(name='first')
        self.factory.makeOCIRecipeName(name='second')

        created = self.factory.makeOCIRecipeName()
        fetched = getUtility(IOCIRecipeNameSet).getByName(created.name)
        self.assertEqual(fetched, created)

    def test_implements_interface(self):
        recipe_name_set = OCIRecipeNameSet()
        self.assertProvides(recipe_name_set, IOCIRecipeNameSet)
