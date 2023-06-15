# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "CountryNameVocabulary",
    "LanguageVocabulary",
    "TimezoneNameVocabulary",
]

from zope.component import getUtility
from zope.interface import alsoProvides
from zope.schema.vocabulary import SimpleTerm, SimpleVocabulary

from lp.services.webapp.vocabulary import SQLObjectVocabularyBase
from lp.services.worlddata.interfaces.language import ILanguage, ILanguageSet
from lp.services.worlddata.interfaces.timezone import ITimezoneNameVocabulary
from lp.services.worlddata.model.country import Country
from lp.services.worlddata.model.language import Language


def _common_timezones():
    """A list of useful, current time zone names.

    This is inspired by `pytz.common_timezones`, which seems to be
    approximately the list supported by `tzdata` with the additions of some
    Canada- and US-specific names.  Since we're aiming for current rather
    than historical zone names, `zone1970.tab` seems appropriate.
    """
    zones = set()
    with open("/usr/share/zoneinfo/zone.tab") as zone_tab:
        for line in zone_tab:
            if line.startswith("#"):
                continue
            zones.add(line.rstrip("\n").split("\t")[2])
    # Backward-compatible US zone names, still in common use.
    zones.update(
        {
            "US/Alaska",
            "US/Arizona",
            "US/Central",
            "US/Eastern",
            "US/Hawaii",
            "US/Mountain",
            "US/Pacific",
        }
    )
    # Backward-compatible Canadian zone names; see
    # https://bugs.launchpad.net/pytz/+bug/506341.
    zones.update(
        {
            "Canada/Atlantic",
            "Canada/Central",
            "Canada/Eastern",
            "Canada/Mountain",
            "Canada/Newfoundland",
            "Canada/Pacific",
        }
    )
    # pytz has this in addition to UTC.  Perhaps it's more understandable
    # for people not steeped in time zone lore.
    zones.add("GMT")

    # UTC comes first, then everything else.
    yield "UTC"
    zones.discard("UTC")
    yield from sorted(zones)


_timezone_vocab = SimpleVocabulary.fromValues(_common_timezones())
alsoProvides(_timezone_vocab, ITimezoneNameVocabulary)


def TimezoneNameVocabulary(context=None):
    return _timezone_vocab


# Country.name may have non-ASCII characters, so we can't use
# NamedSQLObjectVocabulary here.


class CountryNameVocabulary(SQLObjectVocabularyBase):
    """A vocabulary for country names."""

    _table = Country
    _orderBy = "name"

    def toTerm(self, obj):
        return SimpleTerm(obj, obj.id, obj.name)


class LanguageVocabulary(SQLObjectVocabularyBase):
    """All the languages known by Launchpad."""

    _table = Language
    _orderBy = "englishname"

    def __contains__(self, language):
        """See `IVocabulary`."""
        assert ILanguage.providedBy(language), (
            "'in LanguageVocabulary' requires ILanguage as left operand, "
            "got %s instead." % type(language)
        )
        return super().__contains__(language)

    def toTerm(self, obj):
        """See `IVocabulary`."""
        return SimpleTerm(obj, obj.code, obj.displayname)

    def getTerm(self, obj):
        """See `IVocabulary`."""
        if obj not in self:
            raise LookupError(obj)
        return SimpleTerm(obj, obj.code, obj.displayname)

    def getTermByToken(self, token):
        """See `IVocabulary`."""
        found_language = getUtility(ILanguageSet).getLanguageByCode(token)
        if found_language is None:
            raise LookupError(token)
        return self.getTerm(found_language)
