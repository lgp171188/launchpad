Branch Details
==============

Imports used later in the document:

    >>> from zope.component import getUtility
    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> from datetime import datetime, timezone
    >>> from lp.code.enums import BranchType
    >>> from lp.code.bzr import BranchFormat, RepositoryFormat
    >>> from lp.code.interfaces.branchlookup import IBranchLookup
    >>> from lp.registry.interfaces.person import IPersonSet

Modifying/creating test data for this test case.

    >>> login("admin@canonical.com")
    >>> eric = factory.makePerson(name="eric", email="eric@example.com")
    >>> fooix = factory.makeProduct(name="fooix", owner=eric)
    >>> branch = factory.makeProductBranch(
    ...     name="trunk", product=fooix, owner=eric
    ... )
    >>> fooix.setAliases(["fooey"])
    >>> factory.makeRevisionsForBranch(
    ...     branch, count=5, author="eric@example.com"
    ... )
    >>> logout()


Reaching to branches
--------------------

On the Code site, registered branches are reached by /<owner>/<product
>/<branch-name>, where <product> can be either a product's name or any
of its aliases.  In case an alias is used, the user is redirected to the
branch's canonical URL -- the one which uses the product name.

    >>> anon_browser.open("http://code.launchpad.test/~eric/fooix/trunk")
    >>> anon_browser.url
    'http://code.launchpad.test/~eric/fooix/trunk'

    >>> anon_browser.open("http://code.launchpad.test/~eric/fooey/trunk")
    >>> anon_browser.url
    'http://code.launchpad.test/~eric/fooix/trunk'

    >>> anon_browser.open("http://api.launchpad.test/devel/~eric/fooey/trunk")
    >>> anon_browser.url
    'http://api.launchpad.test/devel/~eric/fooix/trunk'


Recent Revisions
----------------

We display the recent revisions of a branch if it has been scanned.

    >>> user_browser.open("http://code.launchpad.test/~eric/fooix/trunk")
    >>> assert find_tag_by_id(user_browser.contents, "merge-summary") is None
    >>> revisions = find_tag_by_id(user_browser.contents, "recent-revisions")
    >>> def print_merge_links(browser):
    ...     links = find_tag_by_id(browser.contents, "merge-links")
    ...     if not links:
    ...         print(None)
    ...     else:
    ...         print(extract_text(links))
    ...
    >>> print_merge_links(user_browser)
    None


Revision information
....................

Underneath that heading we see the ten most-recent revisions of the
branch in reverse-chronological order.  If the revision author has been
linked to a Launchpad person, then a link to the person is shown rather
than the text of the revision author.

    >>> def print_revisions(browser):
    ...     revisions = find_tags_by_class(
    ...         browser.contents, "revision-details"
    ...     )
    ...     for revision in revisions:
    ...         print(extract_text(revision))
    ...

    >>> print_revisions(user_browser)
    5. By Eric on 2007-01-05
    4. By Eric on 2007-01-04
    3. By Eric on 2007-01-03
    2. By Eric on 2007-01-02
    1. By Eric on 2007-01-01

Each of the revision numbers are no longer anchors to codebrowse and
link to the user's profile instead.

    >>> revision = find_tags_by_class(
    ...     user_browser.contents, "revision-details", only_first=True
    ... )
    >>> print(revision.a)
    <a class="sprite person" href="http://launchpad.test/~eric">Eric</a>


Commit messages
...............

The commit message is displayed in paragraphs underneath the revision id
and author.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/+branch/+junk/junk.dev"
    ... )
    >>> commit_messages = find_tags_by_class(
    ...     browser.contents, "revision-comment"
    ... )
    >>> print(commit_messages[0].p.decode_contents())
    fix bug in bar

When a commit message refers to a bug using the form "bug <bugnumber>",
a link to that bug is created.

    >>> print(commit_messages[3].p.decode_contents())
    fix <a ...>bug 1</a>

This link can be followed to the bug's details page.

    >>> browser.getLink("bug 1").click()
    >>> print(browser.title)
    Bug #1 ...


Unscanned branches
------------------

Some branches won't have any revisions in the database. Sometimes, this
is simply because the branch is empty. However, much of the time, the
lack of revisions will be because of an error or delay in the scanning
process.

Before we can display the revisions, a branch needs to be mirrored (or
'published') and scanned. When a branch is not yet mirrored, we'll see a
helpful message.

    >>> browser.open("http://code.launchpad.test/~name12/firefox/main")
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "recent-revisions"))
    ... )
    Recent revisions
    This branch has not been mirrored yet.

We don't want to use the word 'mirrored' for hosted or imported
branches, because those branches are only mirrored internally.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/pushed"
    ... )
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "recent-revisions"))
    ... )
    Recent revisions
    This branch has not been pushed to yet.

    >>> browser.open("http://code.launchpad.test/~vcs-imports/evolution/main")
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "recent-revisions"))
    ... )
    Recent revisions
    This branch has not been imported yet.

If a branch has been mirrored, but not scanned, we display a different
message. This is helpful particularly for hosted and imported branches,
which are available for download as soon as they are published.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/mirrored"
    ... )
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "recent-revisions"))
    ... )
    Recent revisions
    This branch has not been scanned yet.

If a branch has been mirrored and scanned, and has no revisions, then it
is empty.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/scanned"
    ... )
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "recent-revisions"))
    ... )
    Recent revisions
    This branch is empty.


Branch Details
--------------

The branch page includes a table of details about the branch. The exact
details vary from branch type to branch type.

For hosted branches, the table has a link to the branch's project and
the URL for the branch's canonical location.

    >>> def get_branch_details_table():
    ...     return find_tag_by_id(browser.contents, "branch-info")
    ...
    >>> def get_branch_management_portlet():
    ...     return find_tag_by_id(browser.contents, "branch-management")
    ...

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/scanned"
    ... )
    >>> print(extract_text(get_branch_details_table()))
    Branch information
    Owner: Sample Person
    Project: GNOME Terminal
    Status: Development

    >>> print(extract_text(get_branch_management_portlet()))
    Only Sample Person can upload to this branch.
    If you are Sample Person please log in for upload directions.

For mirrored branches, the table has a link to the branch's project, the
location of the original branch, the mirror on Launchpad, information
about when the branch was last mirrored and when it will be mirrored
again.

First we create an example branch, then call the APIs to indicate that
it has been mirrored:

    >>> login("no-priv@canonical.com")
    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")
    >>> branch = factory.makePersonalBranch(
    ...     branch_type=BranchType.MIRRORED,
    ...     name="mirrored",
    ...     owner=no_priv,
    ...     url="http://example.com/mirrored",
    ... )
    >>> branch.last_mirrored = datetime(
    ...     year=2007, month=10, day=1, tzinfo=timezone.utc
    ... )
    >>> branch.next_mirror_time = None
    >>> flush_database_updates()
    >>> logout()

    >>> browser.open("http://code.launchpad.test/~no-priv/+junk/mirrored")
    >>> print(extract_text(get_branch_details_table()))
    Branch information...
    Status: Development
    Location: http://example.com/mirrored
    Last mirrored: 2007-10-01
    Next mirror: Disabled

The branch description should not be shown if there is none.

    >>> def get_branch_description(browser):
    ...     tag = find_tag_by_id(browser.contents, "branch-description")
    ...     return extract_text(tag) if tag is not None else None
    ...
    >>> print(get_branch_description(browser))
    None

Branches that have never been mirrored don't have a 'Last mirrored'
field.

    >>> browser.open("http://code.launchpad.test/~name12/gnome-terminal/main")
    >>> print(extract_text(get_branch_details_table()))
    Branch information
    Owner: Sample Person
    Project: GNOME Terminal
    Status: Development
    Location: http://example.com/gnome-terminal/main
    Last mirrored: Not mirrored yet
    Next mirror: Disabled

    >>> print(get_branch_description(browser))
    Main branch of development for GNOME Terminal.
    Stable branches are based on that one...

If next_mirror_time is NULL, then mirroring of the branch is disabled.

(First we make a branch which has a NULL next_mirror_time)

    >>> login("no-priv@canonical.com")
    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")
    >>> branch = factory.makePersonalBranch(
    ...     branch_type=BranchType.MIRRORED,
    ...     name="mirror-disabled",
    ...     owner=no_priv,
    ...     url="http://example.com/disabled",
    ... )
    >>> branch.next_mirror_time = None
    >>> flush_database_updates()
    >>> logout()

    >>> browser.open(
    ...     "http://code.launchpad.test/~no-priv/+junk/mirror-disabled"
    ... )
    >>> print(extract_text(get_branch_details_table()))
    Branch information
    Owner: No Privileges Person
    Status: Development
    Location: http://example.com/disabled
    Last mirrored: Not mirrored yet
    Next mirror: Disabled


Codebrowse link
---------------

The codebrowse link does not appear for bzr branches because we are
shutting down loggerhead as a part of the upcoming bzr codehosting
decommissioning.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/scanned"
    ... )
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "recent-revisions"))
    ... )
    Recent revisions
    This branch is empty.

In addition, there is a "All revisions" link that links to the changelog
view in codebrowse.

    >>> browser.open("http://code.launchpad.test/~name12/+junk/junk.dev")
    >>> print(browser.getLink("All revisions").url)
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

If the branch is private, the browse code link is not shown. In order to
see the private branch, we need to log in as a user that is able to see
the branch.

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open(
    ...     "http://code.launchpad.test/~landscape-developers/landscape/"
    ...     "trunk"
    ... )


Download URL
------------

In the details table there is a link to the branch download URL.

For public branches this shows links to the codehosting using http,
whereas private branches show bzr+ssh as they are not available over
anonymous http, and anyone who can see the branch is able to access it
using bzr+ssh.

The download URL is only shown for branches that actually have
revisions. So we need to fake that here.

    >>> login("foo.bar@canonical.com")
    >>> branch = getUtility(IBranchLookup).getByUniqueName(
    ...     "~landscape-developers/landscape/trunk"
    ... )
    >>> branch.revision_count = 42
    >>> branch = getUtility(IBranchLookup).getByUniqueName(
    ...     "~name12/gnome-terminal/scanned"
    ... )
    >>> branch.revision_count = 13
    >>> flush_database_updates()
    >>> logout()

    >>> browser.open(
    ...     "http://code.launchpad.test/~landscape-developers/landscape/"
    ...     "trunk"
    ... )
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser.contents, "branch-management")
    ...     )
    ... )
    Get this branch:
      bzr branch lp://dev/~landscape-developers/landscape/trunk
    ...

Public branches use the lp spec bzr lookup name.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/scanned"
    ... )
    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser.contents, "branch-management")
    ...     )
    ... )
    Get this branch: bzr branch lp://dev/~name12/gnome-terminal/scanned
    ...


Branch formats
--------------

    >>> login("no-priv@canonical.com")
    >>> branch = factory.makeAnyBranch(
    ...     branch_format=BranchFormat.BZR_BRANCH_5,
    ...     repository_format=RepositoryFormat.BZR_KNITPACK_1,
    ... )
    >>> url = canonical_url(branch)
    >>> logout()
    >>> browser.open(url)

The data that we specified is shown on the web page.

    >>> print(extract_text(find_tag_by_id(browser.contents, "branch-format")))
    Branch format: Branch format 5

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(browser.contents, "repository-format")
    ...     )
    ... )
    Repository format:
    Bazaar pack repository format 1 (needs bzr 0.92)


Stacking
........

Say we have one branch stacked on another:

    >>> login("no-priv@canonical.com")
    >>> stacked_on_branch = factory.makeAnyBranch()
    >>> stacked_branch = factory.makeAnyBranch(stacked_on=stacked_on_branch)
    >>> url = canonical_url(stacked_branch)
    >>> stacked_on_name = stacked_on_branch.bzr_identity
    >>> stacked_on_url = canonical_url(stacked_on_branch)
    >>> logout()

And we browse to the stacked branch:

    >>> browser.open(url)

The stacked-on information appears in the branch summary:

    >>> print(extract_text(find_tag_by_id(browser.contents, "stacked-on")))
    Stacked on: lp://dev/~person-name.../product-name.../branch...

    >>> browser.getLink(stacked_on_name).url == stacked_on_url
    True

If the stacked-on branch is private, then a branch is also considered private
even if it is not explicitly marked as such.

The stacked branch is initially public:

    >>> browser.open(url)
    >>> content = find_tag_by_id(browser.contents, "document")
    >>> print(extract_text(find_tag_by_id(content, "privacy")))
    This branch contains Public information...

Navigation Context
..................

The tabs shown for a branch depend on whether or not the branch is a
junk branch or not.  If the branch is associated with a product, then
the product is the primary context, and used for the tabs and the
breadcrumbs.  If the branch is not associated with a product then the
owner of the branch is used as the primary context for the branch and
used for the breadcrumbs and tabs.

    >>> browser.open(
    ...     "http://code.launchpad.test/~name12/gnome-terminal/scanned"
    ... )
    >>> print_location(browser.contents)
    Hierarchy: GNOME Terminal
    Tabs:
    * Overview - http://launchpad.test/gnome-terminal
    * Code (selected) - http://code.launchpad.test/gnome-terminal
    * Bugs - http://bugs.launchpad.test/gnome-terminal
    * Blueprints - http://blueprints.launchpad.test/gnome-terminal
    * Translations - http://translations.launchpad.test/gnome-terminal
    * Answers - http://answers.launchpad.test/gnome-terminal
    Main heading: lp://dev/~name12/gnome-terminal/scanned

    >>> browser.open("http://code.launchpad.test/~name12/+junk/junk.dev")
    >>> print_location(browser.contents)
    Hierarchy: Sample Person
    Tabs:
    * Overview - http://launchpad.test/~name12
    * Code (selected) - http://code.launchpad.test/~name12
    * Bugs - http://bugs.launchpad.test/~name12
    * Blueprints - http://blueprints.launchpad.test/~name12
    * Translations - http://translations.launchpad.test/~name12
    * Answers - http://answers.launchpad.test/~name12
    Main heading: lp://dev/~name12/+junk/junk.dev


