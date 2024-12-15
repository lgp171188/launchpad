Advanced searching using person-based filters
=============================================

The advanced search form allows us to filter bugs based on the people
related to them: assignees, commenters, package subscribers and
subscribers.


Widget basics
-------------

When searching by username we need to both select the corresponding
radio button and enter a valid user name. The username input
automatically selects the corresponding radio button when we type some
text into it by calling the selectWidget Javascript function.

    >>> browser.open("http://launchpad.test/firefox/+bugs?advanced=1")
    >>> assignee_widget = find_tag_by_id(browser.contents, "field.assignee")
    >>> print(assignee_widget["onkeypress"])
    selectWidget('assignee_option', event)

    >>> print(find_tag_by_id(browser.contents, "assignee_option"))
    <input...type="radio"...>


Searching by assignee
---------------------

To search bugs by assignee, we can select from two options: `Nobody`
(bugs that aren't assigned) or by a specific user name.

    >>> from lp.bugs.tests.bug import print_bugtasks

Let's test the advanced form for a distribution.  We get the search
results when we use a valid assignee.

    >>> from lp.testing.service_usage_helpers import set_service_usage
    >>> set_service_usage("debian", bug_tracking_usage="LAUNCHPAD")

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/debian/+bugs?advanced=1"
    ... )
    >>> anon_browser.getControl(name="field.assignee").value = "name12"
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_bugtasks(anon_browser.contents)
    2 Blackhole Trash folder mozilla-firefox (Debian) Low Confirmed

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/~name12/+reportedbugs?advanced=1"
    ... )
    >>> anon_browser.getControl(name="field.assignee").value = "mark"
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_bugtasks(anon_browser.contents)
    1 Firefox does not support SVG Mozilla Firefox Low New

If we enter an invalid assignee, we'll get a nice error message.

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+bugs?advanced=1"
    ... )
    >>> anon_browser.getControl(name="field.assignee").value = (
    ...     "invalid-assignee"
    ... )
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_feedback_messages(anon_browser.contents)
    There's no person with the name or email address 'invalid-assignee'.

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/~name12/+reportedbugs?advanced=1"
    ... )
    >>> anon_browser.getControl(name="field.assignee").value = (
    ...     "invalid-assignee"
    ... )
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_feedback_messages(anon_browser.contents)
    There's no person with the name or email address 'invalid-assignee'.


Searching by reporter
---------------------

Valid searches work:

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/debian/+bugs?advanced=1"
    ... )
    >>> anon_browser.getControl(name="field.bug_reporter").value = "name12"
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_bugtasks(anon_browser.contents)
    1 Firefox does not support SVG mozilla-firefox (Debian) Low Confirmed
    2 Blackhole Trash folder mozilla-firefox (Debian) Low Confirmed

    >>> anon_browser.open("http://bugs.launchpad.test/~name12/+assignedbugs")
    >>> anon_browser.getControl(name="field.bug_reporter").value = "name12"
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_bugtasks(anon_browser.contents)
    5 Firefox ... should be complete Mozilla Firefox Critical New
    2 Blackhole Trash folder mozilla-firefox (Debian) Low Confirmed

and invalid searches don't OOPS:

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/debian/+bugs?advanced=1"
    ... )
    >>> anon_browser.getControl(name="field.bug_reporter").value = (
    ...     "invalid-reporter"
    ... )
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_feedback_messages(anon_browser.contents)
    There's no person with the name or email address 'invalid-reporter'.

    >>> anon_browser.open("http://bugs.launchpad.test/~name12/+assignedbugs")
    >>> anon_browser.getControl(name="field.bug_reporter").value = (
    ...     "invalid-reporter"
    ... )
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print_feedback_messages(anon_browser.contents)
    There's no person with the name or email address 'invalid-reporter'.


Searching for a bug commenter's bugs
------------------------------------

On the advanced search there's a field for specifying a bug commenter.

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+bugs?advanced=1"
    ... )
    >>> anon_browser.getControl("Commenter") is not None
    True

If an non-existent person is entered there, an error message is
displayed.

    >>> anon_browser.getControl("Commenter").value = "non-existent"
    >>> anon_browser.getControl("Search", index=0).click()
    >>> for message in find_tags_by_class(anon_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There's no person with the name or email address 'non-existent'.

Entering an existing person shows all bugs that person has commented on
or made metadata changes to.

    >>> anon_browser.getControl("Commenter").value = "foo.bar@canonical.com"
    >>> anon_browser.getControl("Search", index=0).click()

    >>> from lp.bugs.tests.bug import print_bugtasks
    >>> print_bugtasks(anon_browser.contents)
    1 Firefox does not support SVG
      mozilla-firefox (Ubuntu) Medium New
    10 another test bug
      linux-source-2.6.15 (Ubuntu) Medium New
    2 Blackhole Trash folder
      Ubuntu Medium New


Searching for a package subscriber's bugs
-----------------------------------------

On the advanced search there's a field for specifying a project,
distribution, package, or series subscriber.

    >>> anon_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+bugs?advanced=1"
    ... )
    >>> anon_browser.getControl("Package or series subscriber") is not None
    True

Entering an existing person shows all bugs for packages or products that
the person is a package subscriber for. Since we're in the ubuntu
context, only bugs for Ubuntu packages will be returned. In Ubuntu, Foo
Bar is a package subscriber for mozilla-firefox and pmount, but there
aren't any bugs open for pmount.

    >>> anon_browser.getControl("Package or series subscriber").value = (
    ...     "foo.bar@canonical.com"
    ... )
    >>> anon_browser.getControl("Search", index=0).click()

    >>> from lp.bugs.tests.bug import print_bugtasks
    >>> print_bugtasks(anon_browser.contents)
    1 Firefox does not support SVG
      mozilla-firefox (Ubuntu) Medium New


Searching for a bug subscriber's bugs
=====================================

On the advanced search page there's a field for specifying a bug
subscriber:

    >>> search_url = "http://bugs.launchpad.test/firefox/+bugs?advanced=1"
    >>> anon_browser.open(search_url)
    >>> anon_browser.getControl("Subscriber") is not None
    True

If an non-existent person is entered there, an error message is
displayed:

    >>> anon_browser.getControl("Subscriber").value = "non-existent"
    >>> anon_browser.getControl("Search", index=0).click()
    >>> for message in find_tags_by_class(anon_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There's no person with the name or email address 'non-existent'.

Entering an existing person shows all bugs for packages or products that
the person is subscribed to. To demonstrate, we'll begin with a user who
isn't subscribed to any bugs. In this case, no bugs are found:

    >>> subscriber = "no-priv@canonical.com"
    >>> anon_browser.getControl("Subscriber").value = subscriber
    >>> anon_browser.getControl("Search", index=0).click()
    >>> print(extract_text(find_main_content(anon_browser.contents)))
    Advanced search
    ...
    No results for search

We'll continue by subscribing the same user to a couple of bugs.
However, first we'll register a couple of bugs for the Mozilla Firefox
product:

    >>> browser = setupBrowser(auth="Basic test@canonical.com:test")
    >>> browser.open("http://bugs.launchpad.test/firefox/")
    >>> browser.getLink("Report a bug").click()
    >>> print(extract_text(find_main_content(browser.contents)))
    Report a bug...

    >>> report_bug_url = browser.url

    >>> browser.getControl("Summary", index=0).value = "Test Bug 1"
    >>> browser.getControl("Continue").click()

    >>> browser.getControl("Bug Description").value = "Test Bug 1"
    >>> browser.getControl("Submit").click()
    >>> print_feedback_messages(browser.contents)
    Thank you for your bug report...

    >>> bug_1_url = browser.url

    >>> browser.open(report_bug_url)
    >>> browser.getControl("Summary", index=0).value = "Test Bug 2"
    >>> browser.getControl("Continue").click()
    >>> browser.getControl("Bug Description").value = "Test Bug 2"
    >>> browser.getControl("Submit").click()
    >>> print_feedback_messages(browser.contents)
    Thank you for your bug report...

    >>> bug_2_url = browser.url

Next we'll subscribe our user to the first bug we've just registered:

    >>> browser.open(bug_1_url)
    >>> browser.getLink("Subscribe someone else").click()
    >>> print(extract_text(find_main_content(browser.contents)))
    Subscribe someone else to bug #...

    >>> browser.getControl("Person").value = subscriber
    >>> browser.getControl("Subscribe user").click()
    >>> print_feedback_messages(browser.contents)
    No Privileges Person has been subscribed to this bug...

Now if we repeat our earlier search for bugs our user is subscribed to,
we'll find our first bug within the results:

    >>> anon_browser.open(search_url)
    >>> anon_browser.getControl("Subscriber").value = subscriber
    >>> anon_browser.getControl("Search", index=0).click()
    >>> from lp.bugs.tests.bug import extract_bugtasks
    >>> for bugtask in extract_bugtasks(anon_browser.contents):
    ...     print("Task:" + bugtask)
    ...
    Task:...Test Bug 1...Undecided...New

Next we'll subscribe our user to the second bug we've just registered:

    >>> browser.open(bug_2_url)
    >>> browser.getLink("Subscribe someone else").click()
    >>> print(extract_text(find_main_content(browser.contents)))
    Subscribe someone else to bug #...

    >>> browser.getControl("Person").value = subscriber
    >>> browser.getControl("Subscribe user").click()
    >>> print_feedback_messages(browser.contents)
    No Privileges Person has been subscribed to this bug...

Finally, if we repeat our earlier search for bugs our user is subscribed
to, we'll find both of our bugs within the results:

    >>> anon_browser.open(search_url)
    >>> anon_browser.getControl("Subscriber").value = subscriber
    >>> anon_browser.getControl("Search", index=0).click()
    >>> for bugtask in extract_bugtasks(anon_browser.contents):
    ...     print("Task:" + bugtask)
    ...
    Task:...Test Bug 1...Undecided...New
    Task:...Test Bug 2...Undecided...New


