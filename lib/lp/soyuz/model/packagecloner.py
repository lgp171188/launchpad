# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Logic for bulk copying of source/binary publishing history data."""

__all__ = [
    "PackageCloner",
]


import transaction
from storm.expr import And, Column, Insert, Is, Join, Not, Or, Select, Table
from zope.interface import implementer

from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import BulkUpdate
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.interfaces.packagecloner import IPackageCloner
from lp.soyuz.interfaces.publishing import active_publishing_status
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.packagesetsources import PackagesetSources
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
)
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease


@implementer(IPackageCloner)
class PackageCloner:
    """Used for copying of various publishing history data across archives."""

    def clonePackages(
        self,
        origin,
        destination,
        distroarchseries_list=None,
        processors=None,
        sourcepackagenames=None,
    ):
        """Copies packages from origin to destination package location.

        Binary packages are only copied for the `DistroArchSeries` pairs
        specified.

        @type origin: PackageLocation
        @param origin: the location from which packages are to be copied.
        @type destination: PackageLocation
        @param destination: the location to which the data is to be copied.
        @type distroarchseries_list: list of pairs of (origin, destination)
            distroarchseries instances.
        @param distroarchseries_list: the binary packages will be copied
            for the distroarchseries pairs specified (if any).
        @param processors: the processors to create builds for.
        @type processors: Iterable
        @param sourcepackagenames: the sourcepackages to copy to the
            destination
        @type sourcepackagenames: Iterable
        """
        # First clone the source packages.
        self._clone_source_packages(origin, destination, sourcepackagenames)

        # Are we also supposed to clone binary packages from origin to
        # destination distroarchseries pairs?
        if distroarchseries_list is not None:
            for origin_das, destination_das in distroarchseries_list:
                self._clone_binary_packages(
                    origin,
                    destination,
                    origin_das,
                    destination_das,
                    sourcepackagenames,
                )

        if processors is None:
            processors = []

        self._create_missing_builds(
            destination.distroseries,
            destination.archive,
            distroarchseries_list,
            processors,
        )

    def _create_missing_builds(
        self, distroseries, archive, distroarchseries_list, processors
    ):
        """Create builds for all cloned source packages.

        :param distroseries: the distro series for which to create builds.
        :param archive: the archive for which to create builds.
        :param processors: the list of processors for which to create builds.
        """
        # Avoid circular imports.
        from lp.soyuz.interfaces.publishing import active_publishing_status

        # Listify the architectures to avoid hitting this MultipleJoin
        # multiple times.
        architectures = list(distroseries.architectures)

        # Filter the list of DistroArchSeries so that only the ones
        # specified in processors remain.
        architectures = [
            architecture
            for architecture in architectures
            if architecture.processor in processors
        ]

        if len(architectures) == 0:
            return

        # Both, PENDING and PUBLISHED sources will be considered for
        # as PUBLISHED. It's part of the assumptions made in:
        # https://launchpad.net/soyuz/+spec/build-unpublished-source
        sources_published = archive.getPublishedSources(
            distroseries=distroseries, status=active_publishing_status
        )

        for pubrec in sources_published:
            pubrec.createMissingBuilds(architectures_available=architectures)
            # Commit to avoid MemoryError: bug 304459
            transaction.commit()

    def _clone_binary_packages(
        self,
        origin,
        destination,
        origin_das,
        destination_das,
        sourcepackagenames=None,
    ):
        """Copy binary publishing data from origin to destination.

        @type origin: PackageLocation
        @param origin: the location from which binary publishing
            records are to be copied.
        @type destination: PackageLocation
        @param destination: the location to which the data is
            to be copied.
        @type origin_das: DistroArchSeries
        @param origin_das: the DistroArchSeries from which to copy
            binary packages
        @type destination_das: DistroArchSeries
        @param destination_das: the DistroArchSeries to which to copy
            binary packages
        @param sourcepackagenames: List of source packages to restrict
            the copy to
        @type sourcepackagenames: Iterable
        """
        use_names = sourcepackagenames and len(sourcepackagenames) > 0
        BPB = BinaryPackageBuild
        BPPH = BinaryPackagePublishingHistory
        BPR = BinaryPackageRelease
        SPN = SourcePackageName
        SPR = SourcePackageRelease
        clauses = [
            BPPH.distroarchseries == origin_das,
            BPPH.status.is_in(active_publishing_status),
            BPPH.pocket == origin.pocket,
            BPPH.archive == origin.archive,
        ]
        if use_names:
            clauses.extend(
                [
                    BPPH.binarypackagerelease == BPR.id,
                    BPR.build == BPB.id,
                    BPB.source_package_release == SPR.id,
                    SPR.sourcepackagename == SPN.id,
                    SPN.name.is_in(sourcepackagenames),
                ]
            )
        # We do not need to set phased_update_percentage; that is heavily
        # context-dependent and should be set afresh for the new location if
        # required.
        IStore(BPPH).execute(
            Insert(
                (
                    BPPH.binarypackagerelease_id,
                    BPPH.distroarchseries_id,
                    BPPH.status,
                    BPPH.component_id,
                    BPPH.section_id,
                    BPPH.priority,
                    BPPH.archive_id,
                    BPPH.datecreated,
                    BPPH.datepublished,
                    BPPH.pocket,
                    BPPH.binarypackagename_id,
                ),
                values=Select(
                    (
                        BPPH.binarypackagerelease_id,
                        destination_das.id,
                        BPPH.status,
                        BPPH.component_id,
                        BPPH.section_id,
                        BPPH.priority,
                        destination.archive.id,
                        UTC_NOW,
                        UTC_NOW,
                        destination.pocket.value,
                        BPPH.binarypackagename_id,
                    ),
                    where=And(*clauses),
                ),
            )
        )

    def mergeCopy(self, origin, destination):
        """Please see `IPackageCloner`."""
        # Calculate the package set delta in order to find packages that are
        # obsolete or missing in the target archive.
        self.packageSetDiff(origin, destination)

        # Now copy the fresher or new packages.
        MCD = Table("tmp_merge_copy_data")
        SPPH = SourcePackagePublishingHistory
        store = IStore(SPPH)
        store.execute(
            Insert(
                (
                    SPPH.sourcepackagerelease_id,
                    SPPH.distroseries_id,
                    SPPH.status,
                    SPPH.component_id,
                    SPPH.section_id,
                    SPPH.archive_id,
                    SPPH.datecreated,
                    SPPH.datepublished,
                    SPPH.pocket,
                    SPPH.sourcepackagename_id,
                ),
                values=Select(
                    (
                        Column("s_sourcepackagerelease", MCD),
                        destination.distroseries.id,
                        Column("s_status", MCD),
                        Column("s_component", MCD),
                        Column("s_section", MCD),
                        destination.archive.id,
                        UTC_NOW,
                        UTC_NOW,
                        destination.pocket.value,
                        Column("sourcepackagename_id", MCD),
                    ),
                    where=Or(
                        Is(Column("obsoleted", MCD), True),
                        Is(Column("missing", MCD), True),
                    ),
                ),
            )
        )

        # Finally set the publishing status for the packages obsoleted in the
        # target archive accordingly (i.e make them superseded).
        store.execute(
            BulkUpdate(
                {
                    SPPH.status: PackagePublishingStatus.SUPERSEDED.value,
                    SPPH.datesuperseded: UTC_NOW,
                    SPPH.supersededby_id: Column(
                        "s_sourcepackagerelease", MCD
                    ),
                },
                table=SPPH,
                values=MCD,
                where=And(
                    SPPH.id == Column("t_sspph", MCD),
                    Is(Column("obsoleted", MCD), True),
                ),
            )
        )

        self._create_missing_builds(
            destination.distroseries,
            destination.archive,
            (),
            destination.archive.processors,
        )

    def _compute_packageset_delta(self, origin):
        """Given a source/target archive find obsolete or missing packages.

        This means finding out which packages in a given source archive are
        fresher or new with respect to a target archive.
        """
        MCD = Table("tmp_merge_copy_data")
        SPN = SourcePackageName
        SPPH = SourcePackagePublishingHistory
        SPR = SourcePackageRelease
        store = IStore(SPPH)

        # The query below will find all packages in the source archive that
        # are fresher than their counterparts in the target archive.
        newer_packages_clauses = [
            SPPH.archive == origin.archive,
            SPPH.status.is_in(active_publishing_status),
            SPPH.distroseries == origin.distroseries,
            SPPH.pocket == origin.pocket,
            SPPH.sourcepackagerelease == SPR.id,
            SPR.sourcepackagename == SPN.id,
            SPN.name == Column("sourcepackagename", MCD),
            SPR.version > Column("t_version", MCD),
        ]
        if origin.component is not None:
            newer_packages_clauses.append(SPPH.component == origin.component)
        store.execute(
            BulkUpdate(
                {
                    Column("s_sspph", MCD): SPPH.id,
                    Column("s_sourcepackagerelease", MCD): SPR.id,
                    Column("s_version", MCD): SPR.version,
                    Column("obsoleted", MCD): True,
                    Column("s_status", MCD): SPPH.status,
                    Column("s_component", MCD): SPPH.component_id,
                    Column("s_section", MCD): SPPH.section_id,
                },
                table=MCD,
                values=(SPPH, SPR, SPN),
                where=And(*newer_packages_clauses),
            )
        )

        # Now find the packages that exist in the source archive but *not* in
        # the target archive.
        origin_only_packages_clauses = [
            SPPH.archive == origin.archive,
            SPPH.status.is_in(active_publishing_status),
            SPPH.distroseries == origin.distroseries,
            SPPH.pocket == origin.pocket,
            Not(SPN.name.is_in(Select(Column("sourcepackagename", MCD)))),
        ]
        if origin.component is not None:
            origin_only_packages_clauses.append(
                SPPH.component == origin.component
            )
        store.execute(
            Insert(
                (
                    Column(col_name, MCD)
                    for col_name in (
                        "s_sspph",
                        "s_sourcepackagerelease",
                        "sourcepackagename",
                        "sourcepackagename_id",
                        "s_version",
                        "missing",
                        "s_status",
                        "s_component",
                        "s_section",
                    )
                ),
                values=Select(
                    (
                        SPPH.id,
                        SPPH.sourcepackagerelease_id,
                        SPN.name,
                        SPN.id,
                        SPR.version,
                        True,
                        SPPH.status,
                        SPPH.component_id,
                        SPPH.section_id,
                    ),
                    tables=(
                        SPPH,
                        Join(SPR, SPPH.sourcepackagerelease == SPR.id),
                        Join(SPN, SPR.sourcepackagename == SPN.id),
                    ),
                    where=And(*origin_only_packages_clauses),
                ),
            )
        )

    def _init_packageset_delta(self, destination):
        """Set up a temp table with data about target archive packages.

        This is a first step in finding out which packages in a given source
        archive are fresher or new with respect to a target archive.

        Merge copying of packages is one of the use cases that requires such a
        package set diff capability.

        In order to find fresher or new packages we first set up a temporary
        table that lists what packages exist in the target archive
        (additionally considering the distroseries, pocket and component).
        """
        MCD = Table("tmp_merge_copy_data")
        SPN = SourcePackageName
        SPPH = SourcePackagePublishingHistory
        SPR = SourcePackageRelease
        store = IStore(SPPH)

        # Use a temporary table to hold the data needed for the package set
        # delta computation. This will prevent multiple, parallel delta
        # calculations from interfering with each other.
        store.execute(
            """
            CREATE TEMP TABLE tmp_merge_copy_data (
                -- Source archive package data, only set for packages that
                -- will be copied.
                s_sspph integer,
                s_sourcepackagerelease integer,
                s_version debversion,
                s_status integer,
                s_component integer,
                s_section integer,
                -- Target archive package data, set for all published or
                -- pending packages.
                t_sspph integer,
                t_sourcepackagerelease integer,
                t_version debversion,
                -- Whether a target package became obsolete due to a more
                -- recent source package.
                obsoleted boolean DEFAULT false NOT NULL,
                missing boolean DEFAULT false NOT NULL,
                sourcepackagename text NOT NULL,
                sourcepackagename_id integer NOT NULL
            );
            CREATE INDEX source_name_index
            ON tmp_merge_copy_data USING btree (sourcepackagename);
        """
        )
        # Populate the temporary table with package data from the target
        # archive considering the distroseries, pocket and component.
        pop_clauses = [
            SPPH.archive == destination.archive,
            SPPH.status.is_in(active_publishing_status),
            SPPH.distroseries == destination.distroseries,
            SPPH.pocket == destination.pocket,
        ]
        if destination.component is not None:
            pop_clauses.append(SPPH.component == destination.component)
        store.execute(
            Insert(
                (
                    Column(col_name, MCD)
                    for col_name in (
                        "t_sspph",
                        "t_sourcepackagerelease",
                        "sourcepackagename",
                        "sourcepackagename_id",
                        "t_version",
                    )
                ),
                values=Select(
                    (
                        SPPH.id,
                        SPPH.sourcepackagerelease_id,
                        SPN.name,
                        SPN.id,
                        SPR.version,
                    ),
                    tables=(
                        SPPH,
                        Join(SPR, SPPH.sourcepackagerelease == SPR.id),
                        Join(SPN, SPR.sourcepackagename == SPN.id),
                    ),
                    where=And(*pop_clauses),
                ),
            )
        )

    def _clone_source_packages(self, origin, destination, sourcepackagenames):
        """Copy source publishing data from origin to destination.

        @type origin: PackageLocation
        @param origin: the location from which source publishing
            records are to be copied.
        @type destination: PackageLocation
        @param destination: the location to which the data is
            to be copied.
        @type sourcepackagenames: Iterable
        @param sourcepackagenames: List of source packages to restrict
            the copy to
        """
        FPSI = Table("FlatPackagesetInclusion")
        SPN = SourcePackageName
        SPPH = SourcePackagePublishingHistory
        SPR = SourcePackageRelease
        store = IStore(SPPH)

        clauses = [
            SPPH.distroseries == origin.distroseries,
            SPPH.status.is_in(active_publishing_status),
            SPPH.pocket == origin.pocket,
            SPPH.archive == origin.archive,
        ]

        if sourcepackagenames:
            clauses.append(
                SPPH.sourcepackagerelease_id.is_in(
                    Select(
                        SPR.id,
                        tables=(
                            SPR,
                            Join(SPN, SPR.sourcepackagename == SPN.id),
                        ),
                        where=SPN.name.is_in(sourcepackagenames),
                    )
                )
            )

        if origin.packagesets:
            clauses.append(
                SPPH.sourcepackagerelease_id.is_in(
                    Select(
                        SPR.id,
                        tables=(
                            SPR,
                            Join(
                                PackagesetSources,
                                PackagesetSources.sourcepackagename_id
                                == SPR.sourcepackagename_id,
                            ),
                            Join(
                                FPSI,
                                Column("child", FPSI)
                                == PackagesetSources.packageset_id,
                            ),
                        ),
                        where=Column("parent", FPSI).is_in(
                            [p.id for p in origin.packagesets]
                        ),
                    )
                )
            )

        if origin.component:
            clauses.append(SPPH.component == origin.component)

        store.execute(
            Insert(
                (
                    SPPH.sourcepackagerelease_id,
                    SPPH.distroseries_id,
                    SPPH.status,
                    SPPH.component_id,
                    SPPH.section_id,
                    SPPH.archive_id,
                    SPPH.datecreated,
                    SPPH.datepublished,
                    SPPH.pocket,
                    SPPH.sourcepackagename_id,
                ),
                values=Select(
                    (
                        SPPH.sourcepackagerelease_id,
                        destination.distroseries.id,
                        SPPH.status,
                        SPPH.component_id,
                        SPPH.section_id,
                        destination.archive.id,
                        UTC_NOW,
                        UTC_NOW,
                        destination.pocket.value,
                        SPPH.sourcepackagename_id,
                    ),
                    where=And(*clauses),
                ),
            )
        )

    def packageSetDiff(self, origin, destination, logger=None):
        """Please see `IPackageCloner`."""
        # Find packages that are obsolete or missing in the target archive.
        store = IStore(BinaryPackagePublishingHistory)
        self._init_packageset_delta(destination)
        self._compute_packageset_delta(origin)

        # Get the list of SourcePackagePublishingHistory keys for
        # source packages that are fresher in the origin archive.
        fresher_packages = store.execute(
            """
            SELECT s_sspph FROM tmp_merge_copy_data WHERE obsoleted = True;
        """
        )

        # Get the list of SourcePackagePublishingHistory keys for
        # source packages that are new in the origin archive.
        new_packages = store.execute(
            """
            SELECT s_sspph FROM tmp_merge_copy_data WHERE missing = True;
        """
        )

        if logger is not None:
            self._print_diagnostics(logger, store)

        return (
            [package for [package] in fresher_packages],
            [package for [package] in new_packages],
        )

    def _print_diagnostics(self, logger, store):
        """Print details of source packages that are fresher or new.

        Details of packages that are fresher or new in the origin archive
        are logged using the supplied 'logger' instance. This data is only
        available after a package set delta has been computed (see
        packageSetDiff()).
        """
        fresher_info = sorted(
            store.execute(
                """
            SELECT sourcepackagename, s_version, t_version
            FROM tmp_merge_copy_data
            WHERE obsoleted = True;
        """
            )
        )
        logger.info("Fresher packages: %d" % len(fresher_info))
        for info in fresher_info:
            logger.info("* %s (%s > %s)" % info)
        new_info = sorted(
            store.execute(
                """
            SELECT sourcepackagename, s_version
            FROM tmp_merge_copy_data
            WHERE missing = True;
        """
            )
        )
        logger.info("New packages: %d" % len(new_info))
        for info in new_info:
            logger.info("* %s (%s)" % info)
