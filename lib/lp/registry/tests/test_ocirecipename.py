# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIRecipeName."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

import transaction
from testtools.testcase import ExpectedException

from lp.registry.errors import (
    InvalidName,
    NoSuchRecipeName,
    )
from lp.registry.model.ocirecipename import (
    OCIRecipeName,
    OCIRecipeNameSet,
    )
from lp.services.database.interfaces import IStore
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class OCIRecipeNameTest(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        name = self.factory.makeOCIRecipeName()
        self.assertTrue(name.name.startswith('oci-base-name'))

    def test_invalid_name(self):
        with ExpectedException(
            InvalidName,
            'invalid%20name is not a valid name for an OCI recipe.'):
            OCIRecipeNameSet().new('invalid%20name')

    def test_get_missing(self):
        with ExpectedException(
            NoSuchRecipeName,
            "No such OCI recipe: 'invalid'"):
            OCIRecipeNameSet().getByName(u'invalid')

    def test_get(self):
        created = self.factory.makeOCIRecipeName()
        IStore(OCIRecipeName).flush()
        fetched = OCIRecipeNameSet().getByName(created.name)
        self.assertEqual(fetched, created)

    def test_get_all(self):
        for i in range(5):
            self.factory.makeOCIRecipeName()
        all_recipes = OCIRecipeNameSet().getAll()
        self.assertEqual(all_recipes.count(), 5)
