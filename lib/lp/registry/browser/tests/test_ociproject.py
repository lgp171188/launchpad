# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test OCI project views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = []

from datetime import datetime

import pytz

from lp.services.database.constants import UTC_NOW
from lp.services.webapp import canonical_url
from lp.services.webapp.escaping import structured
from lp.testing import (
    BrowserTestCase,
    person_logged_in,
    test_tales,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import MatchesTagText
from lp.testing.pages import (
    extract_text,
    find_main_content,
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
