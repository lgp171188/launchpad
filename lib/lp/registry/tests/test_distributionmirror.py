# Copyright 2009-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.distributionmirror import (
    IDistributionMirrorSet,
    MirrorContent,
    MirrorFreshness,
    MirrorSpeed,
    MirrorStatus,
    )
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.database.sqlbase import flush_database_updates
from lp.services.mail import stub
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.testing import (
    api_url,
    login,
    login_as,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.pages import webservice_for_person


class TestDistributionMirror(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        login('test@canonical.com')
        mirrorset = getUtility(IDistributionMirrorSet)
        self.cdimage_mirror = mirrorset.getByName('releases-mirror')
        self.archive_mirror = mirrorset.getByName('archive-mirror')
        self.hoary = getUtility(IDistributionSet)['ubuntu']['hoary']
        self.hoary_i386 = self.hoary['i386']

    def _create_source_mirror(self, distroseries, pocket, component,
                              freshness):
        source_mirror1 = self.archive_mirror.ensureMirrorDistroSeriesSource(
            distroseries, pocket, component)
        removeSecurityProxy(source_mirror1).freshness = freshness

    def _create_bin_mirror(self, archseries, pocket, component, freshness):
        bin_mirror = self.archive_mirror.ensureMirrorDistroArchSeries(
            archseries, pocket, component)
        removeSecurityProxy(bin_mirror).freshness = freshness

    def test_archive_mirror_without_content_should_be_disabled(self):
        self.assertTrue(self.archive_mirror.shouldDisable())

    def test_archive_mirror_with_any_content_should_not_be_disabled(self):
        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        flush_database_updates()
        self.assertFalse(self.archive_mirror.shouldDisable())

    def test_cdimage_mirror_not_missing_content_should_not_be_disabled(self):
        expected_file_count = 1
        self.cdimage_mirror.ensureMirrorCDImageSeries(
            self.hoary, flavour='ubuntu')
        self.assertFalse(
            self.cdimage_mirror.shouldDisable(expected_file_count))

    def test_cdimage_mirror_missing_content_should_be_disabled(self):
        expected_file_count = 1
        self.assertTrue(
            self.cdimage_mirror.shouldDisable(expected_file_count))

    def test_delete_all_mirror_cdimage_series(self):
        self.cdimage_mirror.ensureMirrorCDImageSeries(
            self.hoary, flavour='ubuntu')
        self.cdimage_mirror.ensureMirrorCDImageSeries(
            self.hoary, flavour='edubuntu')
        self.assertEqual(2, len(self.cdimage_mirror.cdimage_series))
        self.cdimage_mirror.deleteAllMirrorCDImageSeries()
        self.assertEqual(0, len(self.cdimage_mirror.cdimage_series))

    def test_archive_mirror_without_content_freshness(self):
        self.assertTrue(self.archive_mirror.source_series.is_empty())
        self.assertTrue(self.archive_mirror.arch_series.is_empty())
        self.assertEqual(
            self.archive_mirror.getOverallFreshness(),
            MirrorFreshness.UNKNOWN)

    def test_source_mirror_freshness_property(self):
        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorFreshness.TWODAYSBEHIND)
        flush_database_updates()
        self.assertEqual(
            removeSecurityProxy(self.archive_mirror).source_mirror_freshness,
            MirrorFreshness.TWODAYSBEHIND)

    def test_arch_mirror_freshness_property(self):
        self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorFreshness.ONEHOURBEHIND)
        flush_database_updates()
        self.assertEqual(
            removeSecurityProxy(self.archive_mirror).arch_mirror_freshness,
            MirrorFreshness.ONEHOURBEHIND)

    def test_archive_mirror_with_source_content_freshness(self):
        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorFreshness.TWODAYSBEHIND)
        flush_database_updates()
        self.assertEqual(
            self.archive_mirror.getOverallFreshness(),
            MirrorFreshness.TWODAYSBEHIND)

    def test_archive_mirror_with_binary_content_freshness(self):
        self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorFreshness.ONEHOURBEHIND)
        flush_database_updates()
        self.assertEqual(
            self.archive_mirror.getOverallFreshness(),
            MirrorFreshness.ONEHOURBEHIND)

    def test_archive_mirror_with_binary_and_source_content_freshness(self):
        self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        self._create_bin_mirror(
            self.hoary_i386, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorFreshness.ONEHOURBEHIND)

        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[0], MirrorFreshness.UP)
        self._create_source_mirror(
            self.hoary, PackagePublishingPocket.RELEASE,
            self.hoary.components[1], MirrorFreshness.TWODAYSBEHIND)
        flush_database_updates()

        self.assertEqual(
            self.archive_mirror.getOverallFreshness(),
            MirrorFreshness.TWODAYSBEHIND)

    def test_disabling_mirror_and_notifying_owner(self):
        login('karl@canonical.com')

        mirror = self.cdimage_mirror
        # If a mirror has been probed only once, the owner will always be
        # notified when it's disabled --it doesn't matter whether it was
        # previously enabled or disabled.
        self.factory.makeMirrorProbeRecord(mirror)
        self.assertTrue(mirror.enabled)
        log = 'Got a 404 on http://foo/baz'
        mirror.disable(notify_owner=True, log=log)
        # A notification was sent to the owner and other to the mirror admins.
        transaction.commit()
        self.assertEqual(len(stub.test_emails), 3)

        # In order to prevent data disclosure, emails have to be sent to one
        # person each, ie it is not allowed to have multiple recipients in an
        # email's `to` field.
        for email in stub.test_emails:
            number_of_to_addresses = len(email[1])
            self.assertLess(number_of_to_addresses, 2)

        stub.test_emails = []

        mirror.disable(notify_owner=True, log=log)
        # Again, a notification was sent to the owner and other to the mirror
        # admins.
        transaction.commit()
        self.assertEqual(len(stub.test_emails), 3)
        stub.test_emails = []

        # For mirrors that have been probed more than once, we'll only notify
        # the owner if the mirror was previously enabled.
        self.factory.makeMirrorProbeRecord(mirror)
        mirror.enabled = True
        mirror.disable(notify_owner=True, log=log)
        # A notification was sent to the owner and other to the mirror admins.
        transaction.commit()
        self.assertEqual(len(stub.test_emails), 3)
        stub.test_emails = []

        # We can always disable notifications to the owner by passing
        # notify_owner=False to mirror.disable().
        mirror.enabled = True
        mirror.disable(notify_owner=False, log=log)
        transaction.commit()
        self.assertEqual(len(stub.test_emails), 2)
        stub.test_emails = []

        mirror.enabled = False
        mirror.disable(notify_owner=True, log=log)
        # No notifications were sent this time
        transaction.commit()
        self.assertEqual(len(stub.test_emails), 0)
        stub.test_emails = []

    def test_no_email_sent_to_uncontactable_owner(self):
        # If the owner has no contact address, only the mirror admins are
        # notified.
        mirror = self.cdimage_mirror
        login_as(mirror.owner)
        # Deactivate the mirror owner to remove the contact address.
        mirror.owner.deactivate(comment="I hate mirror spam.")
        login_as(mirror.distribution.mirror_admin)
        # Clear out notifications about the new team member.
        transaction.commit()
        stub.test_emails = []

        # Disabling the mirror results in one notification for each of
        # the three mirror admins.
        self.factory.makeMirrorProbeRecord(mirror)
        mirror.disable(notify_owner=True, log="It broke.")
        transaction.commit()
        self.assertEqual(len(stub.test_emails), 3)

    def test_permissions_for_resubmit(self):
        self.assertRaises(
            Unauthorized, getattr,  self.archive_mirror, 'resubmitForReview')
        login_as(self.archive_mirror.owner)
        self.archive_mirror.status = MirrorStatus.BROKEN
        self.archive_mirror.resubmitForReview()
        self.assertEqual(
            MirrorStatus.PENDING_REVIEW, self.archive_mirror.status)


class TestDistributionMirrorWebservice(TestCaseWithFactory):
    """Test the IDistributionMirror API.

    Some tests already exist in distribution-mirror.rst.
    """
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson(
            displayname="Test Person")
        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel")

    def test_base_url(self):
        distroset = getUtility(IDistributionSet)
        with person_logged_in(self.person):
            ubuntu = distroset.get(1)
            owner = getUtility(IPersonSet).getByName('name16')
            speed = MirrorSpeed.S2M
            brazil = getUtility(ICountrySet)['BR']
            content = MirrorContent.ARCHIVE
            http_base_url = 'http://foo.bar.com/pub'
            whiteboard = "This mirror is based deep in the Amazon rainforest."
            new_mirror = ubuntu.newMirror(owner, speed, brazil, content,
                                          http_base_url=http_base_url,
                                          whiteboard=whiteboard)
            mirror_url = api_url(new_mirror)
            expected_url = new_mirror.base_url
        response = self.webservice.get(
            mirror_url)
        self.assertEqual(200, response.status, response.body)

        search_body = response.jsonBody()
        self.assertEqual(expected_url, search_body["base_url"])
