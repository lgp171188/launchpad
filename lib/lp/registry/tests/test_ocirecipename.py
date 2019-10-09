# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIRecipeName."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.testcase import ExpectedException

from lp.registry.errors import (
    InvalidName,
    NoSuchOCIRecipeName,
    )
from lp.registry.interfaces.ocirecipename import IOCIRecipeName
from lp.registry.model.ocirecipename import (
    OCIRecipeName,
    OCIRecipeNameSet,
    )
from lp.services.database.interfaces import IStore
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIRecipeName(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        name = self.factory.makeOCIRecipeName()
        self.assertTrue(name.name.startswith('oci-base-name'))

    def test_invalid_name(self):
        with ExpectedException(
            InvalidName,
            ""):
            OCIRecipeNameSet().new(name='invalid%20name')

    def test_get_missing(self):
        with ExpectedException(
            NoSuchOCIRecipeName,
            "No such OCI recipe: 'invalid'"):
            OCIRecipeNameSet().getByName(u'invalid')

    def test_get(self):
        created = self.factory.makeOCIRecipeName()
        IStore(OCIRecipeName).flush()
        fetched = OCIRecipeNameSet()[created.name]
        self.assertEqual(fetched, created)

    def test_getByName(self):
        created = self.factory.makeOCIRecipeName()
        IStore(OCIRecipeName).flush()
        fetched = OCIRecipeNameSet().getByName(created.name)
        self.assertEqual(fetched, created)

    def test_implements_interface(self):
        recipe_name = OCIRecipeName('test-name')
        with admin_logged_in():
            self.assertProvides(recipe_name, IOCIRecipeName)
