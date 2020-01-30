# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes to manage signing keys stored at the signing service."""


__metaclass__ = type

import pytz
from lp.archivepublisher.enums import SigningKeyType
from lp.archivepublisher.interfaces.signingkey import ISigningKey
from lp.registry.model.distroseries import DistroSeries
from lp.services.database.constants import UTC_NOW, DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.soyuz.model.archive import Archive
from storm.locals import (
    Int,
    Reference,
    Unicode,
    DateTime
    )
from zope.interface.declarations import implementer


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

    fingerprint = Unicode(allow_none=False)

    public_key = Unicode(allow_none=True)

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=pytz.UTC)

    def __init__(self, key_type, archive, fingerprint, public_key,
                 distro_series=None, date_created=DEFAULT):
        super(SigningKey, self).__init__()
        self.key_type = key_type
        self.archive = archive
        self.fingerprint = fingerprint
        self.public_key = public_key
        self.distro_series = distro_series
        self.date_created = date_created

    @classmethod
    def generate(cls):
        """Generated a new key on signing service, and save it to db.

        :returns: The generated SigningKey
        """
