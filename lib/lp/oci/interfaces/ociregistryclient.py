# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for communication with an OCI registry."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'BlobUploadFailed',
    'IOCIRegistryClient',
    'ManifestUploadFailed',
]

from zope.interface import Interface


class BlobUploadFailed(Exception):
    pass


class ManifestUploadFailed(Exception):
    pass


class IOCIRegistryClient(Interface):
    """Interface for the API provided by an OCI registry."""

    def upload(build):
        """Upload an OCI image to a registry.

        :param ocibuild: The `IOCIRecipeBuild` to upload.
        """
