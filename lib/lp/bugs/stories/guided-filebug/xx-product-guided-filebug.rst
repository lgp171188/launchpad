Filing bugs on Products
=======================

Launchpad does its best to minimize duplicate bug reports. The +filebug
page for a product starts by asking the user to see if their bug has
already been reported.

    >>> user_browser.open("http://bugs.launchpad.test/firefox")
    >>> user_browser.getLink("Report a bug").click()

If no title is entered, the user is asked to supply one.

    >>> user_browser.getControl("Summary", index=0).value
    ''

    >>> user_browser.getControl("Continue").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/firefox/+filebug'

    >>> top_portlet = first_tag_by_class(user_browser.contents, "top-portlet")
    >>> for message in top_portlet.find_all(attrs={"class": "error message"}):
    ...     print(message.decode_contents())
    There is 1 error.
    >>> for message in top_portlet.find_all(
    ...     lambda node: node.attrs.get("class") == ["message"]
    ... ):
    ...     print(message.decode_contents())
    Required input is missing.

The user fills in some keywords, and clicks a button to search existing
bugs.

    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "SVG images are broken"
    ... )
    >>> user_browser.getControl("Continue").click()

The form is self-posting, so the user is still at +filebug. This makes
it difficult to bypass the search-for-dupes bit.

    >>> print(user_browser.url)
    http://bugs.launchpad.test/firefox/+filebug

After searching, the user is presented with a list of similar bugs in
the current context.

    >>> from lp.bugs.tests.bug import print_bugs_list

    >>> print_bugs_list(user_browser.contents, "similar-bugs")
    #1 Firefox does not support SVG
    New (1 comment) last updated 2006-05-19...
    Firefox needs to support embedded SVG...

If the user doesn't see their bug already reported, they can proceed to
file the bug.

If the user for some reason would erase the summary, an error message
will be displayed as well.

    >>> user_browser.getControl("Bug Description").value = "not empty"
    >>> user_browser.getControl("Summary", index=0).value = ""
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> print(user_browser.url)
    http://bugs.launchpad.test/firefox/+filebug

    >>> print(find_main_content(user_browser.contents).decode_contents())
    <...
    No similar bug reports were found...

    >>> for message in find_tags_by_class(user_browser.contents, "message"):
    ...     print(message.decode_contents())
    ...
    There is 1 error.
    Provide a one-line summary of the problem.

With both values set, the bug is created.

    >>> user_browser.getControl("Summary", index=0).value = "a brand new bug"
    >>> user_browser.getControl("Bug Description").value = "test"
    >>> user_browser.getControl("Submit Bug Report").click()

    >>> print(user_browser.url)
    http://bugs.launchpad.test/firefox/+bug/...


Subscribing to a similar bug
----------------------------

If our bug is described by one of the suggested similar bugs, we can
subscribe to it instead of filing a new bug. This also loosely implies a
"me too" vote.

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "SVG images are broken"
    ... )
    >>> user_browser.getControl("Continue").click()

As before, we get a list of similar bugs to choose from.

    >>> print_bugs_list(user_browser.contents, "similar-bugs")
    #1 Firefox does not support SVG
    New (1 comment) last updated 2006-05-19...
    Firefox needs to support embedded SVG...

This one matches, so we mark it as affecting us.

    >>> user_browser.getControl(
    ...     "Yes, this is the bug I'm trying to report"
    ... ).click()

    >>> print(user_browser.url)
    http://bugs.launchpad.test/firefox/+bug/1

    >>> print_feedback_messages(user_browser.contents)
    This bug has been marked as affecting you.

It's also possible to subscribe to the suggested duplicates. This is
handled by a JavaScript FormOverlay, but for the sake of integration
testing we'll test it here, too.

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "SVG images are broken"
    ... )
    >>> user_browser.getControl("Continue").click()

There's a hidden field on the "yes, this is my bug" form, which we can
set to ensure that we get subscribed to the bug.

    >>> user_browser.getControl(
    ...     name="field.subscribe_to_existing_bug"
    ... ).value = "yes"
    >>> user_browser.getControl(
    ...     "Yes, this is the bug I'm trying to report"
    ... ).click()

    >>> print_feedback_messages(user_browser.contents)
    This bug is already marked as affecting you.
    You have subscribed to this bug report.


Filing a bug when there are none similar
----------------------------------------

When no similar bugs are found the form works the same but appears
different in the user agent.

    >>> user_browser.open("http://launchpad.test/firefox/+filebug")

Submitting some distinctive details...

    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "Frankenzombulon reanimated neighbour's dead pet"
    ... )
    >>> user_browser.getControl("Continue").click()

...yields no similar bugs. In fact, the similar bugs table is not even
shown.

    >>> similar_bugs_list = find_tag_by_id(
    ...     user_browser.contents, "similar-bugs"
    ... )
    >>> print(similar_bugs_list)
    None

But, as before, entering a description and submitting the bug takes the
user to the bug page.

    >>> user_browser.getControl("Bug Description").value = (
    ...     "Frankenzombulon is only meant to check my mail."
    ... )
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/firefox/+bug/...'

    >>> print(user_browser.title)
    Bug #...Frankenzombulon reanimated... : Bugs : Mozilla Firefox
