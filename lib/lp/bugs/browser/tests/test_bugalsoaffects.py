# Copyright 2011-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.security.proxy import removeSecurityProxy

from lp.services.features.testing import FeatureFixture
from lp.services.webapp import canonical_url
from lp.soyuz.enums import PackagePublishingStatus
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.pages import get_feedback_messages


class TestBugAlsoAffectsDistribution(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.distribution = self.factory.makeDistribution(displayname="Distro")
        self.distribution_name = self.distribution.name
        self.distribution_display_name = self.distribution.display_name
        removeSecurityProxy(self.distribution).official_malone = True

    def openBugPage(self, bug):
        browser = self.getUserBrowser()
        browser.open(canonical_url(bug))
        return browser

    def test_bug_alsoaffects_spn_exists(self):
        # If a source package is published to a main archive with the given
        # name, there is no error.
        bug = self.factory.makeBug()
        distroseries = self.factory.makeDistroSeries(
            distribution=self.distribution
        )
        dsp1 = self.factory.makeDSPCache(distroseries=distroseries)
        with person_logged_in(bug.owner):
            bug.addTask(bug.owner, dsp1)
        dsp2 = self.factory.makeDSPCache(distroseries=distroseries)
        spn = dsp2.sourcepackagename
        browser = self.openBugPage(bug)
        browser.getLink(url="+distrotask").click()
        browser.getControl("Distribution").value = [self.distribution_name]
        browser.getControl("Source Package Name").value = spn.name
        browser.getControl("Continue").click()
        self.assertEqual([], get_feedback_messages(browser.contents))

    def test_bug_alsoaffects_spn_exists_dsp_picker_feature_flag(self):
        # If the distribution source package for an spn is official,
        # there is no error.
        bug = self.factory.makeBug()
        distroseries = self.factory.makeDistroSeries(
            distribution=self.distribution
        )
        dsp1 = self.factory.makeDSPCache(distroseries=distroseries)
        with person_logged_in(bug.owner):
            bug.addTask(bug.owner, dsp1)
        dsp2 = self.factory.makeDSPCache(
            distroseries=distroseries, sourcepackagename="snarf"
        )
        with FeatureFixture({"disclosure.dsp_picker.enabled": "on"}):
            browser = self.openBugPage(bug)
            browser.getLink(url="+distrotask").click()
            browser.getControl("Distribution").value = [self.distribution_name]
            browser.getControl("Source Package Name").value = dsp2.name
            browser.getControl("Continue").click()
        self.assertEqual([], get_feedback_messages(browser.contents))

    def test_bug_alsoaffects_spn_not_exists_with_published_binaries(self):
        # When the distribution has published binaries, we search both
        # source and binary package names.
        bug = self.factory.makeBug()
        distroseries = self.factory.makeDistroSeries(
            distribution=self.distribution
        )
        das = self.factory.makeDistroArchSeries(distroseries=distroseries)
        self.factory.makeBinaryPackagePublishingHistory(
            distroarchseries=das, status=PackagePublishingStatus.PUBLISHED
        )
        self.assertTrue(self.distribution.has_published_binaries)
        browser = self.openBugPage(bug)
        browser.getLink(url="+distrotask").click()
        browser.getControl("Distribution").value = [self.distribution_name]
        browser.getControl("Source Package Name").value = "does-not-exist"
        browser.getControl("Continue").click()
        expected = [
            "There is 1 error.",
            'There is no package in %s named "does-not-exist".'
            % (self.distribution_display_name),
        ]
        self.assertEqual(expected, get_feedback_messages(browser.contents))

    def test_bug_alsoaffects_spn_not_exists_with_no_binaries(self):
        # When the distribution has no binary packages published, we can't.
        bug = self.factory.makeBug()
        browser = self.openBugPage(bug)
        browser.getLink(url="+distrotask").click()
        browser.getControl("Distribution").value = [self.distribution_name]
        browser.getControl("Source Package Name").value = "does-not-exist"
        browser.getControl("Continue").click()
        expected = [
            "There is 1 error.",
            'There is no package in %s named "does-not-exist". Launchpad '
            "does not track binary package names in %s."
            % (self.distribution_display_name, self.distribution_display_name),
        ]
        self.assertEqual(expected, get_feedback_messages(browser.contents))
