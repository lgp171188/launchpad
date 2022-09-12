An anonymous user who tries to access the bugtask edit page will be
redirected to the login page.

    >>> browser.open("http://launchpad.test/thunderbird/+bug/9/+editstatus")
    Traceback (most recent call last):
      ...
    zope.security.interfaces.Unauthorized: ...

Even when the product has a bug supervisor, see bug #49891.

    >>> from zope.component import getUtility
    >>> from lp.testing import login, logout
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.product import IProductSet

    >>> login("test@canonical.com")

    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> sample_person = getUtility(IPersonSet).getByName("name12")
    >>> firefox.bug_supervisor = sample_person

    >>> logout()

    >>> browser.open("http://launchpad.test/firefox/+bug/1/+editstatus")
    Traceback (most recent call last):
      ...
    zope.security.interfaces.Unauthorized: ...

Any logged-in user can edit a bugtask.

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open("http://launchpad.test/firefox/+bug/6/+editstatus")
    >>> print(browser.title)
    Edit status ...

But only privileged users can edit bugtasks on locked bugs.

    >>> from zope.component import getUtility
    >>> from lp.bugs.enums import BugLockStatus
    >>> from lp.bugs.interfaces.bug import IBugSet

    >>> login("test@canonical.com")
    >>> getUtility(IBugSet).get(6).lock(
    ...     who=sample_person, status=BugLockStatus.COMMENT_ONLY
    ... )
    >>> logout()

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open("http://launchpad.test/firefox/+bug/6/+editstatus")
    >>> print(browser.title)
    Edit status ...

    >>> user_browser.open("http://launchpad.test/firefox/+bug/6/+editstatus")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...
