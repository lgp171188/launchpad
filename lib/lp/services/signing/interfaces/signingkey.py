# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for signing keys stored at the signing service."""

__metaclass__ = type

__all__ = [
    'ISigningKey',
    'ISigningKeySet',
    'IArchiveSigningKey',
    'IArchiveSigningKeySet',
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

    def sign(message, message_name=None):
        """Sign the given message using this key

        :param message: The message to be signed.
        :param message_name: A name for the message being signed.
        """


class ISigningKeySet(Interface):
    """Interface to deal with the collection of signing keys
    """

    def generate(key_type, description=None):
        """Generates a new signing key on lp-signing and stores it in LP's
        database.

        :param key_type: One of the SigningKeyType enum's value
        :param description: (optional) The description associated with this
                            key
        :returns: The SigningKey object associated with the newly created
                  key at lp-signing"""


class IArchiveSigningKey(Interface):
    """Which signing key should be used by a specific archive"""

    id = Int(title=_('ID'), required=True, readonly=True)

    archive = Reference(
        IArchive, title=_("Archive"), required=True,
        description=_("The archive that owns this key."))

    distro_series = Reference(
        IDistroSeries, title=_("Distro series"), required=False,
        description=_("The minimum series that uses this key, if any."))

    signing_key = Reference(
        ISigningKey, title=_("Signing key"), required=True, readonly=True,
        description=_("Which signing key should be used by this archive"))


class IArchiveSigningKeySet(Interface):
    """Management class to deal with ArchiveSigningKey objects
    """

    def create(archive, distro_series, signing_key):
        """Creates a new ArchiveSigningKey, or updates the existing one from
        the same type to point to the new signing key.

        :return: A tuple like (db_object:ArchiveSigningKey, created:boolean)
                 with the ArchiveSigningKey and True if it was created (
                 False if it was updated).
        """

    def getSigningKeys(archive, distro_series):
        """Get the most suitable keys for a given archive / distro series
        pair.

        :return: A dict of most suitable key per type, like {
            SigningKeyType.UEFI: <ArchiveSigningKey object 1>,
            SigningKeyType.KMOD: <ArchiveSigningKey object 2>, ... }
        """

    def generate(key_type, archive, distro_series=None, description=None):
        """Generate a new key on signing service, and save it to db.

        :param key_type: One of the SigningKeyType enum's value
        :param archive: The package Archive that should be associated with
                        this key
        :param distro_series: (optional) The DistroSeries object
        :param description: (optional) The description associated with this
                            key
        :returns: The generated ArchiveSigningKey
        """
