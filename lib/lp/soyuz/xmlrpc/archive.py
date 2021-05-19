# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations of the XML-RPC APIs for Soyuz archives."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'ArchiveAPI',
    ]

from pymacaroons import Macaroon
from zope.component import (
    ComponentLookupError,
    getUtility,
    )
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.services.macaroons.interfaces import (
    IMacaroonIssuer,
    NO_USER,
    )
from lp.services.webapp import LaunchpadXMLRPCView
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.archiveapi import IArchiveAPI
from lp.soyuz.interfaces.archiveauthtoken import IArchiveAuthTokenSet
from lp.xmlrpc import faults
from lp.xmlrpc.helpers import return_fault


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
            raise faults.NotFound(
                message="No archive found for '%s'." % archive_reference)
        archive = removeSecurityProxy(archive)
        token_set = getUtility(IArchiveAuthTokenSet)

        # If the password is a serialized macaroon for the buildd user, then
        # try macaroon authentication.
        if username == BUILDD_USER_NAME:
            if self._verifyMacaroon(archive, password):
                # Success.
                return
            else:
                raise faults.Unauthorized()

        # Fall back to checking archive auth tokens.
        if username.startswith("+"):
            token = token_set.getActiveNamedTokenForArchive(
                archive, username[1:])
        else:
            token = token_set.getActiveTokenForArchiveAndPersonName(
                archive, username)
        if token is None:
            raise faults.NotFound(
                message="No valid tokens for '%s' in '%s'." % (
                    username, archive_reference))
        secret = removeSecurityProxy(token).token
        if password != secret:
            raise faults.Unauthorized()

    def checkArchiveAuthToken(self, archive_reference, username, password):
        """See `IArchiveAPI`."""
        # This thunk exists because you can't use a decorated function as
        # the implementation of a method exported over XML-RPC.
        return self._checkArchiveAuthToken(
            archive_reference, username, password)
