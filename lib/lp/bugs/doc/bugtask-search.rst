Searching BugTasks
*******************

BugTasks are usually searched through an IBugTarget's searchTasks()
method, but they all delegate the search to IBugTaskSet.search(). That
method accepts a single parameter; an BugTaskSearchParams instance.

    >>> from lp.bugs.interfaces.bugtask import IBugTaskSet
    >>> from lp.bugs.interfaces.bugtasksearch import BugTaskSearchParams
    >>> from lp.services.database.interfaces import IStore
    >>> bugtask_set = getUtility(IBugTaskSet)
    >>> all_public = BugTaskSearchParams(user=None)
    >>> found_bugtasks = bugtask_set.search(all_public)

    >>> from lp.app.enums import InformationType
    >>> from lp.bugs.model.bug import Bug
    >>> from lp.bugs.model.bugtask import BugTask
    >>> store = IStore(BugTask)
    >>> info_types = [InformationType.PUBLIC, InformationType.PUBLICSECURITY]
    >>> all_public_bugtasks = store.find(
    ...     BugTask,
    ...     BugTask.bug_id == Bug.id,
    ...     Bug.information_type.is_in(info_types),
    ... )
    >>> found_bugtasks.count() == all_public_bugtasks.count()
    True


Searching using bug full-text index
************************************

The searchtext parameter does an extensive and expensive search (it
looks through the bug's full text index, bug comments, bugtask
target name, etc.) For some use cases, it is often easier and cheaper
to simply search on the bug's full text index and omit the more
expensive search on other related information.

For example, there are no bugs with the word 'Fnord' in Firefox.

    >>> from lp.registry.interfaces.product import IProductSet
    >>> firefox = getUtility(IProductSet).getByName("firefox")
    >>> text_search = BugTaskSearchParams(user=None, searchtext="Fnord")
    >>> found_bugtasks = firefox.searchTasks(text_search)
    >>> found_bugtasks.count()
    0

But if we put that word in the bug #4 description, it will be found.

    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> login("foo.bar@canonical.com")
    >>> bug_four = getUtility(IBugSet).get(4)
    >>> bug_four.description += (
    ...     "\nThat happens pretty often with the Fnord Highlighter "
    ...     "extension installed."
    ... )

    >>> found_bugtasks = firefox.searchTasks(text_search)
    >>> for bugtask in found_bugtasks:
    ...     print("#%s" % bugtask.bug.id)
    ...
    #4

BugTaskSearchParams' parameters searchtext and fast_searchtext
***************************************************************

Normally, the parameter searchtext should be used. The alternative
parameter fast_searchtext requires a syntactically correct tsquery
expression containing stemmed words.

A simple phrase can be passed as searchtext, but not as fast_searchtext,
see below.

    >>> good_search = BugTaskSearchParams(
    ...     user=None, searchtext="happens pretty often"
    ... )
    >>> found_bugtasks = firefox.searchTasks(good_search)
    >>> for bugtask in found_bugtasks:
    ...     print("#%s" % bugtask.bug.id)
    ...
    #4

The unstemmed word "happens" does not yield any results when used
as fast_textsearch.

    >>> bad_search = BugTaskSearchParams(user=None, fast_searchtext="happens")
    >>> found_bugtasks = firefox.searchTasks(bad_search)
    >>> print(found_bugtasks.count())
    0

If the stem of "happens" is used, we get results.

    >>> good_search = BugTaskSearchParams(user=None, fast_searchtext="happen")
    >>> found_bugtasks = firefox.searchTasks(good_search)
    >>> for bugtask in found_bugtasks:
    ...     print("#%s" % bugtask.bug.id)
    ...
    #4
    #6

Stemmed words may be combined into a valid tsquery expression.

    >>> good_search = BugTaskSearchParams(
    ...     user=None, fast_searchtext="happen&pretti&often"
    ... )
    >>> found_bugtasks = firefox.searchTasks(good_search)
    >>> for bugtask in found_bugtasks:
    ...     print("#%s" % bugtask.bug.id)
    ...
    #4

Passing invalid tsquery expressions as fast_searchtext raises an exception.

    >>> bad_search = BugTaskSearchParams(
    ...     user=None, fast_searchtext="happens pretty often"
    ... )
    >>> list(firefox.searchTasks(bad_search))
    Traceback (most recent call last):
    ...
    storm.database.SyntaxError:
    syntax error in tsquery: "happens pretty often" ...

    >>> import transaction
    >>> transaction.abort()


Bugs with partner packages
***************************

Bugs may also be targeted to partner packages.  First turn "cdrkit" into
a partner package:

    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.soyuz.interfaces.component import IComponentSet
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> proxied_cdrkit = ubuntu.getSourcePackage("cdrkit")
    >>> cdrkit = removeSecurityProxy(proxied_cdrkit)
    >>> cdrkit.component = getUtility(IComponentSet)["partner"]
    >>> cdrkit.archive = ubuntu.getArchiveByComponent("partner")
    >>> transaction.commit()

It starts off with no bugs:

    >>> cdrkit_bugs = cdrkit.searchTasks(all_public)
    >>> cdrkit_bugs.count()
    0

We can file a bug against it and see that show up in a search:

    >>> from lp.bugs.interfaces.bug import CreateBugParams
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")
    >>> bug = cdrkit.createBug(
    ...     CreateBugParams(
    ...         owner=no_priv,
    ...         title="Bug to be fixed in trunk",
    ...         comment="Something",
    ...     )
    ... )
    >>> cdrkit_bugs = cdrkit.searchTasks(all_public)
    >>> cdrkit_bugs.count()
    1


Ordering search results
************************

The result returned by bugtask searches can come sorted by a specified order


Ordering by number of duplicates
*********************************

It is possible to sort the results by the number of duplicates each bag has.

Here is the list of bugs for Ubuntu.

    >>> def bugTaskInfo(bugtask):
    ...     return "%s %s" % (bugtask.bugtargetdisplayname, bugtask.bug.title)
    ...

    >>> params = BugTaskSearchParams(
    ...     orderby="-number_of_duplicates", user=None
    ... )
    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for bugtask in ubuntu_tasks:
    ...     print(bugTaskInfo(bugtask))
    ...
    mozilla-firefox (Ubuntu) Firefox does not support SVG
    thunderbird (Ubuntu) Thunderbird crashes
    linux-source-2.6.15 (Ubuntu) another test bug
    Ubuntu Blackhole Trash folder
    cdrkit (Ubuntu) Bug to be fixed in trunk

None of these bugs have any duplicates.

    >>> [
    ...     bugtask.bug.id
    ...     for bugtask in ubuntu_tasks
    ...     if bugtask.bug.duplicateof is not None
    ... ]
    []

    >>> from lp.services.database.sqlbase import flush_database_updates

We mark bug #10 as a duplicate of bug #9.

    >>> bug_nine = getUtility(IBugSet).get(9)
    >>> bug_ten = getUtility(IBugSet).get(10)
    >>> bug_ten.markAsDuplicate(bug_nine)
    >>> flush_database_updates()

Searching again reveals bug #9 at the top of the list, since it now has
a duplicate.

    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for bugtask in ubuntu_tasks:
    ...     print(bugTaskInfo(bugtask))
    ...
    thunderbird (Ubuntu) Thunderbird crashes
    mozilla-firefox (Ubuntu) Firefox does not support SVG
    linux-source-2.6.15 (Ubuntu) another test bug
    Ubuntu Blackhole Trash folder
    cdrkit (Ubuntu) Bug to be fixed in trunk


Ordering by number of comments
*******************************

It is also possible to sort the results by the number of comments on a bug.

Here is the list of bugs for Ubuntu, sorted by their number of comments.

    >>> params = BugTaskSearchParams(orderby="-message_count", user=None)
    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for bugtask in ubuntu_tasks:
    ...     bug = bugtask.bug
    ...     print("%s [%s comments]" % (bug.title, bug.message_count))
    ...
    Blackhole Trash folder [3 comments]
    Firefox does not support SVG [2 comments]
    another test bug [2 comments]
    Thunderbird crashes [1 comments]
    Bug to be fixed in trunk [1 comments]


Ordering by bug heat
*********************

Another way of sorting searches is by bug heat.

    >>> params = BugTaskSearchParams(orderby="id", user=None)
    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for task in ubuntu_tasks:
    ...     removeSecurityProxy(task.bug).heat = task.bug.id
    ...
    >>> removeSecurityProxy(bug).heat = 16
    >>> transaction.commit()
    >>> params = BugTaskSearchParams(orderby="-heat", user=None)
    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for bugtask in ubuntu_tasks:
    ...     bug = bugtask.bug
    ...     print("%s [heat: %s]" % (bug.title, bug.heat))
    ...
    Bug to be fixed in trunk [heat: 16]
    another test bug [heat: 10]
    Thunderbird crashes [heat: 9]
    Blackhole Trash folder [heat: 2]
    Firefox does not support SVG [heat: 1]


Ordering by patch age
**********************

We can also sort search results by the creation time of the youngest
patch attached to a bug.

Since we have at present no bugs with patches, we use effectively
the default sort order, by bug task ID (which is implicitly added as
a "second level" sort order to ensure reliable sorting).

    >>> params = BugTaskSearchParams(
    ...     orderby="latest_patch_uploaded", user=None
    ... )
    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for bugtask in ubuntu_tasks:
    ...     print(bugTaskInfo(bugtask))
    ...
    cdrkit (Ubuntu) Bug to be fixed in trunk
    Ubuntu Blackhole Trash folder
    linux-source-2.6.15 (Ubuntu) another test bug
    thunderbird (Ubuntu) Thunderbird crashes
    mozilla-firefox (Ubuntu) Firefox does not support SVG

If we add a patch attachment to bug 2 and bug 10, they are listed first.

    >>> bug_two = getUtility(IBugSet).get(2)
    >>> patch_attachment_bug_2 = factory.makeBugAttachment(
    ...     bug=bug_two, is_patch=True
    ... )
    >>> transaction.commit()
    >>> patch_attachment_bug_10 = factory.makeBugAttachment(
    ...     bug=bug_ten, is_patch=True
    ... )
    >>> params = BugTaskSearchParams(
    ...     orderby="latest_patch_uploaded", user=None
    ... )
    >>> ubuntu_tasks = ubuntu.searchTasks(params)
    >>> for bugtask in ubuntu_tasks:
    ...     print(bugTaskInfo(bugtask))
    ...
    Ubuntu Blackhole Trash folder
    linux-source-2.6.15 (Ubuntu) another test bug
    cdrkit (Ubuntu) Bug to be fixed in trunk
    thunderbird (Ubuntu) Thunderbird crashes
    mozilla-firefox (Ubuntu) Firefox does not support SVG
