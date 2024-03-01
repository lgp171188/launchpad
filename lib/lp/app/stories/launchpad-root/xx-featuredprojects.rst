
Featured Projects
=================

We maintain a list of featured projects, which are displayed on the home
page and managed via a special admin-only page.

    >>> MANAGE_LINK = "Manage featured project list"


The home page listing
---------------------

Anonymous users will see the list of featured projects with links to the
projects' pages in Launchpad.

    >>> anon_browser.open("http://launchpad.test/")
    >>> featured = find_tag_by_id(anon_browser.contents, "homepage-featured")
    >>> print(extract_text(featured.h2))
    Featured projects

    >>> featured_list = featured.find("", "featured-projects-list")
    >>> for link in featured_list.find_all("a"):
    ...     print(extract_text(link))
    ...
    Gnome Applets
    Bazaar
    Mozilla Firefox
    Gentoo
    GNOME
    GNOME Terminal
    The Mozilla Project
    Mozilla Thunderbird
    Ubuntu

Adding a featured project
-------------------------

Anonymous users cannot see the link to administer featured projects:

    >>> anon_browser.getLink(MANAGE_LINK)
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

A user without privileges cannot see the administration link, either:

    >>> user_browser.open("http://launchpad.test/")
    >>> user_browser.getLink(MANAGE_LINK)
    Traceback (most recent call last):
    ...
    zope.testbrowser.browser.LinkNotFoundError

But Foo Bar, who is an administrator, can see the management link:

    >>> admin_browser.open("http://launchpad.test/")
    >>> admin_browser.getLink(MANAGE_LINK).click()
    >>> admin_browser.url
    'http://launchpad.test/+featuredprojects'

No Privilege persons is denied access to this page:

    >>> user_browser.open("http://launchpad.test/+featuredprojects")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

Administrators can add a project. Here Foo Bar adds apache as a featured
project:

    >>> admin_browser.getControl("Add project").value = "apache"
    >>> admin_browser.getControl("Update").click()
    >>> admin_browser.url
    'http://launchpad.test/'
    >>> featured = find_tag_by_id(admin_browser.contents, "homepage-featured")
    >>> "Apache" in extract_text(featured)
    True

Just to be certain, we will iterate the list as we did before and see
that Apache has been added. Because the list has changed, a different project
is now at index '4' and is therefore displayed as the top project:

    >>> anon_browser.open("http://launchpad.test/")
    >>> featured = find_tag_by_id(anon_browser.contents, "homepage-featured")
    >>> featured_list = featured.find("", "featured-projects-list")
    >>> for link in featured_list.find_all("a"):
    ...     print(extract_text(link))
    ...
    Apache
    Gnome Applets
    Bazaar
    Mozilla Firefox
    Gentoo
    GNOME
    GNOME Terminal
    The Mozilla Project
    Mozilla Thunderbird
    Ubuntu

Removing a project
------------------

    >>> admin_browser.getLink(MANAGE_LINK).click()
    >>> admin_browser.getControl("Apache").click()
    >>> admin_browser.getControl("Update").click()
    >>> admin_browser.url
    'http://launchpad.test/'
    >>> featured = find_tag_by_id(admin_browser.contents, "homepage-featured")
    >>> "Apache" in extract_text(featured)
    False

Just to be certain, we will iterate the list as we did before and see
that Apache has been removed:

    >>> anon_browser.open("http://launchpad.test/")
    >>> featured = find_tag_by_id(anon_browser.contents, "homepage-featured")
    >>> for link in featured.find_all("a"):
    ...     print(extract_text(link))
    ...
    Gnome Applets
    Bazaar
    Mozilla Firefox
    Gentoo
    GNOME
    GNOME Terminal
    The Mozilla Project
    Mozilla Thunderbird
    Ubuntu
    Browse all ... projects


