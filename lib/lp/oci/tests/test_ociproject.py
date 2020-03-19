# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests OCI project."""

from __future__ import absolute_import, print_function, unicode_literals

import transaction
from lp.services.macaroons.testing import MatchesStructure
from lp.services.webapp.interaction import ANONYMOUS
from lp.testing import TestCaseWithFactory, person_logged_in, login, api_url, \
    launchpadlib_for, admin_logged_in, login_person
from lp.testing.layers import ZopelessDatabaseLayer, LaunchpadFunctionalLayer, \
    DatabaseFunctionalLayer, FunctionalLayer
from lp.testing.pages import webservice_for_person
from testtools.matchers import Equals
from zope.security.proxy import removeSecurityProxy


class TestOCIProjectWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIProjectWebservice, self).setUp()
        self.webservice = None
        self.person = self.factory.makePerson(displayname="Test Person")
        login_person(self.person)

    def load(self, obj, person=None):
        if person is None:
            person = self.person
        if self.webservice is None:
            self.webservice = launchpadlib_for("testing", person)
        with person_logged_in(person):
            url = api_url(obj)
        return self.webservice.load(url)

    def test_get_oci_project(self):
        project = removeSecurityProxy(self.factory.makeOCIProject(
            registrant=self.person))
        transaction.commit()

        ws_project = self.load(project)

        self.assertThat(ws_project, MatchesStructure(
            date_created=Equals(project.date_created),
            date_last_modified=Equals(project.date_last_modified),
            display_name=Equals(project.display_name),
            registrant=MatchesStructure.byEquality(name=project.registrant.name)
        ))
