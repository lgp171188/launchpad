# Copyright 2011-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for Distribution page."""

import re

import soupmatchers
from fixtures import FakeLogger
from lazr.restful.fields import Reference
from lazr.restful.interfaces import IFieldMarshaller, IJSONRequestCache
from testtools.matchers import MatchesAll, MatchesAny, Not
from zope.component import getMultiAdapter
from zope.schema.vocabulary import SimpleVocabulary
from zope.security.proxy import removeSecurityProxy

from lp.app.browser.lazrjs import vocabulary_to_choice_edit_items
from lp.app.enums import InformationType
from lp.registry.enums import (
    EXCLUSIVE_TEAM_POLICY,
    DistributionDefaultTraversalPolicy,
)
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.ociproject import OCI_PROJECT_ALLOW_CREATE
from lp.registry.interfaces.series import SeriesStatus
from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.services.webapp.publisher import RedirectionView
from lp.services.webapp.servers import WebServiceTestRequest
from lp.services.webapp.vhosts import allvhosts
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    login_celebrity,
    login_person,
)
from lp.testing.layers import DatabaseFunctionalLayer, ZopelessDatabaseLayer
from lp.testing.publication import test_traverse
from lp.testing.views import create_initialized_view


class TestDistributionNavigation(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def assertRedirects(self, url, expected_url):
        _, view, _ = test_traverse(url)
        self.assertIsInstance(view, RedirectionView)
        self.assertEqual(expected_url, removeSecurityProxy(view).target)

    def test_classic_series_url(self):
        distroseries = self.factory.makeDistroSeries()
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/%s"
            % (distroseries.distribution.name, distroseries.name)
        )
        self.assertEqual(distroseries, obj)

    def test_classic_series_url_with_alias(self):
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.development_series_alias = "devel"
        self.assertRedirects(
            "http://launchpad.test/%s/devel" % distroseries.distribution.name,
            "http://launchpad.test/%s/%s"
            % (distroseries.distribution.name, distroseries.name),
        )

    def test_classic_series_url_redirects(self):
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.redirect_default_traversal = True
        self.assertRedirects(
            "http://launchpad.test/%s/%s"
            % (distroseries.distribution.name, distroseries.name),
            "http://launchpad.test/%s/+series/%s"
            % (distroseries.distribution.name, distroseries.name),
        )

    def test_classic_series_url_with_alias_redirects(self):
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.redirect_default_traversal = True
        distroseries.distribution.development_series_alias = "devel"
        self.assertRedirects(
            "http://launchpad.test/%s/devel" % distroseries.distribution.name,
            "http://launchpad.test/%s/+series/%s"
            % (distroseries.distribution.name, distroseries.name),
        )

    def test_new_series_url(self):
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.redirect_default_traversal = True
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+series/%s"
            % (distroseries.distribution.name, distroseries.name)
        )
        self.assertEqual(distroseries, obj)

    def test_new_series_url_with_alias(self):
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.redirect_default_traversal = True
        distroseries.distribution.development_series_alias = "devel"
        self.assertRedirects(
            "http://launchpad.test/%s/+series/devel"
            % (distroseries.distribution.name),
            "http://launchpad.test/%s/+series/%s"
            % (distroseries.distribution.name, distroseries.name),
        )

    def test_new_series_url_redirects(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertRedirects(
            "http://launchpad.test/%s/+series/%s"
            % (distroseries.distribution.name, distroseries.name),
            "http://launchpad.test/%s/%s"
            % (distroseries.distribution.name, distroseries.name),
        )

    def test_new_series_url_with_alias_redirects(self):
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.development_series_alias = "devel"
        self.assertRedirects(
            "http://launchpad.test/%s/+series/devel"
            % (distroseries.distribution.name),
            "http://launchpad.test/%s/%s"
            % (distroseries.distribution.name, distroseries.name),
        )

    def assertDereferences(self, url, expected_obj, environ=None):
        field = Reference(schema=IDistroSeries)
        request = WebServiceTestRequest(environ=environ)
        request.setVirtualHostRoot(names=["devel"])
        marshaller = getMultiAdapter((field, request), IFieldMarshaller)
        self.assertIsInstance(marshaller.dereference_url(url), RedirectionView)
        self.assertEqual(expected_obj, marshaller.marshall_from_json_data(url))

    def test_classic_series_url_supports_object_lookup(self):
        # Classic series URLs (without +series) are compatible with
        # webservice object lookup, even if the distribution is configured
        # to redirect the default traversal.
        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.redirect_default_traversal = True
        distroseries_url = "/%s/%s" % (
            distroseries.distribution.name,
            distroseries.name,
        )
        self.assertDereferences(distroseries_url, distroseries)

        # Objects subordinate to the redirected series work too.
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries
        )
        distroarchseries_url = "/%s/%s/%s" % (
            distroarchseries.distroseries.distribution.name,
            distroarchseries.distroseries.name,
            distroarchseries.architecturetag,
        )
        self.assertDereferences(distroarchseries_url, distroarchseries)

    def test_classic_series_url_supports_object_lookup_https(self):
        # Classic series URLs (without +series) are compatible with
        # webservice object lookup, even if the distribution is configured
        # to redirect the default traversal and the vhost is configured to
        # use HTTPS.  "SERVER_URL": None exposes a bug in lazr.restful <
        # 0.22.2.
        self.addCleanup(allvhosts.reload)
        self.pushConfig("vhosts", use_https=True)
        allvhosts.reload()

        distroseries = self.factory.makeDistroSeries()
        distroseries.distribution.redirect_default_traversal = True
        distroseries_url = "/%s/%s" % (
            distroseries.distribution.name,
            distroseries.name,
        )
        self.assertDereferences(
            distroseries_url,
            distroseries,
            environ={"HTTPS": "on", "SERVER_URL": None},
        )

        # Objects subordinate to the redirected series work too.
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries
        )
        distroarchseries_url = "/%s/%s/%s" % (
            distroarchseries.distroseries.distribution.name,
            distroarchseries.distroseries.name,
            distroarchseries.architecturetag,
        )
        self.assertDereferences(
            distroarchseries_url,
            distroarchseries,
            environ={"HTTPS": "on", "SERVER_URL": None},
        )

    def test_new_series_url_supports_object_lookup(self):
        # New-style +series URLs are compatible with webservice object
        # lookup.
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = "/%s/+series/%s" % (
            distroseries.distribution.name,
            distroseries.name,
        )
        self.assertDereferences(distroseries_url, distroseries)

        # Objects subordinate to the redirected series work too.
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries
        )
        distroarchseries_url = "/%s/+series/%s/%s" % (
            distroarchseries.distroseries.distribution.name,
            distroarchseries.distroseries.name,
            distroarchseries.architecturetag,
        )
        self.assertDereferences(distroarchseries_url, distroarchseries)

    def test_new_series_url_supports_object_lookup_https(self):
        # New-style +series URLs are compatible with webservice object
        # lookup, even if the vhost is configured to use HTTPS.
        # "SERVER_URL": None exposes a bug in lazr.restful < 0.22.2.
        self.addCleanup(allvhosts.reload)
        self.pushConfig("vhosts", use_https=True)
        allvhosts.reload()

        distroseries = self.factory.makeDistroSeries()
        distroseries_url = "/%s/+series/%s" % (
            distroseries.distribution.name,
            distroseries.name,
        )
        self.assertDereferences(
            distroseries_url,
            distroseries,
            environ={
                "HTTPS": "on",
                "HTTP_HOST": "api.launchpad.test:443",
                "SERVER_URL": None,
            },
        )

        # Objects subordinate to the redirected series work too.
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries
        )
        distroarchseries_url = "/%s/+series/%s/%s" % (
            distroarchseries.distroseries.distribution.name,
            distroarchseries.distroseries.name,
            distroarchseries.architecturetag,
        )
        self.assertDereferences(
            distroarchseries_url,
            distroarchseries,
            environ={
                "HTTPS": "on",
                "HTTP_HOST": "api.launchpad.test:443",
                "SERVER_URL": None,
            },
        )

    def test_short_source_url(self):
        dsp = self.factory.makeDistributionSourcePackage()
        dsp.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.SOURCE_PACKAGE
        )
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/%s" % (dsp.distribution.name, dsp.name)
        )
        self.assertEqual(dsp, obj)

    def test_short_source_url_redirects(self):
        dsp = self.factory.makeDistributionSourcePackage()
        dsp.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.SOURCE_PACKAGE
        )
        dsp.distribution.redirect_default_traversal = True
        self.assertRedirects(
            "http://launchpad.test/%s/%s" % (dsp.distribution.name, dsp.name),
            "http://launchpad.test/%s/+source/%s"
            % (dsp.distribution.name, dsp.name),
        )

    def test_long_non_default_source_url(self):
        dsp = self.factory.makeDistributionSourcePackage()
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+source/%s"
            % (dsp.distribution.name, dsp.name)
        )
        self.assertEqual(dsp, obj)

    def test_long_default_source_url(self):
        dsp = self.factory.makeDistributionSourcePackage()
        dsp.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.SOURCE_PACKAGE
        )
        dsp.distribution.redirect_default_traversal = True
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+source/%s"
            % (dsp.distribution.name, dsp.name)
        )
        self.assertEqual(dsp, obj)

    def test_long_default_source_url_redirects(self):
        dsp = self.factory.makeDistributionSourcePackage()
        dsp.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.SOURCE_PACKAGE
        )
        self.assertRedirects(
            "http://launchpad.test/%s/+source/%s"
            % (dsp.distribution.name, dsp.name),
            "http://launchpad.test/%s/%s" % (dsp.distribution.name, dsp.name),
        )

    def test_short_oci_url(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution()
        )
        oci_project.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.OCI_PROJECT
        )
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/%s"
            % (oci_project.distribution.name, oci_project.name)
        )
        self.assertEqual(oci_project, obj)

    def test_short_oci_url_redirects(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution()
        )
        oci_project.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.OCI_PROJECT
        )
        oci_project.distribution.redirect_default_traversal = True
        self.assertRedirects(
            "http://launchpad.test/%s/%s"
            % (oci_project.distribution.name, oci_project.name),
            "http://launchpad.test/%s/+oci/%s"
            % (oci_project.distribution.name, oci_project.name),
        )

    def test_long_non_default_oci_url(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution()
        )
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+oci/%s"
            % (oci_project.distribution.name, oci_project.name)
        )
        self.assertEqual(oci_project, obj)

    def test_long_default_oci_url(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution()
        )
        oci_project.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.OCI_PROJECT
        )
        oci_project.distribution.redirect_default_traversal = True
        obj, _, _ = test_traverse(
            "http://launchpad.test/%s/+oci/%s"
            % (oci_project.distribution.name, oci_project.name)
        )
        self.assertEqual(oci_project, obj)

    def test_long_default_oci_url_redirects(self):
        oci_project = self.factory.makeOCIProject(
            pillar=self.factory.makeDistribution()
        )
        oci_project.distribution.default_traversal_policy = (
            DistributionDefaultTraversalPolicy.OCI_PROJECT
        )
        self.assertRedirects(
            "http://launchpad.test/%s/+oci/%s"
            % (oci_project.distribution.name, oci_project.name),
            "http://launchpad.test/%s/%s"
            % (oci_project.distribution.name, oci_project.name),
        )


class TestDistributionPage(TestCaseWithFactory):
    """A TestCase for the distribution index page."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.distro = self.factory.makeDistribution(
            name="distro", displayname="distro"
        )
        self.simple_user = self.factory.makePerson()
        # Use a FakeLogger fixture to prevent Memcached warnings to be
        # printed to stdout while browsing pages.
        self.useFixture(FeatureFixture({OCI_PROJECT_ALLOW_CREATE: True}))
        self.useFixture(FakeLogger())

    def test_distributionpage_addseries_link(self):
        # An admin sees the +addseries link.
        self.admin = login_celebrity("admin")
        view = create_initialized_view(
            self.distro, "+index", principal=self.admin
        )
        series_matches = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "link to add a series",
                "a",
                attrs={
                    "href": canonical_url(self.distro, view_name="+addseries")
                },
                text="Add series",
            ),
            soupmatchers.Tag(
                "Active series and milestones widget",
                "h2",
                text="Active series and milestones",
            ),
        )
        self.assertThat(view.render(), series_matches)

    def test_distributionpage_search_oci_project_link_is_hidden(self):
        # User can't see the +search-oci-project link if there are no
        # available OCI projects.
        admin = login_celebrity("admin")
        distro_url = canonical_url(self.distro)
        browser = self.getUserBrowser(distro_url, user=admin)
        matchers = Not(
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "link to search oci project",
                    "a",
                    attrs={"href": "%s/+search-oci-project" % distro_url},
                    text="Search for OCI project",
                )
            )
        )
        self.assertThat(browser.contents, matchers)

    def test_distributionpage_search_oci_project_link_is_shown(self):
        # User can see the +search-oci-project link if there are OCI projects.
        self.factory.makeOCIProject(pillar=self.distro)
        admin = login_celebrity("admin")
        distro_url = canonical_url(self.distro)
        browser = self.getUserBrowser(distro_url, user=admin)
        matchers = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "link to search oci project",
                "a",
                attrs={"href": "%s/+search-oci-project" % distro_url},
                text="Search for OCI project",
            )
        )
        self.assertThat(browser.contents, matchers)

    def test_distributionpage_oci_links_are_hidden_if_disabled_flag(self):
        # User can't see OCI project create/search links if the feature flag
        # is disabled.
        self.useFixture(FeatureFixture({OCI_PROJECT_ALLOW_CREATE: ""}))
        user = self.factory.makePerson()
        distro_url = canonical_url(self.distro)
        browser = self.getUserBrowser(distro_url, user=user)

        self.assertThat(
            browser.contents,
            Not(
                soupmatchers.HTMLContains(
                    soupmatchers.Tag(
                        "link to search oci project",
                        "a",
                        attrs={"href": "%s/+search-oci-project" % distro_url},
                        text="Search for OCI project",
                    )
                )
            ),
        )

        self.assertThat(
            browser.contents,
            Not(
                soupmatchers.HTMLContains(
                    soupmatchers.Tag(
                        "link to create oci project",
                        "a",
                        attrs={"href": "%s/+new-oci-project" % distro_url},
                        text="Create an OCI project",
                    )
                )
            ),
        )

    def test_distributionpage_oci_links_for_user_no_permission(self):
        # User can't see OCI project create links if the the user
        # doesn't have permission to create OCI projects.
        self.factory.makeOCIProject(pillar=self.distro)
        user = self.factory.makePerson()
        distro_url = canonical_url(self.distro)
        browser = self.getUserBrowser(distro_url, user=user)

        # User can see search link
        self.assertThat(
            browser.contents,
            soupmatchers.HTMLContains(
                soupmatchers.Tag(
                    "link to search oci project",
                    "a",
                    attrs={"href": "%s/+search-oci-project" % distro_url},
                    text="Search for OCI project",
                )
            ),
        )

        # User cannot see "new-oci-project" link.
        self.assertThat(
            browser.contents,
            Not(
                soupmatchers.HTMLContains(
                    soupmatchers.Tag(
                        "link to create oci project",
                        "a",
                        attrs={"href": "%s/+new-oci-project" % distro_url},
                        text="Create an OCI project",
                    )
                )
            ),
        )

    def test_distributionpage_addseries_link_noadmin(self):
        # A non-admin does not see the +addseries link nor the series
        # header (since there is no series yet).
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, "+index", principal=self.simple_user
        )
        add_series_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "link to add a series",
                "a",
                attrs={
                    "href": canonical_url(self.distro, view_name="+addseries")
                },
                text="Add series",
            )
        )
        series_header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "Active series and milestones widget",
                "h2",
                text="Active series and milestones",
            )
        )
        self.assertThat(
            view.render(),
            Not(MatchesAny(add_series_match, series_header_match)),
        )

    def test_distributionpage_series_list_noadmin(self):
        # A non-admin does see the series list when there is a series.
        self.factory.makeDistroSeries(
            distribution=self.distro, status=SeriesStatus.CURRENT
        )
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, "+index", principal=self.simple_user
        )
        add_series_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "link to add a series",
                "a",
                attrs={
                    "href": canonical_url(self.distro, view_name="+addseries")
                },
                text="Add series",
            )
        )
        series_header_match = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "Active series and milestones widget",
                "h2",
                text="Active series and milestones",
            )
        )
        self.assertThat(view.render(), series_header_match)
        self.assertThat(view.render(), Not(add_series_match))

    def test_mirrors_links(self):
        view = create_initialized_view(self.distro, "+index")
        cd_mirrors_link = soupmatchers.HTMLContains(
            soupmatchers.Tag("CD mirrors link", "a", text="CD mirrors")
        )
        archive_mirrors_link = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "Archive mirrors link", "a", text="Archive mirrors"
            )
        )
        self.assertThat(
            view(), Not(MatchesAny(cd_mirrors_link, archive_mirrors_link))
        )
        with admin_logged_in():
            self.distro.supports_mirrors = True
        self.assertThat(
            view(), MatchesAll(cd_mirrors_link, archive_mirrors_link)
        )

    def test_ppas_link(self):
        view = create_initialized_view(self.distro, "+index")
        ppas_link = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "PPAs link", "a", text="Personal Package Archives"
            )
        )
        self.assertThat(view(), Not(ppas_link))
        with admin_logged_in():
            self.distro.supports_ppas = True
        self.assertThat(view(), ppas_link)

    def test_builds_link(self):
        view = create_initialized_view(self.distro, "+index")
        builds_link = soupmatchers.HTMLContains(
            soupmatchers.Tag("Builds link", "a", text="Builds")
        )
        self.assertThat(view(), Not(builds_link))
        with admin_logged_in():
            self.distro.official_packages = True
        self.assertThat(view(), builds_link)

    def test_requires_subscription_owner(self):
        # If the distribution is proprietary and doesn't have much time left
        # on its commercial subscription, the owner sees a portlet directing
        # them to purchase a subscription.
        owner = self.distro.owner
        with admin_logged_in():
            self.distro.information_type = InformationType.PROPRIETARY
        login_person(owner)
        view = create_initialized_view(self.distro, "+index", principal=owner)
        warning = soupmatchers.HTMLContains(
            soupmatchers.Within(
                soupmatchers.Tag(
                    "Portlet container",
                    "div",
                    attrs={"id": "portlet-requires-subscription"},
                ),
                soupmatchers.Tag(
                    "Heading",
                    "h2",
                    text=re.compile(
                        r"Purchasing a commercial subscription is required"
                    ),
                ),
            )
        )
        self.assertThat(view(), warning)

    def test_requires_subscription_non_owner(self):
        # If the distribution is proprietary and doesn't have much time left
        # on its commercial subscription, non-owners do not see a portlet
        # directing them to purchase a subscription.
        with admin_logged_in():
            self.distro.information_type = InformationType.PROPRIETARY
            policy = self.factory.makeAccessPolicy(
                pillar=self.distro, check_existing=True
            )
            self.factory.makeAccessPolicyGrant(
                policy=policy, grantee=self.simple_user
            )
        login_person(self.simple_user)
        view = create_initialized_view(
            self.distro, "+index", principal=self.simple_user
        )
        warning = soupmatchers.HTMLContains(
            soupmatchers.Tag(
                "Portlet container",
                "div",
                attrs={"id": "portlet-requires-subscription"},
            )
        )
        self.assertThat(view(), Not(warning))


class TestDistributionView(TestCaseWithFactory):
    """Tests the DistributionView."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.distro = self.factory.makeDistribution(
            name="distro", displayname="distro"
        )

    def test_view_data_model(self):
        # The view's json request cache contains the expected data.
        view = create_initialized_view(self.distro, "+index")
        cache = IJSONRequestCache(view.request)
        policy_items = [(item.name, item) for item in EXCLUSIVE_TEAM_POLICY]
        team_membership_policy_data = vocabulary_to_choice_edit_items(
            SimpleVocabulary.fromItems(policy_items),
            value_fn=lambda item: item.name,
        )
        self.assertContentEqual(
            team_membership_policy_data,
            cache.objects["team_membership_policy_data"],
        )
