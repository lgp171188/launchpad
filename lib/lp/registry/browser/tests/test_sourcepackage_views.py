# Copyright 2010-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for SourcePackage view code."""

from urllib.parse import parse_qsl, splitquery

from soupmatchers import HTMLContains, Tag
from testtools.matchers import Not
from testtools.testcase import ExpectedException
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.registry.browser.sourcepackage import (
    PackageUpstreamTracking,
    SourcePackageOverviewMenu,
    get_register_upstream_url,
)
from lp.registry.enums import DistributionDefaultTraversalPolicy
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries, IDistroSeriesSet
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import BrowserTestCase, TestCaseWithFactory, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import find_tag_by_id
from lp.testing.views import create_initialized_view


class TestSourcePackageViewHelpers(TestCaseWithFactory):
    """Tests for SourcePackage view helper functions."""

    layer = DatabaseFunctionalLayer

    def _makePublishedSourcePackage(self):
        test_publisher = SoyuzTestPublisher()
        test_data = test_publisher.makeSourcePackageSummaryData()
        source_package_name = test_data[
            "source_package"
        ].sourcepackagename.name
        distroseries_id = test_data["distroseries"].id
        test_publisher.updatePackageCache(test_data["distroseries"])

        # updatePackageCache reconnects the db, so the objects need to be
        # reloaded.
        distroseries = getUtility(IDistroSeriesSet).get(distroseries_id)
        return distroseries.getSourcePackage(source_package_name)

    def assertInQueryString(self, url, field, value):
        base, query = splitquery(url)
        params = parse_qsl(query)
        self.assertTrue((field, value) in params)

    def test_get_register_upstream_url_fields(self):
        distroseries = self.factory.makeDistroSeries(
            distribution=self.factory.makeDistribution(name="zoobuntu"),
            name="walrus",
        )
        source_package = self.factory.makeSourcePackage(
            distroseries=distroseries, sourcepackagename="python-super-package"
        )
        url = get_register_upstream_url(source_package)
        base, query = splitquery(url)
        self.assertEqual("/projects/+new", base)
        params = parse_qsl(query)
        expected_params = [
            (
                "_return_url",
                "http://launchpad.test/zoobuntu/walrus/"
                "+source/python-super-package",
            ),
            ("field.__visited_steps__", "projectaddstep1"),
            ("field.actions.continue", "Continue"),
            ("field.display_name", "Python Super Package"),
            ("field.distroseries", "zoobuntu/walrus"),
            ("field.name", "python-super-package"),
            ("field.source_package_name", "python-super-package"),
            ("field.title", "Python Super Package"),
        ]
        self.assertEqual(expected_params, params)

    def test_get_register_upstream_url_display_name(self):
        # The sourcepackagename 'python-super-package' is split on
        # the hyphens, and each word is capitalized.
        distroseries = self.factory.makeDistroSeries(
            distribution=self.factory.makeDistribution(name="zoobuntu"),
            name="walrus",
        )
        source_package = self.factory.makeSourcePackage(
            distroseries=distroseries, sourcepackagename="python-super-package"
        )
        url = get_register_upstream_url(source_package)
        self.assertInQueryString(
            url, "field.display_name", "Python Super Package"
        )

    def test_get_register_upstream_url_summary(self):
        source_package = self._makePublishedSourcePackage()
        url = get_register_upstream_url(source_package)
        self.assertInQueryString(
            url,
            "field.summary",
            "summary for flubber-bin\nsummary for flubber-lib",
        )

    def test_get_register_upstream_url_summary_duplicates(self):
        class Faker:
            # Fakes attributes easily.
            def __init__(self, **kw):
                self.__dict__.update(kw)

        @implementer(ISourcePackage)
        class FakeSourcePackage(Faker):
            # Interface necessary for canonical_url() call in
            # get_register_upstream_url().
            pass

        @implementer(IDistroSeries)
        class FakeDistroSeries(Faker):
            pass

        @implementer(IDistribution)
        class FakeDistribution(Faker):
            pass

        releases = Faker(
            sample_binary_packages=[
                Faker(summary="summary for foo"),
                Faker(summary="summary for bar"),
                Faker(summary="summary for baz"),
                Faker(summary="summary for baz"),
            ]
        )
        source_package = FakeSourcePackage(
            name="foo",
            sourcepackagename=Faker(name="foo"),
            distroseries=FakeDistroSeries(
                name="walrus",
                distribution=FakeDistribution(
                    name="zoobuntu",
                    default_traversal_policy=(
                        DistributionDefaultTraversalPolicy.SERIES
                    ),
                    redirect_default_traversal=False,
                ),
            ),
            releases=[releases],
            currentrelease=Faker(homepage=None),
        )
        url = get_register_upstream_url(source_package)
        self.assertInQueryString(
            url,
            "field.summary",
            "summary for bar\nsummary for baz\nsummary for foo",
        )

    def test_get_register_upstream_url_homepage(self):
        source_package = self._makePublishedSourcePackage()
        # SourcePackageReleases cannot be modified by users.
        removeSecurityProxy(source_package.currentrelease).homepage = (
            "http://eg.dom/bonkers"
        )
        url = get_register_upstream_url(source_package)
        self.assertInQueryString(
            url, "field.homepageurl", "http://eg.dom/bonkers"
        )


class TestSourcePackageView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def test_register_upstream_forbids_proprietary(self):
        # Cannot specify information_type if registering for sourcepackage.
        sourcepackage = self.factory.makeSourcePackage(publish=True)
        browser = self.getViewBrowser(sourcepackage)
        browser.getControl("Register the upstream project").click()
        browser.getControl("Link to Upstream Project").click()
        browser.getControl("Summary").value = "summary"
        browser.getControl("Continue").click()
        t = Tag("info_type", "input", attrs={"name": "field.information_type"})
        self.assertThat(browser.contents, Not(HTMLContains(t)))

    def test_link_upstream_handles_initial_proprietary(self):
        # Proprietary product is not listed as an option.
        owner = self.factory.makePerson()
        sourcepackage = self.factory.makeSourcePackage()
        product_name = sourcepackage.name
        product_displayname = self.factory.getUniqueString()
        self.factory.makeProduct(
            name=product_name,
            owner=owner,
            information_type=InformationType.PROPRIETARY,
            displayname=product_displayname,
        )
        browser = self.getViewBrowser(sourcepackage, user=owner)
        with ExpectedException(LookupError):
            browser.getControl(product_displayname)

    def test_link_upstream_handles_proprietary(self):
        # Proprietary products produce an 'invalid value' error.
        owner = self.factory.makePerson()
        product = self.factory.makeProduct(owner=owner)
        product_name = product.name
        product_displayname = product.displayname
        sourcepackage = self.factory.makeSourcePackage(
            sourcepackagename=product_name
        )
        with person_logged_in(None):
            browser = self.getViewBrowser(sourcepackage, user=owner)
            with person_logged_in(owner):
                product.information_type = InformationType.PROPRIETARY
            browser.getControl(product_displayname).click()
            browser.getControl("Link to Upstream Project").click()
        error = Tag(
            "error", "div", attrs={"class": "message"}, text="Invalid value"
        )
        self.assertThat(browser.contents, HTMLContains(error))
        self.assertNotIn(
            "The project %s was linked to this source package."
            % str(product_displayname),
            browser.contents,
        )


class TestSourcePackageUpstreamConnectionsView(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        productseries = self.factory.makeProductSeries(name="1.0")
        self.milestone = self.factory.makeMilestone(
            product=productseries.product, productseries=productseries
        )
        distroseries = self.factory.makeDistroSeries()
        self.source_package = self.factory.makeSourcePackage(
            distroseries=distroseries, sourcepackagename="fnord"
        )
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=self.source_package.sourcepackagename,
            distroseries=distroseries,
            version="1.5-0ubuntu1",
        )
        removeSecurityProxy(self.source_package).setPackaging(
            productseries, productseries.product.owner
        )

    def makeUpstreamRelease(self, version):
        with person_logged_in(self.milestone.productseries.product.owner):
            self.milestone.name = version
            self.factory.makeProductRelease(self.milestone)

    def assertId(self, view, id_):
        element = find_tag_by_id(view.render(), id_)
        self.assertTrue(element is not None)

    def test_current_release_tracking_none(self):
        view = create_initialized_view(
            self.source_package, name="+upstream-connections"
        )
        self.assertEqual(
            PackageUpstreamTracking.NONE, view.current_release_tracking
        )
        self.assertId(view, "no-upstream-version")

    def test_current_release_tracking_current(self):
        self.makeUpstreamRelease("1.5")
        view = create_initialized_view(
            self.source_package, name="+upstream-connections"
        )
        self.assertEqual(
            PackageUpstreamTracking.CURRENT, view.current_release_tracking
        )
        self.assertId(view, "current-upstream-version")

    def test_current_release_tracking_older(self):
        self.makeUpstreamRelease("1.4")
        view = create_initialized_view(
            self.source_package, name="+upstream-connections"
        )
        self.assertEqual(
            PackageUpstreamTracking.OLDER, view.current_release_tracking
        )
        self.assertId(view, "older-upstream-version")

    def test_current_release_tracking_newer(self):
        self.makeUpstreamRelease("1.6")
        view = create_initialized_view(
            self.source_package, name="+upstream-connections"
        )
        self.assertEqual(
            PackageUpstreamTracking.NEWER, view.current_release_tracking
        )
        self.assertId(view, "newer-upstream-version")


class TestSourcePackagePackagingLinks(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self, *args, **kwargs):
        super().setUp(*args, **kwargs)
        self.sourcepackage = self.factory.makeSourcePackage()
        self.maintainer = self.sourcepackage.distribution.owner
        self.product_owner = self.factory.makePerson()
        self.product = self.factory.makeProduct(owner=self.product_owner)
        self.productseries = self.factory.makeProductSeries(self.product)

    def makePackaging(self):
        self.factory.makePackagingLink(
            sourcepackagename=self.sourcepackage.sourcepackagename,
            distroseries=self.sourcepackage.distroseries,
            productseries=self.productseries,
        )

    def makeSourcePackageOverviewMenu(self, user):
        with person_logged_in(user):
            menu = SourcePackageOverviewMenu(self.sourcepackage)
        return menu

    def test_edit_packaging_link__enabled_without_packaging_maintainer(self):
        # If no packaging exists, the edit_packaging link is always
        # enabled.
        menu = self.makeSourcePackageOverviewMenu(self.maintainer)
        with person_logged_in(self.maintainer):
            self.assertTrue(menu.edit_packaging().enabled)

    def test_set_upstream_link__enabled_without_packaging_maintainer(self):
        # If no packaging exists, the set_upstream link is always
        # enabled.
        menu = self.makeSourcePackageOverviewMenu(self.maintainer)
        with person_logged_in(self.maintainer):
            self.assertTrue(menu.set_upstream().enabled)

    def test_remove_packaging_link__enabled_without_packaging_maintainer(self):
        # If no packaging exists, the remove_packaging link is always
        # disabled.
        menu = self.makeSourcePackageOverviewMenu(self.maintainer)
        with person_logged_in(self.maintainer):
            self.assertFalse(menu.remove_packaging().enabled)

    def test_edit_packaging_link__enabled_with_packaging_maintainer(self):
        # If a packaging exists, the edit_packaging link is enabled
        # for the package maintainer.
        self.makePackaging()
        menu = self.makeSourcePackageOverviewMenu(self.maintainer)
        with person_logged_in(self.maintainer):
            self.assertTrue(menu.edit_packaging().enabled)

    def test_set_upstream_link__enabled_with_packaging_maintainer(self):
        # If a packaging exists, the set_upstream link is enabled
        # for the package maintainer.
        self.makePackaging()
        menu = self.makeSourcePackageOverviewMenu(self.maintainer)
        with person_logged_in(self.maintainer):
            self.assertTrue(menu.set_upstream().enabled)

    def test_remove_packaging_link__enabled_with_packaging_maintainer(self):
        # If a packaging exists, the remove_packaging link is enabled
        # for the package maintainer.
        self.makePackaging()
        menu = self.makeSourcePackageOverviewMenu(self.maintainer)
        with person_logged_in(self.maintainer):
            self.assertTrue(menu.remove_packaging().enabled)

    def test_edit_packaging_link__disabled_for_product_owner(self):
        # If a packaging exists, the edit_packaging link is disabled
        # for the product owner.
        self.makePackaging()
        menu = self.makeSourcePackageOverviewMenu(self.product_owner)
        with person_logged_in(self.product_owner):
            self.assertFalse(menu.edit_packaging().enabled)

    def test_set_upstream_link__disabled_for_product_owner(self):
        # If a packaging exists, the set_upstream link is disabled
        # for the product owner.
        self.makePackaging()
        menu = self.makeSourcePackageOverviewMenu(self.product_owner)
        with person_logged_in(self.product_owner):
            self.assertFalse(menu.set_upstream().enabled)

    def test_remove_packaging_link__enabled_for_product_owner(self):
        # If a packaging exists, the remove_packaging link is enabled
        # for product owner.
        self.makePackaging()
        menu = self.makeSourcePackageOverviewMenu(self.product_owner)
        with person_logged_in(self.product_owner):
            self.assertTrue(menu.remove_packaging().enabled)

    def test_edit_packaging_link__enabled_with_packaging_arbitrary(self):
        # If a packaging exists, the edit_packaging link is not enabled
        # for arbitrary users.
        self.makePackaging()
        user = self.factory.makePerson()
        menu = self.makeSourcePackageOverviewMenu(user)
        with person_logged_in(user):
            self.assertFalse(menu.edit_packaging().enabled)

    def test_set_upstream_link__enabled_with_packaging_arbitrary(self):
        # If a packaging exists, the set_upstream link is not enabled
        # for arbitrary users.
        self.makePackaging()
        user = self.factory.makePerson()
        menu = self.makeSourcePackageOverviewMenu(user)
        with person_logged_in(user):
            self.assertFalse(menu.set_upstream().enabled)

    def test_remove_packaging_link__enabled_with_packaging_arbitrary(self):
        # If a packaging exists, the remove_packaging link is not enabled
        # for arbitrary users.
        self.makePackaging()
        user = self.factory.makePerson()
        menu = self.makeSourcePackageOverviewMenu(user)
        with person_logged_in(user):
            self.assertFalse(menu.remove_packaging().enabled)


class TestSourcePackageChangeUpstreamView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def test_error_on_proprietary_product(self):
        """Packaging cannot be created for PROPRIETARY products"""
        product_owner = self.factory.makePerson()
        product_name = "proprietary-product"
        self.factory.makeProduct(
            name=product_name,
            owner=product_owner,
            information_type=InformationType.PROPRIETARY,
        )
        sp = self.factory.makeSourcePackage()
        browser = self.getViewBrowser(
            sp, "+edit-packaging", user=self.factory.makeAdministrator()
        )
        browser.getControl("Project").value = product_name
        browser.getControl("Continue").click()
        self.assertIn(
            "Only Public projects can be packaged, not Proprietary.",
            browser.contents,
        )

    def test_error_on_proprietary_productseries(self):
        """Packaging cannot be created for PROPRIETARY productseries"""
        product_owner = self.factory.makePerson()
        product_name = "proprietary-product"
        product = self.factory.makeProduct(
            name=product_name, owner=product_owner
        )
        series = self.factory.makeProductSeries(product=product)
        series_displayname = series.displayname
        sp = self.factory.makeSourcePackage()
        browser = self.getViewBrowser(
            sp, "+edit-packaging", user=self.factory.makeAdministrator()
        )
        browser.getControl("Project").value = product_name
        browser.getControl("Continue").click()
        with person_logged_in(product_owner):
            product.information_type = InformationType.PROPRIETARY
        browser.getControl(series_displayname).selected = True
        browser.getControl("Change").click()
        self.assertIn(
            "Only Public projects can be packaged, not Proprietary.",
            browser.contents,
        )
