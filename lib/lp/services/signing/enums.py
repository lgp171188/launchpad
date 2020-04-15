# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enums for signing keys management
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
    """Available key types on lp-signing service.

    These items should be kept in sync with
    lp-signing:lp-signing/lp_signing/enums.py (specially the numbers) to
    avoid confusion when reading values from different databases.
    """
    UEFI = DBItem(1, """
        UEFI

        A signing key for UEFI Secure Boot images.
        """)

    KMOD = DBItem(2, """
        Kmod

        A signing key for kernel modules.
        """)

    OPAL = DBItem(3, """
        OPAL

        A signing key for OPAL kernel images.
        """)

    SIPL = DBItem(4, """
        SIPL

        A signing key for Secure Initial Program Load kernel images.
        """)

    FIT = DBItem(5, """
        FIT

        A signing key for U-Boot Flat Image Tree images.
        """)


class SigningMode(EnumeratedType):
    """Archive file signing mode."""

    ATTACHED = Item("Attached signature")
    DETACHED = Item("Detached signature")
    CLEAR = Item("Cleartext signature")
