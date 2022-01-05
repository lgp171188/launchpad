# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A container for data encrypted at rest using configured keys."""

__all__ = [
    'NaClEncryptedContainerBase',
    ]

import base64

from nacl.exceptions import CryptoError as NaClCryptoError
from nacl.public import (
    PrivateKey,
    PublicKey,
    SealedBox,
    )
from zope.interface import implementer

from lp.services.crypto.interfaces import (
    CryptoError,
    IEncryptedContainer,
    )


@implementer(IEncryptedContainer)
class NaClEncryptedContainerBase:
    """A container that can encrypt and decrypt data using NaCl.

    See `IEncryptedContainer`.
    """

    @property
    def public_key_bytes(self):
        """The serialised public key as a byte string.

        Concrete implementations must provide this.
        """
        raise NotImplementedError

    @property
    def public_key(self):
        """The public key as a L{nacl.public.PublicKey}."""
        if self.public_key_bytes is not None:
            try:
                return PublicKey(self.public_key_bytes)
            except NaClCryptoError as e:
                raise CryptoError(str(e)) from e
        else:
            return None

    @property
    def can_encrypt(self):
        try:
            return self.public_key is not None
        except CryptoError:
            return False

    def encrypt(self, data):
        """See `IEncryptedContainer`."""
        if self.public_key is None:
            raise RuntimeError("No public key configured")
        try:
            data_encrypted = SealedBox(self.public_key).encrypt(data)
        except NaClCryptoError as e:
            raise CryptoError(str(e)) from e
        return (
            base64.b64encode(self.public_key_bytes).decode("UTF-8"),
            base64.b64encode(data_encrypted).decode("UTF-8"))

    @property
    def private_key_bytes(self):
        """The serialised private key as a byte string.

        Concrete implementations must provide this.
        """
        raise NotImplementedError

    @property
    def private_key(self):
        """The private key as a L{nacl.public.PrivateKey}."""
        if self.private_key_bytes is not None:
            try:
                return PrivateKey(self.private_key_bytes)
            except NaClCryptoError as e:
                raise CryptoError(str(e)) from e
        else:
            return None

    @property
    def can_decrypt(self):
        try:
            return self.private_key is not None
        except CryptoError:
            return False

    def decrypt(self, data):
        """See `IEncryptedContainer`."""
        public_key, encrypted = data
        try:
            public_key_bytes = base64.b64decode(public_key.encode("UTF-8"))
            encrypted_bytes = base64.b64decode(encrypted.encode("UTF-8"))
        except TypeError as e:
            raise CryptoError(str(e)) from e
        if public_key_bytes != self.public_key_bytes:
            raise ValueError(
                "Public key %r does not match configured public key %r" %
                (public_key_bytes, self.public_key_bytes))
        if self.private_key is None:
            raise ValueError("No private key configured")
        try:
            return SealedBox(self.private_key).decrypt(encrypted_bytes)
        except NaClCryptoError as e:
            raise CryptoError(str(e)) from e
