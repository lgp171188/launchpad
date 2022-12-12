Distribution mirror prober logs
===============================

Every time we probe a mirror for its contents we keep a log of the probe.
All these logs can be seen by the mirror owner or the mirror admin of
that mirror's distribution or Launchpad team members.

    >>> browser.addHeader("Authorization", "Basic mark@example.com:test")
    >>> browser.open("http://launchpad.test/ubuntu/+mirror/archive-mirror2/")

    >>> browser.getLink("Prober logs").click()
    >>> browser.url
    'http://launchpad.test/ubuntu/+mirror/archive-mirror2/+prober-logs'

    >>> navigation = find_tags_by_class(
    ...     browser.contents, "batch-navigation-index"
    ... )[0]
    >>> print(extract_text(navigation.decode_contents()))
    1...→...1...of...1...result

    >>> login("admin@canonical.com")
    >>> from zope.component import getUtility
    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> launchpad_developer = factory.makePerson(
    ...     member_of=[getUtility(ILaunchpadCelebrities).launchpad_developers]
    ... )
    >>> from lp.testing import logout
    >>> logout()

    >>> from lp.testing.pages import setupBrowserForUser
    >>> lp_dev_browser = setupBrowserForUser(launchpad_developer)
    >>> lp_dev_browser.open(
    ...     "http://launchpad.test/ubuntu/+mirror/archive-mirror2/"
    ... )
    >>> lp_dev_browser.getLink("Prober logs").click()
    >>> lp_dev_browser.url
    'http://launchpad.test/ubuntu/+mirror/archive-mirror2/+prober-logs'

    >>> navigation = find_tags_by_class(
    ...     lp_dev_browser.contents, "batch-navigation-index"
    ... )[0]
    >>> print(extract_text(navigation.decode_contents()))
    1...→...1...of...1...result


A random logged in user won't have the rights to see that page.

    >>> user_browser.open(
    ...     "http://launchpad.test/ubuntu/+mirror/archive-mirror2/"
    ... )
    >>> user_browser.getLink("Content check logs")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

    >>> user_browser.open(
    ...     "http://launchpad.test/ubuntu/+mirror/archive-mirror2/"
    ...     "+prober-logs"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...
