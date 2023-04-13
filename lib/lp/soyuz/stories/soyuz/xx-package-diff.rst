Package Diff
------------

'Available diffs' page section is only presented when there is, at
least, one `PackageDiff` recorded in the database for a context
SourcePackageRelease.

It's exposed in the following pages:

 * Ubuntu sources (`DistributionSourcePackage`);
 * Ubuntu source release (`DistributionSourcePackageRelease`);
 * PPA sources (PPA Overview).

The section is rendered based on the `SourcePackageRelease` content
class, so, theoretically is can be displayed in any page that has
access to one or more objects of this nature.

When there is no diff available the 'Available diffs' section is
omitted.

The pages mentioned are public, therefore the package diffs are also
public.

See further information about `PackageDiff` documentation in
doc/package-diff.rst.


Testable diff setup
-------------------

We will create a set of `PackageDiff` so we can precisely test how
they show up in the UI.

    >>> from zope.component import getUtility
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.person import IPersonSet

    >>> login("foo.bar@canonical.com")

    >>> ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
    >>> hoary = ubuntu.getSeries("hoary")

    >>> from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
    >>> test_publisher = SoyuzTestPublisher()
    >>> name16 = getUtility(IPersonSet).getByName("name16")
    >>> test_publisher.person = name16

Create a series of 'biscuit' sources in ubuntu primary archive.

    >>> biscuit_one_pub = test_publisher.getPubSource(
    ...     sourcename="biscuit", version="1.0-1", distroseries=hoary
    ... )

    >>> biscuit_two_pub = test_publisher.getPubSource(
    ...     sourcename="biscuit", version="1.0-2", distroseries=hoary
    ... )

    >>> biscuit_three_pub = test_publisher.getPubSource(
    ...     sourcename="biscuit", version="1.0-3", distroseries=hoary
    ... )

Activate Foo Bar's PPA and upload another 'biscuit' source version.

    >>> from lp.soyuz.enums import ArchivePurpose
    >>> from lp.soyuz.interfaces.archive import IArchiveSet
    >>> foobar = getUtility(IPersonSet).getByName("name16")
    >>> ppa = getUtility(IArchiveSet).new(
    ...     owner=foobar, distribution=ubuntu, purpose=ArchivePurpose.PPA
    ... )

    >>> biscuit_four_pub = test_publisher.getPubSource(
    ...     sourcename="biscuit",
    ...     version="1.0-4",
    ...     distroseries=hoary,
    ...     archive=foobar.archive,
    ... )

Creating corresponding `PackageDiff`s for all sources uploaded, except
the first one (new upload).

    >>> diff_one = biscuit_one_pub.sourcepackagerelease.requestDiffTo(
    ...     requester=name16,
    ...     to_sourcepackagerelease=biscuit_two_pub.sourcepackagerelease,
    ... )
    >>> diff_two = biscuit_two_pub.sourcepackagerelease.requestDiffTo(
    ...     requester=name16,
    ...     to_sourcepackagerelease=biscuit_three_pub.sourcepackagerelease,
    ... )
    >>> diff_three = biscuit_three_pub.sourcepackagerelease.requestDiffTo(
    ...     requester=name16,
    ...     to_sourcepackagerelease=biscuit_four_pub.sourcepackagerelease,
    ... )

Perform some diffs in advance, the first diff in ubuntu and the diff
in PPA will be performed, the second diff in ubuntu will be performed
later.

    >>> import io
    >>> from zope.security.proxy import removeSecurityProxy
    >>> from lp.services.database.constants import UTC_NOW
    >>> from lp.services.librarian.interfaces.client import ILibrarianClient
    >>> from lp.soyuz.enums import PackageDiffStatus

    >>> def perform_fake_diff(diff, filename):
    ...     naked_diff = removeSecurityProxy(diff)
    ...     naked_diff.date_fulfilled = UTC_NOW
    ...     naked_diff.status = PackageDiffStatus.COMPLETED
    ...     naked_diff.diff_content = getUtility(ILibrarianClient).addFile(
    ...         filename, 3, io.BytesIO(b"Foo"), "application/gzipped-patch"
    ...     )
    ...

    >>> perform_fake_diff(diff_one, "biscuit_1.0-1_1.0-2.diff.gz")

    >>> perform_fake_diff(diff_three, "biscuit_1.0-3_1.0-4.diff.gz")

Commit again, so the diffs will be available, and log out, we
are done here.

    >>> import transaction
    >>> transaction.commit()
    >>> logout()


Ubuntu sources
--------------

All diffs are visible in the 'biscuit source in ubuntu' change log page, right
below the text for each uploaded version.

    >>> anon_browser.open(
    ...     "http://launchpad.test/ubuntu/+source/biscuit/+changelog"
    ... )
    >>> changes = find_tags_by_class(anon_browser.contents, "boardComment")
    >>> for change in changes:
    ...     print(30 * "=")
    ...     print(extract_text(change))
    ...
    ==============================
    1.0-3
    Pending in hoary-release
    ...
    Available diffs
    diff from 1.0-2 to 1.0-3 (pending)
    ==============================
    1.0-2
    Pending in hoary-release
    ...
    Available diffs
    diff from 1.0-1 to 1.0-2 (3 bytes)
    ==============================
    1.0-1
    Pending in hoary-release
    ...
