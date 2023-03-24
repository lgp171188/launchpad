Atom Feeds For Revisions
========================

Atom feeds produce XML not HTML.  Therefore we must parse the output as XML
by asking BeautifulSoup to use lxml.

    >>> import feedparser
    >>> from lp.services.beautifulsoup import BeautifulSoup
    >>> from lp.services.feeds.tests.helper import parse_ids, parse_links

Create some specific branches to use for this test
--------------------------------------------------

    >>> login(ANONYMOUS)
    >>> from lp.testing import time_counter
    >>> from datetime import datetime, timedelta, timezone

Since the feed only shows revisions from the last 30 days, we need recent
revisions.

    >>> initial_revision_date = datetime.now(timezone.utc) - timedelta(
    ...     days=10
    ... )
    >>> date_generator = time_counter(
    ...     initial_revision_date, timedelta(days=1)
    ... )
    >>> mike = factory.makePerson(
    ...     name="mike", displayname="Mike Murphy", email="mike@example.com"
    ... )
    >>> mary = factory.makePerson(
    ...     name="mary", displayname="Mary Murphy", email="mary@example.com"
    ... )
    >>> fubar = factory.makeProject(name="fubar", displayname="Fubar")
    >>> fooix = factory.makeProduct(
    ...     name="fooix", displayname="Fooix", projectgroup=fubar
    ... )
    >>> fooey = factory.makeProduct(
    ...     name="fooey", displayname="Fooey", projectgroup=fubar
    ... )
    >>> fooix_branch = factory.makeProductBranch(
    ...     name="feature-x", product=fooix, owner=mike
    ... )
    >>> fooey_branch = factory.makeProductBranch(
    ...     name="feature-x", product=fooey, owner=mike
    ... )

    >>> from zope.security.proxy import removeSecurityProxy
    >>> def makeRevision(author, rev_id, log_body):
    ...     global factory, date_generator
    ...     return factory.makeRevision(
    ...         author=removeSecurityProxy(author).preferredemail.email,
    ...         revision_date=next(date_generator),
    ...         rev_id=rev_id,
    ...         log_body=log_body,
    ...     )
    ...
    >>> ignored = fooey_branch.createBranchRevision(
    ...     1, makeRevision(mike, "rev1", "This is a short log message")
    ... )
    >>> ignored = fooix_branch.createBranchRevision(
    ...     2,
    ...     makeRevision(
    ...         mike,
    ...         "rev2",
    ...         "This is a much longer log message that will"
    ...         " be truncated due to length of a single line.",
    ...     ),
    ... )
    >>> ignored = fooix_branch.createBranchRevision(
    ...     None,
    ...     makeRevision(mike, "rev2.1", "This is a two\nline log message."),
    ... )
    >>> ignored = fooey_branch.createBranchRevision(
    ...     3, makeRevision(mary, "rev3", "Mary's revision")
    ... )

    >>> ignored = login_person(mike)
    >>> team = factory.makeTeam(mike, "The M Team", name="m-team")
    >>> ignored = team.addMember(mary, mike)
    >>> from zope.component import getUtility
    >>> from lp.code.interfaces.revision import IRevisionSet
    >>> revision_set = getUtility(IRevisionSet)
    >>> revision_set.updateRevisionCacheForBranch(fooey_branch)
    >>> revision_set.updateRevisionCacheForBranch(fooix_branch)
    >>> logout()


Feed for a person's revisions
-----------------------------

The feed for a person's revisions will show the most recent 25 revisions
that have been committed by that person (or attributed to that person).

    >>> anon_browser.open("http://feeds.launchpad.test/~mike/revisions.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Latest Revisions by Mike Murphy
    >>> def print_parse_ids(browser):
    ...     for id in parse_ids(browser.contents):
    ...         print(id)
    ...

Ignore the date associated with the id of 'mike' as this is the date created
of the person, which will be different each time the test is run.

    >>> print_parse_ids(anon_browser)
    <id>tag:launchpad.net,...:/code/~mike</id>
    <id>tag:launchpad.net,...:/revision/rev2.1</id>
    <id>tag:launchpad.net,...:/revision/rev2</id>
    <id>tag:launchpad.net,...:/revision/rev1</id>

Ensure the self link is correct and there is only one.

    >>> def print_parse_links(browser):
    ...     for link in parse_links(browser.contents, rel="self"):
    ...         print(link)
    ...
    >>> print_parse_links(anon_browser)
    <link href="http://feeds.launchpad.test/~mike/revisions.atom" rel="self"/>

If we look at the feed for a team, we get revisions created by any member
of that team.

    >>> browser.open("http://feeds.launchpad.test/~m-team/revisions.atom")
    >>> _ = feedparser.parse(browser.contents)
    >>> for element in BeautifulSoup(browser.contents, "xml").title.contents:
    ...     print(element)
    ...
    Latest Revisions by members of The M Team
    >>> print_parse_ids(browser)
    <id>tag:launchpad.net,...:/code/~m-team</id>
    <id>tag:launchpad.net,...:/revision/rev3</id>
    <id>tag:launchpad.net,...:/revision/rev2.1</id>
    <id>tag:launchpad.net,...:/revision/rev2</id>
    <id>tag:launchpad.net,...:/revision/rev1</id>

A HEAD request works too.

    >>> response = http(
    ...     r"""
    ... HEAD /~mike/revisions.atom HTTP/1.1
    ... Host: feeds.launchpad.test
    ... """
    ... )
    >>> print(str(response).split("\n")[0])
    HTTP/1.1 200 Ok
    >>> print(response.getHeader("Content-Length"))
    0
    >>> print(six.ensure_text(response.getBody()))
    <BLANKLINE>


Feed for a product's revisions
------------------------------

The feed for a product's revisions will show the most recent 25 revisions
that have been committed on branches for the product.

    >>> anon_browser.open("http://feeds.launchpad.test/fooix/revisions.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Latest Revisions for Fooix

Ignore the date associated with the id of 'fooix' as this is the date created
for the product, which will be different each time the test is run.

    >>> print_parse_ids(anon_browser)
    <id>tag:launchpad.net,...:/code/fooix</id>
    <id>tag:launchpad.net,...:/revision/rev2.1</id>
    <id>tag:launchpad.net,...:/revision/rev2</id>

Ensure the self link points to the feed location and there is only one.

    >>> print_parse_links(anon_browser)
    <link href="http://feeds.launchpad.test/fooix/revisions.atom" rel="self"/>


Feed for a project group's revisions
------------------------------------

A feed for a project group will show the most recent 25 revisions across any
branch for any product that is associated with the project group.

    >>> anon_browser.open("http://feeds.launchpad.test/fubar/revisions.atom")
    >>> _ = feedparser.parse(anon_browser.contents)
    >>> for element in BeautifulSoup(
    ...     anon_browser.contents, "xml"
    ... ).title.contents:
    ...     print(element)
    Latest Revisions for Fubar

Ignore the date associated with the id of 'fubar' as this is the date created
of the project group, which will be different each time the test is run.

    >>> print_parse_ids(anon_browser)
    <id>tag:launchpad.net,...:/code/fubar</id>
    <id>tag:launchpad.net,...:/revision/rev3</id>
    <id>tag:launchpad.net,...:/revision/rev2.1</id>
    <id>tag:launchpad.net,...:/revision/rev2</id>
    <id>tag:launchpad.net,...:/revision/rev1</id>

Ensure the self link points to the feed location and there is only one.

    >>> print_parse_links(anon_browser)
    <link href="http://feeds.launchpad.test/fubar/revisions.atom" rel="self"/>
