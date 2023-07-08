# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for encrypted data containers."""

from nacl.public import PrivateKey

from lp.services.crypto.interfaces import CryptoError
from lp.services.crypto.model import NaClEncryptedContainerBase
from lp.testing import TestCase
from lp.testing.layers import ZopelessLayer


class FakeEncryptedContainer(NaClEncryptedContainerBase):
    def __init__(self, public_key_bytes, private_key_bytes=None):
        self._public_key_bytes = public_key_bytes
        self._private_key_bytes = private_key_bytes

    @property
    def public_key_bytes(self):
        return self._public_key_bytes

    @property
    def private_key_bytes(self):
        return self._private_key_bytes


class TestNaClEncryptedContainerBase(TestCase):
    layer = ZopelessLayer

    def test_public_key_valid(self):
        public_key = PrivateKey.generate().public_key
        container = FakeEncryptedContainer(bytes(public_key))
        self.assertEqual(public_key, container.public_key)
        self.assertTrue(container.can_encrypt)

    def test_public_key_invalid(self):
        container = FakeEncryptedContainer(b"nonsense")
        self.assertRaises(CryptoError, getattr, container, "public_key")
        self.assertFalse(container.can_encrypt)

    def test_public_key_unset(self):
        container = FakeEncryptedContainer(None)
        self.assertIsNone(container.public_key)
        self.assertFalse(container.can_encrypt)

    def test_encrypt_without_private_key(self):
        # Encryption only requires the public key, not the private key.
        public_key = PrivateKey.generate().public_key
        container = FakeEncryptedContainer(bytes(public_key))
        self.assertIsNotNone(container.encrypt(b"plaintext"))

    def test_private_key_valid(self):
        private_key = PrivateKey.generate()
        container = FakeEncryptedContainer(
            bytes(private_key.public_key), bytes(private_key)
        )
        self.assertEqual(private_key, container.private_key)
        self.assertTrue(container.can_decrypt)

    def test_private_key_invalid(self):
        public_key = PrivateKey.generate().public_key
        container = FakeEncryptedContainer(bytes(public_key), b"nonsense")
        self.assertRaises(CryptoError, getattr, container, "private_key")
        self.assertFalse(container.can_decrypt)

    def test_private_key_unset(self):
        public_key = PrivateKey.generate().public_key
        container = FakeEncryptedContainer(bytes(public_key), None)
        self.assertIsNone(container.private_key)
        self.assertFalse(container.can_decrypt)

    def test_encrypt_decrypt(self):
        private_key = PrivateKey.generate()
        container = FakeEncryptedContainer(
            bytes(private_key.public_key), bytes(private_key)
        )
        self.assertEqual(
            b"plaintext", container.decrypt(container.encrypt(b"plaintext"))
        )
