# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enum for archive publisher
"""

__metaclass__ = type
__all__ = [
    'PackagePublishingPocket',
    ]

from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    )

from lazr.enum import DBEnumeratedType


class SigningKeyType(DBEnumeratedType):
    RELEASE = DBItem(0, """
        Release

        The package versions that were published
        when the distribution release was made.
        """)