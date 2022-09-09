API Documentation
=================

The Launchpad API documentation portal is available at
http://launchpad.test/+apidoc. It contains summaries of the different
web service versions, and links to version-specific documents.

    >>> browser.open("http://launchpad.test/+apidoc")
    >>> print(extract_text(browser.contents))
    Launchpad Web Service API
    ...
    Launchpad web service API documentation
    ...
    Active versions
    ...
    devel: This version of the web service reflects the most recent...
    ...

The documentation for a specific version is located at
http://launchpad.test/+apidoc/{version}.html.

    >>> browser.open("http://launchpad.test/+apidoc/devel.html")
    >>> print(browser.title)
    About this service

