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
            # Check if archive contains .crate files
            with tempfile.TemporaryDirectory() as tmpdir:
                with tarfile.open(craft_path, "r:xz") as tar:
                    tar.extractall(path=tmpdir)

                # Look for .crate files and metadata.yaml
                crate_files = list(Path(tmpdir).rglob("*.crate"))
                metadata_path = Path(tmpdir) / "metadata.yaml"

                if crate_files and metadata_path.exists():
                    # If we found a crate file and metadata, upload it
                    try:
                        metadata = yaml.safe_load(metadata_path.read_text())
                        crate_name = metadata.get("name")
                        crate_version = metadata.get("version")
                        self.logger.debug(
                            "Found crate %s version %s",
                            crate_name,
                            crate_version,
                        )
                    except Exception as e:
                        self.logger.warning(
                            "Failed to parse metadata.yaml: %s", e
                        )

                    crate_path = crate_files[
                        0
                    ]  # Take the first (and should be only) crate file
                    with open(crate_path, "rb") as file:
                        libraryfile = self.librarian.create(
                            os.path.basename(str(crate_path)),
                            os.stat(crate_path).st_size,
                            file,
                            filenameToContentType(str(crate_path)),
                            restricted=build.is_private,
                        )
                    build.addFile(libraryfile)
                else:
                    # If no crate file found, upload the original archive
                    self.logger.debug(
                        "No crate files found, uploading archive"
                    )
                    with open(craft_path, "rb") as file:
                        libraryfile = self.librarian.create(
                            os.path.basename(str(craft_path)),
                            os.stat(craft_path).st_size,
                            file,
                            filenameToContentType(str(craft_path)),
                            restricted=build.is_private,
                        )
                    build.addFile(libraryfile)

        # The master verifies the status to confirm successful upload.
        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)
        self.logger.debug("Finished upload.")
