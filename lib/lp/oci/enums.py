# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enums for the OCI app."""

__all__ = [
    "OCIRecipeBuildRequestStatus",
]

from lazr.enum import EnumeratedType, Item


class OCIRecipeBuildRequestStatus(EnumeratedType):
    """The status of a request to build an OCI recipe."""

    PENDING = Item(
        """
        Pending

        This OCI recipe build request is pending.
        """
    )

    FAILED = Item(
        """
        Failed

        This OCI recipe build request failed.
        """
    )

    COMPLETED = Item(
        """
        Completed

        This OCI recipe build request completed successfully.
        """
    )
