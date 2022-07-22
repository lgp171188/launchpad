# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from zope.interface import implementer
from zope.publisher.interfaces.browser import IBrowserRequest

from lp.registry.interfaces.person import IPerson
from lp.services.geoip.interfaces import (
    IRequestLocalLanguages,
    IRequestPreferredLanguages,
)
from lp.services.webapp.interfaces import ILaunchBag
from lp.services.worlddata.helpers import (
    is_english_variant,
    preferred_or_request_languages,
)
from lp.services.worlddata.interfaces.language import ILanguageSet
from lp.testing import TestCase
from lp.testing.fixture import ZopeAdapterFixture, ZopeUtilityFixture
from lp.testing.layers import BaseLayer, FunctionalLayer


class DummyLanguage:
    def __init__(self, code, pluralforms):
        self.code = code
        self.pluralforms = pluralforms
        self.alt_suggestion_language = None


@implementer(ILanguageSet)
class DummyLanguageSet:

    _languages = {
        "ja": DummyLanguage("ja", 1),
        "es": DummyLanguage("es", 2),
        "fr": DummyLanguage("fr", 3),
        "cy": DummyLanguage("cy", None),
    }

    def __getitem__(self, key):
        return self._languages[key]


@implementer(IPerson)
class DummyPerson:
    def __init__(self, codes):
        self.codes = codes
        all_languages = DummyLanguageSet()

        self.languages = [all_languages[code] for code in self.codes]


dummyPerson = DummyPerson(("es",))
dummyNoLanguagePerson = DummyPerson(())


class DummyResponse:
    def redirect(self, url):
        pass


@implementer(IBrowserRequest)
class DummyRequest:
    def __init__(self, **form_data):
        self.form = form_data
        self.URL = "http://this.is.a/fake/url"
        self.response = DummyResponse()

    def get(self, key, default):
        raise key


def adaptRequestToLanguages(request):
    return DummyRequestLanguages()


class DummyRequestLanguages:
    def getPreferredLanguages(self):
        return [
            DummyLanguage("ja", 1),
            DummyLanguage("es", 2),
            DummyLanguage("fr", 3),
        ]

    def getLocalLanguages(self):
        return [
            DummyLanguage("da", 4),
            DummyLanguage("as", 5),
            DummyLanguage("sr", 6),
        ]


@implementer(ILaunchBag)
class DummyLaunchBag:
    def __init__(self, login=None, user=None):
        self.login = login
        self.user = user


class TestPreferredOrRequestLanguages(TestCase):

    layer = FunctionalLayer

    def test_single_preferred_language(self):
        # Test with a person who has a single preferred language.
        self.useFixture(ZopeUtilityFixture(DummyLanguageSet(), ILanguageSet))
        self.useFixture(
            ZopeUtilityFixture(
                DummyLaunchBag("foo.bar@canonical.com", dummyPerson),
                ILaunchBag,
            )
        )
        self.useFixture(
            ZopeAdapterFixture(
                adaptRequestToLanguages,
                (IBrowserRequest,),
                IRequestPreferredLanguages,
            )
        )
        self.useFixture(
            ZopeAdapterFixture(
                adaptRequestToLanguages,
                (IBrowserRequest,),
                IRequestLocalLanguages,
            )
        )

        languages = preferred_or_request_languages(DummyRequest())
        self.assertEqual(1, len(languages))
        self.assertEqual("es", languages[0].code)

    def test_no_preferred_language(self):
        # Test with a person who has no preferred language.
        self.useFixture(ZopeUtilityFixture(DummyLanguageSet(), ILanguageSet))
        self.useFixture(
            ZopeUtilityFixture(
                DummyLaunchBag("foo.bar@canonical.com", dummyNoLanguagePerson),
                ILaunchBag,
            )
        )
        self.useFixture(
            ZopeAdapterFixture(
                adaptRequestToLanguages,
                (IBrowserRequest,),
                IRequestPreferredLanguages,
            )
        )
        self.useFixture(
            ZopeAdapterFixture(
                adaptRequestToLanguages,
                (IBrowserRequest,),
                IRequestLocalLanguages,
            )
        )

        languages = preferred_or_request_languages(DummyRequest())
        self.assertEqual(6, len(languages))
        self.assertEqual("ja", languages[0].code)


class TestIsEnglishVariant(TestCase):

    layer = BaseLayer

    def test_fr(self):
        self.assertFalse(is_english_variant(DummyLanguage("fr", 1)))

    def test_en(self):
        self.assertFalse(is_english_variant(DummyLanguage("en", 1)))

    def test_en_CA(self):
        self.assertTrue(is_english_variant(DummyLanguage("en_CA", 1)))

    def test_enm(self):
        self.assertFalse(is_english_variant(DummyLanguage("enm", 1)))
