# Copyright 2017-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for internal archive APIs."""

__all__ = [
    "IArchiveAPI",
    "IArchiveApplication",
]

from zope.interface import Interface

from lp.services.webapp.interfaces import ILaunchpadApplication


class IArchiveApplication(ILaunchpadApplication):
    """Archive application root."""


class IArchiveAPI(Interface):
    """The Soyuz archive XML-RPC interface to Launchpad.

    Published at "archive" on the private XML-RPC server.

    PPA frontends use this to check archive authorization tokens.
    """

    def checkArchiveAuthToken(archive_reference, username, password):
        """Check an archive authorization token.

        :param archive_reference: The reference form of the archive to check.
        :param username: The username sent using HTTP Basic Authentication;
            this should either be a `Person.name` or "+" followed by the
            name of a named authorization token.
        :param password: The password sent using HTTP Basic Authentication;
            this should be a corresponding `ArchiveAuthToken.token`.

        :returns: A `NotFound` fault if `archive_reference` does not
            identify an archive or the username does not identify a valid
            token for this archive; an `Unauthorized` fault if the password
            is not equal to the selected token for this archive; otherwise
            None.
        """

    def translatePath(archive_reference, path):
        """Find the librarian URL for a relative path within an archive.

        :param archive_reference: The reference form of the archive to check.
        :param path: The relative path within the archive.  This should not
            begin with a "/" character.

        :return: A `NotFound` fault if `archive_reference` does not identify
            an archive, or the archive's repository format is something
            other than `ArchiveRepositoryFormat.DEBIAN`, or the path does
            not identify a file that exists in this archive; otherwise a
            librarian URL.
        """
