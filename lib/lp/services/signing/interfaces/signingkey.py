# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for signing keys stored at the signing service."""

__metaclass__ = type

__all__ = [
    'IArchiveSigningKey',
    'IArchiveSigningKeySet',
    'ISigningKey',
    'ISigningKeySet',
]

from lazr.restful.fields import Reference
from zope.interface.interface import Interface
from zope.schema import (
    Bytes,
    Choice,
    Datetime,
    Int,
    Text,
    )

from lp import _
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.services.signing.enums import SigningKeyType
from lp.soyuz.interfaces.archive import IArchive


class ISigningKey(Interface):
    """A key registered to sign uploaded files"""

    id = Int(title=_('ID'), required=True, readonly=True)

    key_type = Choice(
        title=_("The signing key type (UEFI, KMOD, etc)."),
        required=True, readonly=True, vocabulary=SigningKeyType)

    fingerprint = Text(
        title=_("Fingerprint of the key"), required=True, readonly=True)

    public_key = Bytes(
        title=_("Public key binary content"), required=False,
        readonly=True)

    date_created = Datetime(
        title=_('When this key was created'), required=True, readonly=True)

    def sign(message, message_name):
        """Sign the given message using this key

        :param message: The message to be signed.
        :param message_name: A name for the message being signed.
        """


class ISigningKeySet(Interface):
    """Interface to deal with the collection of signing keys
    """

    def generate(key_type, description):
        """Generates a new signing key on lp-signing and stores it in LP's
        database.

        :param key_type: One of the SigningKeyType enum's value
        :param description: The description associated with this key
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


class IArchiveSigningKey(Interface):
    """Which signing key should be used by a specific archive"""

    id = Int(title=_('ID'), required=True, readonly=True)

    archive = Reference(
        IArchive, title=_("Archive"), required=True, readonly=True,
        description=_("The archive that owns this key."))

    earliest_distro_series = Reference(
        IDistroSeries, title=_("Distro series"), required=False, readonly=True,
        description=_("The minimum series that uses this key, if any."))

    key_type = Choice(
        title=_("The signing key type (UEFI, KMOD, etc)."),
        required=True, readonly=True, vocabulary=SigningKeyType)

    signing_key = Reference(
        ISigningKey, title=_("Signing key"), required=True, readonly=True,
        description=_("Which signing key should be used by this archive"))


class IArchiveSigningKeySet(Interface):
    """Management class to deal with ArchiveSigningKey objects
    """

    def create(archive, earliest_distro_series, signing_key):
        """Creates a new ArchiveSigningKey for archive/distro_series.

        :return: A tuple like (db_object:ArchiveSigningKey, created:boolean)
                 with the ArchiveSigningKey and True if it was created (
                 False if it was updated).
        """

    def getSigningKey(key_type, archive, distro_series, exact_match=False):
        """Get the most suitable key for a given archive / distro series
        pair.

        :param exact_match: If True, returns the ArchiveSigningKey
                            matching exactly the given key_type, archive and
                            distro_series. If False, gets the best match.
        :return: The most suitable key
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

    def inject(key_type, private_key, public_key, description, created_at,
               archive, earliest_distro_series=None):
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
