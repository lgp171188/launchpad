There is a list of IProduct objects that have translations and are using
Launchpad Translations officially from a IProjectGroup's translations page.

GNOME is a good example, it has products with translations.

    >>> browser.open('http://translations.launchpad.test/gnome')
    >>> print(browser.url)
    http://translations.launchpad.test/gnome

Evolution being one with translations and being used officially

    >>> evo_link = browser.getLink('Evolution')
    >>> print(evo_link.url)
    http://launchpad.test/evolution/+translations

    >>> browser.open('http://translations.launchpad.test/gnome')
    >>> print(browser.url)
    http://translations.launchpad.test/gnome

Netapplet is another product of GNOME project. It has translations,
but it's not using Launchpad officially, so it's not listed among
translatable projects.

    >>> translated_projects = find_tag_by_id(
    ...     browser.contents, 'translatable-projects')
    >>> link = translated_projects.find(text='Network Applet')
    >>> print(link)
    None

It does show up among untranslated projects.

    >>> untranslated_projects = find_tag_by_id(
    ...     browser.contents, 'untranslatable-projects')
    >>> link = untranslated_projects.find(text='NetApplet').parent
    >>> print(link['href'])
    http://launchpad.test/netapplet/+translations

Let's confirm what we just stated.

    >>> anon_browser.open('http://launchpad.test/gnome')
    >>> anon_browser.getLink('NetApplet').click()
    >>> print(anon_browser.title)
    NetApplet in Launchpad

Anonymous users don't see the translations

    >>> anon_browser.getLink('Translations').click()
    >>> print(anon_browser.title)
    Translations : NetApplet

    >>> find_tag_by_id(
    ...     anon_browser.contents,
    ...     'portlet-obsolete-translatable-series') is None
    True

alsa-utils is a product that doesn't belong to GNOME project. It has
translations and is using Launchpad Translations officially, and it
shouldn't appear in GNOME project translations page.

    >>> browser.open('http://translations.launchpad.test/gnome')
    >>> browser.getLink('alsa-utils')
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

Let's confirm what we just stated.

    >>> browser.open('http://launchpad.test/gnome')
    >>> print(browser.url)
    http://launchpad.test/gnome

alsa-utils does not belong to GNOME project.

    >>> browser.getLink('alsa-utils')
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

It's using Launchpad Translations officially. And it has translations.

    >>> browser.open('http://translations.launchpad.test/alsa-utils')
    >>> print(browser.url)
    http://translations.launchpad.test/alsa-utils

    >>> alsa_utils_spanish = browser.getLink('Spanish')
    >>> print(alsa_utils_spanish.url)
    http://translations.../alsa-utils/trunk/+pots/alsa-utils/es/+translate
