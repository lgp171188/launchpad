Feeds do not display private bugs
=================================

Feeds never contain private bugs, as we are serving feeds over HTTP.
First, set all the bugs to private.

    >>> import transaction
    >>> from zope.security.interfaces import Unauthorized
    >>> from lp.app.enums import InformationType
    >>> from lp.bugs.model.bug import Bug
    >>> from lp.services.beautifulsoup import BeautifulSoup
    >>> from lp.services.database.interfaces import IStore
    >>> IStore(Bug).find(Bug).set(information_type=InformationType.USERDATA)
    >>> transaction.commit()

There should be zero entries in these feeds, since all the bugs are private.

    >>> browser.open("http://feeds.launchpad.test/jokosher/latest-bugs.atom")
    >>> BeautifulSoup(browser.contents, "xml")("entry")
    []

    >>> browser.open("http://feeds.launchpad.test/mozilla/latest-bugs.atom")
    >>> BeautifulSoup(browser.contents, "xml")("entry")
    []

    >>> browser.open("http://feeds.launchpad.test/~name16/latest-bugs.atom")
    >>> BeautifulSoup(browser.contents, "xml")("entry")
    []

    >>> browser.open(
    ...     "http://feeds.launchpad.test/~simple-team/latest-bugs.atom"
    ... )
    >>> BeautifulSoup(browser.contents, "xml")("entry")
    []

    >>> browser.open(
    ...     "http://feeds.launchpad.test/bugs/+bugs.atom?"
    ...     "field.searchtext=&search=Search+Bug+Reports&"
    ...     "field.scope=all&field.scope.target="
    ... )
    >>> BeautifulSoup(browser.contents, "xml")("entry")
    []

There should be just one <tr> elements for the table header in
these HTML feeds, since all the bugs are private.

    >>> browser.open("http://feeds.launchpad.test/jokosher/latest-bugs.html")
    >>> len(BeautifulSoup(browser.contents, "xml")("tr"))
    1

    >>> print(extract_text(BeautifulSoup(browser.contents, "xml")("tr")[0]))
    Bugs in Jokosher

    >>> browser.open("http://feeds.launchpad.test/mozilla/latest-bugs.html")
    >>> len(BeautifulSoup(browser.contents, "xml")("tr"))
    1

    >>> print(extract_text(BeautifulSoup(browser.contents, "xml")("tr")[0]))
    Bugs in The Mozilla Project

    >>> browser.open("http://feeds.launchpad.test/~name16/latest-bugs.html")
    >>> len(BeautifulSoup(browser.contents, "xml")("tr"))
    1

    >>> print(extract_text(BeautifulSoup(browser.contents, "xml")("tr")[0]))
    Bugs for Foo Bar

    >>> browser.open(
    ...     "http://feeds.launchpad.test/~simple-team/latest-bugs.html"
    ... )
    >>> len(BeautifulSoup(browser.contents, "xml")("tr"))
    1

    >>> print(extract_text(BeautifulSoup(browser.contents, "xml")("tr")[0]))
    Bugs for Simple Team

    >>> browser.open(
    ...     "http://feeds.launchpad.test/bugs/+bugs.html?"
    ...     "field.searchtext=&search=Search+Bug+Reports&"
    ...     "field.scope=all&field.scope.target="
    ... )
    >>> len(BeautifulSoup(browser.contents, "xml")("tr"))
    1

    >>> try:
    ...     browser.open("http://feeds.launchpad.test/bugs/1/bug.html")
    ... except Unauthorized:
    ...     print("Shouldn't  raise Unauthorized exception")
    ...
    >>> BeautifulSoup(browser.contents, "xml")("entry")
    []
