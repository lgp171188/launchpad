# Copyright 2016-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for communication with the snap store."""

__metaclass__ = type
__all__ = [
    'BadRefreshResponse',
    'BadRequestPackageUploadResponse',
    'BadScanStatusResponse',
    'BadSearchResponse',
    'ISnapStoreClient',
    'NeedsRefreshResponse',
    'ScanFailedResponse',
    'SnapStoreError',
    'UnauthorizedUploadResponse',
    'UploadFailedResponse',
    'UploadNotScannedYetResponse',
    ]

from lazr.restful.declarations import error_status
from six.moves import http_client
from zope.interface import Interface


class SnapStoreError(Exception):

    def __init__(
            self, message="", detail=None, messages=None, can_retry=False):
        super(SnapStoreError, self).__init__(message)
        self.message = message
        self.detail = detail
        self.messages = messages
        self.can_retry = can_retry


@error_status(http_client.INTERNAL_SERVER_ERROR)
class BadRequestPackageUploadResponse(SnapStoreError):
    pass


class UploadFailedResponse(SnapStoreError):
    pass


class BadRefreshResponse(SnapStoreError):
    pass


class NeedsRefreshResponse(SnapStoreError):
    pass


class UnauthorizedUploadResponse(SnapStoreError):
    pass


class BadScanStatusResponse(SnapStoreError):
    pass


class UploadNotScannedYetResponse(SnapStoreError):
    pass


class ScanFailedResponse(SnapStoreError):
    pass


class BadSearchResponse(SnapStoreError):
    pass


class ISnapStoreClient(Interface):
    """Interface for the API provided by the snap store."""

    def requestPackageUploadPermission(snappy_series, snap_name):
        """Request permission from the store to upload builds of a snap.

        The returned macaroon will include a third-party caveat that must be
        discharged by the login service.  This method does not acquire that
        discharge; it must be acquired separately.

        :param snappy_series: The `ISnappySeries` in which this snap should
            be published on the store.
        :param snap_name: The registered name of this snap on the store.
        :return: A serialized macaroon appropriate for uploading builds of
            this snap.
        """

    def uploadFile(lfa):
        """Upload a file to the store.

        :param lfa: The `ILibraryFileAlias` to upload.
        :return: An upload ID.
        :raises UploadFailedResponse: if uploading the file to the store
            failed.
        """

    def push(snapbuild, upload_id):
        """Push a snap build to the store.

        :param snapbuild: The `ISnapBuild` to upload.
        :param upload_id: An upload ID previously returned by `uploadFile`.
        :return: A URL to poll for upload processing status.
        :raises BadRefreshResponse: if the authorising macaroons need to be
            refreshed, but attempting to do so fails.
        :raises UnauthorizedUploadResponse: if the user who authorised this
            upload is not themselves authorised to upload the snap in
            question.
        :raises UploadFailedResponse: if uploading the build to the store
            failed.
        """

    def refreshDischargeMacaroon(snap):
        """Refresh a snap's discharge macaroon.

        :param snap: An `ISnap` whose discharge macaroon needs to be refreshed.
        """

    def refreshIfNecessary(snap, f, *args, **kwargs):
        """Call a function, refreshing macaroons if necessary.

        If the called function raises `NeedsRefreshResponse`, then this
        calls `refreshDischargeMacaroon` and tries again.

        :param snap: An `ISnap` whose discharge macaroon may need to be
            refreshed.
        :param f: The function to call.
        :param args: Positional arguments to `f`.
        :param kwargs: Keyword arguments to `f`.
        """

    def checkStatus(status_url):
        """Poll the store once for upload scan status.

        :param status_url: A URL as returned by `upload`.
        :raises UploadNotScannedYetResponse: if the store has not yet
            scanned the upload.
        :raises BadScanStatusResponse: if the store failed to scan the
            upload.
        :return: A tuple of (`url`, `revision`), where `url` is a URL on the
            store with further information about this upload, and `revision`
            is the store revision number for the upload or None.
        """

    def listChannels():
        """Fetch the current list of channels from the store.

        :raises BadSearchResponse: if the attempt to fetch the list of
            channels from the store fails.
        :return: A list of dictionaries, one per channel, each of which
            contains at least "name" and "display_name" keys.
        """
