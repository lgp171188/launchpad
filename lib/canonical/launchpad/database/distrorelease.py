
from sets import Set

# Zope imports
from zope.interface import implements
from zope.component import getUtility

# SQLObject/SQLBase
from sqlobject import MultipleJoin, RelatedJoin, AND, LIKE
from sqlobject import StringCol, ForeignKey, IntCol, MultipleJoin, BoolCol, \
                      DateTimeCol
from sqlobject.sqlbuilder import func

from canonical.database.sqlbase import SQLBase, quote
from canonical.lp import dbschema

# interfaces and database 
from canonical.launchpad.interfaces import IDistroRelease, \
                                           IBinaryPackageUtility, \
                                           ISourcePackageUtility

from canonical.launchpad.database import SourcePackageName, \
                                         BinaryPackageName,\
                                         SourcePackageInDistro,\
                                         BinaryPackageSet, \
                                         SourcePackageInDistroSet


class DistroRelease(SQLBase):
    """Distrorelease SQLObject"""
    implements(IDistroRelease)

    _table = 'DistroRelease'
    _columns = [
        ForeignKey(name='distribution', dbName='distribution',
                   foreignKey='Distribution', notNull=True),
        StringCol('name', dbName='name', notNull=True),
        StringCol('displayname', dbName='displayname', notNull=True),
        StringCol('title', dbName='title', notNull=True),
        StringCol('shortdesc', dbName='shortdesc', notNull=True),
        StringCol('description', dbName='description', notNull=True),
        StringCol('version', dbName='version', notNull=True),
        ForeignKey(name='components', dbName='components', foreignKey='Schema',
                   notNull=True),
        ForeignKey(name='sections', dbName='sections', foreignKey='Schema',
                   notNull=True),
        IntCol('releasestate', dbName='releasestate', notNull=True),
        DateTimeCol('datereleased', dbName='datereleased', notNull=True),
        ForeignKey(name='parentrelease', dbName='parentrelease',
                   foreignKey='DistroRelease', notNull=False),
        ForeignKey(name='owner', dbName='owner', foreignKey='Person',
                   notNull=True),
        StringCol('lucilleconfig', dbName='lucilleconfig', notNull=False)
    ]

    architectures = MultipleJoin('DistroArchRelease',
                                  joinColumn='distrorelease' )
    role_users = MultipleJoin('DistroReleaseRole', 
                               joinColumn='distrorelease')

    def displayname(self):
        return self.name

    displayname = property(displayname)

    def parent(self):
        if self.parentrelease:
            return self.parentrelease.title
        return ''

    parent = property(parent)

    def _getState(self, value):
        for status in dbschema.DistributionReleaseState.items:
            if status.value == value:
                return status.title
        return 'Unknown'

    def state(self):
        return self._getState(self.releasestate)

    state = property(state)

    def sourcecount(self):
        clauseTables = ['SourcePackageName', 'SourcePackage',
            'SourcePackageRelease', 'SourcePackagePublishing']
        query = """ sourcepackagename.id = sourcepackage.sourcepackagename
                AND SourcePackagePublishing.sourcepackagerelease=
                                                  SourcePackageRelease.id
                AND SourcePackageRelease.sourcepackage = SourcePackage.id
                AND SourcePackagePublishing.distrorelease = %s;""" % (self.id)
        resultset = SourcePackageName.select(query, distinct=True,
            clauseTables=clauseTables)
        return resultset.count()


    sourcecount = property(sourcecount)

    def binarycount(self):
        clauseTables = ['BinaryPackageName', 'PackagePublishing',
            'BinaryPackage', 'DistroArchRelease']
        query = """
               BinaryPackageName.id = BinaryPackage.binarypackagename AND
               BinaryPackage.id = PackagePublishing.binarypackage AND
               PackagePublishing.distroarchrelease = DistroArchRelease.id AND
               DistroArchRelease.distrorelease = %s
               """ % (self.id)
        resultset = BinaryPackageName.select(query, distinct=True,
            clauseTables=clauseTables)
        return resultset.count()

    binarycount = property(binarycount)

    def architecturecount(self):
        return len(list(self.architectures))

    def bugCounter(self):
        counts = []
        
        clauseTables = ("VSourcePackageInDistro",
                        "SourcePackage")
        severities = [
            dbschema.BugAssignmentStatus.NEW,
            dbschema.BugAssignmentStatus.ACCEPTED,
            dbschema.BugAssignmentStatus.FIXED,
            dbschema.BugAssignmentStatus.REJECTED
        ]
        
        _query = ("sourcepackagebugassignment.sourcepackage = sourcepackage.id AND "
                 "sourcepackage.sourcepackagename = vsourcepackageindistro.sourcepackagename AND "
                 "vsourcepackageindistro.distrorelease = %i AND "
                 "sourcepackagebugassignment.bugstatus = %i"
                 )

        for severity in severities:
            query = _query %(self.id, int(severity))
            count = SourcePackageBugAssignment.select(query, clauseTables=clauseTables).count()
            counts.append(count)

        counts.insert(0, sum(counts))
        return counts

    bugCounter = property(bugCounter)

    def getBugSourcePackages(self):
        """Get SourcePackages in a DistroRelease with BugAssignement"""

        clauseTables=["SourcePackageBugAssignment",]
        query = ("VSourcePackageInDistro.distrorelease = %i AND "
                 "VSourcePackageInDistro.id = SourcePackageBugAssignment.sourcepackage AND "
                 "(SourcePackageBugAssignment.bugstatus != %i OR "
                 "SourcePackageBugAssignment.bugstatus != %i)"
                 %(self.id,
                   int(dbschema.BugAssignmentStatus.FIXED),
                   int(dbschema.BugAssignmentStatus.REJECTED)))

        return SourcePackageInDistro.select(query,
                                            clauseTables=clauseTables,
                                            distinct=True)

    def findSourcesByName(self, pattern):
        srcset = getUtility(ISourcePackageUtility)
        return srcset.findByNameInDistroRelease(self.id, pattern)

##    def getSourceByName(self, name):
#        srcset = getUtility(ISourcePackageSet)
#        return srcset.getByNameInDistroRelease(self.id, name)

    def __getitem__(self, arch):
        if arch == 'sources':
            return SourcePackageInDistroSet(self)
        
        return BinaryPackageSet(self, arch)
    

    def findBinariesByName(self, pattern):
        binariesutil = getUtility(IBinaryPackageUtility)
        selection = Set(binariesutil.findByNameInDistroRelease(self.id, pattern))
        # FIXME: (distinct_query) Daniel Debonzi 2004-10-13
        # XXX Daniel please can you go over this with SABDFL I don't
        # understand the code here. 11/12/04
        # expensive routine
        # Dummy solution to avoid a binarypackage to be shown more
        # then once
        present = []
        result = []
        for srcpkg in selection:
            if srcpkg.binarypackagename not in present:
                present.append(srcpkg.binarypackagename)
                result.append(srcpkg)
        return result


