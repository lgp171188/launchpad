Person Pages
============

In every person page, the 'Bugs' facet has a series of bug listings for
that person. These pages provide simple and advanced search forms.

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> name16 = getUtility(IPersonSet).get(16)

Let's define a helper function to make it easier to construct a view.

    >>> from zope.component import getMultiAdapter
    >>> from lp.services.webapp.servers import LaunchpadTestRequest
    >>> def create_view(context, name, form=None):
    ...     view = getMultiAdapter(
    ...         (context, LaunchpadTestRequest(form=form)), name=name
    ...     )
    ...     view.initialize()
    ...     return view
    ...


Assigned bugs
-------------

All bug tasks assigned to this person.

By default, only bugtasks with any of the statuses listed in
lp.bugs.interfaces.bugtask.UNRESOLVED_BUGTASK_STATUSES are included:

    >>> assigned_bugtasks_view = create_view(name16, "+assignedbugs")
    >>> assigned_bugtasks = list(assigned_bugtasks_view.search().batch)
    >>> sorted(
    ...     [
    ...         (bugtask.bug.id, bugtask.status.name)
    ...         for bugtask in assigned_bugtasks
    ...     ]
    ... )
    [(7, 'NEW')]

Using the advanced form we can query for closed bugs.

    >>> form = {
    ...     "orderby": "-importance",
    ...     "advanced": 1,
    ...     "search": "Search",
    ...     "field.status": "Fix Released",
    ... }

    >>> closed_bugtasks_view = create_view(name16, "+assignedbugs", form)
    >>> closed_bugtasks = list(closed_bugtasks_view.search().batch)
    >>> [(bugtask.bug.id, bugtask.status.name) for bugtask in closed_bugtasks]
    [(8, 'FIXRELEASED')]


Reported bugs
-------------

All bug tasks reported by someone. By default we'll get assigned and
unassigned bug tasks.

    >>> reported_bugtasks_view = create_view(name16, "+reportedbugs")
    >>> reported_bugtasks = list(reported_bugtasks_view.search().batch)
    >>> print(
    ...     pretty(
    ...         sorted(
    ...             [
    ...                 (
    ...                     bugtask.bug.id,
    ...                     bugtask.status.name,
    ...                     bugtask.bug.owner.name,
    ...                     getattr(bugtask.assignee, "name", None),
    ...                 )
    ...                 for bugtask in reported_bugtasks
    ...             ]
    ...         )
    ...     )
    ... )
    [(3, 'NEW', 'name16', None),
     (7, 'NEW', 'name16', 'name16'),
     (9, 'CONFIRMED', 'name16', None),
     (10, 'NEW', 'name16', None),
     (11, 'NEW', 'name16', None),
     (12, 'CONFIRMED', 'name16', None),
     (15, 'NEW', 'name16', None),
     (15, 'NEW', 'name16', None)]

But the advanced search allows us to query only the bug tasks that aren't
assigned.

    >>> form = {
    ...     "orderby": "-importance",
    ...     "assignee_option": "none",
    ...     "field.assignee": "",
    ...     "advanced": 1,
    ...     "search": "Search",
    ... }
    >>> reported_bugtasks_view = create_view(name16, "+reportedbugs", form)
    >>> reported_bugtasks = sorted(
    ...     reported_bugtasks_view.search().batch,
    ...     key=lambda bugtask: (bugtask.bug.id, bugtask.id),
    ... )
    >>> print(
    ...     pretty(
    ...         [
    ...             (
    ...                 bugtask.bug.id,
    ...                 bugtask.status.name,
    ...                 bugtask.bug.owner.name,
    ...                 getattr(bugtask.assignee, "name", None),
    ...             )
    ...             for bugtask in reported_bugtasks
    ...         ]
    ...     )
    ... )
    [(3, 'NEW', 'name16', None),
     (9, 'CONFIRMED', 'name16', None),
     (10, 'NEW', 'name16', None),
     (11, 'NEW', 'name16', None),
     (12, 'CONFIRMED', 'name16', None),
     (15, 'NEW', 'name16', None),
     (15, 'NEW', 'name16', None)]

Using the advanced form we can also query for closed bugs reported by someone.
Let's first close a bug setting its status to 'Invalid'.

    >>> from lp.services.database.sqlbase import flush_database_updates
    >>> from lp.testing import login

    >>> login("foo.bar@canonical.com")

    >>> from lp.bugs.interfaces.bugtask import BugTaskStatus
    >>> bug_task = reported_bugtasks[1]
    >>> print(bug_task.distribution.name)
    ubuntu
    >>> print(bug_task.sourcepackagename.name)
    thunderbird
    >>> bug_task.bug.id
    9
    >>> old_status = bug_task.status
    >>> bug_task.transitionToStatus(
    ...     BugTaskStatus.INVALID, getUtility(ILaunchBag).user
    ... )
    >>> flush_database_updates()

And now we query for it.

    >>> form = {
    ...     "orderby": "-importance",
    ...     "assignee_option": "none",
    ...     "field.assignee": "",
    ...     "advanced": 1,
    ...     "field.status": "Invalid",
    ...     "search": "Search bugs reported by Foo Bar",
    ... }
    >>> closed_reported_bugtasks_view = create_view(
    ...     name16, "+reportedbugs", form
    ... )
    >>> closed_reported_bugtasks = list(
    ...     closed_reported_bugtasks_view.search().batch
    ... )
    >>> sorted(
    ...     [
    ...         (
    ...             bugtask.bug.id,
    ...             bugtask.status.name,
    ...             getattr(bugtask.assignee, "name", None),
    ...         )
    ...         for bugtask in closed_reported_bugtasks
    ...     ]
    ... )
    [(9, 'INVALID', None)]

    >>> bug_task.transitionToStatus(old_status, getUtility(ILaunchBag).user)
    >>> flush_database_updates()


Subscribed bugs
---------------

All bug tasks someone is subscribed to. By default we'll get bug tasks
with any importance.

    >>> name12 = getUtility(IPersonSet).get(12)
    >>> subscribed_bugtasks_view = create_view(name12, "+subscribedbugs")
    >>> subscribed_bugtasks = list(subscribed_bugtasks_view.search().batch)
    >>> sorted(
    ...     [
    ...         (bugtask.bug.id, bugtask.status.name, bugtask.importance.name)
    ...         for bugtask in subscribed_bugtasks
    ...     ]
    ... )
    [(1, 'CONFIRMED', 'LOW'),
     (1, 'NEW', 'LOW'),
     (1, 'NEW', 'MEDIUM'),
     (4, 'NEW', 'MEDIUM'),
     (9, 'CONFIRMED', 'MEDIUM'),
     (13, 'NEW', 'UNDECIDED')]

Using the advanced form we can query for closed bugs someone is subscribed to.

    >>> form = {
    ...     "orderby": "-importance",
    ...     "assignee_option": "any",
    ...     "field.assignee": "",
    ...     "advanced": 1,
    ...     "field.status": "Fix Released",
    ...     "search": "Search bugs Sample Person is CC'd to",
    ... }
    >>> closed_subscribed_bugtasks_view = create_view(
    ...     name12, "+subscribedbugs", form
    ... )
    >>> closed_subscribed_bugtasks = list(
    ...     closed_subscribed_bugtasks_view.search().batch
    ... )
    >>> print(
    ...     pretty(
    ...         sorted(
    ...             [
    ...                 (
    ...                     bugtask.bug.id,
    ...                     bugtask.status.name,
    ...                     getattr(bugtask.assignee, "name", None),
    ...                 )
    ...                 for bugtask in closed_subscribed_bugtasks
    ...             ]
    ...         )
    ...     )
    ... )
    [(8, 'FIXRELEASED', 'name16')]


Bugs for Bug Supervisor
-----------------------

Malone can generate bug reports for packages on which a user is a bug
supervisor.

Finally, there is a helper method that returns a list of dicts used to
render the overview report.

    >>> packagebugs_search_view = create_view(
    ...     name16, name="+packagebugs", form=form
    ... )

    >>> package_bug_counts = packagebugs_search_view.package_bug_counts
    >>> len(package_bug_counts)
    2
    >>> ubuntu_firefox_bugcounts = package_bug_counts[0]

    >>> print(ubuntu_firefox_bugcounts["package_name"])
    mozilla-firefox in Ubuntu
    >>> print(ubuntu_firefox_bugcounts["package_search_url"])  # noqa
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox?field.status=New&field.status=Deferred&field.status=Incomplete&field.status=Confirmed&field.status=Triaged&field.status=In+Progress&field.status=Fix+Committed&search=Search

    >>> print(ubuntu_firefox_bugcounts["open_bugs_count"])
    1
    >>> print(ubuntu_firefox_bugcounts["critical_bugs_count"])
    0
    >>> print(ubuntu_firefox_bugcounts["unassigned_bugs_count"])
    1
    >>> print(ubuntu_firefox_bugcounts["inprogress_bugs_count"])
    0

    >>> print(ubuntu_firefox_bugcounts["open_bugs_url"])  # noqa
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox?field.status=New&field.status=Deferred&field.status=Incomplete&field.status=Confirmed&field.status=Triaged&field.status=In+Progress&field.status=Fix+Committed&search=Search
    >>> print(ubuntu_firefox_bugcounts["critical_bugs_url"])  # noqa
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox?field.importance=Critical&field.status=New&field.status=Deferred&field.status=Incomplete&field.status=Confirmed&field.status=Triaged&field.status=In+Progress&field.status=Fix+Committed&search=Search
    >>> print(ubuntu_firefox_bugcounts["unassigned_bugs_url"])  # noqa
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox?assignee_option=none&field.status=New&field.status=Deferred&field.status=Incomplete&field.status=Confirmed&field.status=Triaged&field.status=In+Progress&field.status=Fix+Committed&search=Search
    >>> print(ubuntu_firefox_bugcounts["inprogress_bugs_url"])  # noqa
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox?field.status=In+Progress&search=Search

The total number of bugs, broken down in the same ways as the package
bug counts, is also available.

    >>> total_counts = packagebugs_search_view.total_bug_counts
    >>> print(total_counts["open_bugs_count"])
    1
    >>> print(total_counts["critical_bugs_count"])
    0
    >>> print(total_counts["unassigned_bugs_count"])
    1
    >>> print(total_counts["inprogress_bugs_count"])
    0

Adding another bug will update the totals returned by
packagebugs_search_view.total_bug_counts.

    >>> import transaction
    >>> from zope.component import getUtility
    >>> from lp.bugs.interfaces.bug import CreateBugParams
    >>> from lp.bugs.interfaces.bugtask import BugTaskImportance
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> ubuntu_mozilla_firefox = ubuntu.getSourcePackage("mozilla-firefox")
    >>> bug_params = CreateBugParams(
    ...     owner=name16, title="Some new bug", comment="this is a new bug"
    ... )
    >>> new_bug = ubuntu_mozilla_firefox.createBug(bug_params)
    >>> new_bug.bugtasks[0].transitionToImportance(
    ...     BugTaskImportance.CRITICAL, name16
    ... )
    >>> flush_database_updates()

We re-create the view since total_bug_counts and package_bug_counts are
cached properties.

    >>> packagebugs_search_view = create_view(
    ...     name16, name="+packagebugs", form=form
    ... )

We can see that the firefox bug counts have been altered:

    >>> firefox_bug_counts = packagebugs_search_view.package_bug_counts[0]
    >>> print(firefox_bug_counts["open_bugs_count"])
    2
    >>> print(firefox_bug_counts["critical_bugs_count"])
    1
    >>> print(firefox_bug_counts["unassigned_bugs_count"])
    2
    >>> print(firefox_bug_counts["inprogress_bugs_count"])
    0

And the total bug counts reflect this:

    >>> total_counts = packagebugs_search_view.total_bug_counts
    >>> print(total_counts["open_bugs_count"])
    2
    >>> print(total_counts["critical_bugs_count"])
    1
    >>> print(total_counts["unassigned_bugs_count"])
    2
    >>> print(total_counts["inprogress_bugs_count"])
    0

Adding a new bug to a package other than Ubuntu Firefox will naturally
alter the total bug counts but not the firefox ones. Here, we use the
other package listed in name16's package bug listing overview, which is
pmount:

    >>> print(packagebugs_search_view.package_bug_counts[1]["package_name"])
    pmount in Ubuntu

    >>> pmount = ubuntu.getSourcePackage("pmount")
    >>> new_bug = pmount.createBug(bug_params)
    >>> bug_task = new_bug.getBugTask(pmount)
    >>> bug_task.transitionToStatus(BugTaskStatus.INPROGRESS, name16)
    >>> flush_database_updates()

    >>> packagebugs_search_view = create_view(
    ...     name16, name="+packagebugs", form=form
    ... )

So the total counts will have changed:

    >>> total_counts = packagebugs_search_view.total_bug_counts
    >>> print(total_counts["open_bugs_count"])
    3
    >>> print(total_counts["critical_bugs_count"])
    1
    >>> print(total_counts["unassigned_bugs_count"])
    3
    >>> print(total_counts["inprogress_bugs_count"])
    1

Whilst the firefox ones remain static:

    >>> firefox_bug_counts = packagebugs_search_view.package_bug_counts[0]
    >>> print(firefox_bug_counts["open_bugs_count"])
    2
    >>> print(firefox_bug_counts["critical_bugs_count"])
    1
    >>> print(firefox_bug_counts["unassigned_bugs_count"])
    2
    >>> print(firefox_bug_counts["inprogress_bugs_count"])
    0

And the pmount counts make up the difference between the two:

    >>> pmount_bug_counts = packagebugs_search_view.package_bug_counts[1]
    >>> print(pmount_bug_counts["open_bugs_count"])
    1
    >>> print(pmount_bug_counts["critical_bugs_count"])
    0
    >>> print(pmount_bug_counts["unassigned_bugs_count"])
    1
    >>> print(pmount_bug_counts["inprogress_bugs_count"])
    1

    >>> transaction.abort()


Bugs commented on by a Person
-----------------------------

It is possible to search for all the bugs commented on by a specific Person
using that Person's +commentedbugs page. Since No Privileges Person hasn't
commented on any bugs, viewing their +commentedbugs page will return no bugs:

    >>> no_priv = getUtility(IPersonSet).getByName("no-priv")
    >>> commented_bugtasks_view = create_view(no_priv, "+commentedbugs")
    >>> commented_bugs = list(commented_bugtasks_view.search().batch)
    >>> [bugtask.bug.id for bugtask in sorted(commented_bugs)]
    []

If No Privileges Person comments on bug one, their +commentedbugs page will
list that bug as being one of the bugs on which they have commented. The bug
will be listed three times since there are three BugTasks for that
particular bug (see bug 1357):

    >>> from lp.bugs.interfaces.bug import IBugSet
    >>> bug_one = getUtility(IBugSet).get(1)
    >>> bug_one.newMessage(no_priv, "Some message", "Contents")
    <Message id=...>

    >>> commented_bugtasks_view = create_view(no_priv, "+commentedbugs")
    >>> commented_bugs = list(commented_bugtasks_view.search().batch)
    >>> [bugtask.bug.id for bugtask in commented_bugs]
    [1, 1, 1]


Milestone lists in Person advanced bug search pages
---------------------------------------------------

The lists of milestones to select from on bug search pages is
calculated by doing an unmodified search (i.e. as if the user had gone
to the advanced search page and immediately clicked "Search") of the
user's bugs, then finding all the distinct milestones assigned to the
bug tasks found.

    >>> user = factory.makePerson()


Related bugs
............

    >>> related_bugs_view = create_view(user, "+bugs", {"advanced": 1})

A new user will have no related bugs, and therefore no related
milestones.

    >>> print(pretty(list(related_bugs_view.searchUnbatched())))
    []
    >>> print(pretty(related_bugs_view.getMilestoneWidgetValues()))
    []

Even if the user registers a product with a milestone, the list of
relevant milestones remains empty.

    >>> product = factory.makeProduct(owner=user, displayname="Coughing Bob")
    >>> milestone09 = factory.makeMilestone(product=product, name="0.9")

    >>> print(pretty(related_bugs_view.getMilestoneWidgetValues()))
    []

Even if the user files a bug against a product with a milestone, the
list of relevant milestones remains empty.

    >>> bug = factory.makeBug(target=product, owner=user)
    >>> transaction.commit()

    >>> print(pretty(list(related_bugs_view.searchUnbatched())))
    [<BugTask ...>]
    >>> print(pretty(related_bugs_view.getMilestoneWidgetValues()))
    []

Only when a milestone is set for a related bug task does the advanced
search page allow selection of a milestone.

    >>> bug.bugtasks[0].milestone = milestone09
    >>> transaction.commit()

    >>> print(pretty(related_bugs_view.getMilestoneWidgetValues()))
    [{'checked': False,
      'title': 'Coughing Bob 0.9',
      'value': ...}]


Reported bugs
.............

Similar behaviour is found when searching for reported bugs.

    >>> reported_bugs_view = create_view(
    ...     user, "+reportedbugs", {"advanced": 1}
    ... )

The earlier bug was reported by our user, so the assigned milestone
will already appear.

    >>> print(pretty(reported_bugs_view.getMilestoneWidgetValues()))
    [{'checked': False,
      'title': 'Coughing Bob 0.9',
      'value': ...}]

Filing a new bug and assigning a new milestone will make the new
milestone appear amongst the possible options.

    >>> milestone10 = factory.makeMilestone(product=product, name="1.0")
    >>> bug = factory.makeBug(target=product, owner=user)
    >>> bug.bugtasks[0].milestone = milestone10

    >>> print(pretty(reported_bugs_view.getMilestoneWidgetValues()))
    [{'checked': False,
      'title': 'Coughing Bob 1.0',
      'value': ...},
     {'checked': False,
      'title': 'Coughing Bob 0.9',
      'value': ...}]


Assigned bugs
.............

    >>> assigned_bugs_view = create_view(
    ...     user, "+assignedbugs", {"advanced": 1}
    ... )

No bugs have been assigned to our user, so no relevant milestones are
found.

    >>> print(pretty(assigned_bugs_view.getMilestoneWidgetValues()))
    []

Once a bug has been assigned, the milestone appears.

    >>> bug.bugtasks[0].transitionToAssignee(user)

    >>> print(pretty(assigned_bugs_view.getMilestoneWidgetValues()))
    [{'checked': False,
      'title': 'Coughing Bob 1.0',
      'value': ...}]


Commented bugs
..............

    >>> commented_bugs_view = create_view(
    ...     user, "+commentedbugs", {"advanced": 1}
    ... )

Our user has not commented on any bugs, so no relevant milestones are
found.

    >>> print(pretty(commented_bugs_view.getMilestoneWidgetValues()))
    []

Once the user has commented, the related milestone does appear.

    >>> bug.newMessage(user)
    <Message id=...>

    >>> print(pretty(commented_bugs_view.getMilestoneWidgetValues()))
    [{'checked': False,
      'title': 'Coughing Bob 1.0',
      'value': ...}]


Subscribed bugs
...............

    >>> new_user = factory.makePerson()
    >>> subscribed_bugs_view = create_view(
    ...     new_user, "+subscribedbugs", {"advanced": 1}
    ... )

Our new_user is not subscribed to any bugs, so no relevant milestones
are found.

    >>> print(pretty(subscribed_bugs_view.getMilestoneWidgetValues()))
    []

Once new_user has subscribed, the related milestones appear.

    >>> bug.subscribe(new_user, new_user)
    <BugSubscription ...>

    >>> print(pretty(subscribed_bugs_view.getMilestoneWidgetValues()))
    [{'checked': False,
      'title': 'Coughing Bob 1.0',
      'value': ...}]
