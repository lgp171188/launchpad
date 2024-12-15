Bug filing options for bug supervisors
======================================

During the bug filing process, normal or advanced, bug supervisors are
able to set the status and importance of the bug being filed, can
target it to a milestone, and assign it to a user.

Users who are not bug supervisors do not see any of these options:

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "Bug"
    >>> user_browser.getControl("Continue").click()

    >>> user_browser.getControl("Status")
    Traceback (most recent call last):
    ...
    LookupError: label ...'Status'
    ...

    >>> user_browser.getControl("Importance")
    Traceback (most recent call last):
    ...
    LookupError: label ...'Importance'
    ...

    >>> user_browser.getControl("Milestone")
    Traceback (most recent call last):
    ...
    LookupError: label ...'Milestone'
    ...

    >>> user_browser.getControl("Assign to")
    Traceback (most recent call last):
    ...
    LookupError: label ...'Assign to'
    ...

Users who are bug supervisors can see these options:

    >>> admin_browser.open(
    ...     "http://bugs.launchpad.test/firefox/+bugsupervisor"
    ... )
    >>> admin_browser.getControl("Bug Supervisor").value = "no-priv"
    >>> admin_browser.getControl("Change").click()

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "Bug"
    >>> user_browser.getControl("Continue").click()

    >>> user_browser.getControl("Status")
    <ListControl name='field.status' type='select'>
    >>> user_browser.getControl("Importance")
    <ListControl name='field.importance' type='select'>
    >>> user_browser.getControl("Milestone")
    <ListControl name='field.milestone' type='select'>
    >>> user_browser.getControl("Assign to")
    <Control name='field.assignee' type='text'>


Using these extra options
-------------------------

    >>> from lp.bugs.tests.bug import print_bug_affects_table

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "Bug"
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.getControl("Bug Description").value = "Blah"

A bug supervisor can set the status, importance, milestone, and/or
assignee, and the bug will be filed with those choices.

    >>> user_browser.getControl("Status").displayValue = ["Triaged"]
    >>> user_browser.getControl("Importance").displayValue = ["High"]
    >>> user_browser.getControl("Milestone").displayValue = [
    ...     "Mozilla Firefox 1.0"
    ... ]
    >>> user_browser.getControl("Assign to").value = "spiv"

    >>> user_browser.getControl("Submit Bug Report").click()
    >>> print_bug_affects_table(user_browser.contents)
    Mozilla Firefox ...
    Triaged
    High
    Andrew Bennetts
    ...
    1.0
