Translations front page
=======================

Set up
------

    >>> import transaction
    >>> from lp.app.enums import ServiceUsage
    >>> from lp.registry.interfaces.product import IProductSet
    >>> from zope.component import getUtility
    >>> login("admin@canonical.com")
    >>> evolution = getUtility(IProductSet).getByName("evolution")
    >>> evolution.translations_usage = ServiceUsage.LAUNCHPAD
    >>> logout()
    >>> transaction.commit()

Make the test browser look like it's coming from an arbitrary South African
IP address, since we'll use that later.

    >>> browser.addHeader("X_FORWARDED_FOR", "196.36.161.227")

The front page
--------------

    >>> browser.open("http://translations.launchpad.test/")
    >>> print(browser.title)
    Launchpad Translations

The page includes a list of translatable distribution series
in the left column.

    >>> left_column = find_tags_by_class(
    ...     browser.contents, "three column left"
    ... )[0]
    >>> print(extract_text(left_column))
    Translatable operating systems
    Ubuntu Hoary (5.04)

The middle lists translatable products, Evolution is one of most
translated projects.

    >>> middle_column = find_tags_by_class(
    ...     browser.contents, "three column middle"
    ... )[0]
    >>> heading = middle_column.find_all("h2")[0]
    >>> print(extract_text(heading))
    Translatable projects
    >>> for project in middle_column.find_all("span"):
    ...     print(extract_text(project))
    ...
    Evolution
    >>> print(extract_text(middle_column.find_all("div")[0]))
    » List all translatable projects...

The translation front page list of the user's translatable languages.
in the right column.

    >>> right_column = find_tags_by_class(
    ...     browser.contents, "three column right"
    ... )[0]
    >>> print(extract_text(right_column))
    Your preferred languages
    Afrikaans
    Sotho, Southern
    Xhosa
    Zulu
    ...
    Change your preferred languages...

    >>> right_column.find_all("a")[-1]
    <a href="/+editmylanguages"...Change your preferred languages...
