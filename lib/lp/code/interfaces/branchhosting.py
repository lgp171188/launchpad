# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for communication with the Loggerhead API."""

__all__ = [
    "IBranchHostingClient",
    "InvalidRevisionException",
]

from zope.interface import Interface


class InvalidRevisionException(Exception):
    """An exception thrown when a revision ID is not valid"""


class IBranchHostingClient(Interface):
    """Interface for the internal API provided by Loggerhead."""

    def getDiff(branch_id, new, old=None, context_lines=None, logger=None):
        """Get the diff between two revisions.

        :param branch_id: The ID of the branch.
        :param new: The new revno or revision ID.
        :param old: The old revno or revision ID.  Defaults to the parent
            revision of `new`.
        :param context_lines: Include this number of lines of context around
            each hunk.
        :param logger: An optional logger.
        :raises ValueError: if `old` or `new` is ill-formed.
        :raises BranchHostingFault: if the API returned an error.
        :return: The diff between `old` and `new` as a byte string.
        """

    def getBlob(branch_id, path, rev=None, logger=None):
        """Get a blob by file name from a branch.

        :param branch_id: The ID of the branch.
        :param path: The relative path of the file.
        :param rev: An optional revno or revision ID.  Defaults to 'head:'.
        :param logger: An optional logger.
        :raises ValueError: if `rev` is ill-formed.
        :raises BranchFileNotFound: if the directory does not exist.
        :raises BranchHostingFault: if the API returned some other error.
        :return: The blob content as a byte string.
        """
