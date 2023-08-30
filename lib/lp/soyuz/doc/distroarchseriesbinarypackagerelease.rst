Distro Arch Release Binary Package Release
==========================================

    >>> from lp.services.database.interfaces import IStore
    >>> from lp.soyuz.model.distroarchseriesbinarypackagerelease import (
    ...     DistroArchSeriesBinaryPackageRelease as DARBPR,
    ... )
    >>> from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
    >>> from lp.soyuz.model.distroarchseries import DistroArchSeries

Grab the relevant DARs and BPRs:

    >>> warty = IStore(DistroArchSeries).get(DistroArchSeries, 1)
    >>> print(warty.distroseries.name)
    warty
    >>> hoary = IStore(DistroArchSeries).get(DistroArchSeries, 6)
    >>> print(hoary.distroseries.name)
    hoary

    >>> mf = IStore(BinaryPackageRelease).get(BinaryPackageRelease, 12)
    >>> print(mf.binarypackagename.name)
    mozilla-firefox

    >>> pm = IStore(BinaryPackageRelease).get(BinaryPackageRelease, 15)
    >>> print(pm.binarypackagename.name)
    pmount

Assemble our DARBPRs for fun and profit:

    >>> mf_warty = DARBPR(warty, mf)
    >>> mf_hoary = DARBPR(hoary, mf)
    >>> pm_warty = DARBPR(warty, pm)
    >>> pm_hoary = DARBPR(hoary, pm)

    >>> for darbpr in [mf_warty, mf_hoary, pm_warty, pm_hoary]:
    ...     print(
    ...         darbpr.name,
    ...         darbpr.version,
    ...         darbpr._latest_publishing_record(),
    ...     )
    ...
    mozilla-firefox 0.9 <BinaryPackagePublishingHistory object>
    mozilla-firefox 0.9 None
    pmount 0.1-1 <BinaryPackagePublishingHistory object>
    pmount 0.1-1 <BinaryPackagePublishingHistory object>

    >>> print(
    ...     mf_warty.status.title,
    ...     pm_warty.status.title,
    ...     pm_hoary.status.title,
    ... )
    Published Superseded Published


Retrieving the parent object, a DistroArchSeriesBinaryPackage.

    >>> from lp.registry.interfaces.distribution import IDistributionSet

    >>> warty_i386 = getUtility(IDistributionSet)["ubuntu"]["warty"]["i386"]

    >>> warty_i386_pmount = warty_i386.getBinaryPackage("pmount")
    >>> print(warty_i386_pmount.title)
    pmount binary package in Ubuntu Warty i386

    >>> pmount_release_in_warty = warty_i386_pmount["0.1-1"]
    >>> print(pmount_release_in_warty.title)
    pmount 0.1-1 (i386 binary) in ubuntu warty

    >>> parent = pmount_release_in_warty.distroarchseriesbinarypackage
    >>> print(parent.title)
    pmount binary package in Ubuntu Warty i386

