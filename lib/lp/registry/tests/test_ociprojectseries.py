# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCIProjectSeries."""

from testtools.matchers import ContainsDict, Equals, MatchesStructure
from testtools.testcase import ExpectedException
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.registry.errors import InvalidName
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.ociprojectseries import OCIProjectSeries
from lp.services.database.constants import UTC_NOW
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import TestCaseWithFactory, api_url, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import webservice_for_person


class TestOCIProjectSeries(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        name = "test-name"
        oci_project = self.factory.makeOCIProject()
        summary = "test_summary"
        registrant = self.factory.makePerson()
        status = SeriesStatus.DEVELOPMENT
        project_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status
        )
        self.assertProvides(project_series, IOCIProjectSeries)

    def test_init(self):
        name = "test-name"
        oci_project = self.factory.makeOCIProject()
        summary = "test_summary"
        registrant = self.factory.makePerson()
        status = SeriesStatus.DEVELOPMENT
        date_created = UTC_NOW
        project_series = OCIProjectSeries(
            oci_project, name, summary, registrant, status, date_created
        )
        self.assertThat(
            project_series,
            MatchesStructure.byEquality(
                oci_project=project_series.oci_project,
                name=project_series.name,
                summary=project_series.summary,
                registrant=project_series.registrant,
                status=project_series.status,
                date_created=project_series.date_created,
            ),
        )

    def test_invalid_name(self):
        name = "invalid%20name"
        oci_project = self.factory.makeOCIProject()
        summary = "test_summary"
        registrant = self.factory.makePerson()
        status = SeriesStatus.DEVELOPMENT
        with ExpectedException(InvalidName):
            OCIProjectSeries(oci_project, name, summary, registrant, status)

    def test_edit_permissions_invalid(self):
        name = "test-name"
        summary = "test_summary"
        registrant = self.factory.makePerson()
        another_person = self.factory.makePerson()

        driver = self.factory.makePerson()
        distribution = self.factory.makeDistribution(driver=driver)

        with person_logged_in(driver):
            project_series = self.factory.makeOCIProject(
                pillar=distribution
            ).newSeries(name, summary, registrant)

        with person_logged_in(another_person):
            with ExpectedException(Unauthorized):
                project_series.name = "not-allowed"

    def test_edit_permissions_valid(self):
        name = "test-name"
        summary = "test_summary"
        registrant = self.factory.makePerson()

        driver = self.factory.makePerson()
        distribution = self.factory.makeDistribution(driver=driver)

        with person_logged_in(driver):
            project_series = self.factory.makeOCIProject(
                pillar=distribution
            ).newSeries(name, summary, registrant)
            project_series.name = "allowed"

            self.assertEqual(project_series.name, "allowed")


class TestOCIProjectSeriesWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson(displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )

    def getAbsoluteURL(self, target):
        """Get the webservice absolute URL of the given object or relative
        path."""
        if not isinstance(target, str):
            target = api_url(target)
        return self.webservice.getAbsoluteUrl(target)

    def load_from_api(self, url):
        response = self.webservice.get(url)
        self.assertEqual(200, response.status, response.body)
        return response.jsonBody()

    def test_get_oci_project_series(self):
        with person_logged_in(self.person):
            project = removeSecurityProxy(
                self.factory.makeOCIProject(registrant=self.person)
            )
            series = self.factory.makeOCIProjectSeries(
                oci_project=project, registrant=self.person
            )
            url = api_url(series)
            expected_url = "{project}/+series/{name}".format(
                project=api_url(project), name=series.name
            )
            self.assertEqual(expected_url, url)
            series_matcher = ContainsDict(
                {
                    "date_created": Equals(series.date_created.isoformat()),
                    "name": Equals(series.name),
                    "oci_project_link": Equals(self.getAbsoluteURL(project)),
                    "registrant_link": Equals(
                        self.getAbsoluteURL(series.registrant)
                    ),
                    "status": Equals(series.status.title),
                    "summary": Equals(series.summary),
                }
            )

        ws_series = self.load_from_api(url)

        self.assertThat(ws_series, series_matcher)

    def test_get_non_existent_series(self):
        with person_logged_in(self.person):
            project = removeSecurityProxy(
                self.factory.makeOCIProject(registrant=self.person)
            )
            series = self.factory.makeOCIProjectSeries(
                oci_project=project, registrant=self.person
            )
            url = "{project}/+series/{name}trash".format(
                project=api_url(project), name=series.name
            )

        resp = self.webservice.get(url + "trash")
        self.assertEqual(404, resp.status, resp.body)
