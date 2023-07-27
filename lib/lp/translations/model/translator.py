# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["Translator", "TranslatorSet"]

from datetime import timezone

from storm.locals import DateTime, Int, Join, Reference, Store, Unicode
from zope.interface import implementer

from lp.registry.interfaces.person import validate_public_person
from lp.registry.model.teammembership import TeamParticipation
from lp.services.database.constants import DEFAULT
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.translator import ITranslator, ITranslatorSet


@implementer(ITranslator)
class Translator(StormBase):
    """A Translator in a TranslationGroup."""

    __storm_table__ = "Translator"
    # default to listing newest first
    __storm_order__ = "-id"

    id = Int(primary=True)

    translationgroup_id = Int(name="translationgroup", allow_none=False)
    translationgroup = Reference(translationgroup_id, "TranslationGroup.id")
    language_id = Int(name="language", allow_none=False)
    language = Reference(language_id, "Language.id")
    translator_id = Int(
        name="translator", validator=validate_public_person, allow_none=False
    )
    translator = Reference(translator_id, "Person.id")
    datecreated = DateTime(
        allow_none=False, default=DEFAULT, tzinfo=timezone.utc
    )
    style_guide_url = Unicode(allow_none=True, default=None)

    def __init__(
        self, translationgroup, language, translator, style_guide_url=None
    ):
        super().__init__()
        self.translationgroup = translationgroup
        self.language = language
        self.translator = translator
        self.style_guide_url = style_guide_url


@implementer(ITranslatorSet)
class TranslatorSet:
    def new(
        self, translationgroup, language, translator, style_guide_url=None
    ):
        return Translator(
            translationgroup=translationgroup,
            language=language,
            translator=translator,
            style_guide_url=style_guide_url,
        )

    def getByTranslator(self, translator):
        """See ITranslatorSet."""

        store = Store.of(translator)
        # TranslationGroup is referenced directly in SQL to avoid
        # a cyclic import.
        origin = [
            Translator,
            Join(
                TeamParticipation,
                TeamParticipation.team_id == Translator.translator_id,
            ),
            Join(
                "TranslationGroup",
                on="TranslationGroup.id = Translator.translationgroup",
            ),
        ]
        result = store.using(*origin).find(
            Translator, TeamParticipation.person == translator
        )

        return result.order_by("TranslationGroup.title")
