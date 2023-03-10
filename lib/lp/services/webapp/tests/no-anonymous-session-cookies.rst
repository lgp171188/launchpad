We will verify that we do not put session cookies in anonymous requests. This
is important for caching anonymous requests in front of Zope, such as with
Squid.  Note that we are checking whether the browser has a session cookie
set, not whether the server has sent a "set-cookie" header.

When we go to launchpad as an anonymous user, the browser has no cookies.

    >>> from lp.testing.layers import BaseLayer
    >>> root_url = BaseLayer.appserver_root_url()
    >>> browser.open(root_url)
    >>> len(browser.cookies)
    0

Now let's log in and show that the session cookie is set.

    >>> from datetime import datetime, timedelta, timezone
    >>> now = datetime.now(timezone.utc).replace(microsecond=0)
    >>> year_from_now = now + timedelta(days=365)
    >>> year_plus_from_now = year_from_now + timedelta(minutes=1)
    >>> browser.open("%s/+login" % root_url)

    # On a browser with JS support, this page would've been automatically
    # submitted (thanks to the onload handler), but testbrowser doesn't
    # support JS, so we have to submit the form manually.
    >>> print(browser.contents)
    <html>...<body onload="document.forms[0].submit();"...
    >>> browser.getControl("Continue").click()

    >>> from lp.services.webapp.tests.test_login import (
    ...     fill_login_form_and_submit,
    ... )
    >>> fill_login_form_and_submit(browser, "foo.bar@canonical.com")
    >>> print(extract_text(find_tag_by_id(browser.contents, "logincontrol")))
    Foo Bar (name16) ...

    # Open a page again so that we see the cookie for a launchpad.test request
    # and not a testopenid.test request (as above).
    >>> browser.open(root_url)

    >>> len(browser.cookies)
    1
    >>> browser.cookies.keys()
    ['launchpad_tests']
    >>> expires = browser.cookies.getinfo("launchpad_tests")["expires"]
    >>> year_from_now <= expires < year_plus_from_now
    True
    >>> browser.cookies.getinfo("launchpad_tests")["domain"]
    '.launchpad.test'

The cookie will be set to expire in ten minutes when you log out.  The ten
minute time interval (set in lp.services.webapp.login and enforced
with an assert in lp.services.webapp.session) is intended to be fudge
time for browsers with bad system clocks.

    >>> browser.followRedirects = False
    >>> browser.getControl("Log Out").click()
    >>> print(browser.headers["Status"])
    303 See Other
    >>> print(browser.headers["Location"])
    https://bazaar.launchpad.test/+logout?next_to=...

After ensuring the browser has not left the launchpad.test domain, the
single cookie is shown to have the ten minute expiration.

    >>> browser.open(root_url)
    >>> len(browser.cookies)
    1
    >>> expires = browser.cookies.getinfo("launchpad_tests")["expires"]
    >>> ten_minutes_from_now = now + timedelta(minutes=10)
    >>> eleven_minutes_from_now = now + timedelta(minutes=11)
    >>> ten_minutes_from_now <= expires < eleven_minutes_from_now
    True
