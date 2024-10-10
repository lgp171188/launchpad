# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a craft recipe upload."""

__all__ = [
    "CraftRecipeUpload",
]

import os

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

        found_craft = False
        craft_paths = []
        for dirpath, _, filenames in os.walk(self.upload_path):
            if dirpath == self.upload_path:
                # All relevant files will be in a subdirectory.
                continue
            for craft_file in sorted(filenames):
                if craft_file.endswith(".tar.xz"):
                    found_craft = True
                craft_paths.append(os.path.join(dirpath, craft_file))

        if not found_craft:
            raise UploadError("Build did not produce any craft files.")

        for craft_path in craft_paths:
            with open(craft_path, "rb") as file:
                libraryfile = self.librarian.create(
                    os.path.basename(craft_path),
                    os.stat(craft_path).st_size,
                    file,
                    filenameToContentType(craft_path),
                    restricted=build.is_private,
                )
            build.addFile(libraryfile)

        # The master verifies the status to confirm successful upload.
        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)

        self.logger.debug("Finished upload.")
