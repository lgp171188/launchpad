# Copyright 2015-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `OCIRecipeBuildBehavior`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

import json
import os
import shutil
import tempfile

from testtools import ExpectedException
from twisted.internet import defer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interactor import BuilderInteractor
from lp.buildmaster.interfaces.builder import BuildDaemonError
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.tests.mock_slaves import WaitingSlave
from lp.buildmaster.tests.test_buildfarmjobbehaviour import (
    TestGetUploadMethodsMixin,
    )
from lp.oci.model.ocirecipebuildbehaviour import OCIRecipeBuildBehaviour
from lp.services.config import config
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications


class MakeOCIBuildMixin:

    def makeBuild(self):
        build = self.factory.makeOCIRecipeBuild()
        build.queueBuild()
        return build

    def makeUnmodifiableBuild(self):
        build = self.factory.makeOCIRecipeBuild()
        build.distro_arch_series = 'failed'
        build.queueBuild()
        return build


class TestOCIBuildBehaviour(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_provides_interface(self):
        # OCIRecipeBuildBehaviour provides IBuildFarmJobBehaviour.
        job = OCIRecipeBuildBehaviour(None)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_adapts_IOCIRecipeBuild(self):
        # IBuildFarmJobBehaviour adapts an IOCIRecipeBuild.
        build = self.factory.makeOCIRecipeBuild()
        job = IBuildFarmJobBehaviour(build)
        self.assertProvides(job, IBuildFarmJobBehaviour)


class TestHandleStatusForOCIRecipeBuild(MakeOCIBuildMixin,
                                        TestCaseWithFactory):
    # This is mostly copied from TestHandleStatusMixin, however
    # we can't use all of those tests, due to the way OCIRecipeBuildBehaviour
    # parses the file contents, rather than just retrieving all that are
    # available. There's also some differences in the filemap handling, as
    # we need a much more complex filemap here.

    layer = LaunchpadZopelessLayer

    def _createTestFile(self, name, content, hash):
        path = os.path.join(self.test_files_dir, name)
        with open(path, 'wb') as fp:
            fp.write(content)
        self.slave.valid_files[hash] = path

    def setUp(self):
        super(TestHandleStatusForOCIRecipeBuild, self).setUp()
        self.factory = LaunchpadObjectFactory()
        self.build = self.makeBuild()
        # For the moment, we require a builder for the build so that
        # handleStatus_OK can get a reference to the slave.
        self.builder = self.factory.makeBuilder()
        self.build.buildqueue_record.markAsBuilding(self.builder)
        self.slave = WaitingSlave('BuildStatus.OK')
        self.slave.valid_files['test_file_hash'] = ''
        self.interactor = BuilderInteractor()
        self.behaviour = self.interactor.getBuildBehaviour(
            self.build.buildqueue_record, self.builder, self.slave)

        # We overwrite the buildmaster root to use a temp directory.
        tempdir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tempdir)
        self.upload_root = tempdir
        self.pushConfig('builddmaster', root=self.upload_root)

        # We stub out our builds getUploaderCommand() method so
        # we can check whether it was called as well as
        # verifySuccessfulUpload().
        removeSecurityProxy(self.build).verifySuccessfulUpload = FakeMethod(
            result=True)

        digests = {
            "diff_id_1": {
                "digest": "digest_1",
                "source": "test/base_1",
                "layer_id": "layer_1"
            },
            "diff_id_2": {
                "digest": "digest_2",
                "source": "",
                "layer_id": "layer_2"
            }
        }

        self.test_files_dir = tempfile.mkdtemp()
        self._createTestFile('buildlog', '', 'buildlog')
        self._createTestFile(
            'manifest.json',
            '[{"Config": "config_file_1.json", '
            '"Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]',
            'manifest_hash')
        self._createTestFile(
            'digests.json',
            json.dumps(digests),
            'digests_hash')
        self._createTestFile(
            'config_file_1.json',
            '{"rootfs": {"diff_ids": ["diff_id_1", "diff_id_2"]}}',
            'config_1_hash')
        self._createTestFile(
            'layer_2.tar.gz',
            '',
            'layer_2_hash'
        )

        self.filemap = {
            'manifest.json': 'manifest_hash',
            'digests.json': 'digests_hash',
            'config_file_1.json': 'config_1_hash',
            'layer_1.tar.gz': 'layer_1_hash',
            'layer_2.tar.gz': 'layer_2_hash'
        }
        self.factory.makeOCIFile(
            build=self.build, layer_file_digest=u'digest_1',
            content="retrieved from librarian")

    def assertResultCount(self, count, result):
        self.assertEqual(
            1, len(os.listdir(os.path.join(self.upload_root, result))))

    @defer.inlineCallbacks
    def test_handleStatus_OK_normal_image(self):
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, 'OK',
                {'filemap': self.filemap})
        self.assertEqual(
            ['buildlog', 'manifest_hash', 'digests_hash', 'config_1_hash',
             'layer_2_hash'],
            self.slave._got_file_record)
        # This hash should not appear as it is already in the librarian
        self.assertNotIn('layer_1_hash', self.slave._got_file_record)
        self.assertEqual(BuildStatus.UPLOADING, self.build.status)
        self.assertResultCount(1, "incoming")

        # layer_1 should have been retrieved from the librarian
        layer_1_path = os.path.join(
            self.upload_root,
            "incoming",
            self.behaviour.getUploadDirLeaf(self.build.build_cookie),
            str(self.build.archive.id),
            self.build.distribution.name,
            "layer_1.tar.gz"
        )
        with open(layer_1_path, 'rb') as layer_1_fp:
            contents = layer_1_fp.read()
            self.assertEqual(contents, b'retrieved from librarian')

    @defer.inlineCallbacks
    def test_handleStatus_OK_absolute_filepath(self):

        self._createTestFile(
            'manifest.json',
            '[{"Config": "/notvalid/config_file_1.json", '
            '"Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]',
            'manifest_hash')

        self.filemap['/notvalid/config_file_1.json'] = 'config_1_hash'

        # A filemap that tries to write to files outside of the upload
        # directory will not be collected.
        with ExpectedException(
                BuildDaemonError,
                "Build returned a file named "
                "'/notvalid/config_file_1.json'."):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, 'OK',
                    {'filemap': self.filemap})

    @defer.inlineCallbacks
    def test_handleStatus_OK_relative_filepath(self):

        self._createTestFile(
            'manifest.json',
            '[{"Config": "../config_file_1.json", '
            '"Layers": ["layer_1/layer.tar", "layer_2/layer.tar"]}]',
            'manifest_hash')

        self.filemap['../config_file_1.json'] = 'config_1_hash'
        # A filemap that tries to write to files outside of
        # the upload directory will not be collected.
        with ExpectedException(
                BuildDaemonError,
                "Build returned a file named '../config_file_1.json'."):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, 'OK',
                    {'filemap': self.filemap})

    @defer.inlineCallbacks
    def test_handleStatus_OK_sets_build_log(self):
        # The build log is set during handleStatus.
        self.assertEqual(None, self.build.log)
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, 'OK',
                {'filemap': self.filemap})
        self.assertNotEqual(None, self.build.log)

    @defer.inlineCallbacks
    def test_handleStatus_ABORTED_cancels_cancelling(self):
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.CANCELLING)
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, "ABORTED", {})
        self.assertEqual(0, len(pop_notifications()), "Notifications received")
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)

    @defer.inlineCallbacks
    def test_handleStatus_ABORTED_illegal_when_building(self):
        self.builder.vm_host = "fake_vm_host"
        self.behaviour = self.interactor.getBuildBehaviour(
            self.build.buildqueue_record, self.builder, self.slave)
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.BUILDING)
            with ExpectedException(
                    BuildDaemonError,
                    "Build returned unexpected status: u'ABORTED'"):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "ABORTED", {})

    @defer.inlineCallbacks
    def test_handleStatus_ABORTED_cancelling_sets_build_log(self):
        # If a build is intentionally cancelled, the build log is set.
        self.assertEqual(None, self.build.log)
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.CANCELLING)
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, "ABORTED", {})
        self.assertNotEqual(None, self.build.log)

    @defer.inlineCallbacks
    def test_date_finished_set(self):
        # The date finished is updated during handleStatus_OK.
        self.assertEqual(None, self.build.date_finished)
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record, 'OK',
                {'filemap': self.filemap})
        self.assertNotEqual(None, self.build.date_finished)

    @defer.inlineCallbacks
    def test_givenback_collection(self):
        with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: u'GIVENBACK'"):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "GIVENBACK", {})

    @defer.inlineCallbacks
    def test_builderfail_collection(self):
        with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: u'BUILDERFAIL'"):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "BUILDERFAIL", {})

    @defer.inlineCallbacks
    def test_invalid_status_collection(self):
        with ExpectedException(
                BuildDaemonError,
                "Build returned unexpected status: u'BORKED'"):
            with dbuser(config.builddmaster.dbuser):
                yield self.behaviour.handleStatus(
                    self.build.buildqueue_record, "BORKED", {})


class TestGetUploadMethodsForOCIRecipeBuild(
    MakeOCIBuildMixin, TestGetUploadMethodsMixin, TestCaseWithFactory):
    """IPackageBuild.getUpload-related methods work with OCI recipe builds."""
