# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "TranslationTemplateItem",
]

from storm.locals import Int, Reference, Store
from zope.interface import implementer

from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.translationtemplateitem import (
    ITranslationTemplateItem,
)


@implementer(ITranslationTemplateItem)
class TranslationTemplateItem(StormBase):
    """See `ITranslationTemplateItem`."""

    __storm_table__ = "TranslationTemplateItem"

    id = Int(primary=True)
    potemplate_id = Int(name="potemplate", allow_none=False)
    potemplate = Reference(potemplate_id, "POTemplate.id")
    sequence = Int(name="sequence", allow_none=False)
    potmsgset_id = Int(name="potmsgset", allow_none=False)
    potmsgset = Reference(potmsgset_id, "POTMsgSet.id")

    def __init__(self, potemplate, sequence, potmsgset):
        super().__init__()
        self.potemplate = potemplate
        self.sequence = sequence
        self.potmsgset = potmsgset

    def destroySelf(self):
        Store.of(self).remove(self)
