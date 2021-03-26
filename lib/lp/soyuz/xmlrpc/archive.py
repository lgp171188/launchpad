# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations of the XML-RPC APIs for Soyuz archives."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'ArchiveAPI',
    ]

from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

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

    @return_fault
    def _checkArchiveAuthToken(self, archive_reference, username, password):
        archive = getUtility(IArchiveSet).getByReference(archive_reference)
        if archive is None:
            raise faults.NotFound(
                message="No archive found for '%s'." % archive_reference)
        archive = removeSecurityProxy(archive)
        token_set = getUtility(IArchiveAuthTokenSet)
        if username == BUILDD_USER_NAME:
            secret = archive.buildd_secret
        else:
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
