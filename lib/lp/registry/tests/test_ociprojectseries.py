# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIProjectSeries."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.component import getUtility

from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.registry.interfaces.series import SeriesStatus
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
        status = SeriesStatus.DEVELOPMENT
        project_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status)
        self.assertProvides(project_series, IOCIProjectSeries)

    def test_init(self):
        name = 'test-name'
        oci_project = self.factory.makeOCIProject()
        summary = 'test_summary'
        registrant = self.factory.makePerson()
        status = SeriesStatus.DEVELOPMENT
        project_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status)
        self.assertEqual(oci_project, project_series.ociproject)
        self.assertEqual(name, project_series.name)
        self.assertEqual(summary, project_series.summary)
        self.assertEqual(registrant, project_series.registrant)
        self.assertEqual(status, project_series.status)
