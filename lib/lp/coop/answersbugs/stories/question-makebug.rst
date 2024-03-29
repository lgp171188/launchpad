Turning a Question into a Bug
=============================

The question page shows a link to make the question into a bug.

    >>> browser.open("http://launchpad.test/firefox/+question/2")
    >>> createLink = browser.getLink("Create bug report")
    >>> createLink is not None
    True

This link brings the user to page proposing to create a new bug based
on the content of the question. The bug description is set to the
the question's description and the title is empty.

    >>> browser.addHeader("Authorization", "Basic foo.bar@canonical.com:test")
    >>> createLink.click()
    >>> print(browser.title)
    Create bug report based on question #2...
    >>> browser.getControl("Summary").value
    ''
    >>> browser.getControl("Description").value
    "...I'm trying to learn about SVG..."

The user must enter a valid title and description before creating the
bug.

    >>> browser.getControl("Description").value = ""
    >>> browser.getControl("Create").click()
    >>> soup = find_main_content(browser.contents)
    >>> for tag in soup("div", "message"):
    ...     print(tag.string)
    ...
    Required input is missing.
    Required input is missing.

Clicking the 'Create' button creates the bug with the user-specified title
and description and redirects the user to the bug page.

    >>> browser.getControl("Summary").value = (
    ...     "W3C SVG demo doesn't work in Firefox"
    ... )
    >>> browser.getControl("Description").value = (
    ...     "Browsing to the W3C SVG demo results in a blank page."
    ... )
    >>> browser.getControl("Create").click()
    >>> browser.url
    '.../firefox/+bug/...'
    >>> soup = find_main_content(browser.contents)
    >>> for tag in soup("h1"):
    ...     print(extract_text(tag))
    ...
    W3C SVG demo doesn't work in Firefox Edit
    >>> print(
    ...     extract_text(find_tag_by_id(browser.contents, "edit-description"))
    ... )
    Edit Bug Description
    Browsing to the W3C SVG demo results in a blank page.

The bug page will display a link to the originating question in the 'Related
questions' portlet:

    >>> portlet = find_portlet(browser.contents, "Related questions")
    >>> for question in portlet.find_all("li", "question-row"):
    ...     print(question.decode_contents())
    ...
    <span class="sprite question">Mozilla Firefox</span>:
    ...<a href=".../firefox/+question/2">Problem...

A user can't create a bug report when a question has already a bug linked
to it.

    >>> browser.open("http://launchpad.test/firefox/+question/2")
    >>> browser.contents
    '...<h3>Related bugs</h3>...'
    >>> browser.getLink("Create bug report")
    Traceback (most recent call last):
      ..
    zope.testbrowser.browser.LinkNotFoundError

It works with distribution questions as well.

    >>> browser.open("http://launchpad.test/ubuntu/+question/5/+makebug")
    >>> browser.getControl("Summary").value = (
    ...     "Ubuntu Installer can't find CDROM"
    ... )
    >>> browser.getControl("Create Bug Report").click()
    >>> browser.url
    '.../ubuntu/+bug/...'
    >>> soup = find_main_content(browser.contents)
    >>> for tag in soup("div", "informational message"):
    ...     print(tag.string)
    ...
    Thank you! Bug...created.
