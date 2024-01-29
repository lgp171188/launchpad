Distribution mirrors
====================

There are several pages which list the mirrors of a given distribution based
on their status and content.

    # First we'll define a helper function to extract some data from the
    # pages we're going to use.
    >>> def print_mirrors_by_countries(contents):
    ...     mirrors_table = find_tag_by_id(contents, "mirrors_list")
    ...     header = mirrors_table.find("tr")
    ...     country = extract_text(header.find("th"))
    ...     mirrors = []
    ...     for tr in header.find_next_siblings("tr"):
    ...         if "head" in str(tr.attrs):
    ...             print("%s: %s" % (country, pretty(mirrors)))
    ...             country = extract_text(tr.find("th"))
    ...             if country == "Total":
    ...                 break
    ...             mirrors = []
    ...         elif "section-break" in str(tr.attrs):
    ...             # This is an empty row to visually separate the mirrors
    ...             # from different countries, so we'll just skip it.
    ...             pass
    ...         else:
    ...             tds = tuple(
    ...                 [extract_text(td) for td in tr.find_all("td")]
    ...             )
    ...             mirrors.append(tds)
    ...

Official mirrors
----------------

These are the mirrors that show up in public listings. They're highly
reliable and we strongly encourage their use.

We have one page which lists all archive mirrors and another one which lists
the release (cdimage) ones.

The archive mirrors display the "freshness", how far behind they are.

    >>> browser.open("http://launchpad.test/ubuntu")
    >>> browser.getLink("Archive mirrors").click()
    >>> print(browser.title)
    Mirrors :...
    >>> print_mirrors_by_countries(browser.contents)
    Antarctica:
      [('Archive-mirror2', 'http', '128 Kbps', 'Six hours behind'),
       ('Archive-redirect-mirror', 'http', '128 Kbps',
        'Last update unknown')]
    France:
      [('Archive-404-mirror', 'http', '512 Kbps', 'Last update unknown'),
       ('Archive-mirror', 'http', '128 Kbps', 'Last update unknown')]
    United Kingdom: [('Canonical-archive', 'http', '100 Mbps',
      'Last update unknown')]

    >>> find_tags_by_class(
    ...     browser.contents, "distromirrorstatusSIXHOURSBEHIND"
    ... )
    [<span class="distromirrorstatusSIXHOURSBEHIND">Six hours behind</span>]
    >>> find_tags_by_class(browser.contents, "distromirrorstatusUNKNOWN")[0]
    <span class="distromirrorstatusUNKNOWN">Last update unknown</span>

Freshness doesn't make sense for CD mirrors so it is not shown for them.

    >>> browser.open("http://launchpad.test/ubuntu")
    >>> browser.getLink("CD mirrors").click()
    >>> browser.url
    'http://launchpad.test/ubuntu/+cdmirrors'
    >>> print_mirrors_by_countries(browser.contents)
    France:
      [('Releases-mirror', 'http', '2 Mbps'),
       ('Unreachable-mirror', 'http', '512 Kbps')]
    Germany: [('Releases-mirror2', 'http', '2 Mbps')]
    United Kingdom: [('Canonical-releases', 'http', '100 Mbps')]


Disabled mirrors
................

These are official mirrors for which the last check wasn't successful (e.g.
they were out of date, missing some content, etc). This list can only be
seen by distro owners, mirror admins of the distro or launchpad admins.

    >>> user_browser.open("http://launchpad.test/ubuntu/+disabledmirrors")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth="Basic karl@canonical.com:test")
    >>> browser.open("http://launchpad.test/ubuntu/+disabledmirrors")
    >>> browser.url
    'http://launchpad.test/ubuntu/+disabledmirrors'

    >>> print(
    ...     find_tag_by_id(browser.contents, "maincontent").decode_contents()
    ... )
    <BLANKLINE>
    ...We don't know of any Disabled Mirrors for this distribution...


Unofficial mirrors
------------------

The unofficial mirrors are listed in a separate page, which is not public.
It's only visible to distro owners, mirror admins of the distro or
launchpad admins.

    >>> user_browser.open("http://launchpad.test/ubuntu/+unofficialmirrors")
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth="Basic karl@canonical.com:test")
    >>> browser.open("http://launchpad.test/ubuntu/+unofficialmirrors")
    >>> browser.url
    'http://launchpad.test/ubuntu/+unofficialmirrors'

    >>> print_mirrors_by_countries(browser.contents)
    France: [('Invalid-mirror', 'http', '2 Mbps', 'Last update unknown')]


Pending-review mirrors
----------------------

These are the mirrors that were created but none of the mirror admins have
looked at yet.  Since all pending mirrors are grouped on one page the
type of mirror is shown.  Also the freshness is not visible since
pending mirrors have never been probed.

    >>> user_browser.open(
    ...     "http://launchpad.test/ubuntu/+pendingreviewmirrors"
    ... )
    Traceback (most recent call last):
    ...
    zope.security.interfaces.Unauthorized: ...

    >>> browser = setupBrowser(auth="Basic karl@canonical.com:test")

Register an unreviewed archive mirror.

    >>> browser.open("http://launchpad.test/ubuntu/+newmirror")
    >>> browser.getControl(name="field.display_name").value = (
    ...     "Kabul LUG mirror"
    ... )
    >>> browser.getControl(name="field.ftp_base_url").value = (
    ...     "ftp://kabullug.org/ubuntu"
    ... )
    >>> browser.getControl(name="field.country").value = ["1"]  # Afghanistan
    >>> browser.getControl(name="field.speed").value = ["S10G"]
    >>> browser.getControl(name="field.content").value = ["ARCHIVE"]
    >>> browser.getControl("Register Mirror").click()

    >>> browser.open("http://launchpad.test/ubuntu/+pendingreviewmirrors")
    >>> print_mirrors_by_countries(browser.contents)
    Afghanistan:
     [('Kabul LUG mirror', 'ftp', '10 Gbps',
       'Archive')]
    United Kingdom:
      [('Random-releases-mirror', 'http', '100 Mbps',
        'CD Image')]
