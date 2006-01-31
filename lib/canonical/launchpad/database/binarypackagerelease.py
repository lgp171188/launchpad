# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['BinaryPackageRelease', 'BinaryPackageReleaseSet']


from zope.interface import implements

from sqlobject import StringCol, ForeignKey, IntCol, MultipleJoin, BoolCol

from canonical.database.sqlbase import SQLBase, quote, sqlvalues, quote_like

from canonical.launchpad.interfaces import (
    IBinaryPackageRelease, IBinaryPackageReleaseSet, NotFoundError)

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.database.publishing import (
    BinaryPackagePublishing, SecureBinaryPackagePublishingHistory)
from canonical.launchpad.database.files import BinaryPackageFile
from canonical.launchpad.helpers import shortlist

from canonical.lp import dbschema
from canonical.lp.dbschema import EnumCol


class BinaryPackageRelease(SQLBase):
    implements(IBinaryPackageRelease)
    _table = 'BinaryPackageRelease'
    binarypackagename = ForeignKey(dbName='binarypackagename', 
        foreignKey='BinaryPackageName', notNull=True)
    version = StringCol(dbName='version', notNull=True)
    summary = StringCol(dbName='summary', notNull=True, default="")
    description = StringCol(dbName='description', notNull=True)
    build = ForeignKey(dbName='build', foreignKey='Build', notNull=True)
    binpackageformat = EnumCol(dbName='binpackageformat', notNull=True,
        schema=dbschema.BinaryPackageFormat)
    component = ForeignKey(dbName='component', foreignKey='Component',
        notNull=True)
    section = ForeignKey(dbName='section', foreignKey='Section', notNull=True)
    priority = EnumCol(dbName='priority',
        schema=dbschema.PackagePublishingPriority)
    shlibdeps = StringCol(dbName='shlibdeps')
    depends = StringCol(dbName='depends')
    recommends = StringCol(dbName='recommends')
    suggests = StringCol(dbName='suggests')
    conflicts = StringCol(dbName='conflicts')
    replaces = StringCol(dbName='replaces')
    provides = StringCol(dbName='provides')
    essential = BoolCol(dbName='essential', default=False)
    installedsize = IntCol(dbName='installedsize')
    copyright = StringCol(dbName='copyright')
    licence = StringCol(dbName='licence')
    architecturespecific = BoolCol(dbName='architecturespecific',
        notNull=True)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    files = MultipleJoin('BinaryPackageFile',
        joinColumn='binarypackagerelease')

    @property
    def title(self):
        """See IBinaryPackageRelease."""
        return '%s-%s' % (self.binarypackagename.name, self.version)

    @property
    def name(self):
        """See IBinaryPackageRelease."""
        return self.binarypackagename.name

    @property
    def distributionsourcepackagerelease(self):
        """See IBinaryPackageRelease."""
        # import here to avoid circular import problems
        from canonical.launchpad.database.distributionsourcepackagerelease \
            import DistributionSourcePackageRelease
        return DistributionSourcePackageRelease(
            distribution=self.build.distribution,
            sourcepackagerelease=self.build.sourcepackagerelease)

    def lastversions(self):
        """Return the SUPERSEDED BinaryPackageReleases in a DistroRelease
        that comes from the same SourcePackage.
        """
        # Daniel Debonzi: To get the lastest versions of a BinaryPackage
        # Im suposing that one BinaryPackage is build for only one
        # DistroRelease (Each DistroRelease compile all its Packages). 
        # (BinaryPackage.build.distroarchrelease = \
        # PackagePublishing.distroarchrelease
        # where PackagePublishing.binarypackage = BinaryPackage.id)
        # When it is not true anymore, probably it should
        # be retrieved in a view class where I can use informations from
        # the launchbag.

        clauseTables = ['BinaryPackagePublishing', 'BinaryPackageName']
        query = ('''BinaryPackagePublishing.binarypackagerelease =
                        BinaryPackageRelease.id
                    AND BinaryPackageRelease.binarypackagename =
                    BinaryPackageName.id
                    AND BinaryPackageName.id = %s
                    AND BinaryPackagePublishing.distroarchrelease = %s
                    AND BinaryPackagePublishing.status = %s'''
                 % sqlvalues(self.binarypackagename.id,
                             self.build.distroarchrelease.id,
                             dbschema.PackagePublishingStatus.SUPERSEDED)
                 )

        return shortlist(BinaryPackageRelease.select(
            query, clauseTables=clauseTables, distinct=True))

    @property
    def status(self):
        """Returns the BinaryPackageRelease Status."""
        # XXX: dsilvers: 20050901: This entire method is a wrong. It shouldn't
        # exist like this because a BinaryPackageRelease is likely to be in
        # more than one DistroArchRelease as time goes by. In particular it
        # may be inherited.
        # This method should be considered for removal when BinaryPackage is
        # reworked properly.
        packagepublishing = BinaryPackagePublishing.selectOneBy(
            binarypackagereleaseID=self.id,
            distroarchreleaseID=self.build.distroarchrelease.id)
        if packagepublishing is None:
            raise NotFoundError('BinaryPackageRelease not found in '
                                'PackagePublishing')
        return packagepublishing.status.title

    def addFile(self, file):
        """See IBinaryPackageRelease."""
        determined_filetype = None
        if file.filename.endswith(".deb"):
            determined_filetype = dbschema.BinaryPackageFileType.DEB
        elif file.filename.endswith(".rpm"):
            determined_filetype = dbschema.BinaryPackageFileType.RPM
        elif file.filename.endswith(".udeb"):
            determined_filetype = dbschema.BinaryPackageFileType.UDEB

        return BinaryPackageFile(binarypackagerelease=self.id,
                                 filetype=determined_filetype,
                                 libraryfile=file.id)

    def publish(self, priority, status, pocket, embargo,
                distroarchrelease=None):
        """See IBinaryPackageRelease."""
        # XXX: completely untested code
        if not distroarchrelease:
            distroarchrelease = self.build.distroarchrelease

        return SecureBinaryPackagePublishingHistory(
            binarypackagereleaseID=self.id,
            distroarchreleaseID=distroarchrelease.id,
            componentID=self.build.sourcepackagerelease.component,
            sectionID=self.build.sourcepackagerelease.section,
            priority=priority,
            status=status,
            pocket=pocket,
            embargo=embargo,
            )

    def override(self, component=None, section=None, priority=None):
        """See IBinaryPackageRelease."""
        if component:
            self.component = component
        if section:
            self.section = section
        if priority:
            self.priority = priority


class BinaryPackageReleaseSet:
    """A Set of BinaryPackageReleases."""
    implements(IBinaryPackageReleaseSet)

    def findByNameInDistroRelease(self, distroreleaseID, pattern, archtag=None,
                                  fti=False):
        """Returns a set of binarypackagereleases that matchs pattern inside a
        distrorelease.
        """
        pattern = pattern.replace('%', '%%')
        query, clauseTables = self._buildBaseQuery(distroreleaseID)
        queries = [query]

        # XXX: Rewrite this code to use "AND".join(); I'm hacking on an
        # extra space here to make this work.
        #   -- kiko, 2005-09-23
        if fti:
            queries.append("""
                (BinaryPackageName.name LIKE lower('%%' || %s || '%%')
                 OR BinaryPackageRelease.fti @@ ftq(%s))
                """ % (quote_like(pattern), quote(pattern)))
        else:
            queries.append('BinaryPackageName.name ILIKE %s '
                           % sqlvalues('%%' + pattern + '%%'))

        if archtag:
            queries.append('DistroArchRelease.architecturetag=%s'
                           % sqlvalues(archtag))

        query = " AND ".join(queries)

        return BinaryPackageRelease.select(query, clauseTables=clauseTables,
                                           orderBy='BinaryPackageName.name')

    def getByNameInDistroRelease(self, distroreleaseID, name=None,
                                 version=None, archtag=None, orderBy=None):
        """Get a BinaryPackageRelease in a DistroRelease by its name."""

        # XXX: Rewrite this code to use "AND".join(); I'm hacking on an
        # extra space here to make this work.
        #   -- kiko, 2005-09-23
        query, clauseTables = self._buildBaseQuery(distroreleaseID)
        queries = [query]

        if name:
            queries.append('BinaryPackageName.name = %s'% sqlvalues(name))

        # Look for a specific binarypackage version or if version == None
        # return the current one
        if version:
            queries.append('BinaryPackageRelease.version = %s'
                         % sqlvalues(version))
        else:
            status_published = dbschema.PackagePublishingStatus.PUBLISHED
            queries.append('BinaryPackagePublishing.status = %s'
                         % sqlvalues(status_published))

        if archtag:
            queries.append('DistroArchRelease.architecturetag = %s'
                         % sqlvalues(archtag))

        query = " AND ".join(queries)
        return BinaryPackageRelease.select(query, distinct=True,
                                           clauseTables=clauseTables,
                                           orderBy=orderBy)

    def _buildBaseQuery(self, distroreleaseID):
        query = '''BinaryPackagePublishing.binarypackagerelease =
                        BinaryPackageRelease.id
                   AND BinaryPackagePublishing.distroarchrelease =
                        DistroArchRelease.id
                   AND DistroArchRelease.distrorelease = %d
                   AND BinaryPackageRelease.binarypackagename =
                        BinaryPackageName.id''' % distroreleaseID

        clauseTables = ['BinaryPackagePublishing', 'DistroArchRelease',
                        'BinaryPackageRelease', 'BinaryPackageName']

        return query, clauseTables

