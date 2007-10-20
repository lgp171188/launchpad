# Copyright 2005-2007 Canonical Ltd.  All rights reserved.

"""Classes to represent source package releases in a distribution series."""

__metaclass__ = type

__all__ = [
    'DistroSeriesSourcePackageRelease',
    ]

from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import sqlvalues
from canonical.launchpad.database.build import Build
from canonical.launchpad.database.binarypackagerelease import (
    BinaryPackageRelease)
from canonical.launchpad.database.publishing import (
    SecureSourcePackagePublishingHistory, SourcePackagePublishingHistory)
from canonical.launchpad.database.queue import PackageUpload
from canonical.launchpad.interfaces import (
    IDistroSeriesSourcePackageRelease, ISourcePackageRelease)
from canonical.launchpad.scripts.ftpmaster import ArchiveOverriderError
from canonical.lp import decorates
from canonical.lp.dbschema import (
    PackagePublishingStatus, PackageUploadStatus)


class DistroSeriesSourcePackageRelease:
    """This is a "Magic SourcePackageRelease in Distro Release". It is not
    an SQLObject but instead it describes the behaviour of a specific
    release of the package in the distroseries."""

    implements(IDistroSeriesSourcePackageRelease)

    decorates(ISourcePackageRelease, context='sourcepackagerelease')

    def __init__(self, distroseries, sourcepackagerelease):
        self.distroseries = distroseries
        self.sourcepackagerelease = sourcepackagerelease

    @property
    def distribution(self):
        """See IDistroSeriesSourcePackageRelease."""
        return self.distroseries.distribution

    @property
    def displayname(self):
        """See IDistroSeriesSourcePackageRelease."""
        return '%s %s' % (self.name, self.version)

    @property
    def title(self):
        """See IDistroSeriesSourcePackageRelease."""
        return '%s %s (source) in %s %s' % (
            self.name, self.version, self.distribution.name,
            self.distroseries.name)

    @property
    def current_publishing_record(self):
        """An internal property used by methods of this class to know where
        this release is or was published.
        """
        pub_hist = self.publishing_history
        if pub_hist.count() == 0:
            return None
        return pub_hist[0]

    @property
    def version(self):
        """See IDistroSeriesSourcePackageRelease."""
        return self.sourcepackagerelease.version

    @property
    def pocket(self):
        """See IDistroSeriesSourcePackageRelease."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.pocket

    @property
    def section(self):
        """See IDistroSeriesSourcePackageRelease."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.section

    @property
    def component(self):
        """See IDistroSeriesSourcePackageRelease."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.component

    @property
    def publishing_history(self):
        """See IDistroSeriesSourcePackage."""
        return SourcePackagePublishingHistory.select("""
            distrorelease = %s AND
            archive IN %s AND
            sourcepackagerelease = %s
            """ % sqlvalues(
                    self.distroseries,
                    self.distroseries.distribution.all_distro_archive_ids,
                    self.sourcepackagerelease),
            orderBy='-id')

    @property
    def builds(self):
        """See IDistroSeriesSourcePackageRelease."""
        return Build.select("""
            Build.sourcepackagerelease = %s AND
            Build.distroarchrelease = DistroArchRelease.id AND
            DistroArchRelease.distrorelease = %s
            """ % sqlvalues(self.sourcepackagerelease.id,
                            self.distroseries.id),
            orderBy='-id',
            clauseTables=['DistroArchRelease'])

    @property
    def files(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.files

    @property
    def binaries(self):
        """See IDistroSeriesSourcePackageRelease."""
        clauseTables = [
            'BinaryPackageRelease',
            'DistroArchRelease',
            'Build',
            'BinaryPackagePublishingHistory'
        ]

        query = """
        BinaryPackageRelease.build=Build.id AND
        DistroArchRelease.id =
            BinaryPackagePublishingHistory.distroarchrelease AND
        BinaryPackagePublishingHistory.binarypackagerelease=
            BinaryPackageRelease.id AND
        DistroArchRelease.distrorelease=%s AND
        BinaryPackagePublishingHistory.archive IN %s AND
        Build.sourcepackagerelease=%s
        """ % sqlvalues(self.distroseries,
                        self.distroseries.distribution.all_distro_archive_ids,
                        self.sourcepackagerelease)

        return BinaryPackageRelease.select(
                query, prejoinClauseTables=['Build'],
                clauseTables=clauseTables, distinct=True)

    @property
    def meta_binaries(self):
        """See IDistroSeriesSourcePackageRelease."""
        return [self.distroseries.getBinaryPackage(
                    binary.binarypackagename)
                for binary in self.binaries]

    @property
    def changesfile(self):
        """See IDistroSeriesSourcePackageRelease."""
        clauseTables = [
            'PackageUpload',
            'PackageUploadSource',
            ]
        query = """
        PackageUpload.id = PackageUploadSource.packageupload AND
        PackageUpload.distrorelease = %s AND
        PackageUploadSource.sourcepackagerelease = %s AND
        PackageUpload.status = %s
        """ % sqlvalues(self.distroseries, self.sourcepackagerelease,
                        PackageUploadStatus.DONE)
        queue_record = PackageUpload.selectOne(
            query, clauseTables=clauseTables)

        if not queue_record:
            return None

        return queue_record.changesfile

    @property
    def current_published(self):
        """See IDistroArchSeriesSourcePackage."""
        # Retrieve current publishing info
        current = SourcePackagePublishingHistory.selectFirst("""
        distrorelease = %s AND
        archive IN %s AND
        sourcepackagerelease = %s AND
        status = %s
        """ % sqlvalues(self.distroseries,
                        self.distroseries.distribution.all_distro_archive_ids,
                        self.sourcepackagerelease,
                        PackagePublishingStatus.PUBLISHED),
            orderBy='-id')

        return current

    def changeOverride(self, new_component=None, new_section=None):
        """See `IDistroSeriesSourcePackageRelease`."""

        # Check we have been asked to do something
        if (new_component is None and
            new_section is None):
            raise AssertionError("changeOverride must be passed either a"
                                 " new component or new section")

        # Retrieve current publishing info
        current = self.current_published

        # Check there is a change to make
        if new_component is None:
            new_component = current.component
        if new_section is None:
            new_section = current.section

        if (new_component == current.component and
            new_section == current.section):
            return None

        # See if the archive has changed by virtue of the component
        # changing:
        new_archive = self.distribution.getArchiveByComponent(
            new_component.name)
        if new_archive != None and new_archive != current.archive:
            raise ArchiveOverriderError(
                "Overriding component to '%s' failed because it would "
                "require a new archive." % new_component.name)

        return SecureSourcePackagePublishingHistory(
            distroseries=current.distroseries,
            sourcepackagerelease=current.sourcepackagerelease,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            embargo=False,
            pocket=current.pocket,
            component=new_component,
            section=new_section,
            archive=current.archive
        )

    def supersede(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        # Retrieve current publishing info
        current = self.current_published
        current = SecureSourcePackagePublishingHistory.get(current.id)
        current.status = PackagePublishingStatus.SUPERSEDED
        current.datesuperseded = UTC_NOW

        return current

    def delete(self, removed_by, removal_comment=None):
        """See `IDistroSeriesSourcePackageRelease`."""
        # Retrieve current publishing info
        current = self.current_published
        current = SecureSourcePackagePublishingHistory.get(current.id)
        current.status = PackagePublishingStatus.DELETED
        current.datesuperseded = UTC_NOW
        current.removed_by = removed_by
        current.removal_comment = removal_comment

        return current

    def copyTo(self, distroseries, pocket):
        """See `IDistroSeriesSourcePackageRelease`."""
        current = self.current_published

        copy = SecureSourcePackagePublishingHistory(
            distroseries=distroseries,
            pocket=pocket,
            archive=current.archive,
            sourcepackagerelease=current.sourcepackagerelease,
            component=current.component,
            section=current.section,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            embargo=False,
        )
        return copy

    @property
    def published_binaries(self):
        """See `IDistroSeriesSourcePackageRelease`."""
        target_binaries = []

        # Get the binary packages in each distroarchseries and store them
        # in target_binaries for returning.  We are looking for *published*
        # binarypackagereleases in all arches for the 'source' and its
        # location.
        for binary in self.binaries:
            if binary.architecturespecific:
                considered_arches = [binary.build.distroarchseries]
            else:
                considered_arches = self.distroseries.architectures

            for distroarchseries in considered_arches:
                dasbpr = distroarchseries.getBinaryPackage(
                    binary.name)[binary.version]
                # Only include objects with published binaries.
                if dasbpr is None or dasbpr.current_publishing_record is None:
                    continue
                target_binaries.append(dasbpr)

        return target_binaries

