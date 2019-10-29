# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIProjectSeries."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.matchers import MatchesStructure
from testtools.testcase import ExpectedException

from lp.registry.errors import InvalidName
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.ociprojectseries import OCIProjectSeries
from lp.services.database.constants import UTC_NOW
from lp.testing import (
    anonymous_logged_in,
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
            project_series = OCIProjectSeries(
                oci_project, name, summary, registrant, status)

    def test_edit_permissions(self):
        name = 'test-name'
        oci_project = self.factory.makeOCIProject()
        summary = 'test_summary'
        registrant = self.factory.makePerson()
        status = SeriesStatus.DEVELOPMENT
        date_created = UTC_NOW
        project_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status, date_created)

        person = self.factory.makePerson()
        with anonymous_logged_in():
            setattr(project_series, 'name', 'not-allowed')
