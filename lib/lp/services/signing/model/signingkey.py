# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes to manage signing keys stored at the signing service."""


__metaclass__ = type

__all__ = [
    'SigningKey',
    'ArchiveSigningKey',
    ]

import base64
from collections import defaultdict

import pytz
from storm.locals import (
    DateTime,
    Int,
    RawStr,
    Reference,
    Unicode,
    )
from zope.interface.declarations import implementer

from lp.services.database.constants import (
    DEFAULT,
    UTC_NOW,
    )
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import (
    IArchiveSigningKey,
    ISigningKey,
    )
from lp.services.signing.proxy import SigningServiceClient


@implementer(ISigningKey)
class SigningKey(StormBase):
    """A key stored at lp-signing, used to sign uploaded files and packages"""

    __storm_table__ = 'SigningKey'

    id = Int(primary=True)

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    description = Unicode(allow_none=True)

    fingerprint = Unicode(allow_none=False)

    public_key = RawStr(allow_none=False)

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

    def sign(self, message, message_name=None):
        """Sign the given message using this key

        :param message: The message to be signed.
        :param message_name: A name for the message beign signed.
        """
        if self.key_type in (SigningKeyType.UEFI, SigningKeyType.FIT):
            mode = "ATTACHED"
        else:
            mode = "DETACHED"
        signing_service = SigningService()
        signed = signing_service.sign(
            self.key_type, self.fingerprint, message_name, message, mode)
        return signed['signed-message']


@implementer(IArchiveSigningKey)
class ArchiveSigningKey(StormBase):
    """Which signing key should be used by a given archive / series.
    """

    __storm_table__ = 'ArchiveSigningKey'

    id = Int(primary=True)

    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, 'Archive.id')

    distro_series_id = Int(name="distro_series", allow_none=True)
    distro_series = Reference(distro_series_id, 'DistroSeries.id')

    signing_key_id = Int(name="signing_key", allow_none=False)
    signing_key = Reference(signing_key_id, SigningKey.id)

    def __init__(self, archive, distro_series, signing_key):
        super(ArchiveSigningKey, self).__init__()
        self.archive = archive
        self.distro_series = distro_series
        self.signing_key = signing_key

    @classmethod
    def create_or_update(cls, archive, distro_series, signing_key):
        """Creates a new ArchiveSigningKey, or updates the existing one from
        the same type to point to the new signing key.

        :return: A tuple like (db_object:ArchiveSigningKey, created:boolean)
                 with the ArchiveSigningKey and True if it was created (
                 False if it was updated).
        """
        store = IMasterStore(SigningKey)
        key_type = signing_key.key_type
        obj = store.find(ArchiveSigningKey,
            ArchiveSigningKey.signing_key_id == SigningKey.id,
            SigningKey.key_type == key_type,
            ArchiveSigningKey.distro_series == distro_series,
            ArchiveSigningKey.archive == archive
            ).one()
        if obj is not None:
            obj.signing_key = signing_key
            created = False
        else:
            obj = ArchiveSigningKey(archive, distro_series, signing_key)
            created = True
        store.add(obj)
        return obj, created

    @classmethod
    def get_signing_keys(cls, archive, distro_series):
        """Get the most suitable keys for a given archive / distro series
        pair.

        :return: A dict of most suitable key per type, like {
            SigningKeyType.UEFI: <ArchiveSigningKey object 1>,
            SigningKeyType.KMOD: <ArchiveSigningKey object 1>, ... }
        """
        # Gets all the keys available for the given archive.
        store = IStore(ArchiveSigningKey)
        rs = store.find(ArchiveSigningKey, [
                ArchiveSigningKey.archive == archive])

        # prefetch related signing keys to avoid extra queries.
        signing_keys = store.find(SigningKey, [
            SigningKey.id.is_in([i.signing_key_id for i in rs])])
        signing_keys_by_id = {i.id: i for i in signing_keys}

        # Group keys per type, and per distro series
        keys_data = defaultdict(dict)
        for i in rs:
            signing_key = signing_keys_by_id[i.signing_key_id]
            keys_data[signing_key.key_type][i.distro_series] = i

        ret_keys = {}

        # Let's search the most suitable per key type.
        for key_type, keys_per_series in keys_data.items():
            found_series = False
            found_key = False
            for series in archive.distribution.series:
                if series == distro_series:
                    found_series = True
                if found_series and series in keys_per_series:
                    ret_keys[key_type] = keys_per_series[series]
                    found_key = True
                    break
            # If not specific keys for distro_series was found, returns
            # the keys for the archive itself (or None if no key is
            # available for the archive either).
            if not found_series or not found_key:
                ret_keys[key_type] = keys_per_series.get(None)
        return ret_keys

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
