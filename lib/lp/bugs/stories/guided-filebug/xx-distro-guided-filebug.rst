Filing bugs on Distributions
============================

Like filing bugs on products, filing bugs on distributions involves
first finding out if you're bug has already been reported.

    >>> user_browser.open("http://launchpad.test/ubuntu/+filebug")

Submitting a bug title...

The example here are a little short - in reality we have a comprehensive
database to find candidates from, our sample data has no real near-fits,
see bug 612384 for the overall effort to provide a sensible search facility.

    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "Thunderbird crashes opening"
    ... )
    >>> user_browser.getControl("Continue").click()

...yields one similar bug.

    >>> from lp.bugs.tests.bug import print_bugs_list
    >>> print_bugs_list(user_browser.contents, "similar-bugs")
    #9 Thunderbird crashes
    Confirmed (0 comments) last updated 2006-07-14...
    Every time I start Thunderbird...

Subscribing to one of the similar bugs takes us to the bug page.

    >>> user_browser.getControl(
    ...     "Yes, this is the bug I'm trying to report"
    ... ).click()

    >>> print(user_browser.url)
    http://bugs.launchpad.test/thunderbird/+bug/9

    >>> print_feedback_messages(user_browser.contents)
    This bug has been marked as affecting you.

Actually, on reflection, that's not our bug after all. Let's go
back...

    # We should use goBack() here but can't because of bug #98372:
    # zope.testbrowser truncates document content after goBack().
    >>> user_browser.open("http://launchpad.test/ubuntu/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "Thunderbird crashes when opening large emails"
    ... )
    >>> user_browser.getControl("Continue").click()

...and continue filing our bug.

    >>> user_browser.getControl(name="packagename_option").value = ["choose"]
    >>> user_browser.getControl("In what package").value = "mozilla-firefox"
    >>> user_browser.getControl("Summary", index=0).value = "a new ubuntu bug"
    >>> user_browser.getControl("Bug Description").value = "test"

The comment field ("Bug Description") is not optional when
filing a bug, but it is optional when subscribing to a similar
bug. Nevertheless, we don't show an "(Optional)" hint next to the
description.

    >>> import re

    >>> page_soup = find_main_content(user_browser.contents)
    >>> field_labels = page_soup.find_all(
    ...     "label", text=re.compile("Bug Description")
    ... )
    >>> for field_label in field_labels:
    ...     print(extract_text(field_label.parent))
    ...
    Bug Description:

Finally, let's submit the bug.

    >>> user_browser.getControl("Submit Bug Report").click()

    >>> print(user_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/...


Filing a bug when there are none similar
----------------------------------------

When no similar bugs are found the form works the same but appears
different in the user agent.

    >>> user_browser.open("http://launchpad.test/ubuntu/+filebug")

Submitting a distinctive bug title...

    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "Frobnobulator emits weird noises."
    ... )
    >>> user_browser.getControl("Continue").click()

...yields no similar bugs. In fact, the similar bugs table is not even
shown.

    >>> similar_bugs_list = find_tag_by_id(
    ...     user_browser.contents, "similar-bugs"
    ... )
    >>> print(similar_bugs_list)
    None

But the bug can be filed as before.

    >>> user_browser.getControl(name="packagename_option").value = ["choose"]
    >>> user_browser.getControl("In what package").value = "mozilla-firefox"
    >>> user_browser.getControl("Bug Description").value = (
    ...     "Frobnobulator is a Firefox add-on, ..."
    ... )
    >>> user_browser.getControl("Submit Bug Report").click()

    >>> print(user_browser.url)
    http://bugs.launchpad.test/ubuntu/+source/mozilla-firefox/+bug/...
