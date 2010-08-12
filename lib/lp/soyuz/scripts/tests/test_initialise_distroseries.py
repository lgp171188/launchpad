# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the initialise_distroseries script machinery."""

__metaclass__ = type

import os
import subprocess
import sys
import transaction
from zope.component import getUtility

from lp.buildmaster.interfaces.buildbase import BuildStatus
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.sourcepackageformat import SourcePackageFormat
from lp.soyuz.scripts.initialise_distroseries import (
    InitialiseDistroSeries, InitialisationError)
from lp.testing import TestCaseWithFactory

from canonical.config import config
from canonical.launchpad.interfaces import IDistributionSet
from canonical.launchpad.ftests import login
from canonical.testing.layers import LaunchpadZopelessLayer


class TestInitialiseDistroSeries(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestInitialiseDistroSeries, self).setUp()
        login("foo.bar@canonical.com")
        distribution_set = getUtility(IDistributionSet)
        self.ubuntutest = distribution_set['ubuntutest']
        self.ubuntu = distribution_set['ubuntu']
        self.hoary = self.ubuntu['hoary']

    def _create_distroseries(self, parent_series):
        foobuntu = self.ubuntutest.newSeries(
            'foobuntu', 'FooBuntu', 'The Foobuntu', 'yeck', 'doom',
            '888', parent_series, self.hoary.owner)
        return foobuntu

    def _set_pending_to_failed(self, distroseries):
        pending_builds = distroseries.getBuildRecords(
            BuildStatus.NEEDSBUILD, pocket=PackagePublishingPocket.RELEASE)
        for build in pending_builds:
            build.status = BuildStatus.FAILEDTOBUILD

    def test_failure_with_no_parent_series(self):
        foobuntu = self._create_distroseries(None)
        ids = InitialiseDistroSeries(foobuntu)
        self.assertRaises(InitialisationError, ids.check)

    def test_failure_for_already_released_distroseries(self):
        ids = InitialiseDistroSeries(self.ubuntutest['breezy-autotest'])
        self.assertRaises(InitialisationError, ids.check)

    def test_failure_with_pending_builds(self):
        foobuntu = self._create_distroseries(self.hoary)
        transaction.commit()
        ids = InitialiseDistroSeries(foobuntu)
        self.assertRaises(InitialisationError, ids.check)

    def test_failure_with_queue_items(self):
        foobuntu = self._create_distroseries(
            self.ubuntu['breezy-autotest'])
        ids = InitialiseDistroSeries(foobuntu)
        self.assertRaises(InitialisationError, ids.check)

    def test_initialise(self):
        foobuntu = self._create_distroseries(self.hoary)
        self._set_pending_to_failed(self.hoary)
        transaction.commit()
        ids = InitialiseDistroSeries(foobuntu)
        ids.check()
        ids.initialise()
        hoary_pmount_pubs = self.hoary.getPublishedReleases('pmount')
        foobuntu_pmount_pubs = foobuntu.getPublishedReleases('pmount')
        self.assertEqual(len(hoary_pmount_pubs), len(foobuntu_pmount_pubs))
        hoary_i386_pmount_pubs = self.hoary['i386'].getReleasedPackages(
            'pmount')
        foobuntu_i386_pmount_pubs = foobuntu['i386'].getReleasedPackages(
            'pmount')
        self.assertEqual(
            len(hoary_i386_pmount_pubs), len(foobuntu_i386_pmount_pubs))
        pmount_binrel = (
            foobuntu['i386'].getReleasedPackages(
            'pmount')[0].binarypackagerelease)
        self.assertEqual(pmount_binrel.title, u'pmount-0.1-1')
        self.assertEqual(pmount_binrel.build.id, 7)
        self.assertEqual(
            pmount_binrel.build.title,
            u'i386 build of pmount 0.1-1 in ubuntu hoary RELEASE')
        pmount_srcrel = pmount_binrel.build.source_package_release
        self.assertEqual(pmount_srcrel.title, u'pmount - 0.1-1')
        foobuntu_pmount = pmount_srcrel.getBuildByArch(
            foobuntu['i386'], foobuntu.main_archive)
        hoary_pmount = pmount_srcrel.getBuildByArch(
            self.hoary['i386'], self.hoary.main_archive)
        self.assertEqual(foobuntu_pmount.id, hoary_pmount.id)
        pmount_source = self.hoary.getSourcePackage(
            'pmount').currentrelease
        self.assertEqual(
            pmount_source.title,
            '"pmount" 0.1-2 source package in The Hoary Hedgehog Release')
        pmount_source = foobuntu.getSourcePackage('pmount').currentrelease
        self.assertEqual(
            pmount_source.title,
            '"pmount" 0.1-2 source package in The Foobuntu')
        self.assertEqual(
            pmount_source.sourcepackagerelease.getBuildByArch(
            foobuntu['i386'], foobuntu.main_archive), None)
        created_build = pmount_source.sourcepackagerelease.createBuild(
            foobuntu['i386'], PackagePublishingPocket.RELEASE,
            foobuntu.main_archive)
        retrieved_build = pmount_source.sourcepackagerelease.getBuildByArch(
            foobuntu['i386'], foobuntu.main_archive)
        self.assertEqual(retrieved_build.id, created_build.id)
        self.assertEqual(
            pmount_source.sourcepackagerelease.getBuildByArch(
            foobuntu['hppa'], foobuntu.main_archive), None)
        self.assertTrue(
            foobuntu.isSourcePackageFormatPermitted(
            SourcePackageFormat.FORMAT_1_0))

    def test_copying_packagesets(self):
        # If a parent series has packagesets, we should copy them
        test1 = getUtility(IPackagesetSet).new(
            u'test1', u'test 1 packageset', self.hoary.owner,
            distroseries=self.hoary)
        test2 = getUtility(IPackagesetSet).new(
            u'test2', u'test 2 packageset', self.hoary.owner,
            distroseries=self.hoary)
        test3 = getUtility(IPackagesetSet).new(
            u'test3', u'test 3 packageset', self.hoary.owner,
            distroseries=self.hoary)
        foobuntu = self._create_distroseries(self.hoary)
        self._set_pending_to_failed(self.hoary)
        transaction.commit()
        ids = InitialiseDistroSeries(foobuntu)
        ids.check()
        ids.initialise()
        # We can fetch the copied sets from foobuntu
        foobuntu_test1 = getUtility(IPackagesetSet).getByName(
            u'test1', distroseries=foobuntu)
        foobuntu_test2 = getUtility(IPackagesetSet).getByName(
            u'test2', distroseries=foobuntu)
        foobuntu_test3 = getUtility(IPackagesetSet).getByName(
            u'test3', distroseries=foobuntu)
        # And we can see they are exact copies, with the related_set for the
        # copies pointing to the packageset in the parent
        self.assertEqual(test1.description, foobuntu_test1.description)
        self.assertEqual(test2.description, foobuntu_test2.description)
        self.assertEqual(test3.description, foobuntu_test3.description)
        self.assertEqual(foobuntu_test1.relatedSets().one(), test1)
        self.assertEqual(foobuntu_test2.relatedSets().one(), test2)
        self.assertEqual(foobuntu_test3.relatedSets().one(), test3)

    def test_script(self):
        foobuntu = self._create_distroseries(self.hoary)
        self._set_pending_to_failed(self.hoary)
        transaction.commit()
        ifp = os.path.join(
            config.root, 'scripts', 'ftpmaster-tools',
            'initialise-from-parent.py')
        process = subprocess.Popen(
            [sys.executable, ifp, "-vv", "-d", "ubuntutest", "foobuntu"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        self.assertEqual(process.returncode, 0)
        self.assertTrue(
            "DEBUG   Committing transaction." in stderr.split('\n'))
        hoary_pmount_pubs = self.hoary.getPublishedReleases('pmount')
        foobuntu_pmount_pubs = foobuntu.getPublishedReleases('pmount')
        self.assertEqual(len(hoary_pmount_pubs), len(foobuntu_pmount_pubs))
