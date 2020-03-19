# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests OCI project."""

from __future__ import absolute_import, print_function, unicode_literals

from storm.store import Store
from testtools.matchers import (
    ContainsDict,
    Equals,
    MatchesListwise,
    )
import transaction
from zope.security.proxy import removeSecurityProxy

from lp.services.macaroons.testing import MatchesStructure
from lp.services.webhooks.testing import StartsWith
from lp.testing import (
    api_url,
    launchpadlib_for,
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIProjectWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIProjectWebservice, self).setUp()
        self.webservice = None
        self.person = self.factory.makePerson(displayname="Test Person")
        login_person(self.person)

    def load_from_api(self, obj, person=None):
        if person is None:
            person = self.person
        if self.webservice is None:
            self.webservice = launchpadlib_for("testing", person)
        with person_logged_in(person):
            url = api_url(obj)
        return self.webservice.load(url)

    def test_api_get_oci_project(self):
        project = removeSecurityProxy(self.factory.makeOCIProject(
            registrant=self.person))
        series = removeSecurityProxy(self.factory.makeOCIProjectSeries(
            oci_project=project, registrant=self.person))
        transaction.commit()

        ws_project = self.load_from_api(project)
        ws_series = ws_project.series.entries

        self.assertThat(ws_project, MatchesStructure(
            date_created=Equals(project.date_created),
            date_last_modified=Equals(project.date_last_modified),
            display_name=Equals(project.display_name),
            registrant=MatchesStructure.byEquality(
                name=project.registrant.name)
            ))

        self.assertEqual(1, len(ws_series))
        self.assertThat(ws_series, MatchesListwise([
            ContainsDict(dict(
                name=Equals(series.name),
                summary=Equals(series.summary),
                date_created=Equals(series.date_created.isoformat()),
                registrant_link=StartsWith("http"),
                oci_project_link=StartsWith("http")
            ))
        ]))

    def test_api_save_oci_project(self):
        project = removeSecurityProxy(self.factory.makeOCIProject(
            registrant=self.person))

        ws_project = self.load_from_api(project, self.person)
        new_description = 'Some other description'
        ws_project.description = new_description
        ws_project.lp_save()

        ws_project = self.load_from_api(project)
        self.assertEqual(new_description, ws_project.description)
