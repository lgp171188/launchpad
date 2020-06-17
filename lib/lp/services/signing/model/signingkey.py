# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes to manage signing keys stored at the signing service."""


__metaclass__ = type

__all__ = [
    'ArchiveSigningKey',
    'ArchiveSigningKeySet',
    'SigningKey',
    ]

from collections import defaultdict

import pytz
from storm.locals import (
    Bytes,
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from zope.component import getUtility
from zope.interface import (
    implementer,
    provider,
    )

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
from lp.services.signing.enums import (
    SigningKeyType,
    SigningMode,
    )
from lp.services.signing.interfaces.signingkey import (
    IArchiveSigningKey,
    IArchiveSigningKeySet,
    ISigningKey,
    ISigningKeySet,
    )
from lp.services.signing.interfaces.signingserviceclient import (
    ISigningServiceClient,
    )


@implementer(ISigningKey)
@provider(ISigningKeySet)
class SigningKey(StormBase):
    """A key stored at lp-signing, used to sign uploaded files and packages"""

    __storm_table__ = 'SigningKey'

    id = Int(primary=True)

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    description = Unicode(allow_none=True)

    fingerprint = Unicode(allow_none=False)

    public_key = Bytes(allow_none=False)

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
    def generate(cls, key_type, description):
        signing_service = getUtility(ISigningServiceClient)
        generated_key = signing_service.generate(key_type, description)
        signing_key = SigningKey(
            key_type=key_type, fingerprint=generated_key['fingerprint'],
            public_key=generated_key['public-key'],
            description=description)
        store = IMasterStore(SigningKey)
        store.add(signing_key)
        return signing_key

    @classmethod
    def inject(cls, key_type, private_key, public_key, description,
               created_at):
        signing_service = getUtility(ISigningServiceClient)
        generated_key = signing_service.inject(
            key_type, private_key, public_key, description, created_at)
        fingerprint = generated_key['fingerprint']

        store = IMasterStore(SigningKey)
        # Check if the key is already saved in the database.
        db_key = store.find(
            SigningKey,
            SigningKey.key_type == key_type,
            SigningKey.fingerprint == fingerprint).one()
        if db_key is None:
            db_key = SigningKey(
                key_type=key_type, fingerprint=fingerprint,
                public_key=bytes(public_key),
                description=description, date_created=created_at)
            store.add(db_key)
        return db_key

    def sign(self, message, message_name):
        if self.key_type in (SigningKeyType.UEFI, SigningKeyType.FIT):
            mode = SigningMode.ATTACHED
        else:
            mode = SigningMode.DETACHED
        signing_service = getUtility(ISigningServiceClient)
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

    earliest_distro_series_id = Int(
        name="earliest_distro_series", allow_none=True)
    earliest_distro_series = Reference(
        earliest_distro_series_id, 'DistroSeries.id')

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    signing_key_id = Int(name="signing_key", allow_none=False)
    signing_key = Reference(signing_key_id, SigningKey.id)

    def __init__(self, archive=None, earliest_distro_series=None,
                 signing_key=None):
        super(ArchiveSigningKey, self).__init__()
        self.archive = archive
        self.signing_key = signing_key
        self.key_type = signing_key.key_type
        self.earliest_distro_series = earliest_distro_series


@implementer(IArchiveSigningKeySet)
class ArchiveSigningKeySet:

    @classmethod
    def create(cls, archive, earliest_distro_series, signing_key):
        store = IMasterStore(SigningKey)
        obj = ArchiveSigningKey(archive, earliest_distro_series, signing_key)
        store.add(obj)
        return obj

    @classmethod
    def getSigningKey(cls, key_type, archive, distro_series,
                      exact_match=False):
        store = IStore(ArchiveSigningKey)
        # Gets all the keys of the given key_type available for the archive
        rs = store.find(ArchiveSigningKey,
                SigningKey.id == ArchiveSigningKey.signing_key_id,
                SigningKey.key_type == key_type,
                ArchiveSigningKey.key_type == key_type,
                ArchiveSigningKey.archive == archive)

        if exact_match:
            rs = rs.find(
                ArchiveSigningKey.earliest_distro_series == distro_series)

        # prefetch related signing keys to avoid extra queries.
        signing_keys = store.find(SigningKey, [
            SigningKey.id.is_in([i.signing_key_id for i in rs])])
        signing_keys_by_id = {i.id: i for i in signing_keys}

        # Group keys per type, and per distro series
        keys_per_series = defaultdict(dict)
        for i in rs:
            signing_key = signing_keys_by_id[i.signing_key_id]
            keys_per_series[i.earliest_distro_series] = signing_key

        # Let's search the most suitable per key type.
        found_series = False
        # Note that archive.distribution.series is, by default, sorted by
        # "version", reversed.
        for series in archive.distribution.series:
            if series == distro_series:
                found_series = True
            if found_series and series in keys_per_series:
                return keys_per_series[series]
        # If no specific key for distro_series was found, returns
        # the keys for the archive itself (or None if no key is
        # available for the archive either).
        return keys_per_series.get(None)

    @classmethod
    def generate(cls, key_type, description, archive,
                 earliest_distro_series=None):
        signing_key = SigningKey.generate(key_type, description)
        archive_signing = ArchiveSigningKeySet.create(
            archive, earliest_distro_series, signing_key)
        return archive_signing

    @classmethod
    def inject(cls, key_type, private_key, public_key, description, created_at,
               archive, earliest_distro_series=None):
        signing_key = SigningKey.inject(
            key_type, private_key, public_key, description, created_at)
        archive_signing = ArchiveSigningKeySet.create(
            archive, earliest_distro_series, signing_key)
        return archive_signing
