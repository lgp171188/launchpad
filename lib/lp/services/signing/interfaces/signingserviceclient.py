# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for signing keys stored at the signing service."""

__all__ = [
    'ISigningServiceClient',
    ]

from zope.interface import (
    Attribute,
    Interface,
    )

from lp import _


class ISigningServiceClient(Interface):
    service_public_key = Attribute(_("The public key of signing service."))
    private_key = Attribute(_("This client's private key."))

    def getNonce():
        """Get nonce, to be used when sending messages.
        """

    def generate(key_type, description,
                 openpgp_key_algorithm=None, length=None):
        """Generate a key to be used when signing.

        :param key_type: One of available key types at SigningKeyType
        :param description: String description of the generated key
        :param openpgp_key_algorithm: One of `OpenPGPKeyAlgorithm` (required
            if key_type is SigningKeyType.OPENPGP)
        :param length: The key length (required if key_type is
            SigningKeyType.OPENPGP)
        :return: A dict with 'fingerprint' (str) and 'public-key' (bytes)
        """

    def sign(key_type, fingerprint, message_name, message, mode):
        """Sign the given message using the specified key_type and a
        pre-generated fingerprint (see `generate` method).

        :param key_type: One of the key types from SigningKeyType enum
        :param fingerprint: The fingerprint of the signing key, generated by
                            the `generate` method
        :param message_name: A description of the message being signed
        :param message: The message to be signed
        :param mode: SigningMode.ATTACHED or SigningMode.DETACHED
        :return: A dict with 'public-key' and 'signed-message'
        """

    def inject(key_type, private_key, public_key, description, created_at):
        """Injects an existing key on lp-signing service.

        :param key_type: One of `SigningKeyType` items.
        :param private_key: The private key content, in bytes.
        :param public_key: The public key content, in bytes.
        :param description: The description of this key.
        :param created_at: datetime of when the key was created.
        :return: A dict with 'fingerprint'
        """

    def addAuthorization(key_type, fingerprint, client_name):
        """Authorize another client to use a key.

        :param key_type: One of `SigningKeyType`.
        :param fingerprint: The fingerprint of the signing key.
        :param client_name: The name of the client to authorize.
        """
