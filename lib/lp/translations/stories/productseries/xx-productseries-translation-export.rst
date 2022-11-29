Exporting ProductSeries Translations Through the Web
====================================================

Launchpad supports export of entire productseries translations in a single
tarball.  Meant primarily for upstream maintainers, the tarball will contain
all templates for the product series as well as all their translations.


Where to request
----------------

For qualified users (see below), the option is presented in the sidebar as
"Download translations" on the productseries' translations page.

Mark is a qualified user.

    >>> browser = setupBrowser(auth="Basic mark@example.com:test")
    >>> browser.open("http://translations.launchpad.test/evolution/trunk/")
    >>> download = browser.getLink("download")
    >>> download_url = download.url
    >>> download.click()
    >>> print(browser.url)
    http://translations.launchpad.test/evolution/trunk/+export

Another way of getting there is by going to the product's +translate page.
It will select a series of the product as its primary translation target, and
offer a download link for that series.

    >>> browser.open(
    ...     "http://translations.launchpad.test/evolution/+translations"
    ... )
    >>> browser.getLink("download").click()
    >>> print(browser.url)
    http://translations.launchpad.test/evolution/trunk/+export


Authorization
-------------

The option to download an entire productseries' translations is restricted
to users who are involved in certain ways, in order to keep load to a
reasonable level.

    >>> from zope.security.interfaces import Unauthorized
    >>> from zope.testbrowser.browser import LinkNotFoundError

    >>> def can_download_translations(browser):
    ...     """Can browser download full series translations?
    ...
    ...     Checks for the "Download" link on a series.
    ...     Also attempts direct access to the same series' download
    ...     page and sees that the two have consistent access rules.
    ...     """
    ...     browser.open(
    ...         "http://translations.launchpad.test/evolution/trunk/"
    ...     )
    ...     try:
    ...         browser.getLink("download").click()
    ...     except LinkNotFoundError:
    ...         see_link = False
    ...     else:
    ...         see_link = True
    ...
    ...     try:
    ...         browser.open(download_url)
    ...     except Unauthorized:
    ...         have_access = False
    ...     else:
    ...         have_access = True
    ...
    ...     if have_access != see_link:
    ...         if have_access:
    ...             return "Download link not shown, but direct URL works."
    ...         else:
    ...             return "Download link shown to unauthorized user."
    ...
    ...     return have_access
    ...

An arbitrary user visiting the series' translations page does not see the
download link for the full series, and cannot download.

    >>> can_download_translations(user_browser)
    False

It's the same for anonymous visitors.

    >>> can_download_translations(anon_browser)
    False

An administrator, of course, can download the full translations.

    >>> can_download_translations(admin_browser)
    True

A translations expert can download the full translations.

    >>> translations_admin_browser = setupRosettaExpertBrowser()
    >>> can_download_translations(translations_admin_browser)
    True

An owner of an unrelated translation group cannot download translations.

    >>> from lp.testing.pages import setupBrowserForUser

    >>> login("foo.bar@canonical.com")
    >>> group_owner = factory.makePerson()
    >>> translators = factory.makeTeam(group_owner)
    >>> group = factory.makeTranslationGroup(translators)
    >>> logout()
    >>> group_owner_browser = setupBrowserForUser(group_owner)
    >>> can_download_translations(group_owner_browser)
    False

But if the translation group is in charge of translations for this product,
then the translation group owner can download translations.

    >>> from zope.component import getUtility

    >>> from lp.registry.interfaces.product import IProductSet

    >>> login("foo.bar@canonical.com")
    >>> evolution = getUtility(IProductSet).getByName("evolution")
    >>> evolution.translationgroup = group
    >>> logout()
    >>> can_download_translations(group_owner_browser)
    True

The owner of the product can download translations.

    >>> login("foo.bar@canonical.com")
    >>> evolution_owner = evolution.owner
    >>> logout()
    >>> evolution_owner_browser = setupBrowserForUser(evolution_owner)
    >>> can_download_translations(evolution_owner_browser)
    True

The release manager of the product series can download translations.

    >>> login("foo.bar@canonical.com")
    >>> trunk_driver = factory.makePerson()
    >>> evolution.getSeries("trunk").driver = trunk_driver
    >>> logout()
    >>> trunk_driver_browser = setupBrowserForUser(trunk_driver)
    >>> can_download_translations(trunk_driver_browser)
    True


Making the request
------------------

The logged-in user sees a page that lets them select an export format, and
request the download.

    >>> print(browser.title)
    Download : Series trunk : Translations...


File format
...........

The request must specify a file format.

    >>> browser.getControl("Format:").clear()
    >>> browser.getControl("Request Download").click()

    >>> print_feedback_messages(browser.contents)
    Please select a valid format for download.

The most usual and most well-supported format is PO.

    >>> browser.getControl("Format:").value = ["PO"]
    >>> browser.getControl("Request Download").click()

    >>> print(browser.url)
    http://translations.launchpad.test/evolution/trunk

    >>> print_feedback_messages(browser.contents)
    Your request has been received. Expect to receive an email shortly.

An alternative is MO.

    >>> browser.getLink("download").click()
    >>> browser.getControl("Format:").value = ["PO"]
    >>> browser.getControl("Request Download").click()
    >>> print(browser.url)
    http://translations.launchpad.test/evolution/trunk

    >>> print_feedback_messages(browser.contents)
    Your request has been received. Expect to receive an email shortly.


Nothing to export
.................

Where there are no translation files to be exported, the user is not offered
the option to download any.

    >>> browser.open("http://translations.launchpad.test/bzr/trunk/+export")
    >>> print_feedback_messages(browser.contents)
    There are no translations to download in Bazaar trunk series.

On +translate pages for products that do not have any translations, the action
link for "Download translations" is hidden.

    >>> browser.open("http://translations.launchpad.test/bzr/")
    >>> browser.getLink("download")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError
