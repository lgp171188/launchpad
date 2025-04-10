Bug Privileged Statuses
=======================

Some statuses, e.g. Won't Fix, are restricted. Only members of the Bug
Supervisor team may change a bug to that status.

    >>> from lp.bugs.tests.bug import print_bug_affects_table
    >>> def print_highlighted_bugtask(browser):
    ...     print_bug_affects_table(browser.contents, highlighted_only=True)
    ...

Unprivileged users
------------------

    >>> user_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+source/"
    ...     "mozilla-firefox/+bug/1/+editstatus"
    ... )

    >>> status_control = user_browser.getControl("Status")
    >>> print(status_control.displayValue)
    ['New']

An unprivileged user can confirm the bug:

    >>> status_control.displayValue = ["Confirmed"]
    >>> user_browser.getControl("Save Changes").click()

    >>> print(user_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/1
    >>> print_highlighted_bugtask(user_browser)
    mozilla-firefox (Ubuntu) ... Confirmed  Medium Unassigned ...

But they cannot change the status to Won't Fix or to Triaged, and so
those statuses are not shown in the UI:

    >>> user_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+source/"
    ...     "mozilla-firefox/+bug/1/+editstatus"
    ... )

    >>> status_control = user_browser.getControl("Status")
    >>> print(status_control.displayValue)
    ['Confirmed']

    >>> status_control.displayValue = ["Won't Fix"]
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.ItemNotFoundError: Won't Fix

    >>> status_control.displayValue = ["Triaged"]
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.ItemNotFoundError: Triaged

    >>> status_control.displayValue = ["Does Not Exist"]
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.ItemNotFoundError: Does Not Exist

    >>> status_control.displayValue = ["Deferred"]
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.ItemNotFoundError: Deferred

Bug Supervisor
--------------

Ubuntu needs a Bug Supervisor first of all:

    >>> admin_browser.open("http://bugs.launchpad.test/ubuntu/+bugsupervisor")
    >>> admin_browser.getControl("Bug Supervisor").value = (
    ...     "test@canonical.com"
    ... )
    >>> admin_browser.getControl("Change").click()

    >>> print(
    ...     extract_text(
    ...         find_tag_by_id(admin_browser.contents, "bug-supervisor")
    ...     )
    ... )
    Bug supervisor:
    Sample Person

The new Bug Supervisor for Ubuntu can change the status to Won't Fix:

    >>> bug_supervisor_browser = setupBrowser(
    ...     auth="Basic test@canonical.com:test"
    ... )

    >>> bug_supervisor_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+source/"
    ...     "mozilla-firefox/+bug/1/+editstatus"
    ... )

    >>> status_control = bug_supervisor_browser.getControl("Status")
    >>> print(status_control.displayValue)
    ['Confirmed']

    >>> status_control.displayValue = ["Won't Fix"]
    >>> bug_supervisor_browser.getControl("Save Changes").click()

    >>> print(bug_supervisor_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/1
    >>> print_highlighted_bugtask(bug_supervisor_browser)
    mozilla-firefox (Ubuntu) ... Won't Fix  Medium Unassigned ...

Now the bug has been changed, a regular user can see the Won't Fix
status. Earlier it was not even displayed as an option.

    >>> user_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+source/"
    ...     "mozilla-firefox/+bug/1/+editstatus"
    ... )

    >>> status_control = user_browser.getControl("Status")
    >>> print(status_control.displayValue)
    ["Won't Fix"]

And a regular user can change other aspects of the bug:

    >>> package_control = user_browser.getControl(
    ...     name="ubuntu_mozilla-firefox.target.package"
    ... )
    >>> print(package_control.value)
    mozilla-firefox

    >>> package_control.value = "iceweasel"
    >>> user_browser.getControl("Save Changes").click()

    >>> print(bug_supervisor_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/1
    >>> print_highlighted_bugtask(bug_supervisor_browser)
    mozilla-firefox (Ubuntu) ... Won't Fix  Medium Unassigned ...

The Bug Supervisor for Ubuntu can also change the status to Triaged:

    >>> bug_supervisor_browser.open(
    ...     "http://bugs.launchpad.test/ubuntu/+source/"
    ...     "iceweasel/+bug/1/+editstatus"
    ... )

    >>> status_control = bug_supervisor_browser.getControl("Status")
    >>> print(status_control.displayValue)
    ["Won't Fix"]

    >>> status_control.displayValue = ["Triaged"]
    >>> bug_supervisor_browser.getControl("Save Changes").click()

    >>> print(bug_supervisor_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/iceweasel/+bug/1
    >>> print_highlighted_bugtask(bug_supervisor_browser)
    iceweasel (Ubuntu) ... Triaged  Medium Unassigned ...
