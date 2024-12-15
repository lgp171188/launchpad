Presenting private bug reports
==============================

When a bug report is public, it says so.

    >>> browser = setupBrowser(auth="Basic foo.bar@canonical.com:test")
    >>> browser.open("http://launchpad.test/bugs/4")
    >>> print(extract_text(find_tag_by_id(browser.contents, "privacy")))
    This report contains Public information...

But when marked private, it gains the standard Launchpad presentation
for private things.

    >>> browser.open("http://bugs.launchpad.test/firefox/+bug/4/+secrecy")
    >>> browser.getControl("Private", index=1).selected = True
    >>> browser.getControl("Change").click()
    >>> print(browser.url)
    http://bugs.launchpad.test/firefox/+bug/4
    >>> print(extract_text(find_tag_by_id(browser.contents, "privacy")))
    This report contains Private information...

Bugs created before we started recording the date and time and who
marked the bug private show only a simple message:

    >>> browser.open("http://launchpad.test/bugs/14")
    >>> print(extract_text(find_tag_by_id(browser.contents, "privacy")))
    This report contains Private Security information...

But newer bugs that are filed private at creation time (like security
bugs or where the product requests that bugs are private by default)
have the full message:

    >>> browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> browser.getControl("Summary", index=0).value = (
    ...     "Firefox crashes when I change the default route"
    ... )
    >>> browser.getControl("Continue").click()

    >>> browser.getControl("Bug Description").value = "foo"
    >>> browser.getControl("Private Security").selected = True
    >>> browser.getControl("Submit Bug Report").click()

    >>> print(browser.url)
    http://bugs.launchpad.test/firefox/+bug/...
    >>> print(extract_text(find_tag_by_id(browser.contents, "privacy")))
    This report contains Private Security information...

XXX 20080708 mpt: Bug 246671 again.

If you visit the private bugs page through its shortcut URL, we don't
redirect you unless you are actually able to see the bug. The reason for
this is that redirecting you already discloses what product or distro
the private bug is in.

Of course, Foo Bar gets redirected:

    >>> browser.open("http://bugs.launchpad.test/bugs/4")
    >>> browser.url
    'http://bugs.launchpad.test/firefox/+bug/4'

But poor old no privs does not, and neither do anonymous users:

    >>> browser = setupBrowser(auth="Basic no-priv@canonical.com:test")
    >>> browser.open("http://bugs.launchpad.test/bugs/4")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: ...

    >>> anon_browser.open("http://bugs.launchpad.test/bugs/4")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound: ...

