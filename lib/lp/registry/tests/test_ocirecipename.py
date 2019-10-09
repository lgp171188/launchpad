# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIRecipeName."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.testcase import ExpectedException

from lp.registry.errors import InvalidName
from lp.registry.interfaces.ocirecipename import IOCIRecipeName
from lp.registry.model.ocirecipename import OCIRecipeName
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIRecipeNameSet(TestCaseWithFactory):

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
