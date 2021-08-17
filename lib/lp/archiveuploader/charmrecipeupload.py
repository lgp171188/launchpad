# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a charm recipe upload."""

__metaclass__ = type
__all__ = [
    "CharmRecipeUpload",
    ]

import os

from zope.component import getUtility

from lp.archiveuploader.utils import UploadError
from lp.buildmaster.enums import BuildStatus
from lp.services.helpers import filenameToContentType
from lp.services.librarian.interfaces import ILibraryFileAliasSet


class CharmRecipeUpload:
    """A charm recipe upload."""

    def __init__(self, upload_path, logger):
        """Create a `CharmRecipeUpload`.

        :param upload_path: A directory containing files to upload.
        :param logger: The logger to be used.
        """
        self.upload_path = upload_path
        self.logger = logger

        self.librarian = getUtility(ILibraryFileAliasSet)

    def process(self, build):
        """Process this upload, loading it into the database."""
        self.logger.debug("Beginning processing.")

        found_charm = False
        charm_paths = []
        for dirpath, _, filenames in os.walk(self.upload_path):
            if dirpath == self.upload_path:
                # All relevant files will be in a subdirectory.
                continue
            for charm_file in sorted(filenames):
                if charm_file.endswith(".charm"):
                    found_charm = True
                charm_paths.append(os.path.join(dirpath, charm_file))

        if not found_charm:
            raise UploadError("Build did not produce any charms.")

        for charm_path in charm_paths:
            libraryfile = self.librarian.create(
                os.path.basename(charm_path), os.stat(charm_path).st_size,
                open(charm_path, "rb"),
                filenameToContentType(charm_path),
                restricted=build.is_private)
            build.addFile(libraryfile)

        # The master verifies the status to confirm successful upload.
        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)

        self.logger.debug("Finished upload.")
