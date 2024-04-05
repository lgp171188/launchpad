# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes to manage signing keys stored at the signing service."""

__all__ = [
    "ArchiveSigningKey",
    "ArchiveSigningKeySet",
    "SigningKey",
]

from datetime import timezone

from storm.expr import Join
from storm.locals import Bytes, DateTime, Int, Reference, Unicode
from zope.component import getUtility
from zope.interface import implementer, provider

from lp.registry.model.gpgkey import GPGKey
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.signing.enums import SigningKeyType, SigningMode
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

    __storm_table__ = "SigningKey"

    id = Int(primary=True)

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    description = Unicode(allow_none=True)

    fingerprint = Unicode(allow_none=False)

    public_key = Bytes(allow_none=False)

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )

    def __init__(
        self,
        key_type,
        fingerprint,
        public_key,
        description=None,
        date_created=DEFAULT,
    ):
        """Builds the signing key

        :param key_type: One of the SigningKeyType enum items
        :param fingerprint: The key's fingerprint
        :param public_key: The key's public key (raw; not base64-encoded)
        """
        super().__init__()
        self.key_type = key_type
        self.fingerprint = fingerprint
        self.public_key = public_key
        self.description = description
        self.date_created = date_created

    @classmethod
    def get(cls, key_type, fingerprint):
        """See `ISigningKeySet`."""
        return (
            IStore(SigningKey)
            .find(SigningKey, key_type=key_type, fingerprint=fingerprint)
            .one()
        )

    @classmethod
    def generate(
        cls, key_type, description, openpgp_key_algorithm=None, length=None
    ):
        signing_service = getUtility(ISigningServiceClient)
        generated_key = signing_service.generate(
            key_type,
            description,
            openpgp_key_algorithm=openpgp_key_algorithm,
            length=length,
        )
        signing_key = SigningKey(
            key_type=key_type,
            fingerprint=generated_key["fingerprint"],
            public_key=generated_key["public-key"],
            description=description,
        )
        store = IPrimaryStore(SigningKey)
        store.add(signing_key)
        return signing_key

    @classmethod
    def inject(
        cls, key_type, private_key, public_key, description, created_at
    ):
        signing_service = getUtility(ISigningServiceClient)
        generated_key = signing_service.inject(
            key_type, private_key, public_key, description, created_at
        )
        fingerprint = generated_key["fingerprint"]

        store = IPrimaryStore(SigningKey)
        # Check if the key is already saved in the database.
        db_key = store.find(
            SigningKey,
            SigningKey.key_type == key_type,
            SigningKey.fingerprint == fingerprint,
        ).one()
        if db_key is None:
            db_key = SigningKey(
                key_type=key_type,
                fingerprint=fingerprint,
                public_key=bytes(public_key),
                description=description,
                date_created=created_at,
            )
            store.add(db_key)
        return db_key

    @classmethod
    def sign(cls, signing_keys, message, message_name, mode=None):
        fingerprints = [key.fingerprint for key in signing_keys]
        key_type = signing_keys[0].key_type
        if len(signing_keys) > 1 and not all(
            key.key_type == key_type for key in signing_keys[1:]
        ):
            raise ValueError(
                "Cannot sign as all the keys are not of the same type."
            )
        if mode is None:
            if key_type in (SigningKeyType.UEFI, SigningKeyType.FIT):
                mode = SigningMode.ATTACHED
            else:
                mode = SigningMode.DETACHED
        signing_service = getUtility(ISigningServiceClient)
        signed = signing_service.sign(
            key_type, fingerprints, message_name, message, mode
        )
        return signed["signed-message"]

    def addAuthorization(self, client_name):
        """See `ISigningKey`."""
        signing_service = getUtility(ISigningServiceClient)
        signing_service.addAuthorization(
            self.key_type, self.fingerprint, client_name
        )


@implementer(IArchiveSigningKey)
class ArchiveSigningKey(StormBase):
    """Which signing key should be used by a given archive / series."""

    __storm_table__ = "ArchiveSigningKey"

    id = Int(primary=True)

    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, "Archive.id")

    earliest_distro_series_id = Int(
        name="earliest_distro_series", allow_none=True
    )
    earliest_distro_series = Reference(
        earliest_distro_series_id, "DistroSeries.id"
    )

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    signing_key_id = Int(name="signing_key", allow_none=False)
    signing_key = Reference(signing_key_id, SigningKey.id)

    def __init__(
        self, archive=None, earliest_distro_series=None, signing_key=None
    ):
        super().__init__()
        self.archive = archive
        self.signing_key = signing_key
        self.key_type = signing_key.key_type
        self.earliest_distro_series = earliest_distro_series

    def destroySelf(self):
        IStore(self).remove(self)


@implementer(IArchiveSigningKeySet)
class ArchiveSigningKeySet:
    @classmethod
    def create(cls, archive, earliest_distro_series, signing_key):
        store = IPrimaryStore(SigningKey)
        obj = ArchiveSigningKey(archive, earliest_distro_series, signing_key)
        store.add(obj)
        return obj

    @classmethod
    def get(cls, key_type, archive, distro_series, exact_match=False):
        store = IStore(ArchiveSigningKey)

        # Get all the keys of the given key_type available for the archive.
        archive_signing_keys = store.find(
            ArchiveSigningKey,
            ArchiveSigningKey.key_type == key_type,
            ArchiveSigningKey.archive == archive,
        )

        if exact_match:
            archive_signing_keys = archive_signing_keys.find(
                ArchiveSigningKey.earliest_distro_series == distro_series
            )

        # Group keys per distro series.
        keys_per_series = {
            archive_signing_key.earliest_distro_series_id: archive_signing_key
            for archive_signing_key in archive_signing_keys
        }

        # Find the most suitable per key type.
        found_series = False
        # Note that archive.distribution.series is, by default, sorted by
        # "version", reversed.
        for series in archive.distribution.series:
            if series == distro_series:
                found_series = True
            if found_series and series.id in keys_per_series:
                return keys_per_series[series.id]
        # If no specific key for distro_series was found, returns
        # the keys for the archive itself (or None if no key is
        # available for the archive either).
        return keys_per_series.get(None)

    @classmethod
    def getSigningKey(
        cls, key_type, archive, distro_series, exact_match=False
    ):
        archive_signing_key = cls.get(
            key_type, archive, distro_series, exact_match=exact_match
        )
        return (
            None
            if archive_signing_key is None
            else archive_signing_key.signing_key
        )

    @classmethod
    def getByArchiveAndFingerprint(cls, archive, fingerprint):
        join = (
            ArchiveSigningKey,
            Join(
                SigningKey,
                SigningKey.id == ArchiveSigningKey.signing_key_id,
            ),
        )
        results = (
            IStore(ArchiveSigningKey)
            .using(*join)
            .find(
                ArchiveSigningKey,
                ArchiveSigningKey.archive == archive,
                SigningKey.fingerprint == fingerprint,
            )
        )
        return results.one()

    @classmethod
    def get4096BitRSASigningKey(cls, archive):
        join = (
            ArchiveSigningKey,
            Join(
                SigningKey,
                SigningKey.id == ArchiveSigningKey.signing_key_id,
            ),
            Join(
                GPGKey,
                GPGKey.fingerprint == SigningKey.fingerprint,
            ),
        )
        results = (
            IStore(ArchiveSigningKey)
            .using(*join)
            .find(
                SigningKey,
                ArchiveSigningKey.archive == archive,
                GPGKey.keysize == 4096,
            )
        )
        return results.one()

    @classmethod
    def generate(
        cls, key_type, description, archive, earliest_distro_series=None
    ):
        signing_key = SigningKey.generate(key_type, description)
        archive_signing = ArchiveSigningKeySet.create(
            archive, earliest_distro_series, signing_key
        )
        return archive_signing

    @classmethod
    def inject(
        cls,
        key_type,
        private_key,
        public_key,
        description,
        created_at,
        archive,
        earliest_distro_series=None,
    ):
        signing_key = SigningKey.inject(
            key_type, private_key, public_key, description, created_at
        )
        archive_signing = ArchiveSigningKeySet.create(
            archive, earliest_distro_series, signing_key
        )
        return archive_signing
