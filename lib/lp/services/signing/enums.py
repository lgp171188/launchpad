# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enum for signing keys management
"""

__metaclass__ = type

__all__ = [
    'SigningKeyType',
    'SigningMode',
    ]

from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    EnumeratedType,
    Item,
    )


class SigningKeyType(DBEnumeratedType):
    """Available key types on lp-signing service
    """
    UEFI = DBItem(0, """
        UEFI key
        
        UEFI signing key
        """)

    KMOD = DBItem(1, """
        KMOD key
        
        KMOD signing key
        """)

    OPAL = DBItem(2, """
        OPAL key
        
        OPAL signing key
        """)

    SIPL = DBItem(3, """
        SIPL key
        
        SIPL signing key
        """)

    FIT  = DBItem(4, """
        FIT key
        
        FIT signing key
        """)


class SigningMode(EnumeratedType):
    """Archive file signing mode."""

    ATTACHED = Item("Attached signature")
    DETACHED = Item("Detached signature")
    CLEAR = Item("Cleartext signature")
