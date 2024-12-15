Filing bugs on ProjectGroups
============================

Even though it's not possible to file bugs against projects directly,
it's still possible to file a bug from a project's main page.

    >>> user_browser.open("http://launchpad.test/gnome")
    >>> user_browser.getLink(url="+filebug").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/gnome/+filebug'

The ProjectGroup filebug page is like a Product's filebug page, except
that it also asks for a Product. Only Products that are using Bugs are
shown in the list of options.

    >>> user_browser.getControl("Project", index=0).options
    ['evolution']

After we selected a product and entered a summary, we're sent to the
product's +filebug page to search for duplicates.

    >>> user_browser.getControl("Project", index=0).value = ["evolution"]
    >>> user_browser.getControl("Summary", index=0).value = (
    ...     "Evolution crashes"
    ... )
    >>> user_browser.getControl("Continue").click()

    >>> user_browser.url
    'http://bugs...?field.title=Evolution+crashes&field.tags='
    >>> print(find_main_content(user_browser.contents).decode_contents())
    <...
    <input class="button" id="field.actions.search"
    name="field.actions.search" type="submit" value="Continue"/> ...

Entering a description and submitting the bug takes the user to the bug
page.

    >>> user_browser.getControl("Bug Description").value = "Crash."
    >>> user_browser.getControl("Submit Bug Report").click()
    >>> user_browser.url
    'http://bugs.launchpad.test/evolution/+bug/...'

    >>> user_browser.title
    'Bug #...Evolution crashes... : Bugs : Evolution'


Project groups with no products using Launchpad Bugs
----------------------------------------------------

When no projects within a project group used Launchpad to track bugs,
the page explains the case.

    >>> login("test@canonical.com")
    >>> project = factory.makeProject(
    ...     displayname="Test Group", name="test-group"
    ... )
    >>> logout()

    >>> user_browser.open("http://launchpad.test/test-group/+filebug")
    >>> user_browser.url
    'http://launchpad.test/test-group/+filebug'

    >>> for message in find_tags_by_class(
    ...     user_browser.contents, "informational message"
    ... ):
    ...     print(message.decode_contents())
    There are no projects registered for Test Group that either use Launchpad
    to track bugs or allow new bugs to be filed.
