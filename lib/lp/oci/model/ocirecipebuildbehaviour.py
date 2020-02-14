# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An `IBuildFarmJobBehaviour` for `OCIRecipeBuild`.

Dispatches OCI image build jobs to build-farm slaves.
"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeBuildBehaviour',
    ]


import json
import os

from twisted.internet import defer
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.buildmaster.enums import BuildBaseImageType
from lp.buildmaster.interfaces.builder import BuildDaemonError
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.model.buildfarmjobbehaviour import (
    BuildFarmJobBehaviourBase,
    )
from lp.services.librarian.utils import copy_and_close


@implementer(IBuildFarmJobBehaviour)
class OCIRecipeBuildBehaviour(BuildFarmJobBehaviourBase):

    builder_type = "oci"
    image_types = [BuildBaseImageType.LXD, BuildBaseImageType.CHROOT]

    # These attributes are defined in `IOCIBuildFarmJobBehaviour`,
    # but are not used in this implementation.
    distro_arch_series = None

    def _ensureFilePath(self, file_name, file_path, upload_path):
        # If the evaluated output file name is not within our
        # upload path, then we don't try to copy this or any
        # subsequent files.
        if not os.path.normpath(file_path).startswith(upload_path + '/'):
            raise BuildDaemonError(
                "Build returned a file named '%s'." % file_name)

    def _fetchIntermediaryFile(self, name, filemap, upload_path):
        file_hash = filemap[name]
        file_path = os.path.join(upload_path, name)
        self._ensureFilePath(name, file_path, upload_path)
        self._slave.getFile(file_hash, file_path)

        with open(file_path, 'r') as file_fp:
            contents = json.load(file_fp)
        return contents

    def _extractLayerFiles(self, upload_path, section, config, digests, files):
        # These are different sets of ids, in the same order
        # layer_id is the filename, diff_id is the internal (docker) id
        for diff_id in config['rootfs']['diff_ids']:
            layer_id = digests[diff_id]['layer_id']
            # This is in the form '<id>/layer.tar', we only need the first
            layer_filename = "{}.tar.gz".format(layer_id.split('/')[0])
            digest = digests[diff_id]['digest']
            try:
                _, librarian_layer_file, _ = self.build.getLayerFileByDigest(
                    digest)
            except NotFoundError:
                files.add(layer_filename)
                continue
            layer_path = os.path.join(upload_path, layer_filename)
            librarian_layer_file.open()
            with open(layer_path, 'wb') as layer_fp:
                copy_and_close(librarian_layer_file, layer_fp)

    def _convertToRetrievableFile(self, upload_path, file_name, filemap):
        file_path = os.path.join(upload_path, file_name)
        self._ensureFilePath(file_name, file_path, upload_path)
        return (filemap[file_name], file_path)

    @defer.inlineCallbacks
    def _downloadFiles(self, filemap, upload_path, logger):
        """Download required artifact files."""
        # We don't want to download all of the files that have been created,
        # just the ones that are mentioned in the manifest and config.

        manifest = self._fetchIntermediaryFile(
            'manifest.json', filemap, upload_path)
        digests = self._fetchIntermediaryFile(
            'digests.json', filemap, upload_path)

        files = set()
        for section in manifest:
            config = self._fetchIntermediaryFile(
                section['Config'], filemap, upload_path)
            self._extractLayerFiles(
                upload_path, section, config, digests, files)

        files_to_download = [
            self._convertToRetrievableFile(upload_path, filename, filemap)
            for filename in files]
        yield self._slave.getFiles(files_to_download, logger=logger)

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        # The implementation in BuildFarmJobBehaviourBase checks whether the
        # target suite is modifiable in the target archive.  However, an
        # `OCIRecipeBuild` does not use an archive in this manner.
        return True
