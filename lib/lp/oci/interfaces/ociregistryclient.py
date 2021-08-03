# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for communication with an OCI registry."""

__metaclass__ = type
__all__ = [
    'BlobUploadFailed',
    'IOCIRegistryClient',
    'ManifestUploadFailed',
    'MultipleOCIRegistryError',
    'OCIRegistryError',
]

from zope.interface import Interface


class OCIRegistryError(Exception):
    """An error returned by an OCI registry."""

    def __init__(self, summary, errors):
        super(OCIRegistryError, self).__init__(summary)
        self.errors = errors


class MultipleOCIRegistryError(OCIRegistryError):
    def __init__(self, exceptions):
        self.exceptions = exceptions

    def __str__(self):
        return " / ".join(str(i) for i in self.exceptions)

    @property
    def errors(self):
        return [i.errors for i in self.exceptions
                if isinstance(i, OCIRegistryError)]


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

    def uploadManifestList(build_request):
        """Upload the "fat manifest" which aggregates all platforms built."""
