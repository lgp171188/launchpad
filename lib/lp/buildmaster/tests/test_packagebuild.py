# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `IPackageBuild`."""

__metaclass__ = type

from datetime import datetime
import hashlib
import os

from storm.store import Store
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.testing.layers import (
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.archiveuploader.uploadprocessor import (
    parse_build_upload_leaf_name,
    )
from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildStatus,
    )
from lp.buildmaster.interfaces.packagebuild import (
    IPackageBuild,
    IPackageBuildSet,
    IPackageBuildSource,
    )
from lp.buildmaster.model.packagebuild import PackageBuild
from lp.buildmaster.tests.mock_slaves import WaitingSlave
from lp.registry.interfaces.pocket import (
    PackagePublishingPocket,
    )
from lp.testing import (
    login,
    login_person,
    TestCaseWithFactory,
    )
from lp.testing.fakemethod import FakeMethod


class TestPackageBuildBase(TestCaseWithFactory):
    """Provide a factory method for creating PackageBuilds.

    This is not included in the launchpad test factory because
    only classes deriving from PackageBuild should be used.
    """

    def makePackageBuild(
        self, archive=None, job_type=BuildFarmJobType.PACKAGEBUILD,
        status=BuildStatus.NEEDSBUILD,
        pocket=PackagePublishingPocket.RELEASE):
        if archive is None:
            archive = self.factory.makeArchive()

        return getUtility(IPackageBuildSource).new(
            job_type=job_type, virtualized=True, archive=archive,
            status=status, pocket=pocket)


class TestPackageBuild(TestPackageBuildBase):
    """Tests for the package build object."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        """Create a package build with which to test."""
        super(TestPackageBuild, self).setUp()
        joe = self.factory.makePerson(name="joe")
        joes_ppa = self.factory.makeArchive(owner=joe, name="ppa")
        self.package_build = self.makePackageBuild(archive=joes_ppa)

    def test_providesInterface(self):
        # PackageBuild provides IPackageBuild
        self.assertProvides(self.package_build, IPackageBuild)

    def test_saves_record(self):
        # A package build can be stored in the database.
        store = Store.of(self.package_build)
        store.flush()
        retrieved_build = store.find(
            PackageBuild,
            PackageBuild.id == self.package_build.id).one()
        self.assertEqual(self.package_build, retrieved_build)

    def test_unimplemented_methods(self):
        # Classes deriving from PackageBuild must provide getTitle.
        self.assertRaises(NotImplementedError, self.package_build.getTitle)
        self.assertRaises(
            NotImplementedError, self.package_build.estimateDuration)
        self.assertRaises(
            NotImplementedError, self.package_build.verifySuccessfulUpload)
        self.assertRaises(NotImplementedError, self.package_build.notify)
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        self.assertRaises(
            NotImplementedError, self.package_build.handleStatus,
            None, None, None)

    def test_default_values(self):
        # PackageBuild has a number of default values.
        self.failUnlessEqual(
            'multiverse', self.package_build.current_component.name)
        self.failUnlessEqual(None, self.package_build.distribution)
        self.failUnlessEqual(None, self.package_build.distro_series)

    def test_log_url(self):
        # The url of the build log file is determined by the PackageBuild.
        lfa = self.factory.makeLibraryFileAlias('mybuildlog.txt')
        removeSecurityProxy(self.package_build).log = lfa
        log_url = self.package_build.log_url
        self.failUnlessEqual(
            'http://launchpad.dev/~joe/'
            '+archive/ppa/+build/%d/+files/mybuildlog.txt' % (
                self.package_build.build_farm_job.id),
            log_url)

    def test_storeUploadLog(self):
        # The given content is uploaded to the librarian and linked as
        # the upload log.
        self.package_build.storeUploadLog("Some content")
        self.failIfEqual(None, self.package_build.upload_log)
        self.failUnlessEqual(
            hashlib.sha1("Some content").hexdigest(),
            self.package_build.upload_log.content.sha1)

    def test_storeUploadLog_private(self):
        # A private package build will store the upload log on the
        # restricted librarian.
        login('admin@canonical.com')
        self.package_build.archive.buildd_secret = 'sekrit'
        self.package_build.archive.private = True
        self.failUnless(self.package_build.is_private)
        self.package_build.storeUploadLog("Some content")
        self.failUnless(self.package_build.upload_log.restricted)

    def test_upload_log_url(self):
        # The url of the upload log file is determined by the PackageBuild.
        Store.of(self.package_build).flush()
        build_id = self.package_build.build_farm_job.id
        self.package_build.storeUploadLog("Some content")
        log_url = self.package_build.upload_log_url
        self.failUnlessEqual(
            'http://launchpad.dev/~joe/'
            '+archive/ppa/+build/%d/+files/upload_%d_log.txt' % (
                build_id, build_id),
            log_url)

    def test_view_package_build(self):
        # Anonymous access can read public builds, but not edit.
        self.failUnlessEqual(
            None, self.package_build.dependencies)
        self.assertRaises(
            Unauthorized, setattr, self.package_build,
            'dependencies', u'my deps')

    def test_edit_package_build(self):
        # An authenticated user who belongs to the owning archive team
        # can edit the build.
        login_person(self.package_build.archive.owner)
        self.package_build.dependencies = u'My deps'
        self.failUnlessEqual(
            u'My deps', self.package_build.dependencies)

        # But other users cannot.
        other_person = self.factory.makePerson()
        login_person(other_person)
        self.assertRaises(
            Unauthorized, setattr, self.package_build,
            'dependencies', u'my deps')

    def test_admin_package_build(self):
        # Users with edit access can update attributes.
        login('admin@canonical.com')
        self.package_build.dependencies = u'My deps'
        self.failUnlessEqual(
            u'My deps', self.package_build.dependencies)

    def test_getUploadDirLeaf(self):
        # getUploadDirLeaf returns the current time, followed by the build
        # cookie.
        now = datetime.now()
        build_cookie = self.factory.getUniqueString()
        upload_leaf = self.package_build.getUploadDirLeaf(
            build_cookie, now=now)
        self.assertEqual(
            '%s-%s' % (now.strftime("%Y%m%d-%H%M%S"), build_cookie),
            upload_leaf)

    def test_getBuildCookie(self):
        # A build cookie is made up of the package build id and record id.
        # The uploadprocessor relies on this format.
        Store.of(self.package_build).flush()
        cookie = self.package_build.getBuildCookie()
        expected_cookie = "%d-PACKAGEBUILD-%d" % (
            self.package_build.id, self.package_build.build_farm_job.id)
        self.assertEquals(expected_cookie, cookie)


class TestPackageBuildSet(TestPackageBuildBase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super(TestPackageBuildSet, self).setUp()
        person = self.factory.makePerson()
        self.archive = self.factory.makeArchive(owner=person)
        self.package_builds = []
        self.package_builds.append(
            self.makePackageBuild(archive=self.archive,
                                  pocket=PackagePublishingPocket.UPDATES))
        self.package_builds.append(
            self.makePackageBuild(archive=self.archive,
                                  status=BuildStatus.BUILDING))
        self.package_build_set = getUtility(IPackageBuildSet)

    def test_getBuildsForArchive_all(self):
        # The default call without arguments returns all builds for the
        # archive.
        self.assertContentEqual(
            self.package_builds, self.package_build_set.getBuildsForArchive(
                self.archive))

    def test_getBuildsForArchive_by_status(self):
        # If the status arg is used, the results will be filtered by
        # status.
        self.assertContentEqual(
            self.package_builds[1:],
            self.package_build_set.getBuildsForArchive(
                self.archive, status=BuildStatus.BUILDING))

    def test_getBuildsForArchive_by_pocket(self):
        # If the pocket arg is used, the results will be filtered by
        # pocket.
        self.assertContentEqual(
            self.package_builds[:1],
            self.package_build_set.getBuildsForArchive(
                self.archive, pocket=PackagePublishingPocket.UPDATES))


class TestGetUploadMethodsMixin:
    """Tests for `IPackageBuild` that need objects from the rest of LP."""

    layer = LaunchpadZopelessLayer

    def makeBuild(self):
        """Allow classes to override the build with which the test runs."""
        raise NotImplemented

    def setUp(self):
        super(TestGetUploadMethodsMixin, self).setUp()
        self.build = self.makeBuild()

    def test_getUploadDirLeafCookie_parseable(self):
        # getUploadDirLeaf should return a directory name
        # that is parseable by the upload processor.
        upload_leaf = self.build.getUploadDirLeaf(
            self.build.getBuildCookie())
        job_id = parse_build_upload_leaf_name(upload_leaf)
        self.assertEqual(job_id, self.build.build_farm_job.id)


class TestHandleStatusMixin:
    """Tests for `IPackageBuild`s handleStatus method.

    """

    layer = LaunchpadZopelessLayer

    def makeBuild(self):
        """Allow classes to override the build with which the test runs."""
        raise NotImplementedError

    def setUp(self):
        super(TestHandleStatusMixin, self).setUp()
        self.build = self.makeBuild()
        # For the moment, we require a builder for the build so that
        # handleStatus_OK can get a reference to the slave.
        builder = self.factory.makeBuilder()
        self.build.buildqueue_record.builder = builder
        self.build.buildqueue_record.setDateStarted(UTC_NOW)
        self.slave = WaitingSlave('BuildStatus.OK')
        self.slave.valid_file_hashes.append('test_file_hash')
        builder.setSlaveForTesting(self.slave)

        # We overwrite the buildmaster root to use a temp directory.
        self.upload_root = self.makeTemporaryDirectory()
        tmp_builddmaster_root = """
        [builddmaster]
        root: %s
        """ % self.upload_root
        config.push('tmp_builddmaster_root', tmp_builddmaster_root)

        # We stub out our builds getUploaderCommand() method so
        # we can check whether it was called as well as
        # verifySuccessfulUpload().
        removeSecurityProxy(self.build).verifySuccessfulUpload = FakeMethod(
            result=True)

    def assertResultCount(self, count, result):
        self.assertEquals(
            1, len(os.listdir(os.path.join(self.upload_root, result))))

    def test_handleStatus_OK_normal_file(self):
        # A filemap with plain filenames should not cause a problem.
        # The call to handleStatus will attempt to get the file from
        # the slave resulting in a URL error in this test case.
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        self.build.handleStatus('OK', None, {
                'filemap': {'myfile.py': 'test_file_hash'},
                })

        self.assertEqual(BuildStatus.UPLOADING, self.build.status)
        self.assertResultCount(1, "incoming")

    def test_handleStatus_OK_absolute_filepath(self):
        # A filemap that tries to write to files outside of
        # the upload directory will result in a failed upload.
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        self.build.handleStatus('OK', None, {
            'filemap': {'/tmp/myfile.py': 'test_file_hash'},
            })
        self.assertEqual(BuildStatus.FAILEDTOUPLOAD, self.build.status)
        self.assertResultCount(0, "failed")
        self.assertIs(None, self.build.buildqueue_record)

    def test_handleStatus_OK_relative_filepath(self):
        # A filemap that tries to write to files outside of
        # the upload directory will result in a failed upload.
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        self.build.handleStatus('OK', None, {
            'filemap': {'../myfile.py': 'test_file_hash'},
            })
        self.assertEqual(BuildStatus.FAILEDTOUPLOAD, self.build.status)
        self.assertResultCount(0, "failed")

    def test_handleStatus_OK_sets_build_log(self):
        # The build log is set during handleStatus.
        removeSecurityProxy(self.build).log = None
        self.assertEqual(None, self.build.log)
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        self.build.handleStatus('OK', None, {
                'filemap': {'myfile.py': 'test_file_hash'},
                })
        self.assertNotEqual(None, self.build.log)

    def test_date_finished_set(self):
        # The date finished is updated during handleStatus_OK.
        removeSecurityProxy(self.build).date_finished = None
        self.assertEqual(None, self.build.date_finished)
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        self.build.handleStatus('OK', None, {
                'filemap': {'myfile.py': 'test_file_hash'},
                })
        self.assertNotEqual(None, self.build.date_finished)
