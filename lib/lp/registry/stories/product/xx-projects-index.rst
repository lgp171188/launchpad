Just make sure this page contains the right links:

    >>> user_browser.open("http://launchpad.test/projects/")

This link was removed.

    >>> user_browser.getLink("Show all teams").url
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

The "Show all projects" link is still there.

    >>> user_browser.getLink("Show all projects").url
    'http://launchpad.test/projects/+all'
