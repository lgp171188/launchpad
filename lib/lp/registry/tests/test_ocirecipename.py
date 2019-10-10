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
        with ExpectedException(
                InvalidName,
                ""):
            OCIRecipeName(name='invalid%20name')

    def test_implements_interface(self):
        recipe_name = OCIRecipeName('test-name')
        with admin_logged_in():
            self.assertProvides(recipe_name, IOCIRecipeName)


class TestOCIRecipeNameSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_invalid_name(self):
        with ExpectedException(
                InvalidName,
                ""):
            getUtility(IOCIRecipeNameSet).new(name='invalid%20name')

    def test_getByName_missing(self):
        with ExpectedException(
                NoSuchOCIRecipeName,
                "No such OCI recipe: 'invalid'"):
            getUtility(IOCIRecipeNameSet).getByName(u'invalid')

    def test_getitem(self):
        created = self.factory.makeOCIRecipeName()
        fetched = getUtility(IOCIRecipeNameSet)[created.name]
        self.assertEqual(fetched, created)

    def test_getByName(self):
        created = self.factory.makeOCIRecipeName()
        fetched = getUtility(IOCIRecipeNameSet).getByName(created.name)
        self.assertEqual(fetched, created)

    def test_implements_interface(self):
        recipe_name = OCIRecipeNameSet()
        with admin_logged_in():
            self.assertProvides(recipe_name, IOCIRecipeNameSet)
