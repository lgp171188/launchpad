=======================
Publishing History Page
=======================

The Publishing History page hangs off a distribution source page and
shows the complete history of a package in all series.

    >>> from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
    >>> from lp.soyuz.enums import PackagePublishingStatus
    >>> stp = SoyuzTestPublisher()
    >>> login("foo.bar@canonical.com")
    >>> stp.prepareBreezyAutotest()
    >>> source_pub = stp.getPubSource(
    ...     "test-history", status=PackagePublishingStatus.PUBLISHED
    ... )
    >>> logout()

    >>> anon_browser.open(
    ...     "http://launchpad.test/ubuntutest/+source/test-history/"
    ...     "+publishinghistory"
    ... )

    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))
    Date    Status    Target     Pocket   Component Section Version
    ... UTC Published Breezy ... release  main      base    666
    Created ... ago by Foo Bar
    Published ... ago
    >>> print(table.find_all("tr")[2].td["colspan"])
    8

Copy the package to a new distribution named "foo-distro". The publishing
history page of Foo-distro should show that the package was copied, but no
intermediate archive information.

    >>> login("foo.bar@canonical.com")
    >>> from lp.soyuz.model.archive import ArchivePurpose
    >>> copy_creator = stp.factory.makePerson(name="person123")
    >>> new_distro = stp.factory.makeDistribution(name="foo-distro")
    >>> new_distroseries = stp.factory.makeDistroSeries(
    ...     name="foo-series", distribution=new_distro
    ... )
    >>> new_archive = stp.factory.makeArchive(
    ...     distribution=new_distro, purpose=ArchivePurpose.PRIMARY
    ... )
    >>> new_pub1 = source_pub.copyTo(
    ...     new_distroseries,
    ...     source_pub.pocket,
    ...     new_archive,
    ...     creator=copy_creator,
    ... )
    >>> logout()

    >>> anon_browser.open(
    ...     "http://launchpad.test/foo-distro/+source/test-history/"
    ...     "+publishinghistory"
    ... )

    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))  # noqa
    Date    Status    Target          Pocket   Component Section Version
    ... UTC Pending   Foo-series      release  main      base    666
    Copied from ubuntutest breezy-autotest in Primary Archive for Ubuntu Test by Person123


Copying from "Foo-distro" to a new distribution "Another-distro". It should
show the intermediate archive Foo-distro on Another-distro's history page,
since we copied the package from there. It should also show that the
original distribution was Ubuntutest breezy-autotest.

    >>> login("foo.bar@canonical.com")
    >>> from lp.soyuz.model.archive import ArchivePurpose
    >>> new_distro = stp.factory.makeDistribution(name="another-distro")
    >>> new_distroseries = stp.factory.makeDistroSeries(
    ...     name="another-series", distribution=new_distro
    ... )
    >>> new_archive = stp.factory.makeArchive(
    ...     distribution=new_distro, purpose=ArchivePurpose.PRIMARY
    ... )
    >>> new_pub2 = new_pub1.copyTo(
    ...     new_distroseries,
    ...     source_pub.pocket,
    ...     new_archive,
    ...     creator=copy_creator,
    ... )
    >>> logout()

    >>> anon_browser.open(
    ...     "http://launchpad.test/another-distro/+source/test-history/"
    ...     "+publishinghistory"
    ... )
    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))  # noqa
    Date    Status    Target          Pocket   Component Section Version
    ... UTC Pending   Another-series  release  main      base    666
    Copied from Primary Archive for Foo-distro by Person123
    Originally uploaded to ubuntutest breezy-autotest in Primary Archive for Ubuntu Test

And in this new distro, a change-override on a copied archive should show both
messages.

    >>> from lp.registry.interfaces.person import IPersonSet
    >>> from zope.component import getUtility
    >>> from zope.security.proxy import removeSecurityProxy

    >>> login("foo.bar@canonical.com")
    >>> person = getUtility(IPersonSet).getByEmail("foo.bar@canonical.com")
    >>> new_pub2_changed = removeSecurityProxy(new_pub2).changeOverride(
    ...     new_component="universe", creator=person
    ... )
    >>> logout()
    >>> anon_browser.open(
    ...     "http://launchpad.test/another-distro/+source/test-history/"
    ...     "+publishinghistory"
    ... )
    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))  # noqa
    Date    Status    Target          Pocket   Component Section Version
    ... UTC Pending   Another-series  release  universe  base    666
    Copied from ubuntutest breezy-autotest in Primary Archive for Ubuntu Test by Foo Bar
    ... UTC Pending   Another-series  release  main      base    666
    Copied from Primary Archive for Foo-distro by Person123
    Originally uploaded to ubuntutest breezy-autotest in Primary Archive for Ubuntu Test

Going back to the original distribution, a change-override request should
show who made the request.

    >>> login("foo.bar@canonical.com")
    >>> new_pub = source_pub.changeOverride(
    ...     new_component="universe", creator=person
    ... )
    >>> logout()

    >>> anon_browser.open(
    ...     "http://launchpad.test/ubuntutest/+source/test-history/"
    ...     "+publishinghistory"
    ... )
    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))
    Date    Status    Target     Pocket   Component Section Version
    ... UTC Pending   Breezy ... release  universe  base    666
    Created ... ago by Foo Bar
    ... UTC Published Breezy ... release  main      base    666
    Created ... ago by Foo Bar
    Published ... ago

A publishing record will be shown as deleted in the publishing history after a
request for deletion by a user.

    >>> login("foo.bar@canonical.com")
    >>> unused = source_pub.requestDeletion(
    ...     stp.factory.makePerson(), "fix bug 1"
    ... )
    >>> logout()

    >>> anon_browser.open(
    ...     "http://launchpad.test/ubuntutest/+source/test-history/"
    ...     "+publishinghistory"
    ... )

    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))
    Date    Status    Target     Pocket   Component Section Version
    ... UTC Pending   Breezy ... release  universe  base    666
    Created ... ago by Foo Bar
            Deleted   Breezy ... release  main      base    666
    Deleted ... ago by ... fix bug 1
    Published ... ago

Links to bug reports are added for bugs mentioned in the removal comment.

    >>> print(anon_browser.getLink("bug 1").url)
    http://launchpad.test/bugs/1

Checking how a copied binary publishing history looks like on the
distro-arch-series-binarypackage page.

    >>> login("foo.bar@canonical.com")
    >>> from lp.soyuz.model.distroarchseriesbinarypackage import (
    ...     DistroArchSeriesBinaryPackage,
    ... )
    >>> binary_pub = removeSecurityProxy(stp.getPubBinaries()[0])
    >>> new_archive = stp.factory.makeArchive(
    ...     distribution=(
    ...         binary_pub.distroarchseries.distroseries.distribution
    ...     )
    ... )
    >>> binary_copy = removeSecurityProxy(
    ...     binary_pub.copyTo(
    ...         binary_pub.distroarchseries.distroseries,
    ...         binary_pub.pocket,
    ...         new_archive,
    ...     )[0]
    ... )
    >>> page_obj = DistroArchSeriesBinaryPackage(
    ...     binary_copy.distroarchseries, binary_copy.binarypackagename
    ... )
    >>> url = canonical_url(page_obj)
    >>> logout()

    >>> anon_browser.open(url)
    >>> table = find_tag_by_id(anon_browser.contents, "publishing-summary")
    >>> print(extract_text(table))  # noqa
        Date    Status    Target     Pocket   Component Section Priority Phased updates Version
    ... UTC Pending   ubuntutest Breezy ... release  main  base Standard 666
    Copied from ubuntutest breezy-autotest-release i386 in Primary Archive for Ubuntu Test
