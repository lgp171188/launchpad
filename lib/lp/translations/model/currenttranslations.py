#  Copyright 2022 Canonical Ltd.  This software is licensed under the
#  GNU Affero General Public License version 3 (see the file LICENSE).
from typing import Dict, Iterable, Optional, Set

from storm.expr import Or
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.services.database.interfaces import IStore
from lp.services.worlddata.model.language import Language
from lp.translations.interfaces.currenttranslations import (
    CurrentTranslationKey,
    ICurrentTranslations,
)
from lp.translations.interfaces.side import ITranslationSideTraitsSet
from lp.translations.model.potemplate import POTemplate
from lp.translations.model.potmsgset import POTMsgSet
from lp.translations.model.translationmessage import TranslationMessage


@implementer(ICurrentTranslations)
class CurrentTranslations:
    def getCurrentTranslation(
        self,
        potmsgset: POTMsgSet,
        potemplate: Optional["POTemplate"],
        language: Language,
        side: int,
        use_cache: bool = False,
    ) -> Optional[TranslationMessage]:
        """See `IPOTMsgSet`."""
        potemplate_id = potemplate.id if potemplate else None
        key = CurrentTranslationKey(
            potmsgset.id, potemplate_id, language.id, side
        )
        if use_cache and hasattr(potmsgset, "_current_translations_cache"):
            if key in potmsgset._current_translations_cache:
                return potmsgset._current_translations_cache[key]
        current_translations = self.getCurrentTranslations(
            {potmsgset}, {potemplate}, {language}, {side}
        )
        return current_translations[key]

    def getCurrentTranslations(
        self,
        potmsgsets: Set[POTMsgSet],
        potemplates: Set[Optional[POTemplate]],
        languages: Set[Language],
        sides: Set[int],
    ) -> Dict[CurrentTranslationKey, TranslationMessage]:
        if not potmsgsets:
            raise ValueError("potmsgsets must not be empty")
        if not potemplates:
            raise ValueError("potemplates must not be empty")
        if not languages:
            raise ValueError("languages must not be empty")
        if not sides:
            raise ValueError("sides must not be empty")

        clauses = [
            TranslationMessage.potmsgsetID.is_in(s.id for s in potmsgsets),
            TranslationMessage.languageID.is_in(lang.id for lang in languages),
        ]

        side_clauses = []
        trait_set = getUtility(ITranslationSideTraitsSet)
        for side in sides:
            traits = trait_set.getTraits(side)
            flag = removeSecurityProxy(traits.getFlag(TranslationMessage))
            side_clauses.append(flag == True)

        clauses.append(Or(*side_clauses))

        if potemplates == {None}:
            clauses.append(TranslationMessage.potemplate == None)
        else:
            clauses.append(
                Or(
                    TranslationMessage.potemplate == None,
                    TranslationMessage.potemplateID.is_in(
                        t.id for t in potemplates if t is not None
                    ),
                )
            )

        messages_by_key = {}
        for message in IStore(TranslationMessage).find(
            TranslationMessage, *clauses
        ):
            for side, trait in trait_set.getAllTraits().items():
                if not trait.getFlag(message):
                    continue
                key = CurrentTranslationKey(
                    message.potmsgsetID,
                    message.potemplateID,
                    message.languageID,
                    side,
                )
                messages_by_key[key] = message

        results = {
            CurrentTranslationKey(
                msgset.id,
                potemplate.id if potemplate else None,
                language.id,
                side,
            ): None
            for msgset in potmsgsets
            for potemplate in potemplates
            for language in languages
            for side in sides
        }

        for key in results:
            # Return a diverged translation if it exists, and fall back
            # to the shared one otherwise.
            shared_message_key = key._replace(potemplate_id=None)
            results[key] = messages_by_key.get(key) or messages_by_key.get(
                shared_message_key
            )

        return results

    def cacheCurrentTranslations(
        self,
        msgsets: Iterable["POTMsgSet"],
        potemplates: Iterable[Optional["POTemplate"]],
        languages: Iterable[Language],
        sides: Iterable[int],
    ) -> None:
        msgsets = set(msgsets)
        current_translations = self.getCurrentTranslations(
            msgsets, set(potemplates), set(languages), set(sides)
        )
        for msgset in msgsets:
            cache = getattr(msgset, "_current_translations_cache", {})
            for key, message in current_translations.items():
                cache[key] = current_translations[key]
            msgset._current_translations_cache = cache
