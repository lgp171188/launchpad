# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIProjectSeries."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility

from lp.registry.interfaces.ociprojectseries import (
    IOCIProjectSeries,
    IOCIProjectSeriesSet,
    )
from lp.registry.model.ociprojectseries import OCIProjectSeries
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIProjectSeries(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        oci_project = self.factory.makeOCIProject()
        target_series = OCIProjectSeries(oci_project, 'test-name')
        self.assertProvides(target_series, IOCIProjectSeries)

    def test_init(self):
        name = 'test-name'
        oci_project = self.factory.makeOCIProject()
        target_series = OCIProjectSeries(oci_project, name)
        self.assertEqual(oci_project, target_series.ociproject)
        self.assertEqual(name, target_series.name)


class TestOCIProjectSeriesSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target_series_set = getUtility(IOCIProjectSeriesSet)
        self.assertProvides(target_series_set, IOCIProjectSeriesSet)

    def test_new(self):
        name = 'test-name'
        oci_project = self.factory.makeOCIProject()
        target_series = getUtility(IOCIProjectSeriesSet).new(
            oci_project, name)
        self.assertEqual(oci_project, target_series.ociproject)
        self.assertEqual(name, target_series.name)
