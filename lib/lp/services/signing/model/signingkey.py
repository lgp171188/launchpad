# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes to manage signing keys stored at the signing service."""


__metaclass__ = type

__all__ = [
    'SigningKey',
    'ArchiveSigningKey',
    ]

import base64

import pytz
from storm.locals import (
    DateTime,
    Int,
    Reference,
    Unicode,
    RawStr
    )
from zope.interface.declarations import implementer

from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import ISigningKey, \
    IArchiveSigningKey
from lp.registry.model.distroseries import DistroSeries
from lp.services.database.constants import (
    DEFAULT,
    UTC_NOW,
    )
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IMasterStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.signing.proxy import SigningService
from lp.soyuz.model.archive import Archive


@implementer(ISigningKey)
class SigningKey(StormBase):
    """A key stored at lp-signing, used to sign uploaded files and packages"""

    __storm_table__ = 'SigningKey'

    id = Int(primary=True)

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    description = Unicode(allow_none=True)

    fingerprint = Unicode(allow_none=False)

    public_key = RawStr(allow_none=True)

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=pytz.UTC)

    def __init__(self, key_type, fingerprint, public_key,
                 description=None, date_created=DEFAULT):
        """Builds the signing key

        :param key_type: One of the SigningKeyType enum items
        :param fingerprint: The key's fingerprint
        :param public_key: The key's public key (raw; not base64-encoded)
        """
        super(SigningKey, self).__init__()
        self.key_type = key_type
        self.fingerprint = fingerprint
        self.public_key = public_key
        self.description = description
        self.date_created = date_created

    @classmethod
    def generate(cls, key_type, description=None):
        """Generates a new signing key on lp-signing and stores it in LP's
        database.

        :param key_type: One of the SigningKeyType enum's value
        :param description: (optional) The description associated with this
                            key
        :returns: The SigningKey object associated with the newly created
                  key at lp-singing"""
        signing_service = SigningService()
        generated_key = signing_service.generate(key_type, description)
        signing_key = SigningKey(
            key_type=key_type, fingerprint=generated_key['fingerprint'],
            public_key=base64.b64decode(generated_key['public-key']),
            description=description)
        store = IMasterStore(SigningKey)
        store.add(signing_key)
        return signing_key

    def sign(self, mode, message, message_name=None):
        """Sign the given message using this key

        :param mode: "ATTACHED" or "DETACHED"
        :param message: The message to be signed
        :param message_name: A name for the message beign signed"""
        signing_service = SigningService()
        signed = signing_service.sign(
            self.key_type, self.fingerprint, message_name, message, mode)
        return signed['signed-message']


@implementer(IArchiveSigningKey)
class ArchiveSigningKey(StormBase):
    """Which signing key should be used by a given archive / series"""

    __storm_table__ = 'ArchiveSigningKey'

    id = Int(primary=True)

    archive_id = Int(name="archive")
    archive = Reference(archive_id, Archive.id)

    distro_series_id = Int(name="distro_series", allow_none=True)
    distro_series = Reference(distro_series_id, DistroSeries.id)

    signing_key_id = Int(name="signing_key", allow_none=False)
    signing_key = Reference(signing_key_id, SigningKey.id)

    def __init__(self, archive, distro_series, signing_key):
        super(ArchiveSigningKey, self).__init__()
        self.archive = archive
        self.distro_series = distro_series
        self.signing_key = signing_key

    @classmethod
    def create_or_update(cls, archive, distro_series, signing_key):
        """Creates a new ArchiveSigningKey or updates the existing one to
        point to the new signing key.

        :return: A tuple like (db_object:ArchiveSigningKey, created:boolean)
                 with the ArchiveSigningKey and True if it was created (
                 False if it was updated) """
        store = IMasterStore(SigningKey)
        obj = store.find(ArchiveSigningKey, [
            ArchiveSigningKey.distro_series == distro_series,
            ArchiveSigningKey.archive == archive
            ]).one()
        if obj is not None:
            obj.signing_key = signing_key
            created = False
        else:
            obj = ArchiveSigningKey(archive, distro_series, signing_key)
            created = True
        store.add(obj)
        return obj, created

    @classmethod
    def get_signing_key(cls, archive, distro_series):
        """Get the most suitable key for a given archive / distro series
        pair.
        """
        store = IStore(ArchiveSigningKey)
        rs = store.find(ArchiveSigningKey, [
            ArchiveSigningKey.archive == archive])
        keys_per_series = {i.distro_series: i for i in rs}
        found = False
        for series in archive.distribution.series:
            if series == distro_series:
                found = True
            if found and series in keys_per_series:
                return keys_per_series[series]
        # If not specific key for distro_series was found, returns the key
        # for the archive itself (or None if no key is available for the
        # archive either)
        return keys_per_series.get(None)

    @classmethod
    def generate(cls, key_type, archive, distro_series=None,
                 description=None):
        """Generated a new key on signing service, and save it to db.

        :param key_type: One of the SigningKeyType enum's value
        :param archive: The package Archive that should be associated with
                        this key
        :param distro_series: (optional) The DistroSeries object
        :param description: (optional) The description associated with this
                            key
        :returns: The generated ArchiveSigningKey
        """
        signing_key = SigningKey.generate(key_type, description)
        archive_signing, created = ArchiveSigningKey.create_or_update(
            archive, distro_series, signing_key)
        return archive_signing