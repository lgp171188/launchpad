# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a craft recipe upload."""

__all__ = [
    "CraftRecipeUpload",
]

import os
import tarfile
import tempfile
from pathlib import Path

import yaml
from zope.component import getUtility

from lp.archiveuploader.utils import UploadError
from lp.buildmaster.enums import BuildStatus
from lp.services.helpers import filenameToContentType
from lp.services.librarian.interfaces import ILibraryFileAliasSet


class CraftRecipeUpload:
    # XXX: ruinedyourlife 03-10-2024
    # This could be refactored into a single generic class used for all
    # recipe uploaders.
    """A craft recipe upload."""

    def __init__(self, upload_path, logger):
        """Create a `CraftRecipeUpload`.

        :param upload_path: A directory containing files to upload.
        :param logger: The logger to be used.
        """
        self.upload_path = upload_path
        self.logger = logger

        self.librarian = getUtility(ILibraryFileAliasSet)

    def process(self, build):
        """Process this upload, loading it into the database."""
        self.logger.debug("Beginning processing.")

        # Find all .tar.xz files in subdirectories
        upload_path = Path(self.upload_path)
        craft_paths = list(upload_path.rglob("*.tar.xz"))

        # Skip files directly in upload_path
        craft_paths = [p for p in craft_paths if p.parent != upload_path]

        if not craft_paths:
            raise UploadError("Build did not produce any craft files.")

        for craft_path in sorted(craft_paths):
            # Extract and process .crate files from archive
            self._process_rust_archive(build, str(craft_path))

        # The master verifies the status to confirm successful upload.
        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)
        self.logger.debug("Finished upload.")

    def _process_rust_archive(self, build, archive_path):
        """Process a .tar.xz archive that may contain .crate files."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with tarfile.open(archive_path, "r:xz") as tar:
                tar.extractall(path=tmpdir)

            # Read metadata.yaml for crate info
            metadata_path = Path(tmpdir) / "metadata.yaml"
            if metadata_path.exists():
                try:
                    metadata = yaml.safe_load(metadata_path.read_text())
                    # XXX: ruinedyourlife 2024-12-06
                    # We will need this later to give the crate a name and
                    # version to artifactory. This is a placeholder for now,
                    # which will be changed when we find a way to send that
                    # information to artifactory.
                    _ = metadata.get("name")
                    _ = metadata.get("version")
                except Exception as e:
                    self.logger.warning("Failed to parse metadata.yaml: %s", e)
            else:
                self.logger.debug(
                    "No metadata.yaml found at %s", metadata_path
                )

            # Look for .crate files in extracted contents
            for crate_path in Path(tmpdir).rglob("*.crate"):
                self._process_crate_file(build, str(crate_path))

    def _process_crate_file(self, build, crate_path):
        """Process a single .crate file."""
        with open(crate_path, "rb") as file:
            libraryfile = self.librarian.create(
                os.path.basename(crate_path),
                os.stat(crate_path).st_size,
                file,
                filenameToContentType(crate_path),
                restricted=build.is_private,
            )
        build.addFile(libraryfile)
