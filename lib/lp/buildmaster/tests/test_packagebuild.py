# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `IPackageBuild`."""

import hashlib

from storm.store import Store
from zope.security.management import checkPermission

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.testing import TestCaseWithFactory, login, login_person
from lp.testing.layers import LaunchpadFunctionalLayer


class TestPackageBuildMixin(TestCaseWithFactory):
    """Test methods provided by PackageBuildMixin."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        # BuildFarmJobMixin only operates as part of a concrete
        # IBuildFarmJob implementation. Here we use
        # SourcePackageRecipeBuild.
        joe = self.factory.makePerson(name="joe")
        joes_ppa = self.factory.makeArchive(owner=joe, name="ppa")
        self.package_build = self.factory.makeSourcePackageRecipeBuild(
            archive=joes_ppa
        )

    def test_providesInterface(self):
        # PackageBuild provides IPackageBuild
        login("admin@canonical.com")
        self.assertProvides(self.package_build, IPackageBuild)

    def test_updateStatus_MANUALDEPWAIT_sets_dependencies(self):
        # updateStatus sets dependencies for a MANUALDEPWAIT build.
        self.package_build.updateStatus(
            BuildStatus.MANUALDEPWAIT, worker_status={"dependencies": "deps"}
        )
        self.assertEqual("deps", self.package_build.dependencies)
        self.package_build.updateStatus(
            BuildStatus.MANUALDEPWAIT, worker_status={}
        )
        self.assertEqual(None, self.package_build.dependencies)

    def test_updateStatus_unsets_dependencies_for_other_statuses(self):
        # updateStatus unsets existing dependencies when transitioning
        # to another state.
        self.package_build.updateStatus(
            BuildStatus.MANUALDEPWAIT, worker_status={"dependencies": "deps"}
        )
        self.assertEqual("deps", self.package_build.dependencies)
        self.package_build.updateStatus(BuildStatus.NEEDSBUILD)
        self.assertEqual(None, self.package_build.dependencies)

    def test_log_url(self):
        # The url of the build log file is determined by the PackageBuild.
        lfa = self.factory.makeLibraryFileAlias("mybuildlog.txt")
        self.package_build.setLog(lfa)
        log_url = self.package_build.log_url
        self.assertEqual(
            "http://launchpad.test/~joe/+archive/ubuntu/ppa/"
            "+recipebuild/%d/+files/mybuildlog.txt" % (self.package_build.id),
            log_url,
        )

    def test_storeUploadLog(self):
        # The given content is uploaded to the librarian and linked as
        # the upload log.
        self.package_build.storeUploadLog("Some content")
        self.assertIsNotNone(self.package_build.upload_log)
        self.assertEqual(
            hashlib.sha1(b"Some content").hexdigest(),
            self.package_build.upload_log.content.sha1,
        )

    def test_storeUploadLog_private(self):
        # A private package build will store the upload log on the
        # restricted librarian.
        login("admin@canonical.com")
        self.package_build.archive.private = True
        self.assertTrue(self.package_build.is_private)
        self.package_build.storeUploadLog("Some content")
        self.assertTrue(self.package_build.upload_log.restricted)

    def test_storeUploadLog_unicode(self):
        # Unicode upload logs are uploaded as UTF-8.
        unicode_content = "Some content \N{SNOWMAN}"
        self.package_build.storeUploadLog(unicode_content)
        self.assertIsNotNone(self.package_build.upload_log)
        self.assertEqual(
            hashlib.sha1(unicode_content.encode("utf-8")).hexdigest(),
            self.package_build.upload_log.content.sha1,
        )

    def test_upload_log_url(self):
        # The url of the upload log file is determined by the PackageBuild.
        Store.of(self.package_build).flush()
        self.package_build.storeUploadLog("Some content")
        log_url = self.package_build.upload_log_url
        self.assertEqual(
            "http://launchpad.test/~joe/+archive/ubuntu/ppa/"
            "+recipebuild/%d/+files/upload_%d_log.txt"
            % (self.package_build.id, self.package_build.id),
            log_url,
        )

    def test_view_package_build(self):
        # Anonymous access can read public builds, but not edit.
        self.assertTrue(checkPermission("launchpad.View", self.package_build))
        self.assertFalse(checkPermission("launchpad.Edit", self.package_build))

    def test_edit_package_build(self):
        # An authenticated user who belongs to the owning archive team
        # can edit the build.
        login_person(self.package_build.archive.owner)
        self.assertTrue(checkPermission("launchpad.View", self.package_build))
        self.assertTrue(checkPermission("launchpad.Edit", self.package_build))

        # But other users cannot.
        other_person = self.factory.makePerson()
        login_person(other_person)
        self.assertTrue(checkPermission("launchpad.View", self.package_build))
        self.assertFalse(checkPermission("launchpad.Edit", self.package_build))

    def test_admin_package_build(self):
        # Users with edit access can update attributes.
        login("admin@canonical.com")
        self.assertTrue(checkPermission("launchpad.View", self.package_build))
        self.assertTrue(checkPermission("launchpad.Edit", self.package_build))
