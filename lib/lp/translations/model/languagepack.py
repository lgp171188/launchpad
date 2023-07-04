# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Language pack store."""

__all__ = [
    "LanguagePack",
    "LanguagePackSet",
]

from datetime import timezone

from storm.locals import DateTime, Int, Reference
from zope.interface import implementer

from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.translations.enums import LanguagePackType
from lp.translations.interfaces.languagepack import (
    ILanguagePack,
    ILanguagePackSet,
)


@implementer(ILanguagePack)
class LanguagePack(StormBase):
    __storm_table__ = "LanguagePack"

    id = Int(primary=True)

    file_id = Int(name="file", allow_none=False)
    file = Reference(file_id, "LibraryFileAlias.id")

    date_exported = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )

    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")

    type = DBEnum(
        enum=LanguagePackType, allow_none=False, default=LanguagePackType.FULL
    )

    updates_id = Int(name="updates", allow_none=True, default=None)
    updates = Reference(updates_id, "LanguagePack.id")

    def __init__(self, file, date_exported, distroseries, type, updates=None):
        super().__init__()
        self.file = file
        self.date_exported = date_exported
        self.distroseries = distroseries
        self.type = type
        self.updates = updates


@implementer(ILanguagePackSet)
class LanguagePackSet:
    def addLanguagePack(self, distroseries, file_alias, type):
        """See `ILanguagePackSet`."""
        assert type in LanguagePackType, (
            "Unknown language pack type: %s" % type.name
        )

        if (
            type == LanguagePackType.DELTA
            and distroseries.language_pack_base is None
        ):
            raise AssertionError(
                "There is no base language pack available for %s to get"
                " deltas from." % distroseries
            )

        updates = None
        if type == LanguagePackType.DELTA:
            updates = distroseries.language_pack_base

        return LanguagePack(
            file=file_alias,
            date_exported=UTC_NOW,
            distroseries=distroseries,
            type=type,
            updates=updates,
        )
