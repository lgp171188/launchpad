# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Database class for table Archive."""

__metaclass__ = type

__all__ = ['Archive', 'ArchiveSet']

import os

from sqlobject import StringCol, ForeignKey
from zope.interface import implements

from canonical.archivepublisher.config import Config as PubConfig
from canonical.config import config
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad.interfaces import IArchive, IArchiveSet
from canonical.launchpad.webapp.url import urlappend
from canonical.lp.dbschema import PackagePublishingStatus


class Archive(SQLBase):
    implements(IArchive)
    _table = 'Archive'
    _defaultOrder = 'id'

    owner = ForeignKey(
        foreignKey='Person', dbName='owner', notNull=False)
    description = StringCol(dbName='description', notNull=False, default=None)

    def getPubConfig(self, distribution):
        """See IArchive."""
        pubconf = PubConfig(distribution)

        if self.id == distribution.main_archive.id:
            return pubconf

        pubconf.distroroot = config.personalpackagearchive.root

        pubconf.archiveroot = os.path.join(
            pubconf.distroroot, self.owner.name, distribution.name)

        pubconf.poolroot = os.path.join(pubconf.archiveroot, 'pool')
        pubconf.distsroot = os.path.join(pubconf.archiveroot, 'dists')

        pubconf.overrideroot = None
        pubconf.cacheroot = None
        pubconf.miscroot = None

        return pubconf

    @property
    def archive_url(self):
        """See IArchive."""
        return urlappend(
            config.personalpackagearchive.base_url, self.owner.name)


class ArchiveSet:
    implements(IArchiveSet)
    title = "Archives registered in Launchpad"

    def get(self, archive_id):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        return Archive.get(archive_id)

    def new(self, owner=None):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        return Archive(owner=owner)

    def ensure(self, owner):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        archive = owner.archive
        if archive is None:
            archive = self.new(owner=owner)
        return archive

    def getAllPPAs(self):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        return Archive.select("owner is not NULL")

    def getPendingPPAs(self):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        query = """
        Archive.owner is not NULL AND
        (SourcePackagePublishingHistory.archive = archive.id AND
         SourcePackagePublishingHistory.status = %s) OR
        (BinaryPackagePublishingHistory.archive = archive.id AND
         BinaryPackagePublishingHistory.status = %s)
        """ % sqlvalues(PackagePublishingStatus.PENDING,
                        PackagePublishingStatus.PENDING)

        clauseTables=['SourcePackagePublishingHistory',
                      'BinaryPackagePublishingHistory']

        return Archive.select(
            query, clauseTables=clauseTables, orderBy=['archive.id'],
            distinct=True)

    def __iter__(self):
        """See canonical.launchpad.interfaces.IArchiveSet."""
        return iter(Archive.select())
