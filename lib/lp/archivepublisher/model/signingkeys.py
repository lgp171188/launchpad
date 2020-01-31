# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes to manage signing keys stored at the signing service."""


__metaclass__ = type

import pytz
from storm.locals import (
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from zope.interface.declarations import implementer

from lp.archivepublisher.enums import SigningKeyType
from lp.archivepublisher.interfaces.signingkey import ISigningKey
from lp.registry.model.distroseries import DistroSeries
from lp.services.database.constants import (
    DEFAULT,
    UTC_NOW,
    )
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IMasterStore
from lp.services.database.stormbase import StormBase
from lp.services.signing.proxy import SigningService
from lp.soyuz.model.archive import Archive


@implementer(ISigningKey)
class SigningKey(StormBase):
    """A key stored at lp-signing, used to sign uploaded files and packages"""

    __storm_table__ = 'SigningKey'

    id = Int(primary=True)

    archive_id = Int(name="archive")
    archive = Reference(archive_id, Archive.id)

    distro_series_id = Int(name="distro_series", allow_none=True)
    distro_series = Reference(distro_series_id, DistroSeries.id)

    key_type = DBEnum(enum=SigningKeyType, allow_none=False)

    description = Unicode(allow_none=True)

    fingerprint = Unicode(allow_none=False)

    public_key = Unicode(allow_none=True)

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=pytz.UTC)

    def __init__(self, key_type, archive, fingerprint, public_key,
                 distro_series=None, description=None, date_created=DEFAULT):
        super(SigningKey, self).__init__()
        self.key_type = key_type
        self.archive = archive
        self.fingerprint = fingerprint
        self.public_key = public_key
        self.description = description
        self.distro_series = distro_series
        self.date_created = date_created

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
        :returns: The generated SigningKey
        """
        signing_service = SigningService()
        generated_key = signing_service.generate(key_type.name, description)
        signing_key = SigningKey(
            key_type=key_type, archive=archive,
            fingerprint=generated_key['fingerprint'],
            public_key=generated_key['public-key'],
            distro_series=distro_series, description=description)
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
            self.key_type.name, self.fingerprint, message_name, message, mode)
        return signed['signed-message']
