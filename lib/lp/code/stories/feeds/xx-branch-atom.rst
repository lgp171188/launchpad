Atom Feeds For Branches
=======================

Atom feeds produce XML not HTML.  Therefore we must parse the output as XML
by asking BeautifulSoup to use lxml.

    >>> import feedparser
    >>> from lp.services.beautifulsoup import (
    ...     BeautifulSoup,
    ...     SoupStrainer,
    ... )
    >>> from lp.services.feeds.tests.helper import parse_ids, parse_links

Create some specific branches to use for this test
--------------------------------------------------

    >>> login(ANONYMOUS)
    >>> from lp.testing import time_counter
    >>> from datetime import datetime, timedelta, timezone
    >>> date_generator = time_counter(
    ...     datetime(2007, 12, 1, tzinfo=timezone.utc), timedelta(days=1)
    ... )
    >>> def make_branch(owner, product, name):
    ...     global factory, date_generator
    ...     factory.makeProductBranch(
    ...         name=name,
    ...         product=product,
    ...         owner=owner,
    ...         date_created=next(date_generator),
    ...     )
    ...
    >>> mike = factory.makePerson(name="mike", displayname="Mike Murphy")
    >>> mary = factory.makePerson(name="mary", displayname="Mary Murphy")
    >>> projectgroup = factory.makeProject(
    ...     name="oh-man", displayname="Oh Man"
    ... )
    >>> product1 = factory.makeProduct(
    ...     name="fooix", projectgroup=projectgroup, displayname="Fooix"
    ... )
    >>> product2 = factory.makeProduct(
    ...     name="fooey", projectgroup=projectgroup, displayname="Fooey"
    ... )
    >>> make_branch(mike, product1, "first")
    >>> make_branch(mike, product2, "second")
    >>> make_branch(mike, product1, "third")
    >>> make_branch(mike, product2, "fourth")
    >>> make_branch(mary, product1, "fifth")
    >>> make_branch(mary, product2, "sixth")
    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> flush_database_updates()
    >>> logout()


Feed for a person's branches
----------------------------

The feed for a person's branches will show the most recent 25 branches
which will include an entry for each branch.

    >>> anon_browser.open("http://feeds.launchpad.test/~mike/branches.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Branches for Mike Murphy
    >>> def print_parse_ids(browser):
    ...     for id in parse_ids(browser.contents):
    ...         print(id)
    ...

Ignore the date associated with the id of 'mike' as this is the date created
of the person, which will be different each time the test is run.

    >>> print_parse_ids(anon_browser)
    <id>tag:launchpad.net,...:/code/~mike</id>
    <id>tag:launchpad.net,2007-12-04:/code/~mike/fooey/fourth</id>
    <id>tag:launchpad.net,2007-12-03:/code/~mike/fooix/third</id>
    <id>tag:launchpad.net,2007-12-02:/code/~mike/fooey/second</id>
    <id>tag:launchpad.net,2007-12-01:/code/~mike/fooix/first</id>

Ensure the self link is correct and there is only one.

    >>> def print_parse_links(browser):
    ...     for link in parse_links(browser.contents, rel="self"):
    ...         print(link)
    ...
    >>> print_parse_links(anon_browser)
    <link href="http://feeds.launchpad.test/~mike/branches.atom" rel="self"/>

The <update> field for the feed will be the most recent value for the
updated field in all of the entries.

    >>> strainer = SoupStrainer("updated")
    >>> updated_dates = [
    ...     extract_text(tag)
    ...     for tag in BeautifulSoup(
    ...         anon_browser.contents, "xml", parse_only=strainer
    ...     )
    ... ]
    >>> feed_updated = updated_dates[0]
    >>> entry_dates = sorted(updated_dates[1:], reverse=True)
    >>> assert (
    ...     feed_updated == entry_dates[0]
    ... ), "Feed <update> value is not the same as latest entry."

If an anonymous user fetches the same feed the email addresses will
still be hidden:

    >>> anon_browser.open("http://feeds.launchpad.test/~name12/branches.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Branches for Sample Person
    >>> "foo@localhost" in anon_browser.contents
    False
    >>> "email address hidden" in anon_browser.contents
    True

If a branch is marked private it will not be displayed.  The Landscape
developers team has two branches which are both private.

    >>> from zope.component import getUtility
    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.code.model.branch import Branch
    >>> from lp.code.interfaces.branchcollection import IAllBranches
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from lp.registry.interfaces.product import IProductSet
    >>> login(ANONYMOUS)
    >>> test_user = getUtility(IPersonSet).getByEmail("test@canonical.com")
    >>> landscape = getUtility(IProductSet)["landscape"]
    >>> branches = getUtility(IAllBranches).inProduct(landscape)
    >>> branches = (
    ...     branches.visibleByUser(test_user)
    ...     .getBranches()
    ...     .order_by(Branch.id)
    ... )
    >>> for branch in branches:
    ...     branch = removeSecurityProxy(branch)
    ...     print(branch.unique_name, branch.private)
    ...
    ~landscape-developers/landscape/trunk True
    ~name12/landscape/feature-x True
    >>> logout()

If we look at the feed for landscape developers there will be no
branches listed, just an id for the feed.

    >>> browser.open(
    ...     "http://feeds.launchpad.test/~landscape-developers/branches.atom"
    ... )
    >>> _ = feedparser.parse(browser.contents)
    >>> for element in BeautifulSoup(browser.contents, "xml").title.contents:
    ...     print(element)
    ...
    Branches for Landscape Developers
    >>> print_parse_ids(browser)
    <id>tag:launchpad.net,2006-07-11:/code/~landscape-developers</id>


Feed for a product's branches
-----------------------------

The feed for a product's branches will show the most recent 25 branches
which will include an entry for each branch.

    >>> anon_browser.open("http://feeds.launchpad.test/fooix/branches.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Branches for Fooix
    >>> print_parse_ids(anon_browser)
    <id>tag:launchpad.net,...:/code/fooix</id>
    <id>tag:launchpad.net,2007-12-05:/code/~mary/fooix/fifth</id>
    <id>tag:launchpad.net,2007-12-03:/code/~mike/fooix/third</id>
    <id>tag:launchpad.net,2007-12-01:/code/~mike/fooix/first</id>

    >>> print_parse_links(anon_browser)
    <link href="http://feeds.launchpad.test/fooix/branches.atom" rel="self"/>

The <update> field for the feed will be the most recent value for the
updated field in all of the entries.

    >>> strainer = SoupStrainer("updated")
    >>> updated_dates = [
    ...     extract_text(tag)
    ...     for tag in BeautifulSoup(
    ...         anon_browser.contents, "xml", parse_only=strainer
    ...     )
    ... ]
    >>> feed_updated = updated_dates[0]
    >>> entry_dates = sorted(updated_dates[1:], reverse=True)
    >>> assert (
    ...     feed_updated == entry_dates[0]
    ... ), "Feed <update> value is not the same as latest entry."


Feed for a project group's branches
-----------------------------------

The feed for a project group's branches will show the most recent 25
branches which will include an entry for each branch.

    >>> anon_browser.open("http://feeds.launchpad.test/oh-man/branches.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Branches for Oh Man
    >>> print_parse_ids(anon_browser)
    <id>tag:launchpad.net,...:/code/oh-man</id>
    <id>tag:launchpad.net,2007-12-06:/code/~mary/fooey/sixth</id>
    <id>tag:launchpad.net,2007-12-05:/code/~mary/fooix/fifth</id>
    <id>tag:launchpad.net,2007-12-04:/code/~mike/fooey/fourth</id>
    <id>tag:launchpad.net,2007-12-03:/code/~mike/fooix/third</id>
    <id>tag:launchpad.net,2007-12-02:/code/~mike/fooey/second</id>
    <id>tag:launchpad.net,2007-12-01:/code/~mike/fooix/first</id>

    >>> print_parse_links(anon_browser)
    <link href="http://feeds.launchpad.test/oh-man/branches.atom" rel="self"/>

The <update> field for the feed will be the most recent value for the
updated field in all of the entries.

    >>> strainer = SoupStrainer("updated")
    >>> updated_dates = [
    ...     extract_text(tag)
    ...     for tag in BeautifulSoup(
    ...         anon_browser.contents, "xml", parse_only=strainer
    ...     )
    ... ]
    >>> feed_updated = updated_dates[0]
    >>> entry_dates = sorted(updated_dates[1:], reverse=True)
    >>> assert (
    ...     feed_updated == entry_dates[0]
    ... ), "Feed <update> value is not the same as latest entry."


Feed for a single branch
------------------------

A single branch can have an Atom feed with each revision being a
different entry.

    >>> url = (
    ...     "http://feeds.launchpad.test/~mark/firefox/release--0.9.1/"
    ...     "branch.atom"
    ... )
    >>> browser.open(url)
    >>> _ = feedparser.parse(browser.contents)
    >>> for element in BeautifulSoup(browser.contents, "xml").title.contents:
    ...     print(element)
    ...
    Latest Revisions for Branch lp://dev/~mark/firefox/release--0.9.1
    >>> print(browser.url)
    http://feeds.launchpad.test/~mark/firefox/release--0.9.1/branch.atom

The first <id> in a feed identifies the feed.  Each entry then has its
own <id>, which in the case of a single branch feed will be identical.

    >>> soup = BeautifulSoup(
    ...     browser.contents, "xml", parse_only=SoupStrainer("id")
    ... )
    >>> ids = parse_ids(browser.contents)
    >>> for id_ in ids:
    ...     print(id_)  # noqa
    ...
    <id>tag:launchpad.net,2006-10-16:/code/~mark/firefox/release--0.9.1</id>
    <id>tag:launchpad.net,2005-03-09:/code/~mark/firefox/release--0.9.1/revision/1</id>
    >>> print_parse_links(browser)  # noqa
    <link href="http://feeds.launchpad.test/~mark/firefox/release--0.9.1/branch.atom" rel="self"/>
    >>> strainer = SoupStrainer("updated")
    >>> updated_dates = [
    ...     extract_text(tag)
    ...     for tag in BeautifulSoup(
    ...         browser.contents, "xml", parse_only=strainer
    ...     )
    ... ]

The update date for the entire feed (updated_dates[0]) must be equal
to the update_date of the first entry in the feed (updated_dates[1]).

    >>> updated_dates[0] == updated_dates[1]
    True
