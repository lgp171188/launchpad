# Copyright 2010-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

import hashlib

from lazr.restfulclient.errors import (
    BadRequest,
    Unauthorized,
    )
from testtools.matchers import (
    EndsWith,
    Equals,
    MatchesDict,
    MatchesStructure,
    )
from zope.security.management import endInteraction

from lp.buildmaster.enums import BuildBaseImageType
from lp.registry.enums import PersonVisibility
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.features.testing import FeatureFixture
from lp.soyuz.interfaces.livefs import LIVEFS_FEATURE_FLAG
from lp.testing import (
    api_url,
    launchpadlib_for,
    login_as,
    person_logged_in,
    TestCaseWithFactory,
    ws_object,
    )
from lp.testing.layers import LaunchpadFunctionalLayer


class TestDistroArchSeriesWebservice(TestCaseWithFactory):
    """Unit Tests for 'DistroArchSeries' Webservice.
    """
    layer = LaunchpadFunctionalLayer

    def _makeDistroArchSeries(self):
        """Create a `DistroSeries` object, that is prefilled with 1
        architecture for testing purposes.

        :return: a `DistroSeries` object.
        """
        distro = self.factory.makeDistribution()
        distroseries = self.factory.makeDistroSeries(
            distribution=distro)
        self.factory.makeDistroArchSeries(
            distroseries=distroseries)

        return distroseries

    def test_distroseries_architectures_anonymous(self):
        """Test anonymous DistroArchSeries API Access."""
        distroseries = self._makeDistroArchSeries()
        endInteraction()
        launchpad = launchpadlib_for('test', person=None, version='devel')
        ws_distroseries = ws_object(launchpad, distroseries)
        # Note, we test the length of architectures.entries, not
        # architectures due to the removal of the entries by lazr
        self.assertEqual(1, len(ws_distroseries.architectures.entries))

    def test_distroseries_architectures_authenticated(self):
        """Test authenticated DistroArchSeries API Access."""
        distroseries = self._makeDistroArchSeries()
        #Create a user to use the authenticated API
        accessor = self.factory.makePerson()
        launchpad = launchpadlib_for('test', accessor.name, version='devel')
        ws_distroseries = ws_object(launchpad, distroseries)
        #See note above regarding testing of length of .entries
        self.assertEqual(1, len(ws_distroseries.architectures.entries))

    def test_getBuildRecords(self):
        das = self.factory.makeDistroArchSeries()
        build = self.factory.makeBinaryPackageBuild(distroarchseries=das)
        build_title = build.title
        user = self.factory.makePerson()
        launchpad = launchpadlib_for("testing", user)
        ws_das = ws_object(launchpad, das)
        self.assertEqual(
            [build_title], [entry.title for entry in ws_das.getBuildRecords()])

    def test_setChroot_removeChroot_random_user(self):
        # Random users are not allowed to set or remove chroots.
        das = self.factory.makeDistroArchSeries()
        user = self.factory.makePerson()
        webservice = launchpadlib_for("testing", user, version='devel')
        ws_das = ws_object(webservice, das)
        self.assertRaises(
            Unauthorized, ws_das.setChroot, data=b'xyz', sha1sum='0')
        self.assertRaises(Unauthorized, ws_das.removeChroot)

    def test_setChroot_wrong_sha1sum(self):
        # If the sha1sum calculated is different, the chroot is not set.
        das = self.factory.makeDistroArchSeries()
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        e = self.assertRaises(
            BadRequest, ws_das.setChroot, data=b'zyx', sha1sum='x')
        self.assertEqual(b"Chroot upload checksums do not match", e.content)

    def test_setChroot_missing_trailing_cr(self):
        # Due to http://bugs.python.org/issue1349106 launchpadlib sends
        # MIME with \n line endings, which is illegal. lazr.restful
        # parses each ending as \r\n, resulting in a binary that ends
        # with \r getting the last byte chopped off. To cope with this
        # on the server side we try to append \r if the SHA-1 doesn't
        # match.
        das = self.factory.makeDistroArchSeries()
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        sha1 = '95e0c0e09be59e04eb0e312e5daa11a2a830e526'
        ws_das.setChroot(
            data=b'foo\r', sha1sum='95e0c0e09be59e04eb0e312e5daa11a2a830e526')
        self.assertEqual(sha1, das.getChroot().content.sha1)

    def test_getChrootHash(self):
        das = self.factory.makeDistroArchSeries()
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        sha1 = hashlib.sha1(b'abcxyz').hexdigest()
        sha256 = hashlib.sha256(b'abcxyz').hexdigest()
        ws_das.setChroot(data=b'abcxyz', sha1sum=sha1)
        self.assertThat(
            das.getChrootHash(
                PackagePublishingPocket.RELEASE, BuildBaseImageType.CHROOT),
            MatchesDict({'sha256': Equals(sha256)}))

    def test_setChroot_removeChroot(self):
        das = self.factory.makeDistroArchSeries()
        user = das.distroseries.distribution.main_archive.owner
        expected_file = 'chroot-%s-%s-%s.tar.gz' % (
            das.distroseries.distribution.name, das.distroseries.name,
            das.architecturetag)
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        sha1 = hashlib.sha1(b'abcxyz').hexdigest()
        ws_das.setChroot(data=b'abcxyz', sha1sum=sha1)
        self.assertTrue(ws_das.chroot_url.endswith(expected_file))
        ws_das.removeChroot()
        self.assertIsNone(ws_das.chroot_url)
        ws_das.setChroot(data=b'abcxyz', sha1sum=sha1)
        self.assertTrue(ws_das.chroot_url.endswith(expected_file))

    def test_setChroot_removeChroot_pocket(self):
        das = self.factory.makeDistroArchSeries()
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        sha1_1 = hashlib.sha1(b'abcxyz').hexdigest()
        ws_das.setChroot(data=b'abcxyz', sha1sum=sha1_1)
        sha1_2 = hashlib.sha1(b'123456').hexdigest()
        ws_das.setChroot(data=b'123456', sha1sum=sha1_2, pocket='Updates')
        release_chroot = das.getChroot(pocket=PackagePublishingPocket.RELEASE)
        self.assertEqual(sha1_1, release_chroot.content.sha1)
        updates_chroot = das.getChroot(pocket=PackagePublishingPocket.UPDATES)
        self.assertEqual(sha1_2, updates_chroot.content.sha1)
        with person_logged_in(user):
            release_chroot_url = release_chroot.http_url
            updates_chroot_url = updates_chroot.http_url
        self.assertEqual(
            release_chroot_url, ws_das.getChrootURL(pocket='Release'))
        self.assertEqual(
            updates_chroot_url, ws_das.getChrootURL(pocket='Updates'))
        self.assertEqual(
            updates_chroot_url, ws_das.getChrootURL(pocket='Proposed'))
        ws_das.removeChroot(pocket='Updates')
        self.assertEqual(
            release_chroot_url, ws_das.getChrootURL(pocket='Release'))
        self.assertEqual(
            release_chroot_url, ws_das.getChrootURL(pocket='Updates'))
        self.assertEqual(
            release_chroot_url, ws_das.getChrootURL(pocket='Proposed'))
        ws_das.setChroot(data=b'123456', sha1sum=sha1_2, pocket='Updates')
        updates_chroot = das.getChroot(pocket=PackagePublishingPocket.UPDATES)
        self.assertEqual(sha1_2, updates_chroot.content.sha1)
        with person_logged_in(user):
            updates_chroot_url = updates_chroot.http_url
        self.assertEqual(
            release_chroot_url, ws_das.getChrootURL(pocket='Release'))
        self.assertEqual(
            updates_chroot_url, ws_das.getChrootURL(pocket='Updates'))
        self.assertEqual(
            updates_chroot_url, ws_das.getChrootURL(pocket='Proposed'))

    def test_setChroot_removeChroot_image_type(self):
        das = self.factory.makeDistroArchSeries()
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        sha1_1 = hashlib.sha1(b'abcxyz').hexdigest()
        ws_das.setChroot(data=b'abcxyz', sha1sum=sha1_1)
        sha1_2 = hashlib.sha1(b'123456').hexdigest()
        ws_das.setChroot(
            data=b'123456', sha1sum=sha1_2, image_type='LXD image')
        chroot_image = das.getChroot(image_type=BuildBaseImageType.CHROOT)
        self.assertEqual(sha1_1, chroot_image.content.sha1)
        lxd_image = das.getChroot(image_type=BuildBaseImageType.LXD)
        self.assertEqual(sha1_2, lxd_image.content.sha1)
        with person_logged_in(user):
            chroot_image_url = chroot_image.http_url
            lxd_image_url = lxd_image.http_url
        self.assertEqual(
            chroot_image_url, ws_das.getChrootURL(image_type='Chroot tarball'))
        self.assertEqual(
            lxd_image_url, ws_das.getChrootURL(image_type='LXD image'))
        ws_das.removeChroot(image_type='LXD image')
        self.assertEqual(
            chroot_image_url, ws_das.getChrootURL(image_type='Chroot tarball'))
        self.assertIsNone(ws_das.getChrootURL(image_type='LXD image'))

    def test_setChrootFromBuild(self):
        self.useFixture(FeatureFixture({LIVEFS_FEATURE_FLAG: "on"}))
        das = self.factory.makeDistroArchSeries()
        build = self.factory.makeLiveFSBuild()
        build_url = api_url(build)
        login_as(build.livefs.owner)
        lfas = []
        for filename in (
                "livecd.ubuntu-base.rootfs.tar.gz",
                "livecd.ubuntu-base.manifest"):
            lfa = self.factory.makeLibraryFileAlias(filename=filename)
            lfas.append(lfa)
            build.addFile(lfa)
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        ws_das.setChrootFromBuild(
            livefsbuild=build_url, filename="livecd.ubuntu-base.rootfs.tar.gz")
        self.assertEqual(lfas[0], das.getChroot())

    def test_setChrootFromBuild_random_user(self):
        # Random users are not allowed to set chroots from a livefs build.
        self.useFixture(FeatureFixture({LIVEFS_FEATURE_FLAG: "on"}))
        das = self.factory.makeDistroArchSeries()
        build = self.factory.makeLiveFSBuild()
        build_url = api_url(build)
        login_as(build.livefs.owner)
        build.addFile(self.factory.makeLibraryFileAlias(
            filename="livecd.ubuntu-base.rootfs.tar.gz"))
        user = self.factory.makePerson()
        webservice = launchpadlib_for("testing", user, version='devel')
        ws_das = ws_object(webservice, das)
        self.assertRaises(
            Unauthorized, ws_das.setChrootFromBuild,
            livefsbuild=build_url, filename="livecd.ubuntu-base.rootfs.tar.gz")

    def test_setChrootFromBuild_private(self):
        # Chroots may not be set to the output of a private livefs build.
        self.useFixture(FeatureFixture({LIVEFS_FEATURE_FLAG: "on"}))
        das = self.factory.makeDistroArchSeries()
        owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=owner, visibility=PersonVisibility.PRIVATE)
        login_as(owner)
        build = self.factory.makeLiveFSBuild(
            requester=owner, owner=private_team)
        build_url = api_url(build)
        build.addFile(self.factory.makeLibraryFileAlias(
            filename="livecd.ubuntu-base.rootfs.tar.gz"))
        user = das.distroseries.distribution.main_archive.owner
        private_team.addMember(user, owner)
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        e = self.assertRaises(
            BadRequest, ws_das.setChrootFromBuild,
            livefsbuild=build_url, filename="livecd.ubuntu-base.rootfs.tar.gz")
        self.assertEqual(b"Cannot set chroot from a private build.", e.content)

    def test_setChrootFromBuild_pocket(self):
        self.useFixture(FeatureFixture({LIVEFS_FEATURE_FLAG: "on"}))
        das = self.factory.makeDistroArchSeries()
        build = self.factory.makeLiveFSBuild()
        build_url = api_url(build)
        login_as(build.livefs.owner)
        lfa = self.factory.makeLibraryFileAlias(
            filename="livecd.ubuntu-base.rootfs.tar.gz")
        build.addFile(lfa)
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        ws_das.setChrootFromBuild(
            livefsbuild=build_url, filename="livecd.ubuntu-base.rootfs.tar.gz",
            pocket="Updates")
        self.assertIsNone(
            das.getChroot(pocket=PackagePublishingPocket.RELEASE))
        self.assertEqual(
            lfa, das.getChroot(pocket=PackagePublishingPocket.UPDATES))

    def test_setChrootFromBuild_image_type(self):
        self.useFixture(FeatureFixture({LIVEFS_FEATURE_FLAG: "on"}))
        das = self.factory.makeDistroArchSeries()
        build = self.factory.makeLiveFSBuild()
        build_url = api_url(build)
        login_as(build.livefs.owner)
        lfa = self.factory.makeLibraryFileAlias(
            filename="livecd.ubuntu-base.lxd.tar.gz")
        build.addFile(lfa)
        user = das.distroseries.distribution.main_archive.owner
        webservice = launchpadlib_for("testing", user)
        ws_das = ws_object(webservice, das)
        ws_das.setChrootFromBuild(
            livefsbuild=build_url, filename="livecd.ubuntu-base.lxd.tar.gz",
            image_type="LXD image")
        self.assertIsNone(das.getChroot(image_type=BuildBaseImageType.CHROOT))
        self.assertEqual(lfa, das.getChroot(image_type=BuildBaseImageType.LXD))

    def test_setSourceFilter_removeSourceFilter_random_user(self):
        # Random users are not allowed to set or remove filters.
        das = self.factory.makeDistroArchSeries()
        packageset = self.factory.makePackageset(distroseries=das.distroseries)
        user = self.factory.makePerson()
        packageset_url = api_url(packageset)
        webservice = launchpadlib_for("testing", user, version="devel")
        ws_das = ws_object(webservice, das)
        self.assertRaises(
            Unauthorized, ws_das.setSourceFilter,
            packageset=packageset_url, sense="Include")
        self.assertRaises(Unauthorized, ws_das.removeSourceFilter)

    def test_setSourceFilter_wrong_distroseries(self):
        # Trying to set a filter using a packageset for the wrong
        # distroseries returns an error.
        das = self.factory.makeDistroArchSeries()
        packageset = self.factory.makePackageset()
        user = das.distroseries.distribution.main_archive.owner
        packageset_url = api_url(packageset)
        webservice = launchpadlib_for("testing", user, version="devel")
        ws_das = ws_object(webservice, das)
        e = self.assertRaises(
            BadRequest, ws_das.setSourceFilter,
            packageset=packageset_url, sense="Include")
        expected_error = (
            "The requested package set is for %s and cannot be set as a "
            "filter for %s %s." % (
                packageset.distroseries.fullseriesname,
                das.distroseries.fullseriesname,
                das.architecturetag))
        self.assertEqual(expected_error.encode("UTF-8"), e.content)

    def test_setSourceFilter_removeSourceFilter(self):
        das = self.factory.makeDistroArchSeries()
        packageset = self.factory.makePackageset(distroseries=das.distroseries)
        user = das.distroseries.distribution.main_archive.owner
        packageset_url = api_url(packageset)
        webservice = launchpadlib_for("testing", user, version="devel")
        ws_das = ws_object(webservice, das)
        ws_das.setSourceFilter(packageset=packageset_url, sense="Include")
        ws_dasf = ws_das.getSourceFilter()
        self.assertThat(ws_dasf, MatchesStructure(
            packageset_link=EndsWith(packageset_url),
            sense=Equals("Include")))
        ws_das.setSourceFilter(packageset=packageset_url, sense="Exclude")
        ws_dasf = ws_das.getSourceFilter()
        self.assertThat(ws_dasf, MatchesStructure(
            packageset_link=EndsWith(packageset_url),
            sense=Equals("Exclude")))
        ws_das.removeSourceFilter()
        self.assertIsNone(ws_das.getSourceFilter())
