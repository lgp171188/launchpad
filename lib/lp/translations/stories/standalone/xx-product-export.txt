Downloading Product Series Translations
=======================================

Products and product series that use Translations offer complete
translation downloads.

    >>> user_browser.open('http://translations.launchpad.test/evolution')
    >>> download = user_browser.getLink('download')

For products, that option downloads translations for the series that is
currently the preferred translation target.

    >>> download_url = download.url
    >>> download_url
    'http://translations.launchpad.test/evolution/trunk/+export'

Another way of getting that same export would be to browse to the series
first and requesting a download there.

    >>> user_browser.open(
    ...     'http://translations.launchpad.test/evolution/trunk')
    >>> user_browser.getLink('download').click()
    >>> user_browser.url
    'http://translations.launchpad.test/evolution/trunk/+export'

The translations export is implemented by the same machinery that does
it for source packages (tested and documented separately).

    >>> print(user_browser.title)
    Download : Series trunk : Translations...

    >>> user_browser.getControl('Request Download').click()
    >>> print_feedback_messages(user_browser.contents)
    Your request has been received.  Expect to receive an email shortly.


Use of Launchpad Translations
-----------------------------

The Download link is not shown if the product does not use Launchpad
Translations.

Use the DB classes directly to avoid having to setup a zope interaction
(i.e. login()) and bypass the security proxy.

    >>> from lp.app.enums import ServiceUsage
    >>> from lp.registry.model.product import Product
    >>> product = Product.byName('evolution')
    >>> product.translations_usage = ServiceUsage.NOT_APPLICABLE
    >>> product.sync()
    >>> user_browser.open('http://translations.launchpad.test/evolution')
    >>> user_browser.getLink('download')
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

Restore previous state for subsequent tests, and verify.

    >>> product.translations_usage = ServiceUsage.LAUNCHPAD
    >>> product.sync()
    >>> user_browser.open('http://translations.launchpad.test/evolution')
    >>> user_browser.getLink('download') is not None
    True


Authorization
-------------

Only logged-in users get the option to request downloads.

    >>> anon_browser.open('http://translations.launchpad.test/evolution/')
    >>> anon_browser.getLink('download').click()
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

We can't see its placeholder in non-development mode:

    >>> from lp.services.config import config
    >>> config.launchpad.devmode
    True
    >>> config.push('devmode_test', '\n[launchpad]\ndevmode: true\n')
    >>> anon_browser.open('http://translations.launchpad.test/evolution/')
    >>> for tag in find_tags_by_class(
    ...     anon_browser.contents, 'menu-link-translationdownload'):
    ...     print(tag.decode_contents())

    # Reset global configuration...
    >>> _ = config.pop('devmode_test')

Even "hacking the URL" to the download option will fail.

    >>> anon_browser.open(download_url)
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...
