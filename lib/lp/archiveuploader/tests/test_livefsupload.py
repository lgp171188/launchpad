# Copyright 2014-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test uploads of LiveFSBuilds."""

import os

from storm.store import Store
from zope.component import getUtility

from lp.archiveuploader.tests.test_uploadprocessor import (
    TestUploadProcessorBase,
    )
from lp.archiveuploader.uploadprocessor import (
    UploadHandler,
    UploadStatusEnum,
    )
from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.features.testing import FeatureFixture
from lp.services.osutils import write_file
from lp.soyuz.interfaces.livefs import LIVEFS_FEATURE_FLAG
from lp.soyuz.interfaces.livefsbuild import ILiveFSBuildSet


class TestLiveFSBuildUploads(TestUploadProcessorBase):
    """End-to-end tests of LiveFS build uploads."""

    def setUp(self):
        super().setUp()

        self.useFixture(FeatureFixture({LIVEFS_FEATURE_FLAG: "on"}))
        self.setupBreezy()

        self.switchToAdmin()
        self.livefs = self.factory.makeLiveFS()
        self.build = getUtility(ILiveFSBuildSet).new(
            requester=self.livefs.owner, livefs=self.livefs,
            archive=self.factory.makeArchive(
                distribution=self.ubuntu, owner=self.livefs.owner),
            distro_arch_series=self.breezy["i386"],
            pocket=PackagePublishingPocket.RELEASE)
        self.build.updateStatus(BuildStatus.UPLOADING)
        Store.of(self.build).flush()
        self.switchToUploader()
        self.options.context = "buildd"

        self.uploadprocessor = self.getUploadProcessor(
            self.layer.txn, builds=True)

    def test_sets_build_and_state(self):
        # The upload processor uploads files and sets the correct status.
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu")
        write_file(os.path.join(upload_dir, "ubuntu.squashfs"), b"squashfs")
        write_file(os.path.join(upload_dir, "ubuntu.manifest"), b"manifest")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build)
        result = handler.processLiveFS(self.log)
        self.assertEqual(
            UploadStatusEnum.ACCEPTED, result,
            "LiveFS upload failed\nGot: %s" % self.log.getLogBuffer())
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertTrue(self.build.verifySuccessfulUpload())

    def test_empty_file(self):
        # The upload processor can cope with empty build artifacts.  (LiveFS
        # is quite a general method and can include a variety of artifacts:
        # in particular it often includes an additional log file which can
        # be empty.)
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu")
        write_file(os.path.join(upload_dir, "livecd.magic-proxy.log"), b"")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build)
        result = handler.processLiveFS(self.log)
        self.assertEqual(
            UploadStatusEnum.ACCEPTED, result,
            "LiveFS upload failed\nGot: %s" % self.log.getLogBuffer())
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertTrue(self.build.verifySuccessfulUpload())
