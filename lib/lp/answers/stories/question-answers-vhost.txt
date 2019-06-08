Answers Default Pages
=====================

The answers.launchpad.net domain is used for the Answer Tracker
application. When visiting objects on that virtual host, the default
selected facet is the Answers facet.


Product
-------

    >>> anon_browser.open('http://answers.launchpad.test/firefox')
    >>> print(anon_browser.title)
    Questions : Mozilla Firefox


Distribution
------------

    >>> anon_browser.open('http://answers.launchpad.test/ubuntu')
    >>> print(anon_browser.title)
    Questions : Ubuntu


Distribution Source Package
---------------------------

    >>> anon_browser.open(
    ...     'http://answers.launchpad.test/ubuntu/+source/mozilla-firefox')
    >>> print(anon_browser.title)
    Questions : mozilla-firefox package : Ubuntu


ProjectGroup
------------

    >>> anon_browser.open(
    ...     'http://answers.launchpad.test/mozilla')
    >>> print(anon_browser.title)
    Questions : The Mozilla Project


Person
------

    >>> anon_browser.open('http://answers.launchpad.test/~name16')
    >>> print(anon_browser.title)
    Questions : Foo Bar
