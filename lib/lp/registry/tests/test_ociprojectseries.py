# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIProjectSeries."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.matchers import MatchesStructure
from testtools.testcase import ExpectedException
from zope.security.interfaces import Unauthorized

from lp.registry.errors import InvalidName
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.ociprojectseries import OCIProjectSeries
from lp.services.database.constants import UTC_NOW
from lp.testing import (
    person_logged_in,
    TestCaseWithFactory,
    )
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
        date_created = UTC_NOW
        project_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status, date_created)
        self.assertThat(
            project_series, MatchesStructure.byEquality(
                ociproject=project_series.ociproject,
                name=project_series.name,
                summary=project_series.summary,
                registrant=project_series.registrant,
                status=project_series.status,
                date_created=project_series.date_created))

    def test_invalid_name(self):
        name = 'invalid%20name'
        oci_project = self.factory.makeOCIProject()
        summary = 'test_summary'
        registrant = self.factory.makePerson()
        status = SeriesStatus.DEVELOPMENT
        with ExpectedException(InvalidName):
            OCIProjectSeries(oci_project, name, summary, registrant, status)

    def test_edit_permissions_invalid(self):
        name = 'test-name'
        summary = 'test_summary'
        registrant = self.factory.makePerson()
        another_person = self.factory.makePerson()

        driver = self.factory.makePerson()
        distribution = self.factory.makeDistribution(driver=driver)

        with person_logged_in(driver):
            project_series = self.factory.makeOCIProject(
                pillar=distribution).newSeries(
                    name, summary, registrant)

        with person_logged_in(another_person):
            with ExpectedException(Unauthorized):
                project_series.name = 'not-allowed'

    def test_edit_permissions_valid(self):
        name = 'test-name'
        summary = 'test_summary'
        registrant = self.factory.makePerson()

        driver = self.factory.makePerson()
        distribution = self.factory.makeDistribution(driver=driver)

        with person_logged_in(driver):
            project_series = self.factory.makeOCIProject(
                pillar=distribution).newSeries(
                    name, summary, registrant)
            project_series.name = 'allowed'

            self.assertEqual(project_series.name, 'allowed')
