# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for signing keys stored at the signing service."""

__all__ = [
    "IArchiveSigningKey",
    "IArchiveSigningKeySet",
    "ISigningKey",
    "ISigningKeySet",
]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Bytes, Choice, Datetime, Int, Text

from lp import _
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.services.signing.enums import SigningKeyType
from lp.soyuz.interfaces.archive import IArchive


class ISigningKey(Interface):
    """A key registered to sign uploaded files"""

    id = Int(title=_("ID"), required=True, readonly=True)

    key_type = Choice(
        title=_("The signing key type (UEFI, KMOD, etc)."),
        required=True,
        readonly=True,
        vocabulary=SigningKeyType,
    )

    fingerprint = Text(
        title=_("Fingerprint of the key"), required=True, readonly=True
    )

    public_key = Bytes(
        title=_("Public key binary content"), required=False, readonly=True
    )

    date_created = Datetime(
        title=_("When this key was created"), required=True, readonly=True
    )

    def addAuthorization(client_name):
        """Authorize another client to use this key.

        :param client_name: The name of the client to authorize.
        """


class ISigningKeySet(Interface):
    """Interface to deal with the collection of signing keys"""

    def get(key_type, fingerprint):
        """Get a signing key by key type and fingerprint.

        :param key_type: A `SigningKeyType`.
        :param fingerprint: The key's fingerprint.
        :return: A `SigningKey`, or None.
        """

    def generate(
        key_type, description, openpgp_key_algorithm=None, length=None
    ):
        """Generates a new signing key on lp-signing and stores it in LP's
        database.

        :param key_type: One of the SigningKeyType enum's value
        :param description: The description associated with this key
        :param openpgp_key_algorithm: One of `OpenPGPKeyAlgorithm` (required
            if key_type is SigningKeyType.OPENPGP)
        :param length: The key length (required if key_type is
            SigningKeyType.OPENPGP)
        :return: The SigningKey object associated with the newly created
                 key at lp-signing
        """

    def inject(key_type, private_key, public_key, description, created_at):
        """Inject an existing key pair on lp-signing and stores it in LP's
        database.

        :param key_type: One of the SigningKeyType enum's value.
        :param private_key: The private key to be injected into lp-signing
        :param public_key: The public key to be injected into lp-signing
        :param description: The description of the key being injected
        :param created_at: The datetime when the key was originally created.
        :return: The SigningKey object associated with the newly created
                 key at lp-signing
        """

    def sign(signing_keys, message, message_name, mode=None):
        """Sign the given message using the given keys

        :param signing_keys: A list of one or more signing keys to sign
            the given message with. If more than one signing key is provided,
            all signing keys must be of the same type.
        :param message: The message to be signed.
        :param message_name: A name for the message being signed.
        :param mode: A `SigningMode` specifying how the message is to be
            signed.  Defaults to `SigningMode.ATTACHED` for UEFI and FIT
            keys, and `SigningMode.DETACHED` for other key types.
        """


class IArchiveSigningKey(Interface):
    """Which signing key should be used by a specific archive"""

    id = Int(title=_("ID"), required=True, readonly=True)

    archive = Reference(
        IArchive,
        title=_("Archive"),
        required=True,
        readonly=True,
        description=_("The archive that owns this key."),
    )

    earliest_distro_series = Reference(
        IDistroSeries,
        title=_("Distro series"),
        required=False,
        readonly=True,
        description=_("The minimum series that uses this key, if any."),
    )

    key_type = Choice(
        title=_("The signing key type (UEFI, KMOD, etc)."),
        required=True,
        readonly=True,
        vocabulary=SigningKeyType,
    )

    signing_key = Reference(
        ISigningKey,
        title=_("Signing key"),
        required=True,
        readonly=True,
        description=_("Which signing key should be used by this archive"),
    )

    def destroySelf():
        """Removes the ArchiveSigningKey from the database."""


class IArchiveSigningKeySet(Interface):
    """Management class to deal with ArchiveSigningKey objects"""

    def create(archive, earliest_distro_series, signing_key):
        """Creates a new ArchiveSigningKey for archive/distro_series.

        :return: A tuple like (db_object:ArchiveSigningKey, created:boolean)
                 with the ArchiveSigningKey and True if it was created (
                 False if it was updated).
        """

    def get(key_type, archive, distro_series, exact_match=False):
        """Get the most suitable ArchiveSigningKey for a given context.

        :param exact_match: If True, returns the ArchiveSigningKey matching
            exactly the given key_type, archive and distro_series. If False,
            gets the best match.
        :return: The most suitable key, or None.
        """

    def getOpenPGPSigningKeysForArchive(archive):
        """Find and return the OpenPGP signing keys for the given archive.

        :param archive: The archive to get the OpenPGP signing keys for.
        :return: A list of matching signing keys or an empty list.
        """

    def getByArchiveAndFingerprint(archive, fingerprint):
        """Get ArchiveSigningKey by archive and fingerprint.

        :param archive: The archive associated with the ArchiveSigningKey.
        :param fingerprint: The signing key's fingerprint.
        :return: The matching ArchiveSigningKey or None.
        """

    def get4096BitRSASigningKey(archive):
        """Get the 4096-bit RSA SigningKey for the given archive.

        :param archive: The Archive to search.
        :return: The matching SigningKey or None.
        """

    def getSigningKey(key_type, archive, distro_series, exact_match=False):
        """Get the most suitable SigningKey for a given context.

        :param exact_match: If True, returns the SigningKey matching exactly
            the given key_type, archive and distro_series. If False, gets
            the best match.
        :return: The most suitable key, or None.
        """

    def generate(key_type, description, archive, earliest_distro_series=None):
        """Generate a new key on signing service, and save it to db.

        :param key_type: One of the SigningKeyType enum's value
        :param description: The description associated with this key
        :param archive: The package Archive that should be associated with
                        this key
        :param earliest_distro_series: (optional) The minimum distro series
                                       that should use the generated key.
        :returns: The generated ArchiveSigningKey
        """

    def inject(
        key_type,
        private_key,
        public_key,
        description,
        created_at,
        archive,
        earliest_distro_series=None,
    ):
        """Injects an existing key on signing service, and saves it to db.

        :param key_type: One of the SigningKeyType enum's value
        :param private_key: The private key to be injected into lp-signing
        :param public_key: The public key to be injected into lp-signing
        :param description: The description of the key being injected
        :param created_at: The datetime when the key was originally created.
        :param archive: The package Archive that should be associated with
                        this key
        :param earliest_distro_series: (optional) The minimum distro series
                                       that should use the generated key.
        :returns: The generated ArchiveSigningKey
        """
