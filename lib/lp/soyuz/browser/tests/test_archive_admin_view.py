# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from fixtures import FakeLogger
from zope.security.interfaces import Unauthorized
from zope.testbrowser.browser import LinkNotFoundError

from lp.services.webapp import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.soyuz.browser.archive import ArchiveAdminView
from lp.soyuz.enums import ArchivePublishingMethod, ArchiveRepositoryFormat
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory, login, login_person
from lp.testing.layers import LaunchpadFunctionalLayer


class TestArchiveAdminView(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        """Create a ppa for the tests and login as an admin."""
        super().setUp()
        self.ppa = self.factory.makeArchive()
        # Login as an admin to ensure access to the view's context
        # object.
        login("admin@canonical.com")

    def initialize_admin_view(self, archive, fields):
        """Initialize the admin view to set the privacy.."""
        method = "POST"
        form = {
            "field.enabled": "on",
            "field.actions.save": "Save",
            "field.private": "on" if archive.private else "off",
            "field.publishing_method": archive.publishing_method.title,
            "field.repository_format": archive.repository_format.title,
        }
        form.update(fields)

        view = ArchiveAdminView(
            self.ppa, LaunchpadTestRequest(method=method, form=form)
        )
        view.initialize()
        return view

    def publish_to_ppa(self, ppa):
        """Helper method to publish a package in a PPA."""
        publisher = SoyuzTestPublisher()
        publisher.prepareBreezyAutotest()
        publisher.getPubSource(archive=ppa)

    def test_unauthorized(self):
        # A non-admin user cannot administer an archive.
        self.useFixture(FakeLogger())
        login_person(self.ppa.owner)
        ppa_url = canonical_url(self.ppa)
        browser = self.getUserBrowser(ppa_url, user=self.ppa.owner)
        self.assertRaises(
            LinkNotFoundError, browser.getLink, "Administer archive"
        )
        self.assertRaises(
            Unauthorized,
            self.getUserBrowser,
            ppa_url + "/+admin",
            user=self.ppa.owner,
        )

    def test_set_private_without_packages(self):
        # If a ppa does not have packages published, it is possible to
        # update the private attribute.
        view = self.initialize_admin_view(self.ppa, {"field.private": "on"})
        self.assertEqual(0, len(view.errors))
        self.assertTrue(view.context.private)

    def test_set_public_without_packages(self):
        # If a ppa does not have packages published, it is possible to
        # update the private attribute.
        self.ppa.private = True
        view = self.initialize_admin_view(self.ppa, {"field.private": "off"})
        self.assertEqual(0, len(view.errors))
        self.assertFalse(view.context.private)

    def test_set_private_with_packages_local(self):
        # A local PPA that does have packages cannot be made private.
        self.publish_to_ppa(self.ppa)
        view = self.initialize_admin_view(self.ppa, {"field.private": "on"})
        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            "This archive already has published sources. "
            "It is not possible to switch the privacy.",
            view.errors[0],
        )

    def test_set_public_with_packages_local(self):
        # A local PPA that does have (or had) packages published cannot be
        # made public.
        self.ppa.private = True
        self.publish_to_ppa(self.ppa)

        view = self.initialize_admin_view(self.ppa, {"field.private": "off"})
        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            "This archive already has published sources. "
            "It is not possible to switch the privacy.",
            view.errors[0],
        )

    def test_set_private_with_packages_artifactory(self):
        # An Artifactory PPA that does have packages can be made private.
        self.ppa.publishing_method = ArchivePublishingMethod.ARTIFACTORY
        self.publish_to_ppa(self.ppa)
        view = self.initialize_admin_view(self.ppa, {"field.private": "on"})
        self.assertEqual(0, len(view.errors))
        self.assertTrue(view.context.private)

    def test_set_public_with_packages_artifactory(self):
        # An Artifactory PPA that does have (or had) packages published
        # cannot be made public.
        self.ppa.publishing_method = ArchivePublishingMethod.ARTIFACTORY
        self.ppa.private = True
        self.publish_to_ppa(self.ppa)

        view = self.initialize_admin_view(self.ppa, {"field.private": "off"})
        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            "This archive already has published sources. "
            "It is not possible to switch the privacy.",
            view.errors[0],
        )

    def test_set_publishing_method_without_packages(self):
        # If a PPA does not have packages published, it is possible to
        # update the publishing_method attribute.
        self.assertEqual(
            ArchivePublishingMethod.LOCAL, self.ppa.publishing_method
        )
        view = self.initialize_admin_view(
            self.ppa, {"field.publishing_method": "ARTIFACTORY"}
        )
        self.assertEqual(0, len(view.errors))
        self.assertEqual(
            ArchivePublishingMethod.ARTIFACTORY, self.ppa.publishing_method
        )

    def test_set_publishing_method_with_packages(self):
        # If a PPA has packages published, it is impossible to update the
        # publishing_method attribute.
        self.publish_to_ppa(self.ppa)
        view = self.initialize_admin_view(
            self.ppa, {"field.publishing_method": "ARTIFACTORY"}
        )
        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            "This archive already has published packages. "
            "It is not possible to switch the publishing method.",
            view.errors[0],
        )

    def test_set_repository_format_without_packages(self):
        # If a PPA does not have packages published, it is possible to
        # update the repository_format attribute.
        self.assertEqual(
            ArchiveRepositoryFormat.DEBIAN, self.ppa.repository_format
        )
        view = self.initialize_admin_view(
            self.ppa, {"field.repository_format": "PYTHON"}
        )
        self.assertEqual(0, len(view.errors))
        self.assertEqual(
            ArchiveRepositoryFormat.PYTHON, self.ppa.repository_format
        )

    def test_set_repository_format_with_packages(self):
        # If a PPA has packages published, it is impossible to update the
        # repository_format attribute.
        self.publish_to_ppa(self.ppa)
        view = self.initialize_admin_view(
            self.ppa, {"field.repository_format": "PYTHON"}
        )
        self.assertEqual(1, len(view.errors))
        self.assertEqual(
            "This archive already has published packages. "
            "It is not possible to switch the repository format.",
            view.errors[0],
        )
