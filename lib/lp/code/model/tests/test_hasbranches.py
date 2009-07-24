# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for classes that implement IHasBranches."""

__metaclass__ = type

import unittest

from canonical.testing import DatabaseFunctionalLayer
from lp.code.interfaces.hasbranches import IHasBranches
from lp.testing import TestCaseWithFactory


class TestIHasBranches(TestCaseWithFactory):
    """Test that the correct objects implement the interface."""

    layer = DatabaseFunctionalLayer

    def test_product_implements_hasbranches(self):
        # Products should implement IHasBranches.
        product = self.factory.makeProduct()
        self.assertProvides(product, IHasBranches)

    def test_person_implements_hasbranches(self):
        # People should implement IHasBranches.
        person = self.factory.makePerson()
        self.assertProvides(person, IHasBranches)

    def test_project_implements_hasbranches(self):
        # Projects should implement IHasBranches.
        project = self.factory.makeProject()
        self.assertProvides(project, IHasBranches)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)

