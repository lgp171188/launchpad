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
        name = 'test-name'
        oci_project = self.factory.makeOCIProject()
        summary = 'test_summary'
        registrant = self.factory.makePerson()
        status = 2
        target_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status)
        self.assertProvides(target_series, IOCIProjectSeries)

    def test_init(self):
        name = 'test-name'
        oci_project = self.factory.makeOCIProject()
        summary = 'test_summary'
        registrant = self.factory.makePerson()
        status = 2
        target_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status)
        self.assertEqual(oci_project, target_series.ociproject)
        self.assertEqual(name, target_series.name)
        self.assertEqual(summary, target_series.summary)
        self.assertEqual(registrant, target_series.registrant)
        self.assertEqual(status, target_series.status)
