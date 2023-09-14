# Copyright 2010-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for BuildFarmJobBehaviourBase."""

import hashlib
import os
import shutil
import tempfile
from collections import OrderedDict
from datetime import datetime

import six
from fixtures import MockPatchObject
from testtools import ExpectedException
from testtools.twistedsupport import AsynchronousDeferredRunTest
from twisted.internet import defer
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.archiveuploader.uploadprocessor import parse_build_upload_leaf_name
from lp.buildmaster.enums import BuildBaseImageType, BuildStatus
from lp.buildmaster.interactor import (
    BuilderInteractor,
    shut_down_default_process_pool,
)
from lp.buildmaster.interfaces.builder import BuildDaemonError
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
)
from lp.buildmaster.tests.mock_workers import (
    MockBuilder,
    OkWorker,
    WaitingWorker,
)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.config import config
from lp.services.log.logger import BufferLogger
from lp.services.statsd.tests import StatsMixin
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import (
    LaunchpadZopelessLayer,
    ZopelessDatabaseLayer,
    ZopelessLayer,
)
from lp.testing.mail_helpers import pop_notifications


class FakeBuildFarmJob:
    """Dummy BuildFarmJob."""

    build_cookie = "PACKAGEBUILD-1"
    title = "some job for something"


class FakeLibraryFileContent:
    def __init__(self, filename):
        self.sha1 = hashlib.sha1(six.ensure_binary(filename)).hexdigest()


class FakeLibraryFileAlias:
    def __init__(self, filename):
        self.filename = filename
        self.content = FakeLibraryFileContent(filename)
        self.http_url = "http://librarian.test/%s" % filename


class FakePocketChroot:
    def __init__(self, chroot, image_type):
        self.chroot = chroot
        self.image_type = image_type


class FakeDistroArchSeries:
    def __init__(self):
        self.images = {
            BuildBaseImageType.CHROOT: "chroot-fooix-bar-y86.tar.gz",
        }

    def getPocketChroot(self, pocket, exact_pocket=False, image_type=None):
        if image_type in self.images:
            return FakePocketChroot(
                FakeLibraryFileAlias(self.images[image_type]), image_type
            )
        else:
            return None


class TestBuildFarmJobBehaviourBase(TestCaseWithFactory):
    """Test very small, basic bits of BuildFarmJobBehaviourBase."""

    layer = ZopelessDatabaseLayer

    def _makeBehaviour(self, buildfarmjob=None):
        """Create a `BuildFarmJobBehaviourBase`."""
        if buildfarmjob is None:
            buildfarmjob = FakeBuildFarmJob()
        else:
            buildfarmjob = removeSecurityProxy(buildfarmjob)
        return BuildFarmJobBehaviourBase(buildfarmjob)

    def _makeBuild(self):
        """Create a `Build` object."""
        x86 = getUtility(IProcessorSet).getByName("386")
        distroarchseries = self.factory.makeDistroArchSeries(
            architecturetag="x86", processor=x86
        )
        distroseries = distroarchseries.distroseries
        archive = self.factory.makeArchive(
            distribution=distroseries.distribution
        )
        pocket = PackagePublishingPocket.RELEASE
        spr = self.factory.makeSourcePackageRelease(
            distroseries=distroseries, archive=archive
        )
        return getUtility(IBinaryPackageBuildSet).new(
            spr, archive, distroarchseries, pocket
        )

    def test_getUploadDirLeaf(self):
        # getUploadDirLeaf returns the current time, followed by the build
        # cookie.
        now = datetime.now()
        build_cookie = self.factory.getUniqueString()
        upload_leaf = self._makeBehaviour().getUploadDirLeaf(
            build_cookie, now=now
        )
        self.assertEqual(
            "%s-%s" % (now.strftime("%Y%m%d-%H%M%S"), build_cookie),
            upload_leaf,
        )

    def test_extraBuildArgs_virtualized(self):
        # If the builder is virtualized, extraBuildArgs sends
        # fast_cleanup: True.
        behaviour = self._makeBehaviour(self._makeBuild())
        behaviour.setBuilder(self.factory.makeBuilder(virtualized=True), None)
        self.assertIs(True, behaviour.extraBuildArgs()["fast_cleanup"])

    def test_extraBuildArgs_non_virtualized(self):
        # If the builder is non-virtualized, extraBuildArgs sends
        # fast_cleanup: False.
        behaviour = self._makeBehaviour(self._makeBuild())
        behaviour.setBuilder(self.factory.makeBuilder(virtualized=False), None)
        self.assertIs(False, behaviour.extraBuildArgs()["fast_cleanup"])

    def test_extractBuildStatus_baseline(self):
        # extractBuildStatus picks the name of the build status out of a
        # dict describing the worker's status.
        worker_status = {"build_status": "BuildStatus.BUILDING"}
        self.assertEqual(
            "BUILDING",
            BuildFarmJobBehaviourBase.extractBuildStatus(worker_status),
        )

    def test_extractBuildStatus_malformed(self):
        # extractBuildStatus errors out when the status string is not
        # of the form it expects.
        worker_status = {"build_status": "BUILDING"}
        self.assertRaises(
            AssertionError,
            BuildFarmJobBehaviourBase.extractBuildStatus,
            worker_status,
        )


class TestDispatchBuildToWorker(StatsMixin, TestCase):
    layer = ZopelessLayer
    run_tests_with = AsynchronousDeferredRunTest

    def makeBehaviour(self, das):
        files = OrderedDict(
            [
                ("foo.dsc", {"url": "http://host/foo.dsc", "sha1": "0"}),
                (
                    "bar.tar",
                    {
                        "url": "http://host/bar.tar",
                        "sha1": "0",
                        "username": "admin",
                        "password": "sekrit",
                    },
                ),
            ]
        )

        behaviour = BuildFarmJobBehaviourBase(FakeBuildFarmJob())
        behaviour.composeBuildRequest = FakeMethod(
            (
                "foobuild",
                das,
                PackagePublishingPocket.RELEASE,
                files,
                {"some": "arg", "archives": ["http://admin:sekrit@blah/"]},
            )
        )
        return behaviour

    def assertDispatched(self, worker, logger, chroot_filename, image_type):
        # The worker's been asked to cache the chroot and both source
        # files, and then to start the build.
        expected_calls = [
            (
                "ensurepresent",
                "http://librarian.test/%s" % chroot_filename,
                "",
                "",
            ),
            ("ensurepresent", "http://host/foo.dsc", "", ""),
            ("ensurepresent", "http://host/bar.tar", "admin", "sekrit"),
            (
                "build",
                "PACKAGEBUILD-1",
                "foobuild",
                hashlib.sha1(six.ensure_binary(chroot_filename)).hexdigest(),
                ["foo.dsc", "bar.tar"],
                {
                    "archives": ["http://admin:sekrit@blah/"],
                    "image_type": image_type,
                    "some": "arg",
                },
            ),
        ]
        self.assertEqual(expected_calls, worker.call_log)

        # And details have been logged, including the build arguments
        # with credentials redacted.
        self.assertStartsWith(
            logger.getLogBuffer(),
            "INFO Preparing job PACKAGEBUILD-1 (some job for something) on "
            "http://fake:0000.\n"
            "INFO Dispatching job PACKAGEBUILD-1 (some job for something) to "
            "http://fake:0000:\n{",
        )
        self.assertIn("http://<redacted>@blah/", logger.getLogBuffer())
        self.assertNotIn("sekrit", logger.getLogBuffer())
        self.assertEndsWith(
            logger.getLogBuffer(),
            "INFO Job PACKAGEBUILD-1 (some job for something) started on "
            "http://fake:0000: BuildStatus.BUILDING PACKAGEBUILD-1\n",
        )

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker(self):
        behaviour = self.makeBehaviour(FakeDistroArchSeries())
        builder = MockBuilder()
        worker = OkWorker()
        logger = BufferLogger()
        behaviour.setBuilder(builder, worker)
        yield behaviour.dispatchBuildToWorker(logger)

        self.assertDispatched(
            worker, logger, "chroot-fooix-bar-y86.tar.gz", "chroot"
        )

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_with_other_image_available(self):
        # If a base image is available but isn't in the behaviour's image
        # types, it isn't used.
        das = FakeDistroArchSeries()
        das.images[BuildBaseImageType.LXD] = "lxd-fooix-bar-y86.tar.gz"
        behaviour = self.makeBehaviour(das)
        builder = MockBuilder()
        worker = OkWorker()
        logger = BufferLogger()
        behaviour.setBuilder(builder, worker)
        yield behaviour.dispatchBuildToWorker(logger)

        self.assertDispatched(
            worker, logger, "chroot-fooix-bar-y86.tar.gz", "chroot"
        )

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_lxd(self):
        das = FakeDistroArchSeries()
        das.images[BuildBaseImageType.LXD] = "lxd-fooix-bar-y86.tar.gz"
        behaviour = self.makeBehaviour(das)
        behaviour.image_types = [
            BuildBaseImageType.LXD,
            BuildBaseImageType.CHROOT,
        ]
        builder = MockBuilder()
        worker = OkWorker()
        logger = BufferLogger()
        behaviour.setBuilder(builder, worker)
        yield behaviour.dispatchBuildToWorker(logger)

        self.assertDispatched(
            worker, logger, "lxd-fooix-bar-y86.tar.gz", "lxd"
        )

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_fallback(self):
        behaviour = self.makeBehaviour(FakeDistroArchSeries())
        behaviour.image_types = [
            BuildBaseImageType.LXD,
            BuildBaseImageType.CHROOT,
        ]
        builder = MockBuilder()
        worker = OkWorker()
        logger = BufferLogger()
        behaviour.setBuilder(builder, worker)
        yield behaviour.dispatchBuildToWorker(logger)

        self.assertDispatched(
            worker, logger, "chroot-fooix-bar-y86.tar.gz", "chroot"
        )

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_stats(self):
        self.setUpStats()
        behaviour = self.makeBehaviour(FakeDistroArchSeries())
        builder = MockBuilder()
        worker = OkWorker()
        logger = BufferLogger()
        behaviour.setBuilder(builder, worker)
        yield behaviour.dispatchBuildToWorker(logger)
        self.assertEqual(1, self.stats_client.incr.call_count)
        self.assertEqual(
            (
                "build.count,builder_name=mock-builder,env=test,"
                "job_type=UNKNOWN,region=",
            ),
            self.stats_client.incr.call_args_list[0][0],
        )


class TestGetUploadMethodsMixin:
    """Tests for `IPackageBuild` that need objects from the rest of LP."""

    layer = ZopelessDatabaseLayer

    def makeBuild(self):
        """Allow classes to override the build with which the test runs."""
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.build = self.makeBuild()
        self.behaviour = IBuildFarmJobBehaviour(
            self.build.buildqueue_record.specific_build
        )

    def test_getUploadDirLeafCookie_parseable(self):
        # getUploadDirLeaf should return a directory name
        # that is parseable by the upload processor.
        upload_leaf = self.behaviour.getUploadDirLeaf(self.build.build_cookie)
        (job_type, job_id) = parse_build_upload_leaf_name(upload_leaf)
        self.assertEqual(
            (self.build.job_type.name, self.build.id), (job_type, job_id)
        )


class TestVerifySuccessfulBuildMixin:
    """Tests for `IBuildFarmJobBehaviour`'s verifySuccessfulBuild method."""

    layer = ZopelessDatabaseLayer

    def makeBuild(self):
        """Allow classes to override the build with which the test runs."""
        raise NotImplementedError

    def makeUnmodifiableBuild(self):
        """Allow classes to override the build with which the test runs."""
        raise NotImplementedError

    def test_verifySuccessfulBuild_allows_modifiable_suite(self):
        # verifySuccessfulBuild allows uploading to a suite that the archive
        # says is modifiable.
        build = self.makeBuild()
        behaviour = IBuildFarmJobBehaviour(
            build.buildqueue_record.specific_build
        )
        behaviour.verifySuccessfulBuild()

    def test_verifySuccessfulBuild_denies_unmodifiable_suite(self):
        # verifySuccessfulBuild refuses to upload to a suite that the
        # archive says is unmodifiable.
        build = self.makeUnmodifiableBuild()
        behaviour = IBuildFarmJobBehaviour(
            build.buildqueue_record.specific_build
        )
        self.assertRaises(AssertionError, behaviour.verifySuccessfulBuild)


class TestHandleStatusMixin:
    """Tests for `IPackageBuild`s handleStatus method."""

    layer = LaunchpadZopelessLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=30)

    def makeBuild(self):
        """Allow classes to override the build with which the test runs."""
        raise NotImplementedError

    def setUp(self):
        super().setUp()
        self.factory = LaunchpadObjectFactory()
        self.build = self.makeBuild()
        # For the moment, we require a builder for the build so that
        # handleStatus_OK can get a reference to the worker.
        self.builder = self.factory.makeBuilder()
        self.build.buildqueue_record.markAsBuilding(self.builder)
        self.worker = WaitingWorker("BuildStatus.OK")
        self.worker.valid_files["test_file_hash"] = ""
        self.interactor = BuilderInteractor()
        self.behaviour = self.interactor.getBuildBehaviour(
            self.build.buildqueue_record, self.builder, self.worker
        )
        self.addCleanup(shut_down_default_process_pool)

        # We overwrite the buildmaster root to use a temp directory.
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)
        self.upload_root = tempdir
        tmp_builddmaster_root = (
            """
        [builddmaster]
        root: %s
        """
            % self.upload_root
        )
        config.push("tmp_builddmaster_root", tmp_builddmaster_root)

        # We stub out our builds getUploaderCommand() method so
        # we can check whether it was called as well as
        # verifySuccessfulUpload().
        removeSecurityProxy(self.build).verifySuccessfulUpload = FakeMethod(
            result=True
        )

    def assertResultCount(self, count, result):
        self.assertEqual(
            1, len(os.listdir(os.path.join(self.upload_root, result)))
        )

    @defer.inlineCallbacks
    def test_handleStatus_BUILDING(self):
        # If the builder is BUILDING (or any status other than WAITING),
        # then the behaviour calls updateStatus but doesn't do anything
        # else.
        initial_status = self.build.status
        bq_id = self.build.buildqueue_record.id
        worker_status = {"builder_status": "BuilderStatus.BUILDING"}
        removeSecurityProxy(self.build).updateStatus = FakeMethod()
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, worker_status
            )
        self.assertEqual(None, self.build.log)
        self.assertEqual(0, len(os.listdir(self.upload_root)))
        self.assertEqual(
            [
                (
                    (initial_status,),
                    {"builder": self.builder, "worker_status": worker_status},
                )
            ],
            removeSecurityProxy(self.build).updateStatus.calls,
        )
        self.assertEqual(0, len(pop_notifications()), "Notifications received")
        self.assertEqual(
            self.build.buildqueue_record, getUtility(IBuildQueueSet).get(bq_id)
        )

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_OK_normal_file(self):
        # A filemap with plain filenames should not cause a problem.
        # The call to handleStatus will attempt to get the file from
        # the worker resulting in a URL error in this test case.
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.OK",
                    "filemap": {"myfile.py": "test_file_hash"},
                },
            )
        self.assertEqual(BuildStatus.UPLOADING, self.build.status)
        self.assertResultCount(1, "incoming")

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_OK_gathering_status(self):
        # handleStatus sets the build's status to GATHERING while
        # downloading files from the builder.
        def mock_downloadFiles(*args, **kwargs):
            self.assertEqual(BuildStatus.GATHERING, self.build.status)

        self.useFixture(
            MockPatchObject(
                self.behaviour, "_downloadFiles", mock_downloadFiles
            )
        )
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.OK",
                    "filemap": {"myfile.py": "test_file_hash"},
                },
            )
        self.assertEqual(BuildStatus.UPLOADING, self.build.status)

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_OK_absolute_filepath(self):
        # A filemap that tries to write to files outside of the upload
        # directory will not be collected.
        with ExpectedException(
            BuildDaemonError, "Build returned a file named '/tmp/myfile.py'."
        ):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record,
                    {
                        "builder_status": "BuilderStatus.WAITING",
                        "build_status": "BuildStatus.OK",
                        "filemap": {"/tmp/myfile.py": "test_file_hash"},
                    },
                )

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_OK_relative_filepath(self):
        # A filemap that tries to write to files outside of
        # the upload directory will not be collected.
        with ExpectedException(
            BuildDaemonError, "Build returned a file named '../myfile.py'."
        ):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record,
                    {
                        "builder_status": "BuilderStatus.WAITING",
                        "build_status": "BuildStatus.OK",
                        "filemap": {"../myfile.py": "test_file_hash"},
                    },
                )

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_OK_sets_build_log(self):
        # The build log is set during handleStatus.
        self.assertEqual(None, self.build.log)
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.OK",
                    "filemap": {"myfile.py": "test_file_hash"},
                },
            )
        self.assertNotEqual(None, self.build.log)

    @defer.inlineCallbacks
    def _test_handleStatus_WAITING_notifies(self, status):
        # An email notification is sent for a given build status if
        # notifications are allowed for that status.
        expected_notification = (
            status in self.behaviour.ALLOWED_STATUS_NOTIFICATIONS
        )

        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.%s" % status,
                },
            )

        if expected_notification:
            self.assertNotEqual(
                0, len(pop_notifications()), "Notifications received"
            )
        else:
            self.assertEqual(
                0, len(pop_notifications()), "Notifications received"
            )

    def test_handleStatus_WAITING_DEPFAIL_notifies(self):
        return self._test_handleStatus_WAITING_notifies("DEPFAIL")

    def test_handleStatus_WAITING_CHROOTFAIL_notifies(self):
        return self._test_handleStatus_WAITING_notifies("CHROOTFAIL")

    def test_handleStatus_WAITING_PACKAGEFAIL_notifies(self):
        return self._test_handleStatus_WAITING_notifies("PACKAGEFAIL")

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_ABORTED_cancels_cancelling(self):
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.CANCELLING)
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.ABORTED",
                },
            )
        self.assertEqual(0, len(pop_notifications()), "Notifications received")
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_ABORTED_illegal_when_building(self):
        self.builder.vm_host = "fake_vm_host"
        self.behaviour = self.interactor.getBuildBehaviour(
            self.build.buildqueue_record, self.builder, self.worker
        )
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.BUILDING)
            with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: %r" % "ABORTED",
            ):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record,
                    {
                        "builder_status": "BuilderStatus.WAITING",
                        "build_status": "BuildStatus.ABORTED",
                    },
                )

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_ABORTED_cancelling_sets_build_log(self):
        # If a build is intentionally cancelled, the build log is set.
        self.assertEqual(None, self.build.log)
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.CANCELLING)
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.ABORTED",
                },
            )
        self.assertNotEqual(None, self.build.log)

    @defer.inlineCallbacks
    def test_date_finished_set(self):
        # The date finished is updated during handleStatus_OK.
        self.assertEqual(None, self.build.date_finished)
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {
                    "builder_status": "BuilderStatus.WAITING",
                    "build_status": "BuildStatus.OK",
                    "filemap": {"myfile.py": "test_file_hash"},
                },
            )
        self.assertNotEqual(None, self.build.date_finished)

    @defer.inlineCallbacks
    def test_givenback_collection(self):
        with ExpectedException(
            BuildDaemonError,
            "Build returned unexpected status: %r" % "GIVENBACK",
        ):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record,
                    {
                        "builder_status": "BuilderStatus.WAITING",
                        "build_status": "BuildStatus.GIVENBACK",
                    },
                )

    @defer.inlineCallbacks
    def test_builderfail_collection(self):
        with ExpectedException(
            BuildDaemonError,
            "Build returned unexpected status: %r" % "BUILDERFAIL",
        ):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record,
                    {
                        "builder_status": "BuilderStatus.WAITING",
                        "build_status": "BuildStatus.BUILDERFAIL",
                    },
                )

    @defer.inlineCallbacks
    def test_invalid_status_collection(self):
        with ExpectedException(
            BuildDaemonError, "Build returned unexpected status: %r" % "BORKED"
        ):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record,
                    {
                        "builder_status": "BuilderStatus.WAITING",
                        "build_status": "BuildStatus.BORKED",
                    },
                )
