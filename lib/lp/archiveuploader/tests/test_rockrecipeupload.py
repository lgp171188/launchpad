# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `RockRecipeUpload`."""

import os

from storm.store import Store

from lp.archiveuploader.tests.test_uploadprocessor import (
    TestUploadProcessorBase,
)
from lp.archiveuploader.uploadprocessor import UploadHandler, UploadStatusEnum
from lp.buildmaster.enums import BuildStatus
from lp.rocks.interfaces.rockrecipe import ROCK_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.osutils import write_file


class TestRockRecipeUploads(TestUploadProcessorBase):
    """End-to-end tests of rock recipe uploads."""

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

        self.setupBreezy()

        self.switchToAdmin()
        self.build = self.factory.makeRockRecipeBuild(
            distro_arch_series=self.breezy["i386"]
        )
        self.build.updateStatus(BuildStatus.UPLOADING)
        Store.of(self.build).flush()
        self.switchToUploader()
        self.options.context = "buildd"

        self.uploadprocessor = self.getUploadProcessor(
            self.layer.txn, builds=True
        )

    def test_sets_build_and_state_123(self):
        # The upload processor uploads files and sets the correct status.
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu"
        )
        write_file(os.path.join(upload_dir, "foo_0_all.rock"), b"rock")
        write_file(os.path.join(upload_dir, "foo_0_all.manifest"), b"manifest")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build
        )
        result = handler.processRockRecipe(self.log)
        self.assertEqual(
            UploadStatusEnum.ACCEPTED,
            result,
            "Rock upload failed\nGot: %s" % self.log.getLogBuffer(),
        )
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertTrue(self.build.verifySuccessfulUpload())

    def test_requires_rock(self):
        # The upload processor fails if the upload does not contain any
        # .rock files.
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu"
        )
        write_file(os.path.join(upload_dir, "foo_0_all.manifest"), b"manifest")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build
        )
        result = handler.processRockRecipe(self.log)
        self.assertEqual(UploadStatusEnum.REJECTED, result)
        self.assertIn(
            "ERROR Build did not produce any rocks.", self.log.getLogBuffer()
        )
        self.assertFalse(self.build.verifySuccessfulUpload())
