When filing a private security bug upstream, with no upstream bug
contact, the maintainer will be subscribed to the bug instead.

    >>> browser = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser.open("http://localhost:9000/firefox/+filebug")
    >>> browser.getControl("Summary", index=0).value = (
    ...     "this is a newly created private bug"
    ... )
    >>> browser.getControl("Continue").click()

    >>> browser.getControl(name="field.title").value = (
    ...     "this is a newly created private bug"
    ... )
    >>> browser.getControl(name="field.comment").value = (
    ...     "very secret info here"
    ... )
    >>> browser.getControl("Private Security").selected = True
    >>> browser.getControl("Submit Bug Report").click()

    >>> bug_id = browser.url.split("/")[-1]
    >>> print(browser.url.replace(bug_id, "BUG-ID"))
    http://bugs.launchpad.test/firefox/+bug/BUG-ID


Now the reporter is subscribed.

    >>> from operator import attrgetter

    >>> from zope.component import getUtility

    >>> from lp.testing import login, logout
    >>> from lp.bugs.interfaces.bug import IBugSet

    >>> login("foo.bar@canonical.com")

    >>> bug = getUtility(IBugSet).get(bug_id)

    >>> for subscriber in sorted(
    ...     bug.getDirectSubscribers(), key=attrgetter("name")
    ... ):
    ...     print(subscriber.name)
    name16

    >>> logout()

Of course, we're able to see the private bug we've just filed in the
bug listing.

    >>> browser.open("http://localhost:9000/firefox/+bugs")
    >>> print(browser.contents.replace(bug_id, "BUG-ID"))
    <!DOCTYPE...
    ...
    ...Mozilla Firefox...
    ...
    ...4 results...
    ...
    ...<div class="importance importanceCRITICAL"> Critical </div>...
    ...<span class="bugnumber">#5</span>...
    ...
    ...<div class="importance importanceMEDIUM"> Medium </div>...
    ...<span class="bugnumber">#4</span>...
    ...
    ...<div class="importance importanceLOW"> Low </div>...
    ...<span class="bugnumber">#1</span>...
    ...
    ...<div class="importance importanceUNDECIDED"> Undecided </div>...
    ...<span class="bugnumber">#BUG-ID</span>...

Checking basic access to the private bug pages
----------------------------------------------

Trying to access the task edit page of a task on a private bug
fails, because we pretend that inaccessible private bugs do not exist.

    >>> browser = setupBrowser()
    >>> browser.open(
    ...     "http://launchpad.test/firefox/+bug/%s/+editstatus" % bug_id
    ... )
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: ...

The no-privs user cannot access bug #10, because it's filed on a private bug
on which the no-privs is not an explicit subscriber.

    >>> browser = setupBrowser(auth="Basic no-priv@canonical.com:test")
    >>> browser.open(
    ...     "http://launchpad.test/firefox/+bug/%s/+editstatus" % bug_id
    ... )
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: ...

Foo Bar accesses the bug page of a private bug. They are allowed to
view the page because they are an explicit subscriber on the bug.

    >>> browser = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser.open("http://launchpad.test/firefox/+bug/%s" % bug_id)
    >>> print(browser.headers["Status"])
    200 Ok

They now access the task page of a task on a private bug; also permitted.

    >>> browser = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser.open(
    ...     "http://launchpad.test/firefox/+bug/%s/+editstatus" % bug_id
    ... )
    >>> print(browser.headers["Status"])
    200 Ok



View the bug task listing page as an anonymous user. Note that the
private bug just filed by Sample Person is not visible.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /firefox/+bugs HTTP/1.1
    ... Accept-Language: en-ca,en-us;q=0.8,en;q=0.5,fr-ca;q=0.3
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...3 results...
    ...<span class="bugnumber">#5</span>...
    ...<span class="bugnumber">#4</span>...
    ...<span class="bugnumber">#1</span>...
    ...

Trying to access a private upstream bug as an anonymous user results
in a page not found error.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /firefox/+bug/6 HTTP/1.1
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /firefox/+bug/14 HTTP/1.1
    ... """
    ...     )
    ... )
    HTTP/1.1 404 Not Found
    ...

View the upstream Firefox bug listing as user Foo Bar. Note that Foo
Bar cannot see in this listing the private bug that Sample Person
submitted earlier.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /firefox/+bugs HTTP/1.1
    ... Authorization: Basic Zm9vLmJhckBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...Mozilla Firefox...
    ...<span class="bugnumber">#5</span>...
    ...Firefox install instructions should be complete...
    ...<span class="bugnumber">#4</span>...
    ...Reflow problems with complex page layouts...
    ...<span class="bugnumber">#1</span>...
    ...Firefox does not support SVG...
    ...


View bugs on Mozilla Firefox as the no-privs user:

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /firefox/+bugs HTTP/1.1
    ... Authorization: Basic bm8tcHJpdkBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 200 Ok
    ...
        Mozilla Firefox
    ...

Note that the no-privs user doesn't have the permissions to see bug #13.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /firefox/+bug/14 HTTP/1.1
    ... Authorization: Basic bm8tcHJpdkBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 404 Not Found
    ...

This is also true if no-privs tries to access the bug from another
context.

    >>> print(
    ...     http(
    ...         rb"""
    ... GET /tomcat/+bug/14 HTTP/1.1
    ... Authorization: Basic bm8tcHJpdkBjYW5vbmljYWwuY29tOnRlc3Q=
    ... """
    ...     )
    ... )
    HTTP/1.1 404 Not Found
    ...
