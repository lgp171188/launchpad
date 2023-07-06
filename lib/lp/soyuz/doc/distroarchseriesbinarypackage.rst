=================================
Distro Arch Series Binary Package
=================================

    >>> from lp.soyuz.model.binarypackagename import BinaryPackageName
    >>> from lp.soyuz.model.distroarchseries import DistroArchSeries
    >>> from lp.soyuz.model.distroarchseriesbinarypackage import (
    ...     DistroArchSeriesBinaryPackage,
    ... )
    >>> hoary_i386 = DistroArchSeries.get(6)
    >>> pmount_name = BinaryPackageName.selectOneBy(name="pmount")
    >>> firefox_name = BinaryPackageName.selectOneBy(name="mozilla-firefox")
    >>> pmount_hoary_i386 = DistroArchSeriesBinaryPackage(
    ...     hoary_i386, pmount_name
    ... )
    >>> firefox_hoary_i386 = DistroArchSeriesBinaryPackage(
    ...     hoary_i386, firefox_name
    ... )

`DistroArchSeriesBinaryPackage`s have a title property:

    >>> print(pmount_hoary_i386.title)
    pmount binary package in Ubuntu Hoary i386

First, we create a new version of pmount, and a version of mozilla-
firefox that coincides with pmount's. We're hitch-hiking on two existing
builds that are in sampledata!

    >>> from lp.soyuz.model.publishing import BinaryPackagePublishingHistory
    >>> from lp.services.database.constants import UTC_NOW
    >>> from lp.services.database.interfaces import IStore
    >>> from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
    >>> from lp.soyuz.model.component import Component
    >>> from lp.soyuz.model.section import Section

    >>> main_component = IStore(Component).find(Component, name="main").one()
    >>> misc_section = IStore(Section).find(Section, name="base").one()
    >>> from lp.soyuz.enums import BinaryPackageFormat
    >>> binpackageformat = BinaryPackageFormat.DEB
    >>> from lp.soyuz.enums import (
    ...     PackagePublishingPriority,
    ...     PackagePublishingStatus,
    ... )
    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.pocket import PackagePublishingPocket
    >>> priority = PackagePublishingPriority.STANDARD

XXX: noodles 2008-11-05 bug=294585: The dependency on a database id
needs to be removed.

    >>> bpr = BinaryPackageBuild.get(8).createBinaryPackageRelease(
    ...     binarypackagename=firefox_name.id,
    ...     version="120.6-0",
    ...     summary="Firefox loves lollies",
    ...     description="Lolly-pop loving application",
    ...     binpackageformat=binpackageformat,
    ...     component=main_component.id,
    ...     section=misc_section.id,
    ...     priority=priority,
    ...     shlibdeps=None,
    ...     depends=None,
    ...     recommends=None,
    ...     suggests=None,
    ...     conflicts=None,
    ...     replaces=None,
    ...     provides=None,
    ...     pre_depends=None,
    ...     enhances=None,
    ...     breaks=None,
    ...     built_using=None,
    ...     essential=False,
    ...     installedsize=0,
    ...     architecturespecific=False,
    ...     debug_package=None,
    ... )

    >>> pe = BinaryPackagePublishingHistory(
    ...     binarypackagerelease=bpr.id,
    ...     binarypackagename=bpr.binarypackagename,
    ...     binarypackageformat=bpr.binpackageformat,
    ...     component=main_component.id,
    ...     section=misc_section.id,
    ...     priority=priority,
    ...     distroarchseries=hoary_i386.id,
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     datecreated=UTC_NOW,
    ...     datepublished=UTC_NOW,
    ...     pocket=PackagePublishingPocket.RELEASE,
    ...     archive=hoary_i386.main_archive,
    ...     sourcepackagename=bpr.build.source_package_name,
    ... )

XXX: noodles 2008-11-06 bug=294585: The dependency on a database id
needs to be removed.

    >>> bpr = BinaryPackageBuild.get(9).createBinaryPackageRelease(
    ...     binarypackagename=pmount_name.id,
    ...     version="cr98.34",
    ...     summary="Pmount bakes cakes",
    ...     description="Phat cake-baker application",
    ...     binpackageformat=binpackageformat,
    ...     component=main_component.id,
    ...     section=misc_section.id,
    ...     priority=priority,
    ...     shlibdeps=None,
    ...     depends=None,
    ...     recommends=None,
    ...     suggests=None,
    ...     conflicts=None,
    ...     replaces=None,
    ...     provides=None,
    ...     pre_depends=None,
    ...     enhances=None,
    ...     breaks=None,
    ...     built_using=None,
    ...     essential=False,
    ...     installedsize=0,
    ...     architecturespecific=False,
    ...     debug_package=None,
    ... )

    >>> pe = BinaryPackagePublishingHistory(
    ...     binarypackagerelease=bpr.id,
    ...     binarypackagename=bpr.binarypackagename,
    ...     binarypackageformat=bpr.binpackageformat,
    ...     component=main_component.id,
    ...     section=misc_section.id,
    ...     priority=priority,
    ...     distroarchseries=hoary_i386.id,
    ...     status=PackagePublishingStatus.PUBLISHED,
    ...     datecreated=UTC_NOW,
    ...     datepublished=UTC_NOW,
    ...     pocket=PackagePublishingPocket.RELEASE,
    ...     archive=hoary_i386.main_archive,
    ...     sourcepackagename=bpr.build.source_package_name,
    ... )

Then, we ensure that grabbing the current release of pmount and the old
release both are sane.

    >>> current_release = pmount_hoary_i386.currentrelease
    >>> print(current_release.version)
    cr98.34

    >>> print(current_release.name)
    pmount

    >>> old_release = pmount_hoary_i386["0.1-1"]
    >>> print(old_release.version)
    0.1-1

    >>> print(old_release.name)
    pmount

The source package that was used to build the current release is
available in the binary package's distro_source_package attribute.

    >>> distro_source_package = firefox_hoary_i386.distro_source_package
    >>> print(distro_source_package.displayname)
    mozilla-firefox in Ubuntu

If a given binary package doesn't have a current release, then the
distro_source_package attribute should return None.

    >>> from zope.security.proxy import removeSecurityProxy
    >>> deb_wdy_i386 = removeSecurityProxy(
    ...     getUtility(IDistributionSet)["debian"]["woody"]["i386"]
    ... )
    >>> pmount_woody_i386 = DistroArchSeriesBinaryPackage(
    ...     deb_wdy_i386, pmount_name
    ... )
    >>> print(pmount_woody_i386.distro_source_package)
    None

Check the publishing record of packages returned by 'currentrelease' and
'__getitem__', which are different and in 'Published' state.

    >>> pe.id == current_release.current_publishing_record.id
    True

    >>> print(pe.status.title)
    Published
    >>> print(pe.distroarchseries.architecturetag)
    i386

    >>> old_pubrec = old_release.current_publishing_record
    >>> old_pubrec.id
    12
    >>> print(old_pubrec.status.title)
    Published
    >>> print(old_pubrec.distroarchseries.architecturetag)
    i386

Note that it is only really possible to have two packages in the
"Published" status if domination hasn't run yet.


Package caches and DARBP summaries
----------------------------------

Bug 208233 teaches us that DistroArchSeriesBinaryPackage summaries use
package caches to generate their output, and unfortunately that means
they can interact poorly with PPA-published packages which live in the
same cache table. Here's a test that ensures that the code that fetches
summaries works.

XXX: this is really too complicated, and the code in
DistroArchSeriesBinaryPackage.summary should be simplified.

    -- kiko, 2008-03-28

    >>> from lp.registry.interfaces.distribution import IDistributionSet
    >>> from lp.registry.interfaces.person import IPersonSet
    >>> ubuntu = getUtility(IDistributionSet)["ubuntu"]
    >>> cprov = getUtility(IPersonSet).getByName("cprov")
    >>> warty = ubuntu["warty"]

First, update the cache tables for Celso's PPA:

    >>> from lp.services.config import config
    >>> from lp.testing.dbuser import switch_dbuser
    >>> from lp.testing.layers import LaunchpadZopelessLayer
    >>> switch_dbuser(config.statistician.dbuser)

    >>> from lp.services.log.logger import FakeLogger
    >>> from lp.soyuz.model.distributionsourcepackagecache import (
    ...     DistributionSourcePackageCache,
    ... )
    >>> DistributionSourcePackageCache.updateAll(
    ...     ubuntu,
    ...     archive=cprov.archive,
    ...     ztm=LaunchpadZopelessLayer.txn,
    ...     log=FakeLogger(),
    ... )
    DEBUG Considering sources cdrkit, iceweasel, pmount
    ...

    >>> from lp.soyuz.model.distroseriespackagecache import (
    ...     DistroSeriesPackageCache,
    ... )
    >>> DistroSeriesPackageCache.updateAll(
    ...     warty,
    ...     archive=cprov.archive,
    ...     ztm=LaunchpadZopelessLayer.txn,
    ...     log=FakeLogger(),
    ... )
    DEBUG Considering binaries mozilla-firefox, pmount
    ...

    >>> cprov.archive.updateArchiveCache()
    >>> transaction.commit()
    >>> flush_database_updates()

Then, supersede all pmount publications in warty for pmount (this sets
us up to demonstrate bug 208233).

    >>> switch_dbuser("archivepublisher")
    >>> from lp.soyuz.model.binarypackagename import BinaryPackageName
    >>> from lp.soyuz.model.distroarchseries import DistroArchSeries
    >>> from lp.soyuz.model.distroarchseriesbinarypackage import (
    ...     DistroArchSeriesBinaryPackage,
    ... )
    >>> from lp.soyuz.model.publishing import BinaryPackagePublishingHistory
    >>> warty_i386 = DistroArchSeries.get(1)
    >>> pmount_name = BinaryPackageName.selectOneBy(name="pmount")
    >>> pmount_warty_i386 = DistroArchSeriesBinaryPackage(
    ...     warty_i386, pmount_name
    ... )
    >>> pubs = IStore(BinaryPackagePublishingHistory).find(
    ...     BinaryPackagePublishingHistory,
    ...     archive=1,
    ...     distroarchseries=warty_i386,
    ...     status=PackagePublishingStatus.PUBLISHED,
    ... )
    >>> for p in pubs:
    ...     if p.binarypackagerelease.binarypackagename == pmount_name:
    ...         s = p.supersede()
    ...
    >>> transaction.commit()
    >>> flush_database_updates()
    >>> switch_dbuser(config.statistician.dbuser)

Now, if that bug is actually fixed, this works:

    >>> print(pmount_warty_i386.summary)
    pmount shortdesc

    >>> print(pmount_warty_i386.description)
    pmount description

Yay!
