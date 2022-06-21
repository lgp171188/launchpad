=============
Distributions
=============

Launchpad can be used by both upstream projects and distributions - the
system understands the intrinsic differences between those kinds of
organisation. This test just ensures we can view the distributions in the
system.


Distribution listings
=====================

There is a listing of all distributions at /distros/:

    >>> anon_browser.open('http://launchpad.test/distros/')
    >>> print(anon_browser.title)
    Distributions registered in Launchpad


Distribution home pages
=======================

Each distribution has a home page in the system.  The page will show a
consolidated view of active series, milestones and derivatives of that
series.

Some distributions have listings of major versions, for example Debian:

    >>> anon_browser.open('http://launchpad.test/debian')
    >>> print(extract_text(find_tag_by_id(anon_browser.contents, 'sandm')))
    Active series and milestones
    3.1 “Sarge” series - frozen
    3.0 “Woody” series - current
        Milestones: 3.1 and 3.1-rc1
    All series
    All milestones

If we add another milestone the list is well formatted using English grammar
rules.

    >>> admin_browser.open("http://launchpad.test/debian/woody/+addmilestone")
    >>> admin_browser.getControl("Name:").value = "testmilestone"
    >>> admin_browser.getControl("Register Milestone").click()

    >>> anon_browser.open('http://launchpad.test/debian')
    >>> print(extract_text(find_tag_by_id(anon_browser.contents, 'sandm')))
    Active series and milestones
    ...
        Milestones: testmilestone, 3.1, and 3.1-rc1
    ...

Each series and milestone are links that take you to that
series and milestone page.

    >>> print(anon_browser.getLink(url='/debian/sarge').text)
    3.1 “Sarge” series

    >>> print(anon_browser.getLink(url='/debian/woody').text)
    3.0 “Woody” series

    >>> anon_browser.getLink(url='/debian/+milestone/3.1').text
    '3.1'

    >>> anon_browser.getLink(url='/debian/+milestone/3.1-rc1').text
    '3.1-rc1'

There are also two links "All series" and "All milestones" that take you
to the distribution series and milestones pages respectively.

    >>> anon_browser.getLink('All series').url
    'http://launchpad.test/debian/+series'

    >>> anon_browser.getLink('All milestones').url
    'http://launchpad.test/debian/+milestones'

Others do not have any series so the portlet is not shown.

    >>> anon_browser.open('http://launchpad.test/gentoo')
    >>> print(find_tag_by_id(anon_browser.contents, 'sandm'))
    None

The 5 latest derivatives are displayed on the home page
along with a link to list all of them.

    >>> anon_browser.open('http://launchpad.test/ubuntu')
    >>> print(extract_text(
    ...     find_tag_by_id(anon_browser.contents, 'derivatives')))
    Latest derivatives
    9.9.9
    “Hoary Mock” series
    (from Warty)
    8.06
    “Krunch” series
    (from Hoary)
    6.6.6
    “Breezy Badger Autotest” series
    (from Warty)
    2005
    “Guada2005” series
    (from Hoary)
    All derivatives


The "All derivatives" link takes you to the derivatives page.

    >>> anon_browser.getLink('All derivatives').url
    'http://launchpad.test/ubuntu/+derivatives'

If there are no derivatives, the link to the derivatives page is
not there.

    >>> anon_browser.open('http://launchpad.test/ubuntutest')
    >>> print(extract_text(
    ...     find_tag_by_id(anon_browser.contents, 'derivatives')))
    Latest derivatives
    No derivatives.


If there is a development series alias, it becomes a redirect.

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.testing import celebrity_logged_in
    >>> from zope.component import getUtility

    >>> anon_browser.open("http://launchpad.test/ubuntu/devel")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound:
    Object: <Distribution ...>, name: 'devel'

    >>> with celebrity_logged_in("admin"):
    ...     ubuntu = getUtility(IDistributionSet).getByName(u"ubuntu")
    ...     ubuntu.development_series_alias = "devel"
    >>> anon_browser.open("http://launchpad.test/ubuntu/devel")
    >>> print(anon_browser.url)
    http://launchpad.test/ubuntu/hoary
    >>> anon_browser.open("http://launchpad.test/ubuntu/devel/+builds")
    >>> print(anon_browser.url)
    http://launchpad.test/ubuntu/hoary/+builds


Registration information
========================

The distroseries pages presents the registration information.

    >>> anon_browser.open('http://launchpad.test/ubuntu')

    >>> print(extract_text(
    ...     find_tag_by_id(anon_browser.contents, 'registration')))
    Registered by
    Registry Administrators
    on 2006-10-16

    >>> print(anon_browser.getLink('Ubuntu Team').url)
    http://launchpad.test/~ubuntu-team


Redirection for webservice URLs
===============================

The webservice exposes a URL for the archive associated with the distribution.
Displaying the page for that URL is nonsensical (it looks like the PPA
index page), so the view redirect it to the distribution index page.

    >>> anon_browser.open("http://launchpad.test/ubuntu/+archive/primary")
    >>> print(anon_browser.url)
    http://launchpad.test/ubuntu

    >>> anon_browser.open("http://launchpad.test/ubuntu/+archive/partner")
    >>> print(anon_browser.url)
    http://launchpad.test/ubuntu

Any attempt to access an incomplete URL (missing the archive name
term) or an unavailable name (only 'primary' and 'partner' exist)
results in a NotFound error.

    >>> anon_browser.open("http://launchpad.test/ubuntu/+archive")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound:
    Object: <Distribution ...>, name: '+archive'

    >>> anon_browser.open("http://launchpad.test/ubuntu/+archive/boing")
    Traceback (most recent call last):
    ...
    zope.publisher.interfaces.NotFound:
    Object: <Distribution ...>, name: 'boing'
