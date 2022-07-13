Sourcepackage translations
==========================

This page shows a list of PO templates contained a specific source package
in a particular distribution series. In this case, we're asking for the
translation overview for Evolution in Hoary.

Make the test browser look like it's coming from an arbitrary South African
IP address, since we'll use that later.

    >>> anon_browser.addHeader('X_FORWARDED_FOR', '196.36.161.227')

    >>> anon_browser.open(
    ...     'http://translations.launchpad.test/ubuntu/hoary/'
    ...     '+source/evolution')
    >>> anon_browser.title
    'Hoary (5.04) : Translations : ...evolution...package : Ubuntu'

    >>> content = find_main_content(anon_browser.contents)
    >>> print(backslashreplace(extract_text(content.find_all('h1')[0])))
    Translations for evolution in Ubuntu Hoary

There are two templates for evolution in Ubuntu Hoary

    >>> template_names = content.find_all('h2')
    >>> for name in template_names:
    ...     print(extract_text(name))
    Template "evolution-2.2" in Ubuntu Hoary package "evolution"
    Template "man" in Ubuntu Hoary package "evolution"

Each template lists it's language translation statuses that are
comprised of the translated languages plus the languages of the user,
(except for English which is not translatable). For the Template
"evolution-2.2", there are 22 untranslated strings for each language.
100% of the strings are untranslated. The Last and Edited By columns
indicate that these languages have never been edited my anyone.

    >>> table = content.find_all('table')[0]
    >>> for row in table.find_all('tr'):
    ...     print(extract_text(row, formatter='html'))
    Language        Status Untranslated Need review Changed Last    Edited By
    Afrikaans              22             ...         ...   &mdash; &mdash;
    Sotho, Southern        22             ...         ...   &mdash; &mdash;
    Xhosa                  22             ...         ...   2005-06-15 &mdash;
    Zulu                   22             ...         ...   &mdash; &mdash;
