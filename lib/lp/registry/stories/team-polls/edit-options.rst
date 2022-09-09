Editing poll options
====================

Changing the poll options detail is not possible if you are not one of the
team's administrators:

    >>> user_browser.open("http://launchpad.test/~ubuntu-team/+polls")
    >>> user_browser.getLink("A public poll that never closes").click()
    >>> user_browser.url
    'http://launchpad.test/~ubuntu-team/+poll/never-closes4'
    >>> print(extract_text(find_tag_by_id(user_browser.contents, "options")))
    Name        Title       Active
    OptionA     OptionA     Yes
    ...
    >>> user_browser.getLink("[Edit]")
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

And when the poll already started, administrators cannot change the options
either:

    # Need to craft the URL manually because there's no link to it -- the
    # option can't be changed, after all.
    >>> browser = setupBrowser(auth="Basic jeff.waugh@ubuntulinux.com:test")
    >>> browser.open(
    ...     "http://launchpad.test/~ubuntu-team/+poll/never-closes4/"
    ...     "+option/20"
    ... )
    >>> print_feedback_messages(browser.contents)
    You can’t edit any options because the poll is already open.

Since Jeff is an administrator of ubuntu-team, he should be able to edit the
options of a poll that hasn't been opened yet.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.person import IPersonSet

    >>> login("test@canonical.com")
    >>> ubuntu_team = getUtility(IPersonSet).getByName("ubuntu-team")
    >>> not_yet_opened = factory.makePoll(
    ...     ubuntu_team,
    ...     "not-yet-opened",
    ...     "A public poll that has not opened yet",
    ...     "Whatever proposition.",
    ... )
    >>> _ = not_yet_opened.newOption("OptionX", "OptionX")
    >>> logout()

    >>> browser.open("http://launchpad.test/~ubuntu-team/+polls")
    >>> browser.getLink("A public poll that has not opened yet").click()
    >>> browser.url
    'http://launchpad.test/~ubuntu-team/+poll/not-yet-opened'

    >>> browser.getLink("[Edit]").click()
    >>> browser.url
    'http://launchpad.test/~ubuntu-team/+poll/not-yet-opened/+option/...'

    >>> browser.getControl("Name").value
    'OptionX'
    >>> browser.getControl("Title").value
    'OptionX'
    >>> browser.getControl("Name").value = "option-z"
    >>> browser.getControl("Title").value = "Option Z"
    >>> browser.getControl("Save").click()

    >>> browser.url
    'http://launchpad.test/~ubuntu-team/+poll/not-yet-opened'
    >>> print(
    ...     find_portlet(browser.contents, "Voting options").decode_contents()
    ... )
    <BLANKLINE>
    <h2>Voting options</h2>
    ...
    ...option-z...
    ...

