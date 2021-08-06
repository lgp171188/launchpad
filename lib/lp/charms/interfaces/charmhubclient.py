# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for communication with Charmhub."""

__all__ = [
    "BadExchangeMacaroonsResponse",
    "BadRequestPackageUploadResponse",
    "ICharmhubClient",
    ]

import http.client

from lazr.restful.declarations import error_status
from zope.interface import Interface


class CharmhubError(Exception):

    def __init__(self, message="", detail=None, can_retry=False):
        super().__init__(message)
        self.message = message
        self.detail = detail
        self.can_retry = can_retry


@error_status(http.client.INTERNAL_SERVER_ERROR)
class BadRequestPackageUploadResponse(CharmhubError):
    pass


class BadExchangeMacaroonsResponse(CharmhubError):
    pass


class ICharmhubClient(Interface):
    """Interface for the API provided by Charmhub."""

    def requestPackageUploadPermission(package_name):
        """Request permission from Charmhub to upload builds of a charm.

        We need the following permissions: `package-manage-revisions` (to
        upload new blobs) and `package-manage-releases` (to release
        revisions).

        The returned macaroon will include a third-party caveat that must be
        discharged by Candid.  This method does not acquire that discharge;
        it must be acquired separately.

        :param package_name: The registered name of this charm on Charmhub.
        :return: A serialized macaroon appropriate for uploading builds of
            this charm.
        """

    def exchangeMacaroons(root_macaroon_raw, unbound_discharge_macaroon_raw):
        """Exchange root+discharge macaroons for a new Charmhub-only macaroon.

        :param root_macaroon: A serialized root macaroon from Charmhub.
        :param unbound_discharge_macaroon: A corresponding serialized
            unbound discharge macaroon from Candid.
        :return: A serialized macaroon from Charmhub with no third-party
            Candid caveat.
        """
