# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for communication with an OCI registry."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'BlobUploadFailed',
    'IOCIRegistryClient',
    'ManifestUploadFailed',
    'OCIRegistryError',
]

from zope.interface import Interface


class OCIRegistryError(Exception):
    """An error returned by an OCI registry."""

    def __init__(self, summary, errors):
        super(OCIRegistryError, self).__init__(summary)
        self.errors = errors


class BlobUploadFailed(OCIRegistryError):
    pass


class ManifestUploadFailed(OCIRegistryError):
    pass


class IOCIRegistryClient(Interface):
    """Interface for the API provided by an OCI registry."""

    def upload(build):
        """Upload an OCI image to a registry.

        :param build: The `IOCIRecipeBuild` to upload.
        """
