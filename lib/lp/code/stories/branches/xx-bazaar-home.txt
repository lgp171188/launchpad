The Launchpad Code front page
=============================

First we manually set the Breezy version, so that this document will not need
updating when Launchpad upgrades Breezy.

    >>> import breezy
    >>> breezy_version = breezy.__version__
    >>> breezy.__version__ = '3.0.0'


Check that the Code home page works.

    >>> browser.open('http://code.launchpad.test/')
    >>> footer = find_tag_by_id(browser.contents, 'application-footer')

    >>> print(extract_text(footer))
    30 branches registered in
    6 projects
    1 imported branches
    Launchpad uses Breezy 3.0.0.


Restore the original Breezy version:

    >>> breezy.__version__ = breezy_version


The main code home page now has a subset of the project tag cloud,
with a link to the complete listing.

    >>> preview = find_tag_by_id(browser.contents, 'project-cloud-preview')
    >>> print(extract_text(preview))
    Most active projects in the last month
    see all projects…

    >>> print(preview.find_all('a')[-1]['href'])
    /projects


Search
------

Any user can see the project search form.

    >>> form = find_tag_by_id(browser.contents, 'search-projects-form')
    >>> print(form['action'])
    http://launchpad.test/projects

    >>> browser.getControl(name='text', index=0)
    <Control name='text' type='text'>

    >>> browser.getControl('Find a Project')
    <SubmitControl name='search' type='submit'>


Short Listings
--------------

Each of the three short branch listings on the code homepage now have
an anchor that looks like "more..." that takes the user to a branch
listing view that lists all matching branches ordered appropriately
for the listing.


Recently registered
...................

Since each anchor looks the same, the selection is done on url.

The recently registered branch listing is ordered with the most recently
registered branches first.

    >>> registered = find_tag_by_id(browser.contents, 'recently-registered')
    >>> print(registered.find_all('a')[-1]['href'])
    /+recently-registered-branches

    >>> browser.getLink(url='recently-registered-branches').click()
    >>> print(browser.title)
    Recently registered branches

Since the view contains branches across different projects, the project
is also shown in the listing.  And since the date that the branch was
registered is the ordering, the registered date is also shown.

    >>> table = find_tag_by_id(browser.contents, 'branchtable')
    >>> for row in table.thead.find_all('tr'):
    ...     print(extract_text(row))
    Name
    Status
    Registered
    Project
    Last Modified
    Last Commit
    >>> links = find_tag_by_id(browser.contents, 'branch-batch-links')
    >>> print(links.decode_contents())
    <...1...→...6...of...28...results...


Recently changed
................

Recently changed branches are ordered with the branches with the most
recent commits first.

    >>> browser.open('http://code.launchpad.test/')
    >>> changed = find_tag_by_id(browser.contents, 'recently-changed')
    >>> print(changed.find_all('a')[-1]['href'])
    /+recently-changed-branches

    >>> browser.getLink(url='recently-changed-branches').click()
    >>> print(browser.title)
    Recently changed branches

    >>> table = find_tag_by_id(browser.contents, 'branchtable')
    >>> for row in table.thead.find_all('tr'):
    ...     print(extract_text(row))
    Name
    Status
    Registered
    Project
    Last Modified
    Last Commit



Recently imported
.................

Recently imported branches are ordered by recent commits only in
imported branches.

    >>> browser.open('http://code.launchpad.test/')
    >>> imported = find_tag_by_id(browser.contents, 'recent-imports')
    >>> print(imported.find_all('a')[-1]['href'])
    /+recently-imported-branches

    >>> browser.getLink(url='recently-imported-branches').click()
    >>> print(browser.title)
    Recently imported branches

Since imported branches are all owned by vcs-imports, and the authors
of the branches are not normally set, the Author column is not shown for
imported branch listings.

    >>> table = find_tag_by_id(browser.contents, 'branchtable')
    >>> for row in table.thead.find_all('tr'):
    ...     print(extract_text(row))
    Name
    Status
    Registered
    Project
    Last Modified
    Last Commit
