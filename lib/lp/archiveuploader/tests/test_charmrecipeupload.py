# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `CharmRecipeUpload`."""

__metaclass__ = type

import os

from pymacaroons import Macaroon
from storm.store import Store

from lp.archiveuploader.tests.test_uploadprocessor import (
    TestUploadProcessorBase,
    )
from lp.archiveuploader.uploadprocessor import (
    UploadHandler,
    UploadStatusEnum,
    )
from lp.buildmaster.enums import BuildStatus
from lp.charms.interfaces.charmrecipe import CHARM_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.osutils import write_file


class TestCharmRecipeUploads(TestUploadProcessorBase):
    """End-to-end tests of charm recipe uploads."""

    def setUp(self):
        super(TestCharmRecipeUploads, self).setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

        self.setupBreezy()

        self.switchToAdmin()
        self.build = self.factory.makeCharmRecipeBuild(
            distro_arch_series=self.breezy["i386"])
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
        write_file(os.path.join(upload_dir, "foo_0_all.charm"), b"charm")
        write_file(
            os.path.join(upload_dir, "foo_0_all.manifest"), b"manifest")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build)
        result = handler.processCharmRecipe(self.log)
        self.assertEqual(
            UploadStatusEnum.ACCEPTED, result,
            "Charm upload failed\nGot: %s" % self.log.getLogBuffer())
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertTrue(self.build.verifySuccessfulUpload())

    def test_requires_charm(self):
        # The upload processor fails if the upload does not contain any
        # .charm files.
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu")
        write_file(
            os.path.join(upload_dir, "foo_0_all.manifest"), b"manifest")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build)
        result = handler.processCharmRecipe(self.log)
        self.assertEqual(UploadStatusEnum.REJECTED, result)
        self.assertIn(
            "ERROR Build did not produce any charms.", self.log.getLogBuffer())
        self.assertFalse(self.build.verifySuccessfulUpload())

    def test_triggers_store_uploads(self):
        # The upload processor triggers store uploads if appropriate.
        self.pushConfig("charms", charmhub_url="http://charmhub.example/")
        self.switchToAdmin()
        self.build.recipe.store_name = self.build.recipe.name
        self.build.recipe.store_upload = True
        # CharmRecipe.can_upload_to_store only checks whether
        # "exchanged_encrypted" is present, so don't bother setting up
        # encryption keys here.
        self.build.recipe.store_secrets = {
            "exchanged_encrypted": Macaroon().serialize()}
        Store.of(self.build.recipe).flush()
        self.switchToUploader()
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu")
        write_file(os.path.join(upload_dir, "foo_0_all.charm"), b"charm")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build)
        result = handler.processCharmRecipe(self.log)
        self.assertEqual(
            UploadStatusEnum.ACCEPTED, result,
            "Charm upload failed\nGot: %s" % self.log.getLogBuffer())
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertTrue(self.build.verifySuccessfulUpload())
        self.assertEqual(1, len(list(self.build.store_upload_jobs)))
