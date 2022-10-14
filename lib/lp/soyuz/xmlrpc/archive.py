# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations of the XML-RPC APIs for Soyuz archives."""

__all__ = [
    "ArchiveAPI",
]

import logging
from pathlib import PurePath
from typing import Optional, Union
from xmlrpc.client import Fault

from pymacaroons import Macaroon
from zope.component import getUtility
from zope.interface import implementer
from zope.interface.interfaces import ComponentLookupError
from zope.security.proxy import removeSecurityProxy

from lp.services.macaroons.interfaces import NO_USER, IMacaroonIssuer
from lp.services.webapp import LaunchpadXMLRPCView
from lp.soyuz.enums import ArchiveRepositoryFormat
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.archiveapi import IArchiveAPI
from lp.soyuz.interfaces.archiveauthtoken import IArchiveAuthTokenSet
from lp.soyuz.interfaces.archivefile import IArchiveFileSet
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

    def _translatePathByHash(
        self, archive_reference: str, archive, path: PurePath
    ) -> Optional[str]:
        suite = path.parts[1]
        checksum_type = path.parts[-2]
        checksum = path.parts[-1]
        # We only publish by-hash files for a single checksum type at
        # present.  See `lp.archivepublisher.publishing`.
        if checksum_type != "SHA256":
            return None

        archive_file = (
            getUtility(IArchiveFileSet)
            .getByArchive(
                archive=archive,
                container="release:%s" % suite,
                path_parent="/".join(path.parts[:-3]),
                sha256=checksum,
            )
            .any()
        )
        if archive_file is None:
            return None

        log.info(
            "%s: %s (by-hash) -> LFA %d",
            archive_reference,
            path.as_posix(),
            archive_file.library_file.id,
        )
        return archive_file.library_file.getURL(include_token=True)

    def _translatePathNonPool(
        self, archive_reference: str, archive, path: PurePath
    ) -> Optional[str]:
        archive_file = (
            getUtility(IArchiveFileSet)
            .getByArchive(archive=archive, path=path.as_posix())
            .one()
        )
        if archive_file is None:
            return None

        log.info(
            "%s: %s (non-pool) -> LFA %d",
            archive_reference,
            path.as_posix(),
            archive_file.library_file.id,
        )
        return archive_file.library_file.getURL(include_token=True)

    def _translatePathPool(
        self, archive_reference: str, archive, path: PurePath
    ) -> Optional[str]:
        lfa = archive.getPoolFileByPath(path)
        if lfa is None:
            return None

        log.info(
            "%s: %s (pool) -> LFA %d",
            archive_reference,
            path.as_posix(),
            lfa.id,
        )
        return lfa.getURL(include_token=True)

    @return_fault
    def _translatePath(self, archive_reference: str, path: PurePath) -> str:
        archive = getUtility(IArchiveSet).getByReference(archive_reference)
        if archive is None:
            log.info("%s: No archive found", archive_reference)
            raise faults.NotFound(
                message="No archive found for '%s'." % archive_reference
            )
        archive = removeSecurityProxy(archive)
        if archive.repository_format != ArchiveRepositoryFormat.DEBIAN:
            log.info(
                "%s: Repository format is %s",
                archive_reference,
                archive.repository_format,
            )
            raise faults.NotFound(
                message="Can't translate paths in '%s' with format %s."
                % (archive_reference, archive.repository_format)
            )

        # Consider by-hash index files.
        if path.parts[0] == "dists" and path.parts[2:][-3:-2] == ("by-hash",):
            url = self._translatePathByHash(archive_reference, archive, path)
            if url is not None:
                return url

        # Consider other non-pool files.
        if path.parts[0] != "pool":
            url = self._translatePathNonPool(archive_reference, archive, path)
            if url is not None:
                return url
            log.info("%s: %s not found", archive_reference, path.as_posix())
            raise faults.NotFound(
                message="'%s' not found in '%s'."
                % (path.as_posix(), archive_reference)
            )

        # Consider pool files.
        url = self._translatePathPool(archive_reference, archive, path)
        if url is not None:
            return url
        log.info("%s: %s not found", archive_reference, path.as_posix())
        raise faults.NotFound(
            message="'%s' not found in '%s'."
            % (path.as_posix(), archive_reference)
        )

    def translatePath(
        self, archive_reference: str, path: str
    ) -> Union[str, Fault]:
        """See `IArchiveAPI`."""
        # This thunk exists because you can't use a decorated function as
        # the implementation of a method exported over XML-RPC.
        return self._translatePath(archive_reference, PurePath(path))
