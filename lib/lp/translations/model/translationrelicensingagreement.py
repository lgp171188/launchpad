# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "TranslationRelicensingAgreement",
]

from datetime import timezone

from storm.locals import Bool, DateTime, Int, Reference
from zope.interface import implementer

from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.translationrelicensingagreement import (
    ITranslationRelicensingAgreement,
)


@implementer(ITranslationRelicensingAgreement)
class TranslationRelicensingAgreement(StormBase):
    __storm_table__ = "TranslationRelicensingAgreement"

    id = Int(primary=True)

    person_id = Int(
        name="person", allow_none=False, validator=validate_public_person
    )
    person = Reference(person_id, "Person.id")

    allow_relicensing = Bool(
        name="allow_relicensing", allow_none=False, default=True
    )

    date_decided = DateTime(
        name="date_decided",
        allow_none=False,
        default=UTC_NOW,
        tzinfo=timezone.utc,
    )

    def __init__(self, person, allow_relicensing=True):
        super().__init__()
        self.person = person
        self.allow_relicensing = allow_relicensing
