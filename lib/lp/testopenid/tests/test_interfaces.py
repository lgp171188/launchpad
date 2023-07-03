# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

"""Test Interface implementations."""

from zope.component import getUtility

from lp.testing import TestCaseWithFactory, verifyObject
from lp.testing.layers import FunctionalLayer
from lp.testopenid.interfaces.server import ITestOpenIDApplication


class TestInterfaces(TestCaseWithFactory):
    layer = FunctionalLayer

    def test_ITestOpenIDApplication_implementation(self):
        test_open_app = getUtility(ITestOpenIDApplication)
        self.assertTrue(verifyObject(ITestOpenIDApplication, test_open_app))
