# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Enums for signing keys management."""

__all__ = [
    "OpenPGPKeyAlgorithm",
    "SigningKeyType",
    "SigningMode",
]

from lazr.enum import DBEnumeratedType, DBItem, EnumeratedType, Item


class SigningKeyType(DBEnumeratedType):
    """Available key types on lp-signing service.

    These items should be kept in sync with
    lp-signing:lp-signing/lp_signing/enums.py (specially the numbers) to
    avoid confusion when reading values from different databases.
    """

    UEFI = DBItem(
        1,
        """
        UEFI

        A signing key for UEFI Secure Boot images.
        """,
    )

    KMOD = DBItem(
        2,
        """
        Kmod

        A signing key for kernel modules.
        """,
    )

    OPAL = DBItem(
        3,
        """
        OPAL

        A signing key for OPAL kernel images.
        """,
    )

    SIPL = DBItem(
        4,
        """
        SIPL

        A signing key for Secure Initial Program Load kernel images.
        """,
    )

    FIT = DBItem(
        5,
        """
        FIT

        A signing key for U-Boot Flat Image Tree images.
        """,
    )

    OPENPGP = DBItem(
        6,
        """
        OpenPGP

        An OpenPGP signing key.
        """,
    )

    CV2_KERNEL = DBItem(
        7,
        """
        CV2 Kernel

        An Ambarella CV2 kernel signing key.
        """,
    )

    ANDROID_KERNEL = DBItem(
        8,
        """
        Android Kernel

        An Android kernel signing key.
        """,
    )


class OpenPGPKeyAlgorithm(EnumeratedType):
    RSA = Item(
        """
        RSA

        A Rivest-Shamir-Adleman key.
        """
    )


class SigningMode(EnumeratedType):
    """Archive file signing mode."""

    ATTACHED = Item("Attached signature")
    DETACHED = Item("Detached signature")
    CLEAR = Item("Cleartext signature")
