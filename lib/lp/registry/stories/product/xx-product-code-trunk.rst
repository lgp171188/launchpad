Product's Development Focus
===========================

Development focus for a product is often used to refer to two different
things.  Firstly there is the development focus series, and secondly there is
the development focus branch.  Each product series can be linked to a specific
Bazaar branch.

The development focus information is shown as part of the project information
section on the product overview page.

    >>> from lp.testing import login, logout
    >>> login("admin@canonical.com")
    >>> eric = factory.makePerson(name="eric", email="eric@example.com")
    >>> fooix = factory.makeProduct(name="fooix", owner=eric)
    >>> branch = factory.makeBranch(owner=eric, product=fooix, name="trunk")

Make revisions for the branch so it has a codebrowse link.

    >>> factory.makeRevisionsForBranch(branch)
    >>> logout()

    >>> owner_browser = setupBrowser("Basic eric@example.com:test")
    >>> def print_development_focus(browser):
    ...     """Print out the development focus part of the project info."""
    ...     dev_focus = find_tag_by_id(browser.contents, "development-focus")
    ...     print(extract_text(dev_focus))
    ...     print("Links:")
    ...     for a in dev_focus.find_all("a"):
    ...         for content in a.contents:
    ...             print(content)
    ...         title = a.get("title", "")
    ...         print("%s (%s)" % (title, a["href"]))
    ...
    >>> def print_code_trunk(browser):
    ...     """Print out code trunk part of the project info."""
    ...     project_info = find_tag_by_id(browser.contents, "code-info")
    ...     code_trunk = project_info.find(attrs={"id": "code-trunk"})
    ...     try:
    ...         print(extract_text(code_trunk))
    ...     except TypeError:
    ...         return
    ...     print("Links:")
    ...     for a in code_trunk.find_all("a"):
    ...         for content in a.contents:
    ...             print(content)
    ...         title = a.get("title", "")
    ...         print("%s (%s)" % (title, a["href"]))
    ...
    >>> def print_involvement_portlet(browser):
    ...     involvement = find_tag_by_id(browser.contents, "involvement")
    ...     for a in involvement.find_all("a"):
    ...         for content in a.contents:
    ...             print(content)
    ...         print(a["href"])
    ...


Projects without development focus branches
-------------------------------------------

If the project has not specified a development focus branch then the
development focus section just contains a link to the development focus
series.

    >>> anon_browser.open("http://launchpad.test/fooix")
    >>> print_development_focus(anon_browser)
    trunk series is the current focus of development.
    Links:
      trunk series (/fooix/trunk)
    >>> print_code_trunk(anon_browser)
    >>> print_involvement_portlet(anon_browser)


Setting the development focus branch
------------------------------------

If the user has rights to change the development focus or to specify the
development focus branch, then these links are shown in the involvement
portlet.

    >>> owner_browser.open("http://launchpad.test/fooix")
    >>> print_development_focus(owner_browser)
    trunk series is the current focus of development.  Change details
    Links:
     trunk series (/fooix/trunk)
     Change details (http://launchpad.test/fooix/+edit)
    >>> print_code_trunk(anon_browser)
    >>> print_involvement_portlet(owner_browser)
    Code
    http://launchpad.test/fooix/+configure-code
    Bugs
    http://launchpad.test/fooix/+configure-bugtracker
    Translations
    http://launchpad.test/fooix/+configure-translations
    Answers
    http://launchpad.test/fooix/+configure-answers

The owner can specify the development focus branch from the overview page.

    >>> owner_browser.getLink(url="+configure-code").click()
    >>> owner_browser.getControl("Bazaar", index=0).click()
    >>> owner_browser.getControl(name="field.branch_location").value = (
    ...     "~eric/fooix/trunk"
    ... )
    >>> owner_browser.getControl("Update").click()
    >>> print_feedback_messages(owner_browser.contents)
    Project settings updated.

The owner is taken back to the project page.

    >>> print_development_focus(owner_browser)
    trunk series is the current focus of development.  Change details
    Links:
     trunk series (/fooix/trunk)
     Change details (http://launchpad.test/fooix/+edit)
    >>> print_code_trunk(owner_browser)
    lp://dev/fooix  Configure Code
    Links:
      lp://dev/fooix (http://code.launchpad.test/~eric/fooix/trunk)
      Configure Code
        Configure code for this project
        (http://launchpad.test/fooix/+configure-code)


Projects with development focus branches
----------------------------------------

If the project has a specified development focus branch, this is shown in the
development focus section of the project information.

There is a link both to the branch, and but no source code browser for that
branch.

    >>> anon_browser.open("http://launchpad.test/fooix")
    >>> print_development_focus(anon_browser)
    trunk series is the current focus of development.
    Links:
     trunk series (/fooix/trunk)
    >>> print_code_trunk(anon_browser)
    lp://dev/fooix
    Links:
      lp://dev/fooix (http://code.launchpad.test/~eric/fooix/trunk)

    >>> owner_browser.open("http://launchpad.test/fooix")
    >>> print_development_focus(owner_browser)
    trunk series is the current focus of development.  Change details
    Links:
     trunk series (/fooix/trunk)
     Change details (http://launchpad.test/fooix/+edit)
    >>> print_code_trunk(owner_browser)
    lp://dev/fooix   Configure Code
    Links:
      lp://dev/fooix (http://code.launchpad.test/~eric/fooix/trunk)
      Configure Code
        Configure code for this project
        (http://launchpad.test/fooix/+configure-code)


Private development focus branches
----------------------------------

If the development focus branch is private, then for unauthorized viewers, it
appears as if there is no series branch set.

    >>> login("admin@canonical.com")
    >>> from lp.app.enums import InformationType
    >>> branch.transitionToInformationType(
    ...     InformationType.USERDATA, branch.owner, verify_policy=False
    ... )
    >>> logout()

    >>> anon_browser.open("http://launchpad.test/fooix")
    >>> print_development_focus(anon_browser)
    trunk series is the current focus of development.
    Links:
      trunk series (/fooix/trunk)
    >>> print_code_trunk(anon_browser)

    >>> owner_browser.open("http://launchpad.test/fooix")
    >>> print_development_focus(owner_browser)
    trunk series is the current focus of development.  Change details
    Links:
      trunk series (/fooix/trunk)
      Change details
        (http://launchpad.test/fooix/+edit)
    >>> print_code_trunk(owner_browser)
    lp://dev/fooix   Configure Code
    Links:
      lp://dev/fooix (http://code.launchpad.test/~eric/fooix/trunk)
      Configure Code
        Configure code for this project
        (http://launchpad.test/fooix/+configure-code)
