Adding tags
===========


Normal bug filing page
----------------------

On the normal +filebug page, tags can be added to the bug as the bug
is being filed.

    >>> from lp.bugs.tests.bug import print_bug_tag_anchors

    >>> user_browser.open("http://bugs.launchpad.test/firefox/+filebug")
    >>> user_browser.getControl("Summary", index=0).value = "Bug with tags"
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.getControl("Tags").value = "foo bar"
    >>> user_browser.getControl("Bug Description").value = "This bug has tags"
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/firefox/+bug/...'

    >>> tags_div = find_tag_by_id(user_browser.contents, "bug-tags")
    >>> print_bug_tag_anchors(tags_div("a"))
    unofficial-tag bar
    unofficial-tag foo


Pre-populating the tags field
-----------------------------

For people wanting to pre-fill the tags field with certain tags, it's
possible to do so by supplying a 'field.tags' URL parameter.

This works for the normal bug filing process:

    >>> user_browser.open(
    ...     "http://bugs.launchpad.test/firefox/"
    ...     "+filebug?field.tags=foo+bar"
    ... )
    >>> user_browser.getControl("Summary", index=0).value = "Bug with tags"
    >>> user_browser.getControl("Continue").click()
    >>> user_browser.getControl("Tags").value
    'bar foo'
