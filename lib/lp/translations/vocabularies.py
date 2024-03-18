# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the GNU
# Affero General Public License version 3 (see the file LICENSE).

"""Translations vocabularies."""

__all__ = [
    "FilteredDeltaLanguagePackVocabulary",
    "FilteredFullLanguagePackVocabulary",
    "FilteredLanguagePackVocabulary",
    "TranslatableLanguageVocabulary",
    "TranslationGroupVocabulary",
    "TranslationMessageVocabulary",
    "TranslationTemplateVocabulary",
]

from storm.expr import Is
from storm.locals import Desc, Not, Or
from zope.schema.vocabulary import SimpleTerm

from lp.registry.interfaces.distroseries import IDistroSeries
from lp.services.webapp.vocabulary import (
    NamedStormVocabulary,
    StormVocabularyBase,
)
from lp.services.worlddata.model.language import Language
from lp.services.worlddata.vocabularies import LanguageVocabulary
from lp.translations.enums import LanguagePackType
from lp.translations.model.languagepack import LanguagePack
from lp.translations.model.potemplate import POTemplate
from lp.translations.model.translationgroup import TranslationGroup
from lp.translations.model.translationmessage import TranslationMessage


class TranslatableLanguageVocabulary(LanguageVocabulary):
    """All the translatable languages known by Launchpad.

    Messages cannot be translated into English or a non-visible language.
    This vocabulary contains all the languages known to Launchpad,
    excluding English and non-visible languages.
    """

    _clauses = [Language.code != "en", Is(Language.visible, True)]


class TranslationGroupVocabulary(NamedStormVocabulary):
    _table = TranslationGroup


class TranslationMessageVocabulary(StormVocabularyBase):
    _table = TranslationMessage
    _order_by = "date_created"

    def toTerm(self, obj):
        translation = ""
        if obj.msgstr0 is not None:
            translation = obj.msgstr0.translation
        return SimpleTerm(obj, obj.id, translation)

    def __iter__(self):
        for message in self.context.messages:
            yield self.toTerm(message)


class TranslationTemplateVocabulary(StormVocabularyBase):
    """The set of all POTemplates for a given product or package."""

    _table = POTemplate
    _order_by = "name"

    def __init__(self, context):
        if context.productseries != None:
            self._clauses = [
                Is(POTemplate.iscurrent, True),
                POTemplate.productseries == context.productseries,
            ]
        else:
            self._clauses = [
                Is(POTemplate.iscurrent, True),
                POTemplate.distroseries == context.distroseries,
                POTemplate.sourcepackagename == context.sourcepackagename,
            ]
        super().__init__(context)

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.id, obj.name)


class FilteredLanguagePackVocabularyBase(StormVocabularyBase):
    """Base vocabulary class to retrieve language packs for a distroseries."""

    _table = LanguagePack
    _order_by = Desc(LanguagePack.date_exported)

    def __init__(self, context=None):
        if not IDistroSeries.providedBy(context):
            raise AssertionError(
                "%s is only useful from a DistroSeries context."
                % self.__class__.__name__
            )
        super().__init__(context)

    def toTerm(self, obj):
        return SimpleTerm(
            obj, obj.id, "%s" % obj.date_exported.strftime("%F %T %Z")
        )

    @property
    def _clauses(self):
        return [LanguagePack.distroseries == self.context]


class FilteredFullLanguagePackVocabulary(FilteredLanguagePackVocabularyBase):
    """Full export Language Pack for a distribution series."""

    displayname = "Select a full export language pack"

    @property
    def _clauses(self):
        return super()._clauses + [LanguagePack.type == LanguagePackType.FULL]


class FilteredDeltaLanguagePackVocabulary(FilteredLanguagePackVocabularyBase):
    """Delta export Language Pack for a distribution series."""

    displayname = "Select a delta export language pack"

    @property
    def _clauses(self):
        return super()._clauses + [
            LanguagePack.type == LanguagePackType.DELTA,
            LanguagePack.updates == self.context.language_pack_base,
        ]


class FilteredLanguagePackVocabulary(FilteredLanguagePackVocabularyBase):
    displayname = "Select a language pack"

    def toTerm(self, obj):
        return SimpleTerm(
            obj,
            obj.id,
            "%s (%s)"
            % (obj.date_exported.strftime("%F %T %Z"), obj.type.title),
        )

    @property
    def _clauses(self):
        # We are interested on any full language pack or language pack
        # that is a delta of the current base language pack type,
        # except the ones already used.
        used_lang_packs = []
        if self.context.language_pack_base is not None:
            used_lang_packs.append(self.context.language_pack_base.id)
        if self.context.language_pack_delta is not None:
            used_lang_packs.append(self.context.language_pack_delta.id)
        clauses = []
        if used_lang_packs:
            clauses.append(Not(LanguagePack.id.is_in(used_lang_packs)))
        clauses.append(
            Or(
                LanguagePack.updates == None,
                LanguagePack.updates == self.context.language_pack_base,
            )
        )
        return super()._clauses + clauses
