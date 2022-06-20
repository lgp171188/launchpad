Traversing to pillars
=====================

Our pillars can have any number of aliases, and these aliases can be used to
traverse to that pillar.  As an example we'll add an alias to the firefox
product and show that accessing it using the alias will redirect to its
canonical URL.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.product import IProductSet
    >>> login(ANONYMOUS)
    >>> getUtility(IProductSet)['firefox'].aliases
    []
    >>> logout()

    >>> browser.open('http://launchpad.test/firefox')

    >>> browser.open('http://launchpad.test/iceweasel')
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: ...

    >>> login('mark@example.com')
    >>> getUtility(IProductSet)['firefox'].setAliases(['iceweasel'])
    >>> logout()

    >>> browser.open('http://launchpad.test/iceweasel')
    >>> browser.url
    'http://launchpad.test/firefox'
