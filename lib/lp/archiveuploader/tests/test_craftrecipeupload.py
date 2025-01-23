# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `CraftRecipeUpload`."""

import os
import tarfile
import tempfile

import yaml
from storm.store import Store
from zope.security.proxy import removeSecurityProxy

from lp.archiveuploader.tests.test_uploadprocessor import (
    TestUploadProcessorBase,
)
from lp.archiveuploader.uploadprocessor import UploadHandler, UploadStatusEnum
from lp.buildmaster.enums import BuildStatus
from lp.crafts.interfaces.craftrecipe import CRAFT_RECIPE_ALLOW_CREATE
from lp.services.features.testing import FeatureFixture
from lp.services.osutils import write_file


class TestCraftRecipeUploads(TestUploadProcessorBase):
    """End-to-end tests of craft recipe uploads."""

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

        self.setupBreezy()

        self.switchToAdmin()
        self.build = self.factory.makeCraftRecipeBuild(
            distro_arch_series=self.breezy["i386"]
        )
        self.build.updateStatus(BuildStatus.UPLOADING)
        Store.of(self.build).flush()
        self.switchToUploader()
        self.options.context = "buildd"

        self.uploadprocessor = self.getUploadProcessor(
            self.layer.txn, builds=True
        )

    def _createArchiveWithCrate(
        self, upload_dir, crate_name="test-crate", crate_version="0.1.0"
    ):
        """Helper to create a tar.xz archive containing a crate & metadata."""
        # Create a temporary directory to build our archive
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create metadata.yaml
            metadata = {
                "name": crate_name,
                "version": crate_version,
            }
            metadata_path = os.path.join(tmpdir, "metadata.yaml")
            with open(metadata_path, "w") as f:
                yaml.safe_dump(metadata, f)

            # Create dummy crate file
            crate_path = os.path.join(
                tmpdir, f"{crate_name}-{crate_version}.crate"
            )
            with open(crate_path, "wb") as f:
                f.write(b"dummy crate contents")

            # Create tar.xz archive
            archive_path = os.path.join(upload_dir, "output.tar.xz")
            with tarfile.open(archive_path, "w:xz") as tar:
                tar.add(metadata_path, arcname="metadata.yaml")
                tar.add(crate_path, arcname=os.path.basename(crate_path))

            return archive_path

    def test_sets_build_and_state(self):
        # The upload processor uploads files and sets the correct status.
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu"
        )
        os.makedirs(upload_dir, exist_ok=True)
        self._createArchiveWithCrate(upload_dir)

        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build
        )
        result = handler.processCraftRecipe(self.log)
        self.assertEqual(
            UploadStatusEnum.ACCEPTED,
            result,
            "Craft upload failed\nGot: %s" % self.log.getLogBuffer(),
        )
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        self.assertTrue(self.build.verifySuccessfulUpload())

        # Verify that the crate file was properly extracted and stored
        build = removeSecurityProxy(self.build)
        files = list(build.getFiles())
        self.assertEqual(1, len(files))
        stored_file = files[0][1]
        self.assertTrue(stored_file.filename.endswith(".crate"))

    def test_processes_crate_from_archive(self):
        """Test extracting/processing crates within .tar.xz archives."""
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu"
        )
        os.makedirs(upload_dir, exist_ok=True)

        # Create archive with specific crate name and version
        crate_name = "test-crate"
        crate_version = "0.2.0"
        self._createArchiveWithCrate(upload_dir, crate_name, crate_version)

        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build
        )
        result = handler.processCraftRecipe(self.log)

        # Verify upload succeeded
        self.assertEqual(UploadStatusEnum.ACCEPTED, result)
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)

        # Verify the crate file was properly stored
        build = removeSecurityProxy(self.build)
        files = list(build.getFiles())
        self.assertEqual(1, len(files))
        stored_file = files[0][1]
        expected_filename = f"{crate_name}-{crate_version}.crate"
        self.assertEqual(expected_filename, stored_file.filename)

    def test_requires_craft(self):
        # The upload processor fails if the upload does not contain any
        # .craft files.
        self.assertFalse(self.build.verifySuccessfulUpload())
        upload_dir = os.path.join(
            self.incoming_folder, "test", str(self.build.id), "ubuntu"
        )
        write_file(os.path.join(upload_dir, "foo_0_all.manifest"), b"manifest")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor, self.incoming_folder, "test", self.build
        )
        result = handler.processCraftRecipe(self.log)
        self.assertEqual(UploadStatusEnum.REJECTED, result)
        self.assertIn(
            "ERROR Build did not produce any craft files.",
            self.log.getLogBuffer(),
        )
        self.assertFalse(self.build.verifySuccessfulUpload())
