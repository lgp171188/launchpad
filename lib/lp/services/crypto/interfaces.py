# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface to data encrypted at rest using configured keys."""

__all__ = [
    "CryptoError",
    "IEncryptedContainer",
]

from zope.interface import Attribute, Interface


class CryptoError(Exception):
    pass


class IEncryptedContainer(Interface):
    """Interface to a container that can encrypt and decrypt data."""

    can_encrypt = Attribute(
        "True iff this container has the configuration it needs to encrypt "
        "data."
    )

    def encrypt(data):
        """Encrypt a blob of data to a JSON-serialisable form.

        This includes the public key to ease future key rotation.

        :param data: An unencrypted byte string to encrypt.
        :return: A tuple of (base64-encoded public key, base64-encoded
            encrypted text string).
        :raises RuntimeError: if no public key is configured for this
            container.
        """

    can_decrypt = Attribute(
        "True iff this container has the configuration it needs to decrypt "
        "data."
    )

    def decrypt(data):
        """Decrypt data that was encrypted by L{encrypt}.

        :param data: A tuple of (base64-encoded public key, base64-encoded
            encrypted text string) to decrypt.
        :return: An unencrypted byte string.
        :raises ValueError: if no private key is configured for this container
            that corresponds to the requested public key.
        :raises CryptoError: if decryption failed.
        """
