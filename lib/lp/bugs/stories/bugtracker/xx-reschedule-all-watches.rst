Rescheduling watches on a bugtracker
====================================

It's possible for all the watches on a bug tracker to be rescheduled, in
much the same way as it's possible to reschedule a single bug watch that
is failing to update.

    >>> from lp.services.webapp import canonical_url
    >>> from lp.testing.sampledata import ADMIN_EMAIL
    >>> from lp.testing import login, logout

    >>> login(ADMIN_EMAIL)
    >>> bug_tracker = factory.makeBugTracker(
    ...     name="our-bugtracker", title="Our BugTracker"
    ... )
    >>> bug_watch = factory.makeBugWatch(bugtracker=bug_tracker)
    >>> logout()

    >>> bug_tracker_edit_url = canonical_url(bug_tracker) + "/+edit"

The functionality to do this is available from the bug tracker's +edit
page. It isn't visible to ordinary users, however.

    >>> user_browser.open(bug_tracker_edit_url)
    >>> user_browser.getControl("Reschedule all watches")
    Traceback (most recent call last):
      ...
    LookupError: label ...'Reschedule all watches'
    ...

However, the reschedule button will appear to administrators.

    >>> admin_browser.open(bug_tracker_edit_url)
    >>> admin_browser.getControl("Reschedule all watches")
    <SubmitControl...>

It will also appear for non-admin registry experts.

    >>> from lp.testing import login_celebrity

    >>> registry_expert = login_celebrity("registry_experts")
    >>> registry_browser = setupBrowser(
    ...     auth="Basic %s:test" % registry_expert.preferredemail.email
    ... )
    >>> logout()

    >>> registry_browser.open(bug_tracker_edit_url)
    >>> reschedule_button = registry_browser.getControl(
    ...     "Reschedule all watches"
    ... )

Clicking the button will reschedule the watches for the bug tracker for
checking at some future date.

    >>> reschedule_button.click()
    >>> print(registry_browser.url)
    http://bugs.launchpad.test/bugs/bugtrackers/our-bugtracker

    >>> for message in find_tags_by_class(
    ...     registry_browser.contents, "informational message"
    ... ):
    ...     print(extract_text(message))
    All bug watches on Our BugTracker have been rescheduled.

If we look at the bug watch on our bugtracker we can see that it has
been scheduled for checking at some point in the future.

    >>> from datetime import datetime, timezone

    >>> login(ADMIN_EMAIL)
    >>> print(bug_watch.next_check >= datetime.now(timezone.utc))
    True

Should the bug watch be deleted the reschedule button will no longer
appear on the bugtracker page.

    >>> bug_watch.destroySelf()
    >>> logout()

    >>> registry_browser.open(bug_tracker_edit_url)
    >>> reschedule_button = registry_browser.getControl(
    ...     "Reschedule all watches"
    ... )
    Traceback (most recent call last):
      ...
    LookupError: label ...'Reschedule all watches'
    ...
