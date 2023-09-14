Gina over Multiple Architectures (and Pockets, and Components)
--------------------------------------------------------------

Get the current counts of stuff in the database:

    >>> from lp.services.database.interfaces import IStore
    >>> from lp.services.identity.model.emailaddress import EmailAddress
    >>> from lp.registry.model.person import Person
    >>> from lp.registry.model.teammembership import TeamParticipation
    >>> from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
    >>> from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
    >>> from lp.soyuz.model.publishing import (
    ...     BinaryPackagePublishingHistory,
    ...     SourcePackagePublishingHistory,
    ... )
    >>> from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease
    >>> SSPPH = SourcePackagePublishingHistory
    >>> SBPPH = BinaryPackagePublishingHistory

    >>> orig_spr_count = (
    ...     IStore(SourcePackageRelease).find(SourcePackageRelease).count()
    ... )
    >>> orig_sspph_count = IStore(SSPPH).find(SSPPH).count()
    >>> orig_person_count = Person.select().count()
    >>> orig_tp_count = (
    ...     IStore(TeamParticipation).find(TeamParticipation).count()
    ... )
    >>> orig_email_count = IStore(EmailAddress).find(EmailAddress).count()
    >>> orig_bpr_count = (
    ...     IStore(BinaryPackageRelease).find(BinaryPackageRelease).count()
    ... )
    >>> orig_build_count = (
    ...     IStore(BinaryPackageBuild).find(BinaryPackageBuild).count()
    ... )
    >>> orig_sbpph_count = IStore(SBPPH).find(SBPPH).count()

Create a distribution series and an arch series for dapper:

    >>> from lp.soyuz.model.distroarchseries import DistroArchSeries
    >>> from lp.buildmaster.interfaces.processor import IProcessorSet
    >>> from lp.app.interfaces.launchpad import ILaunchpadCelebrities
    >>> celebs = getUtility(ILaunchpadCelebrities)
    >>> ubuntu = celebs.ubuntu
    >>> hoary = ubuntu.getSeries("hoary")

    # Only the distro owner or admins can create a series.
    >>> ignored = login_person(ubuntu.owner.activemembers[0])
    >>> dapper = ubuntu.newSeries(
    ...     "dapper",
    ...     "Dapper Dragoon",
    ...     "My title",
    ...     "My summary",
    ...     "My description",
    ...     "5.10",
    ...     hoary,
    ...     celebs.launchpad_developers,
    ... )
    >>> login(ANONYMOUS)

Check it was properly created and create its DistroArchSeriess.

    >>> from lp.registry.model.distroseries import DistroSeries
    >>> dapper = (
    ...     IStore(DistroSeries)
    ...     .find(DistroSeries, name="dapper", distribution=ubuntu)
    ...     .one()
    ... )
    >>> processor = getUtility(IProcessorSet).getByName("386")
    >>> dar = dapper.newArch(
    ...     processor=processor,
    ...     architecturetag="i386",
    ...     official=True,
    ...     owner=celebs.launchpad_developers,
    ... )
    >>> processor = getUtility(IProcessorSet).getByName("amd64")
    >>> dar = dapper.newArch(
    ...     processor=processor,
    ...     architecturetag="amd64",
    ...     official=True,
    ...     owner=celebs.launchpad_developers,
    ... )
    >>> processor = getUtility(IProcessorSet).new(
    ...     "powerpc", "PowerPC", "PowerPC"
    ... )
    >>> dar = dapper.newArch(
    ...     processor=processor,
    ...     architecturetag="powerpc",
    ...     official=True,
    ...     owner=celebs.launchpad_developers,
    ... )
    >>> import transaction
    >>> transaction.commit()

Let's set up the filesystem:

    >>> import subprocess, os
    >>> try:
    ...     os.unlink("/var/lock/launchpad-gina.lock")
    ... except OSError:
    ...     pass
    ...
    >>> try:
    ...     os.remove("/tmp/gina_test_archive")
    ... except OSError:
    ...     pass
    ...
    >>> relative_path = "lib/lp/soyuz/scripts/tests/gina_test_archive"
    >>> path = os.path.join(os.getcwd(), relative_path)
    >>> os.symlink(path, "/tmp/gina_test_archive")

    >>> gina_proc = ["scripts/gina.py", "-q", "dapper", "dapper-updates"]
    >>> proc = subprocess.run(
    ...     gina_proc, stderr=subprocess.PIPE, universal_newlines=True
    ... )
    >>> print(proc.stderr)
    WARNING ...
    WARNING No source package bdftopcf (0.99.0-1) listed for bdftopcf
            (0.99.0-1), scrubbing archive...
    WARNING The archive for dapper-updates/universe doesn't contain a
            directory for powerpc, skipping
    <BLANKLINE>
    >>> proc.returncode
    0

Make the changes visible elsewhere:

    >>> transaction.commit()

Check the quantities that were returned. We have:

  * bdftopdf, a binary package that comes from a source package that
    isn't listed in the Sources file (but which we find).

  * ekg, a source package that generates 3 binary packages.

We have two source packages, and we're only really publishing into
breezy:

    >>> (
    ...     IStore(SourcePackageRelease).find(SourcePackageRelease).count()
    ...     - orig_spr_count
    ... )
    2
    >>> print(IStore(SSPPH).find(SSPPH).count() - orig_sspph_count)
    2

Each source package has its own maintainer (in this case, fabbione and
porridge):

    >>> print(Person.select().count() - orig_person_count)
    2
    >>> print(
    ...     IStore(TeamParticipation).find(TeamParticipation).count()
    ...     - orig_tp_count
    ... )
    2
    >>> print(
    ...     IStore(EmailAddress).find(EmailAddress).count() - orig_email_count
    ... )
    2

There are 4 binary packages generated by the two builds of the two
source packages. We should only be publishing them into one
distroarchseries:

    >>> (
    ...     IStore(BinaryPackageRelease).find(BinaryPackageRelease).count()
    ...     - orig_bpr_count
    ... )
    4
    >>> (
    ...     IStore(BinaryPackageBuild).find(BinaryPackageBuild).count()
    ...     - orig_build_count
    ... )
    2
    >>> IStore(SBPPH).find(SBPPH).count() - orig_sbpph_count
    4

Check that the source package was correctly imported:

    >>> from lp.registry.interfaces.sourcepackagename import (
    ...     ISourcePackageNameSet,
    ... )
    >>> from lp.soyuz.interfaces.binarypackagename import (
    ...     IBinaryPackageNameSet,
    ... )
    >>> ekg_name = getUtility(ISourcePackageNameSet)["ekg"]
    >>> ekg = (
    ...     IStore(SourcePackageRelease)
    ...     .find(
    ...         SourcePackageRelease,
    ...         sourcepackagename=ekg_name,
    ...         version="1:1.5-4ubuntu1.2",
    ...     )
    ...     .one()
    ... )
    >>> print(ekg.section.name)
    net
    >>> print(ekg.component.name)
    main

And that one of the packages in main is here too:

    >>> libgadu_dev_name = getUtility(IBinaryPackageNameSet)["libgadu-dev"]
    >>> libgadu_dev = (
    ...     IStore(BinaryPackageRelease)
    ...     .find(
    ...         BinaryPackageRelease,
    ...         binarypackagename=libgadu_dev_name,
    ...         version="1:1.5-4ubuntu1.2",
    ...     )
    ...     .one()
    ... )
    >>> print(libgadu_dev.section.name)
    libdevel
    >>> print(libgadu_dev.component.name)
    main
    >>> print(libgadu_dev.architecturespecific)
    True
    >>> print(libgadu_dev.build.processor.name)
    386

Check that the package it generates in universe was successfully
processed. In particular, its section should be stripped of the
component name.

    >>> from lp.soyuz.enums import PackagePublishingPriority
    >>> ekg_name = getUtility(IBinaryPackageNameSet)["ekg"]
    >>> ekg = (
    ...     IStore(BinaryPackageRelease)
    ...     .find(
    ...         BinaryPackageRelease,
    ...         binarypackagename=ekg_name,
    ...         version="1:1.5-4ubuntu1.2",
    ...     )
    ...     .one()
    ... )
    >>> print(ekg.section.name)
    net
    >>> print(ekg.component.name)
    universe
    >>> print(ekg.priority == PackagePublishingPriority.OPTIONAL)
    True

The bdftopcf package is in a bit of a fix. Its binary package is present
in universe, but no source package is listed for it, and the actual
package files are in main! Gina to the rescue: it finds them in the
right place, updates the component, and creates it with a semi-bogus
DSC.

    >>> bdftopcf_name = getUtility(IBinaryPackageNameSet)["bdftopcf"]
    >>> bdftopcf = (
    ...     IStore(BinaryPackageRelease)
    ...     .find(
    ...         BinaryPackageRelease,
    ...         binarypackagename=bdftopcf_name,
    ...         version="0.99.0-1",
    ...     )
    ...     .one()
    ... )
    >>> print(bdftopcf.section.name)
    x11
    >>> print(bdftopcf.component.name)
    universe
    >>> print(bdftopcf.build.source_package_release.sourcepackagename.name)
    bdftopcf
    >>> print(bdftopcf.build.source_package_release.component.name)
    main
    >>> print(bdftopcf.build.source_package_release.version)
    0.99.0-1

Check that we publishing bdftopcf into the correct distroarchseries:

    >>> processor = getUtility(IProcessorSet).getByName("386")
    >>> dar = (
    ...     IStore(DistroArchSeries)
    ...     .find(
    ...         DistroArchSeries,
    ...         distroseries=dapper,
    ...         processor=processor,
    ...         architecturetag="i386",
    ...         official=True,
    ...         owner=celebs.launchpad_developers,
    ...     )
    ...     .one()
    ... )
    >>> print(dar.architecturetag)
    i386
    >>> for entry in (
    ...     IStore(SBPPH)
    ...     .find(SBPPH, distroarchseries=dar)
    ...     .order_by("binarypackagerelease")
    ... ):
    ...     package = entry.binarypackagerelease
    ...     print(package.binarypackagename.name, package.version)
    bdftopcf 0.99.0-1
    ekg 1:1.5-4ubuntu1.2
    libgadu-dev 1:1.5-4ubuntu1.2
    libgadu3 1:1.5-4ubuntu1.2

Be proper and clean up after ourselves.

    >>> os.remove("/tmp/gina_test_archive")
