Say hello to Bugs. :)

    >>> browser.open("http://bugs.launchpad.test/")
    >>> browser.url
    'http://bugs.launchpad.test/'

    >>> print(browser.title)
    Launchpad Bugs

There are a few related pages linked in a portlet:

    >>> related_pages = find_portlet(browser.contents, "Related pages")
    >>> for link in related_pages.find_all("a"):
    ...     print("%s\n  --> %s" % (extract_text(link), link.get("href")))
    ...
    Bug trackers
    --> http://bugs.launchpad.test/bugs/bugtrackers
    CVE tracker
    --> http://bugs.launchpad.test/bugs/cve
