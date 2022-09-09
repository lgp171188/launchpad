===========
LanguageSet
===========

    >>> from lp.services.worlddata.interfaces.language import ILanguageSet
    >>> language_set = getUtility(ILanguageSet)

getLanguageByCode
=================

We can get hold of languages by their language code.

    >>> language = language_set.getLanguageByCode("es")
    >>> print(language.englishname)
    Spanish

Or if it doesn't exist, we return None.

    >>> language_set.getLanguageByCode("not-existing") is None
    True

canonicalise_language_code
==========================

We can convert language codes to standard form.

    >>> print(language_set.canonicalise_language_code("pt"))
    pt
    >>> print(language_set.canonicalise_language_code("pt_BR"))
    pt_BR
    >>> print(language_set.canonicalise_language_code("pt-br"))
    pt_BR

createLanguage
==============

This method creates a new language.

    >>> foos = language_set.createLanguage("foos", "Foo language")
    >>> print(foos.code)
    foos
    >>> print(foos.englishname)
    Foo language

search
======

We are able to search languages with this method.

    >>> languages = language_set.search("Spanish")
    >>> for language in languages:
    ...     print(language.code, language.englishname)
    ...
    es Spanish
    es_AR Spanish (Argentina)
    es_BO Spanish (Bolivia)
    es_CL Spanish (Chile)
    es_CO Spanish (Colombia)
    es_CR Spanish (Costa Rica)
    es_DO Spanish (Dominican Republic)
    es_EC Spanish (Ecuador)
    es_SV Spanish (El Salvador)
    es_GT Spanish (Guatemala)
    es_HN Spanish (Honduras)
    es_MX Spanish (Mexico)
    es_NI Spanish (Nicaragua)
    es_PA Spanish (Panama)
    es_PY Spanish (Paraguay)
    es_PE Spanish (Peru)
    es_PR Spanish (Puerto Rico)
    es_ES Spanish (Spain)
    es_US Spanish (United States)
    es_UY Spanish (Uruguay)
    es_VE Spanish (Venezuela)
    es@test Spanish test

It's case insensitive:

    >>> languages = language_set.search("spanish")
    >>> for language in languages:
    ...     print(language.code, language.englishname)
    ...
    es Spanish
    es_AR Spanish (Argentina)
    es_BO Spanish (Bolivia)
    es_CL Spanish (Chile)
    es_CO Spanish (Colombia)
    es_CR Spanish (Costa Rica)
    es_DO Spanish (Dominican Republic)
    es_EC Spanish (Ecuador)
    es_SV Spanish (El Salvador)
    es_GT Spanish (Guatemala)
    es_HN Spanish (Honduras)
    es_MX Spanish (Mexico)
    es_NI Spanish (Nicaragua)
    es_PA Spanish (Panama)
    es_PY Spanish (Paraguay)
    es_PE Spanish (Peru)
    es_PR Spanish (Puerto Rico)
    es_ES Spanish (Spain)
    es_US Spanish (United States)
    es_UY Spanish (Uruguay)
    es_VE Spanish (Venezuela)
    es@test Spanish test

And it even does substring searching!

    >>> languages = language_set.search("panis")
    >>> for language in languages:
    ...     print(language.code, language.englishname)
    ...
    es Spanish
    es_AR Spanish (Argentina)
    es_BO Spanish (Bolivia)
    es_CL Spanish (Chile)
    es_CO Spanish (Colombia)
    es_CR Spanish (Costa Rica)
    es_DO Spanish (Dominican Republic)
    es_EC Spanish (Ecuador)
    es_SV Spanish (El Salvador)
    es_GT Spanish (Guatemala)
    es_HN Spanish (Honduras)
    es_MX Spanish (Mexico)
    es_NI Spanish (Nicaragua)
    es_PA Spanish (Panama)
    es_PY Spanish (Paraguay)
    es_PE Spanish (Peru)
    es_PR Spanish (Puerto Rico)
    es_ES Spanish (Spain)
    es_US Spanish (United States)
    es_UY Spanish (Uruguay)
    es_VE Spanish (Venezuela)
    es@test Spanish test

We escape special characters like '%', which is an SQL wildcard
matching any string:

    >>> languages = language_set.search("%")
    >>> for language in languages:
    ...     print(language.code, language.englishname)
    ...

Or '_', which means any character match, but we only get strings
that contain the 'e_' substring:

    >>> languages = language_set.search("e_")
    >>> for language in languages:
    ...     print(language.code, language.englishname)
    ...
    de_AT German (Austria)
    de_BE German (Belgium)
    de_DE German (Germany)
    de_LU German (Luxembourg)
    de_CH German (Switzerland)


========
Language
========

The Language object represents a language.

alt_suggestion_language
=======================

In some languages, you could reasonably expect to find good suggestions in a
second language. They might not be perfect but they are useful nonetheless.

pt_BR is not a descendent of pt:

    >>> pt_BR = language_set.getLanguageByCode("pt_BR")
    >>> print(pt_BR.alt_suggestion_language)
    None

However, es_MX would find es useful:

    >>> language = language_set.getLanguageByCode("es_MX")
    >>> print(language.alt_suggestion_language.code)
    es

And Nynorsk and Bokmål have a special relationship:

    >>> language = language_set.getLanguageByCode("nn")
    >>> print(language.alt_suggestion_language.code)
    nb

    >>> language = language_set.getLanguageByCode("nb")
    >>> print(language.alt_suggestion_language.code)
    nn

English and non-visible languages are not translatable, so there
are no suggestions.

    >>> language = language_set.getLanguageByCode("en")
    >>> language.alt_suggestion_language is None
    True

    >>> language = language_set.getLanguageByCode("zh")
    >>> language.visible
    False
    >>> language.alt_suggestion_language is None
    True

Languages have a useful string representation containing its English name in
quotes and its language code in parentheses.

    >>> language
    <Language 'Chinese' (zh)>


dashedcode
==========

Although we use underscores to separate language and country codes to
represent, for instance pt_BR, when used on web pages, it should use
instead a dash char. This method does it automatically:

    >>> pt_BR = language_set.getLanguageByCode("pt_BR")
    >>> print(pt_BR.dashedcode)
    pt-BR


translators
===========

Property `translators` contains the list of `Person`s who are considered
translators for this language.

    >>> sr = language_set.getLanguageByCode("sr")
    >>> list(sr.translators)
    []

To be considered a translator, they must have done some translations and
have the language among their preferred languages.

    >>> translator_10 = factory.makePerson(name="serbian-translator-karma-10")
    >>> translator_10.addLanguage(sr)
    >>> translator_20 = factory.makePerson(name="serbian-translator-karma-20")
    >>> translator_20.addLanguage(sr)
    >>> translator_30 = factory.makePerson(name="serbian-translator-karma-30")
    >>> translator_30.addLanguage(sr)
    >>> translator_40 = factory.makePerson(name="serbian-translator-karma-40")
    >>> translator_40.addLanguage(sr)

    # We need to fake some Karma.
    >>> from lp.registry.interfaces.karma import IKarmaCacheManager
    >>> from lp.registry.model.karma import KarmaCategory
    >>> from lp.services.database.interfaces import IStore
    >>> from lp.testing.dbuser import switch_dbuser

    >>> switch_dbuser("karma")
    >>> translations_category = (
    ...     IStore(KarmaCategory)
    ...     .find(KarmaCategory, name="translations")
    ...     .one()
    ... )
    >>> cache_manager = getUtility(IKarmaCacheManager)
    >>> karma = cache_manager.new(
    ...     person_id=translator_30.id,
    ...     category_id=translations_category.id,
    ...     value=30,
    ... )
    >>> karma = cache_manager.new(
    ...     person_id=translator_10.id,
    ...     category_id=translations_category.id,
    ...     value=10,
    ... )
    >>> karma = cache_manager.new(
    ...     person_id=translator_20.id,
    ...     category_id=translations_category.id,
    ...     value=20,
    ... )
    >>> karma = cache_manager.new(
    ...     person_id=translator_40.id,
    ...     category_id=translations_category.id,
    ...     value=40,
    ... )
    >>> switch_dbuser("launchpad")
    >>> for translator in sr.translators:
    ...     print(translator.name)
    ...
    serbian-translator-karma-40
    serbian-translator-karma-30
    serbian-translator-karma-20
    serbian-translator-karma-10


=========
Countries
=========

Property holding a list of countries a language is spoken in, and allowing
reading and setting them.

    >>> es = language_set.getLanguageByCode("es")
    >>> for country in es.countries:
    ...     print(country.name)
    ...
    Argentina
    Bolivia
    Chile
    Colombia
    Costa Rica
    Dominican Republic
    Ecuador
    El Salvador
    Guatemala
    Honduras
    Mexico
    Nicaragua
    Panama
    Paraguay
    Peru
    Puerto Rico
    Spain
    United States
    Uruguay
    Venezuela

We can add countries using `ILanguage.addCountry` method.

    >>> from lp.services.worlddata.interfaces.country import ICountrySet
    >>> country_set = getUtility(ICountrySet)
    >>> germany = country_set["DE"]
    >>> es.addCountry(germany)
    >>> for country in es.countries:
    ...     print(country.name)
    ...
    Argentina
    Bolivia
    Chile
    Colombia
    Costa Rica
    Dominican Republic
    Ecuador
    El Salvador
    Germany
    Guatemala
    Honduras
    Mexico
    Nicaragua
    Panama
    Paraguay
    Peru
    Puerto Rico
    Spain
    United States
    Uruguay
    Venezuela

Or, we can remove countries using `ILanguage.removeCountry` method.

    >>> argentina = country_set["AR"]
    >>> es.removeCountry(argentina)
    >>> for country in es.countries:
    ...     print(country.name)
    ...
    Bolivia
    Chile
    Colombia
    Costa Rica
    Dominican Republic
    Ecuador
    El Salvador
    Germany
    Guatemala
    Honduras
    Mexico
    Nicaragua
    Panama
    Paraguay
    Peru
    Puerto Rico
    Spain
    United States
    Uruguay
    Venezuela

We can also assign a complete set of languages directly to `countries`,
but we need to log in as a translations administrator first.

    >>> login("carlos@canonical.com")
    >>> es.countries = set([argentina, germany])
    >>> for country in es.countries:
    ...     print(country.name)
    ...
    Argentina
    Germany
