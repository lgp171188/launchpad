# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "LatestPersonSourcePackageReleaseCache",
]

from datetime import timezone

from lazr.delegates import delegate_to
from storm.locals import Int, Reference
from storm.properties import DateTime
from zope.interface import implementer

from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.interfaces.reporting import (
    ILatestPersonSourcePackageReleaseCache,
)
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease


@implementer(ILatestPersonSourcePackageReleaseCache)
@delegate_to(ISourcePackageRelease, context="sourcepackagerelease")
class LatestPersonSourcePackageReleaseCache(StormBase):
    """See `LatestPersonSourcePackageReleaseCache`."""

    __storm_table__ = "LatestPersonSourcePackageReleaseCache"

    cache_id = Int(name="id", primary=True)
    publication_id = Int(name="publication")
    publication = Reference(
        publication_id, "SourcePackagePublishingHistory.id"
    )
    dateuploaded = DateTime(name="date_uploaded", tzinfo=timezone.utc)
    creator_id = Int(name="creator")
    maintainer_id = Int(name="maintainer")
    upload_archive_id = Int(name="upload_archive")
    upload_archive = Reference(upload_archive_id, "Archive.id")
    archive_purpose = DBEnum(enum=ArchivePurpose)
    upload_distroseries_id = Int(name="upload_distroseries")
    upload_distroseries = Reference(upload_distroseries_id, "DistroSeries.id")
    sourcepackagename_id = Int(name="sourcepackagename")
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")
    sourcepackagerelease_id = Int(name="sourcepackagerelease")
    sourcepackagerelease = Reference(
        sourcepackagerelease_id, "SourcePackageRelease.id"
    )
