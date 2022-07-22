# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations of the XML-RPC APIs for Soyuz archives."""

__all__ = [
    "ArchiveAPI",
]

import logging

from pymacaroons import Macaroon
from zope.component import getUtility
from zope.interface import implementer
from zope.interface.interfaces import ComponentLookupError
from zope.security.proxy import removeSecurityProxy

from lp.services.macaroons.interfaces import NO_USER, IMacaroonIssuer
from lp.services.webapp import LaunchpadXMLRPCView
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.archiveapi import IArchiveAPI
from lp.soyuz.interfaces.archiveauthtoken import IArchiveAuthTokenSet
from lp.xmlrpc import faults
from lp.xmlrpc.helpers import return_fault

log = logging.getLogger(__name__)


BUILDD_USER_NAME = "buildd"


@implementer(IArchiveAPI)
class ArchiveAPI(LaunchpadXMLRPCView):
    """See `IArchiveAPI`."""

    def _verifyMacaroon(self, archive, password):
        try:
            macaroon = Macaroon.deserialize(password)
        # XXX cjwatson 2021-03-31: Restrict exceptions once
        # https://github.com/ecordell/pymacaroons/issues/50 is fixed.
        except Exception:
            return False
        try:
            issuer = getUtility(IMacaroonIssuer, macaroon.identifier)
        except ComponentLookupError:
            return False
        verified = issuer.verifyMacaroon(macaroon, archive)
        if verified and verified.user != NO_USER:
            # We currently only permit verifying standalone macaroons, not
            # ones issued on behalf of a particular user.
            return False
        return verified

    @return_fault
    def _checkArchiveAuthToken(self, archive_reference, username, password):
        archive = getUtility(IArchiveSet).getByReference(archive_reference)
        if archive is None:
            log.info("%s@%s: No archive found", username, archive_reference)
            raise faults.NotFound(
                message="No archive found for '%s'." % archive_reference
            )
        archive = removeSecurityProxy(archive)
        token_set = getUtility(IArchiveAuthTokenSet)

        # If the password is a serialized macaroon for the buildd user, then
        # try macaroon authentication.
        if username == BUILDD_USER_NAME:
            if self._verifyMacaroon(archive, password):
                # Success.
                log.info("%s@%s: Authorized", username, archive_reference)
                return
            else:
                log.info(
                    "%s@%s: Macaroon verification failed",
                    username,
                    archive_reference,
                )
                raise faults.Unauthorized()

        # Fall back to checking archive auth tokens.
        if username.startswith("+"):
            token = token_set.getActiveNamedTokenForArchive(
                archive, username[1:]
            )
        else:
            token = token_set.getActiveTokenForArchiveAndPersonName(
                archive, username
            )
        if token is None:
            log.info("%s@%s: No valid tokens", username, archive_reference)
            raise faults.NotFound(
                message="No valid tokens for '%s' in '%s'."
                % (username, archive_reference)
            )
        secret = removeSecurityProxy(token).token
        if password != secret:
            log.info(
                "%s@%s: Password does not match", username, archive_reference
            )
            raise faults.Unauthorized()
        else:
            log.info("%s@%s: Authorized", username, archive_reference)

    def checkArchiveAuthToken(self, archive_reference, username, password):
        """See `IArchiveAPI`."""
        # This thunk exists because you can't use a decorated function as
        # the implementation of a method exported over XML-RPC.
        return self._checkArchiveAuthToken(
            archive_reference, username, password
        )
