# -*- coding: utf-8 -*-
# Copyright 2011-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Distribution page."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from fixtures import FakeLogger
from lazr.restful.interfaces import IJSONRequestCache
import soupmatchers
from testtools.matchers import (
    MatchesAll,
    MatchesAny,
    Not,
    )
from zope.schema.vocabulary import SimpleVocabulary

from lp.app.browser.lazrjs import vocabulary_to_choice_edit_items
from lp.registry.enums import EXCLUSIVE_TEAM_POLICY
from lp.registry.interfaces.series import SeriesStatus
from lp.services.webapp import canonical_url
from lp.testing import (
    admin_logged_in,
    BrowserTestCase,
    login_celebrity,
    login_person,
    record_two_runs,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import (
    extract_text,
    find_tag_by_id,
    find_tags_by_class,
    )
from lp.testing.views import create_initialized_view


class TestDistributionPage(TestCaseWithFactory):
    """A TestCase for the distribution index page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionPage, self).setUp()
        self.distro = self.factory.makeDistribution(
            name="distro", displayname=u'distro')
        self.simple_user = self.factory.makePerson()
        # Use a FakeLogger fixture to prevent Memcached warnings to be
        # printed to stdout while browsing pages.
        self.useFixture(FakeLogger())

    def test_distributionpage_addseries_link(self):
        # An admin sees the +addseries link.
        self.admin = login_celebrity('admin')
        view = create_initialized_view(
            self.distro, '+index', principal=self.admin)
        series_matches = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to add a series', 'a',
                attrs={'href':
                    canonical_url(self.distro, view_name='+addseries')},
                text='Add series'),
            soupmatchers.Tag(
                'Active series and milestones widget', 'h2',
                text='Active series and milestones'),
            )
        self.assertThat(view.render(), series_matches)

    def test_distributionpage_addseries_link_noadmin(self):
        # A non-admin does not see the +addseries link nor the series
        # header (since there is no series yet).
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, '+index', principal=self.simple_user)
        add_series_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to add a series', 'a',
                attrs={'href':
                    canonical_url(self.distro, view_name='+addseries')},
                text='Add series'))
        series_header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Active series and milestones widget', 'h2',
                text='Active series and milestones'))
        self.assertThat(
            view.render(),
            Not(MatchesAny(add_series_match, series_header_match)))

    def test_distributionpage_series_list_noadmin(self):
        # A non-admin does see the series list when there is a series.
        self.factory.makeDistroSeries(distribution=self.distro,
            status=SeriesStatus.CURRENT)
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, '+index', principal=self.simple_user)
        add_series_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'link to add a series', 'a',
                attrs={'href':
                    canonical_url(self.distro, view_name='+addseries')},
                text='Add series'))
        series_header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                'Active series and milestones widget', 'h2',
                text='Active series and milestones'))
        self.assertThat(view.render(), series_header_match)
        self.assertThat(view.render(), Not(add_series_match))

    def test_mirrors_links(self):
        view = create_initialized_view(self.distro, "+index")
        cd_mirrors_link = soupmatchers.HTMLContains(soupmatchers.Tag(
            "CD mirrors link", "a", text="CD mirrors"))
        archive_mirrors_link = soupmatchers.HTMLContains(soupmatchers.Tag(
            "Archive mirrors link", "a", text="Archive mirrors"))
        self.assertThat(
            view(), Not(MatchesAny(cd_mirrors_link, archive_mirrors_link)))
        with admin_logged_in():
            self.distro.supports_mirrors = True
        self.assertThat(
            view(), MatchesAll(cd_mirrors_link, archive_mirrors_link))

    def test_ppas_link(self):
        view = create_initialized_view(self.distro, "+index")
        ppas_link = soupmatchers.HTMLContains(soupmatchers.Tag(
            "PPAs link", "a", text="Personal Package Archives"))
        self.assertThat(view(), Not(ppas_link))
        with admin_logged_in():
            self.distro.supports_ppas = True
        self.assertThat(view(), ppas_link)

    def test_builds_link(self):
        view = create_initialized_view(self.distro, "+index")
        builds_link = soupmatchers.HTMLContains(soupmatchers.Tag(
            "Builds link", "a", text="Builds"))
        self.assertThat(view(), Not(builds_link))
        with admin_logged_in():
            self.distro.official_packages = True
        self.assertThat(view(), builds_link)


class TestDistributionView(TestCaseWithFactory):
    """Tests the DistributionView."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestDistributionView, self).setUp()
        self.distro = self.factory.makeDistribution(
            name="distro", displayname=u'distro')

    def test_view_data_model(self):
        # The view's json request cache contains the expected data.
        view = create_initialized_view(self.distro, '+index')
        cache = IJSONRequestCache(view.request)
        policy_items = [(item.name, item) for item in EXCLUSIVE_TEAM_POLICY]
        team_membership_policy_data = vocabulary_to_choice_edit_items(
            SimpleVocabulary.fromItems(policy_items),
            value_fn=lambda item: item.name)
        self.assertContentEqual(
            team_membership_policy_data,
            cache.objects['team_membership_policy_data'])


class TestDistributionOCIProjectSearchView(BrowserTestCase):

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
            distribution, user=person, view_name='+search-oci-project')

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
            distro, user=person, view_name='+search-oci-project')

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
            distro, user=person, view_name='+search-oci-project')
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
                distro, user=viewer, view_name='+search-oci-project')
            browser.getControl(name="text").value = name_pattern
            browser.getControl("Search").click()
            return browser

        def do_login():
            login_person(person)

        recorder1, recorder2 = record_two_runs(
            getView, createOCIProject, 1, 10, login_method=do_login)
        self.assertEqual(recorder1.count, recorder2.count)
