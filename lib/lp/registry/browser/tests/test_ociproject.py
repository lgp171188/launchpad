# -*- coding: utf-8 -*-
# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI project views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

from datetime import datetime

import pytz

from lp.registry.interfaces.ociproject import (
    OCI_PROJECT_ALLOW_CREATE,
    OCIProjectCreateFeatureDisabled,
    )
from lp.services.database.constants import UTC_NOW
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.services.webapp.escaping import structured
from lp.testing import (
    admin_logged_in,
    BrowserTestCase,
    login_person,
    person_logged_in,
    record_two_runs,
    test_tales,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import MatchesTagText
from lp.testing.pages import (
    extract_text,
    find_main_content,
    find_tag_by_id,
    find_tags_by_class,
    )
from lp.testing.publication import test_traverse
from lp.testing.views import create_initialized_view


class TestOCIProjectFormatterAPI(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_link(self):
        oci_project = self.factory.makeOCIProject()
        markup = structured(
            '<a href="/%s/+oci/%s">%s</a>',
            oci_project.pillar.name, oci_project.name,
            oci_project.display_name).escapedtext
        self.assertEqual(
            markup,
            test_tales('oci_project/fmt:link', oci_project=oci_project))


class TestOCIProjectNavigation(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_canonical_url(self):
        distribution = self.factory.makeDistribution(name="mydistro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="myociproject")
        self.assertEqual(
            "http://launchpad.test/mydistro/+oci/myociproject",
            canonical_url(oci_project))

    def test_traversal(self):
        oci_project = self.factory.makeOCIProject()
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+oci/%s" %
            (oci_project.pillar.name, oci_project.name))
        self.assertEqual(oci_project, obj)


class TestOCIProjectView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_index(self):
        distribution = self.factory.makeDistribution(displayname="My Distro")
        oci_project = self.factory.makeOCIProject(
            pillar=distribution, ociprojectname="oci-name")
        self.assertTextMatchesExpressionIgnoreWhitespace("""\
            OCI project oci-name for My Distro
            .*
            OCI project information
            Distribution: My Distro
            Name: oci-name
            """, self.getMainText(oci_project))


class TestOCIProjectEditView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_edit_oci_project(self):
        oci_project = self.factory.makeOCIProject()
        new_distribution = self.factory.makeDistribution(
            owner=oci_project.pillar.owner)

        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner)
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.distribution").value = [
            new_distribution.name]
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Update OCI project").click()

        content = find_main_content(browser.contents)
        self.assertEqual(
            "OCI project new-name for %s" % new_distribution.display_name,
            extract_text(content.h1))
        self.assertThat(
            "Distribution:\n%s\nEdit OCI project" % (
                new_distribution.display_name),
            MatchesTagText(content, "distribution"))
        self.assertThat(
            "Name:\nnew-name\nEdit OCI project",
            MatchesTagText(content, "name"))

    def test_edit_oci_project_sets_date_last_modified(self):
        # Editing an OCI project sets the date_last_modified property.
        date_created = datetime(2000, 1, 1, tzinfo=pytz.UTC)
        oci_project = self.factory.makeOCIProject(date_created=date_created)
        self.assertEqual(date_created, oci_project.date_last_modified)
        with person_logged_in(oci_project.pillar.owner):
            view = create_initialized_view(
                oci_project, name="+edit", principal=oci_project.pillar.owner)
            view.update_action.success({"name": "changed"})
        self.assertSqlAttributeEqualsDate(
            oci_project, "date_last_modified", UTC_NOW)

    def test_edit_oci_project_already_exists(self):
        oci_project = self.factory.makeOCIProject(ociprojectname="one")
        self.factory.makeOCIProject(
            pillar=oci_project.pillar, ociprojectname="two")
        pillar_display_name = oci_project.pillar.display_name
        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner)
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.name").value = "two"
        browser.getControl("Update OCI project").click()
        self.assertEqual(
            "There is already an OCI project in %s with this name." % (
                pillar_display_name),
            extract_text(find_tags_by_class(browser.contents, "message")[1]))

    def test_edit_oci_project_invalid_name(self):
        oci_project = self.factory.makeOCIProject()
        browser = self.getViewBrowser(
            oci_project, user=oci_project.pillar.owner)
        browser.getLink("Edit OCI project").click()
        browser.getControl(name="field.name").value = "invalid name"
        browser.getControl("Update OCI project").click()
        self.assertStartsWith(
            extract_text(find_tags_by_class(browser.contents, "message")[1]),
            "Invalid name 'invalid name'.")


class TestOCIProjectAddView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def test_create_oci_project(self):
        oci_project = self.factory.makeOCIProject()
        user = oci_project.pillar.owner
        new_distribution = self.factory.makeDistribution(
            owner=user, oci_project_admin=user)
        browser = self.getViewBrowser(
            new_distribution, user=user, view_name='+new-oci-project')
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Create OCI Project").click()

        content = find_main_content(browser.contents)
        self.assertEqual(
            "OCI project new-name for %s" % new_distribution.display_name,
            extract_text(content.h1))
        self.assertThat(
            "Distribution:\n%s\nEdit OCI project" % (
                new_distribution.display_name),
            MatchesTagText(content, "distribution"))
        self.assertThat(
             "Name:\nnew-name\nEdit OCI project",
             MatchesTagText(content, "name"))

    def test_create_oci_project_already_exists(self):
        person = self.factory.makePerson()
        distribution = self.factory.makeDistribution(oci_project_admin=person)
        self.factory.makeOCIProject(ociprojectname="new-name",
                                    pillar=distribution,
                                    registrant=person)

        browser = self.getViewBrowser(
            distribution, user=person, view_name='+new-oci-project')
        browser.getControl(name="field.name").value = "new-name"
        browser.getControl("Create OCI Project").click()

        self.assertEqual(
            "There is already an OCI project in %s with this name." % (
                distribution.display_name),
            extract_text(find_tags_by_class(browser.contents, "message")[1]))

    def test_create_oci_project_no_permission(self):
        self.useFixture(FeatureFixture({OCI_PROJECT_ALLOW_CREATE: ''}))
        another_person = self.factory.makePerson()
        new_distribution = self.factory.makeDistribution()
        self.assertRaises(
            OCIProjectCreateFeatureDisabled,
            self.getViewBrowser,
            new_distribution,
            user=another_person,
            view_name='+new-oci-project')


class TestOCIProjectSearchView(BrowserTestCase):

    layer = DatabaseFunctionalLayer

    def assertPaginationIsPresent(
            self, browser, results_in_page, total_result):
        """Checks that pagination is shown at the browser."""
        nav_index = find_tags_by_class(
            browser.contents, "batch-navigation-index")[0]
        nav_index_text = extract_text(nav_index).replace('\n', ' ')
        self.assertIn(
            "1 → %s of %s results" % (results_in_page, total_result),
            nav_index_text)

        nav_links = find_tags_by_class(
            browser.contents, "batch-navigation-links")[0]
        nav_links_text = extract_text(nav_links).replace('\n', ' ')
        self.assertIn("First • Previous • Next • Last", nav_links_text)

    def assertOCIProjectsArePresent(self, browser, oci_projects):
        table = find_tag_by_id(browser.contents, "projects_list")
        with admin_logged_in():
            for oci_project in oci_projects:
                url = canonical_url(oci_project, force_local_path=True)
                self.assertIn(url, str(table))
                self.assertIn(oci_project.name, str(table))

    def assertOCIProjectsAreNotPresent(self, browser, oci_projects):
        table = find_tag_by_id(browser.contents, "projects_list")
        with admin_logged_in():
            for oci_project in oci_projects:
                url = canonical_url(oci_project, force_local_path=True)
                self.assertNotIn(url, str(table))
                self.assertNotIn(oci_project.name, str(table))

    def test_search_no_oci_projects(self):
        person = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        browser = self.getViewBrowser(
            distribution, user=person, view_name='+oci-project-search')

        main_portlet = find_tags_by_class(browser.contents, "main-portlet")[0]
        self.assertIn(
            "There are no OCI projects registered for %s" % distribution.name,
            extract_text(main_portlet).replace("\n", " "))

    def test_oci_projects_no_search_keyword(self):
        person = self.factory.makePerson()
        distro = self.factory.makeDistribution(owner=person)

        # Creates 3 OCI Projects
        oci_projects = [
            self.factory.makeOCIProject(
                ociprojectname="test-project-%s" % i,
                registrant=person, pillar=distro) for i in range(3)]

        browser = self.getViewBrowser(
            distro, user=person, view_name='+oci-project-search')

        # Check top message.
        main_portlet = find_tags_by_class(browser.contents, "main-portlet")[0]
        self.assertIn(
            "There are 3 OCI projects registered for %s" % distro.name,
            extract_text(main_portlet).replace("\n", " "))

        self.assertOCIProjectsArePresent(browser, oci_projects)
        self.assertPaginationIsPresent(browser, 3, 3)

    def test_oci_projects_with_search_keyword(self):
        person = self.factory.makePerson()
        distro = self.factory.makeDistribution(owner=person)

        # And 2 OCI projects that will match the name
        oci_projects = [
            self.factory.makeOCIProject(
                ociprojectname="find-me-%s" % i,
                registrant=person, pillar=distro) for i in range(2)]

        # Creates 2 OCI Projects that will not match search
        other_oci_projects = [
            self.factory.makeOCIProject(
                ociprojectname="something-%s" % i,
                registrant=person, pillar=distro) for i in range(2)]

        browser = self.getViewBrowser(
            distro, user=person, view_name='+oci-project-search')
        browser.getControl(name="text").value = "find-me"
        browser.getControl("Search").click()

        # Check top message.
        main_portlet = find_tags_by_class(browser.contents, "main-portlet")[0]
        self.assertIn(
            'There are 2 OCI projects registered for %s matching "%s"' %
            (distro.name, "find-me"),
            extract_text(main_portlet).replace("\n", " "))

        self.assertOCIProjectsArePresent(browser, oci_projects)
        self.assertOCIProjectsAreNotPresent(browser, other_oci_projects)
        self.assertPaginationIsPresent(browser, 2, 2)

    def test_query_count_is_constant(self):
        batch_size = 3
        self.pushConfig("launchpad", default_batch_size=batch_size)

        person = self.factory.makePerson()
        distro = self.factory.makeDistribution(owner=person)
        name_pattern = "find-me-"

        def createOCIProject():
            self.factory.makeOCIProject(
                ociprojectname=self.factory.getUniqueString(name_pattern),
                pillar=distro)

        viewer = self.factory.makePerson()
        def getView():
            browser = self.getViewBrowser(
                distro, user=viewer, view_name='+oci-project-search')
            browser.getControl(name="text").value = name_pattern
            browser.getControl("Search").click()
            return browser

        def do_login():
            login_person(person)

        recorder1, recorder2 = record_two_runs(
            getView, createOCIProject, 1, 10, login_method=do_login)
        self.assertEqual(recorder1.count, recorder2.count)
