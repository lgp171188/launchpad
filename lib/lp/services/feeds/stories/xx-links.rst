Link Tags for Atom Feeds
========================

The icon that appears in a browser's address field to indicate the
presence of an RSS or Atom feed is controlled by adding a <link> tag
to the <head> of the document. We want appropriate pages in
launchpad.test to provide links to corresponding Atom feeds.


All Announcements on Launchpad
------------------------------

The root launchpad.test url will have a link to the Atom feed which
displays the most recent announcements for all the projects.

    >>> from lp.services.beautifulsoup import BeautifulSoup
    >>> browser.open('http://launchpad.test/')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/announcements.atom"
        rel="alternate" title="All Announcements"
        type="application/atom+xml"/>]

The http://launchpad.test/+announcements page also displays recent
announcements for all the projects so it should have a link to the same
feed.

    >>> browser.open('http://launchpad.test/+announcements')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/announcements.atom"
        rel="alternate" title="All Announcements"
        type="application/atom+xml"/>]

Single Bug Feed
---------------

On the page which displays a single bug, there should be a link to the
atom feed for that one bug.

    >>> browser.open('http://bugs.launchpad.test/firefox/+bug/1')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/bugs/1/bug.atom"
        rel="alternate" title="Bug 1 Feed"
        type="application/atom+xml"/>]

But if the bug is private, there should be no link.

    # Set up an authenticated browser.
    >>> from lp.testing.pages import setupBrowserForUser
    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> login(ANONYMOUS)
    >>> user = getUtility(IPersonSet).getByEmail('daf@canonical.com')
    >>> logout()
    >>> auth_browser = setupBrowserForUser(user)

    # First check that the bug exists.
    >>> auth_browser.open('http://launchpad.test/bugs/14')
    >>> print(auth_browser.url)
    http://bugs.launchpad.test/jokosher/+bug/14

    >>> soup = BeautifulSoup(auth_browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    []

Even so, if they somehow manage to hack the url or use inline ajax editing of
the bug status and attempt to subscribe, they are redirected to the bug page:

    >>> auth_browser.open('http://feeds.launchpad.test/bugs/14/bug.atom')
    >>> print(auth_browser.url)
    http://bugs.launchpad.test/
    >>> print_feedback_messages(auth_browser.contents)
    The requested bug is private. Feeds do not serve private bugs.

Latest Bugs and Branches for a Person
-------------------------------------

On the person page on launchpad.test and bugs.launchpad.test, we should
show a link to the atom feed for that person's latest bugs and
branches.

    >>> browser.open('http://launchpad.test/~stevea')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/~stevea/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Steve Alexander"
        type="application/atom+xml"/>,
    <link href="http://feeds.launchpad.test/~stevea/branches.atom"
        rel="alternate" title="Latest Branches for Steve Alexander"
        type="application/atom+xml"/>,
    <link href="http://feeds.launchpad.test/~stevea/revisions.atom"
        rel="alternate" title="Latest Revisions by Steve Alexander"
        type="application/atom+xml"/>]

On the bugs subdomain, only a link to the bugs feed will be included,
not the branches link.

    >>> browser.open('http://bugs.launchpad.test/~stevea')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/~stevea/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Steve Alexander"
        type="application/atom+xml"/>]


Latest Bugs, Branches, and Announcements for a Product
------------------------------------------------------

On the product page on launchpad.test and bugs.launchpad.test, we should
show a link to the atom feed for that product's latest bugs.

Feed links for announcements and branches should also be shown on the
main product page.

    >>> browser.open('http://launchpad.test/jokosher')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/jokosher/announcements.atom"
        rel="alternate" title="Announcements for Jokosher"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/jokosher/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Jokosher"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/jokosher/branches.atom"
        rel="alternate" title="Latest Branches for Jokosher"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/jokosher/revisions.atom"
        rel="alternate" title="Latest Revisions for Jokosher"
        type="application/atom+xml"/>]

Only bug feeds should be linked to on bugs.launchpad.test.

    >>> browser.open('http://bugs.launchpad.test/jokosher')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/jokosher/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Jokosher"
        type="application/atom+xml"/>]


Escaping the title
------------------

Since the link title attribute contains the displayname of the prodect,
it must have quotes and html escaped.

    >>> from lp.testing import login, logout
    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> login('foo.bar@canonical.com')
    >>> from zope.component import getUtility
    >>> from lp.services.webapp.interfaces import ILaunchBag
    >>> from lp.registry.interfaces.product import (
    ...     IProductSet,
    ...     License,
    ...     )
    >>> user = getUtility(ILaunchBag).user
    >>> getUtility(IProductSet).createProduct(
    ...     user, 'bad-displayname',
    ...     'Bad displayname"><script>alert("h4x0r")</script>',
    ...     'title foo', 'summary foo', licenses=[License.GNU_GPL_V2])
    <...Product ...>
    >>> flush_database_updates()
    >>> logout()
    >>> browser.open('http://launchpad.test/bad-displayname')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')  # noqa
    [<link href="http://feeds.launchpad.test/bad-displayname/announcements.atom"
        rel="alternate"
        title='Announcements for Bad displayname"&gt;&lt;script&gt;alert("h4x0r")&lt;/script&gt;'
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/bad-displayname/latest-bugs.atom"
        rel="alternate"
        title='Latest Bugs for Bad displayname"&gt;&lt;script&gt;alert("h4x0r")&lt;/script&gt;'
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/bad-displayname/branches.atom"
        rel="alternate"
        title='Latest Branches for Bad displayname"&gt;&lt;script&gt;alert("h4x0r")&lt;/script&gt;'
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/bad-displayname/revisions.atom"
        rel="alternate"
        title='Latest Revisions for Bad displayname"&gt;&lt;script&gt;alert("h4x0r")&lt;/script&gt;'
        type="application/atom+xml"/>]

Latest Bugs for a ProjectGroup
------------------------------

On the project group page on launchpad.test and bugs.launchpad.test, we should
show a link to the atom feed for that project group's latest bugs.

Feed links for announcements and branches should also be shown
on the main project group page.

    >>> browser.open('http://launchpad.test/gnome')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/gnome/announcements.atom"
        rel="alternate" title="Announcements for GNOME"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/gnome/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for GNOME"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/gnome/branches.atom"
        rel="alternate" title="Latest Branches for GNOME"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/gnome/revisions.atom"
        rel="alternate" title="Latest Revisions for GNOME"
        type="application/atom+xml"/>]

Only bug feeds should be linked to on bugs.launchpad.test.

    >>> browser.open('http://bugs.launchpad.test/gnome')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/gnome/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for GNOME"
        type="application/atom+xml"/>]

The default view for a project group on bugs.launchpad.test is +bugs. The
default bug listing matches the latest-bugs atom feed, but any search
parameters to this view class may cause them to differ. Since the
project group uses the same view class for both tasks, we should check
that the code does not display the atom feed link here inappropriately.

    >>> browser.open('http://bugs.launchpad.test/gnome/+bugs?'
    ...     'search=Search&field.status=New&field.status=Incomplete'
    ...     '&field.status=Confirmed&field.status=Triaged'
    ...     '&field.status=In+Progress&field.status=Fix+Committed')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    []


Latest Bugs for a Distro
------------------------

On the distro page on launchpad.test and bugs.launchpad.test, we should
show a link to the atom feed for that distro's latest bugs.

An announcements feed link should also be shown on the main distro page.

    >>> browser.open('http://launchpad.test/ubuntu')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/ubuntu/announcements.atom"
        rel="alternate" title="Announcements for Ubuntu"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/ubuntu/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Ubuntu"
        type="application/atom+xml"/>]

Only bug feeds should be linked to on bugs.launchpad.test.

    >>> browser.open('http://bugs.launchpad.test/ubuntu')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/ubuntu/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Ubuntu"
        type="application/atom+xml"/>]


Latest Bugs for a Distroseries
------------------------------

On the distroseries page on bugs.launchpad.test, we should
show a link to the atom feed for that distroseries' latest bugs.

    >>> browser.open('http://bugs.launchpad.test/ubuntu/hoary')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link
        href="http://feeds.launchpad.test/ubuntu/hoary/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for Hoary"
        type="application/atom+xml"/>]


Latest Bugs for a Product Series
--------------------------------

On the product series page on bugs.launchpad.test, we should
show a link to the atom feed for that product series' latest bugs.

    >>> browser.open('http://bugs.launchpad.test/firefox/1.0')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/firefox/1.0/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for 1.0"
        type="application/atom+xml"/>]


Latest Bugs for a Source Package
--------------------------------

On the source package page on bugs.launchpad.test, we should
show a link to the atom feed for that source package's latest bugs.

    >>> browser.open('http://bugs.launchpad.test/ubuntu/+source/cnews')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')  # noqa
    [<link
        href="http://feeds.launchpad.test/ubuntu/+source/cnews/latest-bugs.atom"
        rel="alternate" title="Latest Bugs for cnews in Ubuntu"
        type="application/atom+xml"/>]


Latest Branches for a ProjectGroup
----------------------------------

On the project group code page on code.launchpad.test, we should show a link
to the atom feed for that project group's latest branches.

    >>> browser.open('http://code.launchpad.test/mozilla')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link
        href="http://feeds.launchpad.test/mozilla/branches.atom"
        rel="alternate" title="Latest Branches for The Mozilla Project"
        type="application/atom+xml"/>,
     <link
        href="http://feeds.launchpad.test/mozilla/revisions.atom"
        rel="alternate" title="Latest Revisions for The Mozilla Project"
        type="application/atom+xml"/>]


Latest Branches for a Product
-----------------------------

On the project code page on code.launchpad.test, we should show a link
to the atom feed for that product's latest branches.

    >>> browser.open('http://code.launchpad.test/firefox')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/firefox/branches.atom"
        rel="alternate" title="Latest Branches for Mozilla Firefox"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/firefox/revisions.atom"
        rel="alternate"
        title="Latest Revisions for Mozilla Firefox"
        type="application/atom+xml"/>]


Latest Branches for a Person
----------------------------

On a person's code page on code.launchpad.test, we should show a link
to the atom feed for that person's latest branches.

    >>> browser.open('http://code.launchpad.test/~mark')
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    [<link href="http://feeds.launchpad.test/~mark/branches.atom"
        rel="alternate" title="Latest Branches for Mark Shuttleworth"
        type="application/atom+xml"/>,
     <link href="http://feeds.launchpad.test/~mark/revisions.atom"
        rel="alternate" title="Latest Revisions by Mark Shuttleworth"
        type="application/atom+xml"/>]


Latest Revisions on a Branch
----------------------------

On a branch page on code.launchpad.test, we should show a link to the
atom feed for that branch's revisions.

    >>> url = 'http://code.launchpad.test/~mark/firefox/release--0.9.1'
    >>> browser.open(url)
    >>> soup = BeautifulSoup(browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')  # noqa
    [<link
        href="http://feeds.launchpad.test/~mark/firefox/release--0.9.1/branch.atom"
        rel="alternate"
	title="Latest Revisions for Branch lp://dev/~mark/firefox/release--0.9.1"
        type="application/atom+xml"/>]

But if the branch is private, there should be no link.

    >>> login(ANONYMOUS)
    >>> user = getUtility(IPersonSet).getByEmail('test@canonical.com')
    >>> logout()
    >>> auth_browser = setupBrowserForUser(user)
    >>> auth_browser.open(
    ... 'https://code.launchpad.test/~name12/landscape/feature-x')
    >>> soup = BeautifulSoup(auth_browser.contents)
    >>> soup.head.find_all('link', type='application/atom+xml')
    []

Even so, if they somehow manage to hack the url, they are redirected to a page
with an error notification:

    >>> browser.open(
    ...     'http://feeds.launchpad.test/~name12/landscape/feature-x/'
    ...     'branch.atom')
    >>> print(browser.url)
    http://code.launchpad.test/
    >>> print_feedback_messages(browser.contents)
    The requested branch is private. Feeds do not serve private branches.
