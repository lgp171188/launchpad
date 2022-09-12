DistributionSourcePackage translations
======================================

Make the test browser look like it's coming from an arbitrary South African
IP address, since we'll use that later.

    >>> anon_browser.addHeader("X_FORWARDED_FOR", "196.36.161.227")

This page directs users to SourcePackage translations pages.

    >>> anon_browser.open(
    ...     "http://translations.launchpad.test/ubuntu/+source/evolution"
    ... )
    >>> anon_browser.title
    'Translations : ...evolution...package : Ubuntu'

    >>> content = find_main_content(anon_browser.contents)
    >>> print(extract_text(content.find(attrs="top-portlet")))
    Launchpad currently recommends translating evolution in Ubuntu Hoary.

The focus' two templates are shown.

    >>> template_names = content.find_all("h2")
    >>> for name in template_names:
    ...     print(extract_text(name))
    ...
    Template "evolution-2.2" in Ubuntu Hoary package "evolution"
    Template "man" in Ubuntu Hoary package "evolution"
    Other versions of evolution in Ubuntu

Other series are also listed.

    >>> for other in content.find(id="distroseries-list").find_all("li"):
    ...     print(extract_text(other))
    ...
    Breezy Badger Autotest (6.6.6)
    Grumpy (5.10)
    Warty (4.10)
