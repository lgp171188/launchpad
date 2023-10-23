# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Upload OCI build artifacts to the librarian."""

__all__ = ["OCIRecipeUpload"]


import json
import os

from zope.component import getUtility

from lp.archiveuploader.utils import UploadError
from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipebuild import IOCIFileSet
from lp.services.helpers import filenameToContentType
from lp.services.librarian.interfaces import ILibraryFileAliasSet


class OCIRecipeUpload:
    """An OCI image upload."""

    def __init__(self, upload_path, logger):
        """Create a `OCIRecipeUpload`.

        :param upload_path: A directory containing files to upload.
        :param logger: The logger to be used.
        """
        self.upload_path = upload_path
        self.logger = logger

        self.librarian = getUtility(ILibraryFileAliasSet)

    def process(self, build):
        """Process this upload, loading it into the database."""
        self.logger.debug("Beginning processing.")

        # Find digest file
        for dirpath, _, filenames in os.walk(self.upload_path):
            if dirpath == self.upload_path:
                # All relevant files will be in a subdirectory.
                continue
            if "digests.json" not in filenames:
                continue
            # Open the digest file
            digest_path = os.path.join(dirpath, "digests.json")
            self.logger.debug("Digest path: {}".format(digest_path))
            with open(digest_path) as digest_fp:
                digests = json.load(digest_fp)

            # Foreach id in digest file, find matching layer
            for single_digest in digests:
                for data in single_digest.values():
                    digest = data["digest"]
                    layer_id = data["layer_id"]
                    layer_path = os.path.join(
                        dirpath, "{}.tar.gz".format(layer_id)
                    )
                    self.logger.debug("Layer path: {}".format(layer_path))
                    # If the file is already in the librarian,
                    # we can just reuse it.
                    existing_file = getUtility(IOCIFileSet).getByLayerDigest(
                        digest
                    )
                    # XXX 2020-05-14 twom This will need to respect restricted
                    # when we do private builds.
                    if existing_file:
                        build.addFile(
                            existing_file.library_file,
                            layer_file_digest=digest,
                        )
                        continue
                    if not os.path.exists(layer_path):
                        raise UploadError(
                            "Missing layer file: {}.".format(layer_id)
                        )
                    # Upload layer
                    libraryfile = self.librarian.create(
                        os.path.basename(layer_path),
                        os.stat(layer_path).st_size,
                        open(layer_path, "rb"),
                        filenameToContentType(layer_path),
                        restricted=build.is_private,
                    )
                    build.addFile(libraryfile, layer_file_digest=digest)
            # Upload all json files
            for filename in filenames:
                if filename.endswith(".json"):
                    file_path = os.path.join(dirpath, filename)
                    self.logger.debug("JSON file: {}".format(file_path))
                    libraryfile = self.librarian.create(
                        os.path.basename(file_path),
                        os.stat(file_path).st_size,
                        open(file_path, "rb"),
                        filenameToContentType(file_path),
                        restricted=build.is_private,
                    )
                    # This doesn't have a digest as it's not a layer file.
                    build.addFile(libraryfile, layer_file_digest=None)
            # We've found digest, we can stop now
            break
        else:
            # If we get here, we've not got a digests.json,
            # something has gone wrong
            raise UploadError("Build did not produce a digests.json.")

        # The master verifies the status to confirm successful upload.
        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)

        self.logger.debug("Finished upload.")
