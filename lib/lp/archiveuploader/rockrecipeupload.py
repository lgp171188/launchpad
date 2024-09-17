# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a rock recipe upload."""

__all__ = [
    "RockRecipeUpload",
]

import os

from zope.component import getUtility

from lp.archiveuploader.utils import UploadError
from lp.buildmaster.enums import BuildStatus
from lp.services.helpers import filenameToContentType
from lp.services.librarian.interfaces import ILibraryFileAliasSet


class RockRecipeUpload:
    """A rock recipe upload."""

    def __init__(self, upload_path, logger):
        """Create a `RockRecipeUpload`.

        :param upload_path: A directory containing files to upload.
        :param logger: The logger to be used.
        """
        self.upload_path = upload_path
        self.logger = logger

        self.librarian = getUtility(ILibraryFileAliasSet)

    def process(self, build):
        """Process this upload, loading it into the database."""
        self.logger.debug("Beginning processing.")

        found_rock = False
        rock_paths = []
        for dirpath, _, filenames in os.walk(self.upload_path):
            if dirpath == self.upload_path:
                # All relevant files will be in a subdirectory.
                continue
            for rock_file in sorted(filenames):
                if rock_file.endswith(".rock"):
                    found_rock = True
                rock_paths.append(os.path.join(dirpath, rock_file))

        if not found_rock:
            raise UploadError("Build did not produce any rocks.")

        for rock_path in rock_paths:
            libraryfile = self.librarian.create(
                os.path.basename(rock_path),
                os.stat(rock_path).st_size,
                open(rock_path, "rb"),
                filenameToContentType(rock_path),
                restricted=build.is_private,
            )
            build.addFile(libraryfile)

        # The master verifies the status to confirm successful upload.
        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)

        self.logger.debug("Finished upload.")
