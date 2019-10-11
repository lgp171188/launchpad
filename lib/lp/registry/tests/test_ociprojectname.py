# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIProjectName."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.testcase import ExpectedException
from zope.component import getUtility

from lp.registry.errors import (
    InvalidName,
    NoSuchOCIProjectName,
    )
from lp.registry.interfaces.ociprojectname import (
    IOCIProjectName,
    IOCIProjectNameSet,
    )
from lp.registry.model.ociprojectname import (
    OCIProjectName,
    OCIProjectNameSet,
    )
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIProjectName(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_create(self):
        recipe_name = self.factory.makeOCIProjectName()
        self.assertTrue(recipe_name.name.startswith('oci-recipe-name'))

    def test_invalid_name(self):
        self.assertRaises(InvalidName, OCIProjectName, name='invalid%20name')

    def test_implements_interface(self):
        recipe_name = OCIProjectName('test-name')
        self.assertProvides(recipe_name, IOCIProjectName)


class TestOCIProjectNameSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_invalid_name(self):
        recipe_name_set = OCIProjectNameSet()
        self.assertRaises(
            InvalidName, recipe_name_set.new, name='invalid%20name')

    def test_getByName_missing(self):
        self.factory.makeOCIProjectName(name='first')
        self.factory.makeOCIProjectName(name='second')

        recipe_name_set = OCIProjectNameSet()
        self.assertRaises(
            NoSuchOCIProjectName, recipe_name_set.getByName, 'invalid')

    def test_getitem(self):
        self.factory.makeOCIProjectName(name='first')
        self.factory.makeOCIProjectName(name='second')

        created = self.factory.makeOCIProjectName()
        fetched = getUtility(IOCIProjectNameSet)[created.name]
        self.assertEqual(fetched, created)

    def test_getByName(self):
        self.factory.makeOCIProjectName(name='first')
        self.factory.makeOCIProjectName(name='second')

        created = self.factory.makeOCIProjectName()
        fetched = getUtility(IOCIProjectNameSet).getByName(created.name)
        self.assertEqual(fetched, created)

    def test_implements_interface(self):
        recipe_name_set = OCIProjectNameSet()
        self.assertProvides(recipe_name_set, IOCIProjectNameSet)
