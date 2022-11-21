# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for feature flag change log views."""
from http.client import MOVED_PERMANENTLY

from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.services.webapp import canonical_url
from lp.services.webapp.interfaces import ILaunchpadRoot
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class TestRedirectView(TestCaseWithFactory):
    """Test the feature flag ChangeLog view."""

    layer = DatabaseFunctionalLayer

    def setUp(self, **kwargs):
        super().setUp(**kwargs)
        self.root = getUtility(ILaunchpadRoot)
        admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).admin]
        )
        self.admin_browser = self.getNonRedirectingBrowser(user=admin)

    def test_redirect_to_info(self):
        self.admin_browser.open(canonical_url(self.root) + "+feature-info")
        self.assertEqual(
            MOVED_PERMANENTLY,
            self.admin_browser.responseStatusCode,
        )
        self.assertEndsWith(
            self.admin_browser.headers["Location"], "/+feature-rules/info"
        )

    def test_redirect_changelog(self):
        self.admin_browser.open(
            canonical_url(self.root) + "+feature-changelog"
        )
        self.assertEqual(
            MOVED_PERMANENTLY, self.admin_browser.responseStatusCode
        )
        self.assertEndsWith(
            self.admin_browser.headers["Location"], "/+feature-rules/changelog"
        )
