# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "DistroSeriesPackageCache",
]

from collections import defaultdict
from operator import attrgetter

from storm.expr import Desc, Max, Select
from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.services.database import bulk
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.interfaces.distroseriespackagecache import (
    IDistroSeriesPackageCache,
)
from lp.soyuz.interfaces.publishing import active_publishing_status
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.distroarchseries import DistroArchSeries
from lp.soyuz.model.publishing import BinaryPackagePublishingHistory


@implementer(IDistroSeriesPackageCache)
class DistroSeriesPackageCache(StormBase):
    __storm_table__ = "DistroSeriesPackageCache"

    id = Int(primary=True)
    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, "Archive.id")
    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")
    binarypackagename_id = Int(name="binarypackagename", allow_none=False)
    binarypackagename = Reference(binarypackagename_id, "BinaryPackageName.id")

    name = Unicode(allow_none=True, default=None)
    summary = Unicode(allow_none=True, default=None)
    description = Unicode(allow_none=True, default=None)
    summaries = Unicode(allow_none=True, default=None)
    descriptions = Unicode(allow_none=True, default=None)

    def __init__(
        self,
        archive,
        distroseries,
        binarypackagename,
        summary=None,
        description=None,
    ):
        super().__init__()
        self.archive = archive
        self.distroseries = distroseries
        self.binarypackagename = binarypackagename
        self.summary = summary
        self.description = description

    @classmethod
    def findCurrentBinaryPackageNames(cls, archive, distroseries):
        bpn_ids = (
            IStore(BinaryPackagePublishingHistory)
            .find(
                BinaryPackagePublishingHistory.binarypackagename_id,
                BinaryPackagePublishingHistory.distroarchseries_id.is_in(
                    Select(
                        DistroArchSeries.id,
                        tables=[DistroArchSeries],
                        where=DistroArchSeries.distroseries == distroseries,
                    )
                ),
                BinaryPackagePublishingHistory.archive == archive,
                BinaryPackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
            .config(distinct=True)
            # Not necessary for correctness, but useful for testability; and
            # at the time of writing the sort only adds perhaps 10-20 ms to
            # the query time on staging.
            .order_by(BinaryPackagePublishingHistory.binarypackagename_id)
        )
        return bulk.load(BinaryPackageName, bpn_ids)

    @classmethod
    def _find(cls, distroseries, archive=None):
        """All of the cached binary package records for this distroseries.

        If 'archive' is not given it will return all caches stored for the
        distroseries main archives (PRIMARY and PARTNER).
        """
        if archive is not None:
            archives = [archive.id]
        else:
            archives = distroseries.distribution.all_distro_archive_ids

        return (
            IStore(cls)
            .find(
                cls,
                cls.distroseries == distroseries,
                cls.archive_id.is_in(archives),
            )
            .order_by(cls.name)
        )

    @classmethod
    def removeOld(cls, distroseries, archive, log):
        """Delete any records that are no longer applicable.

        Consider all binarypackages marked as REMOVED.

        Also purges all existing cache records for disabled archives.

        :param archive: target `IArchive`.
        :param log: the context logger object able to print DEBUG level
            messages.
        """
        # get the set of package names that should be there
        if not archive.enabled:
            bpns = set()
        else:
            bpns = set(
                cls.findCurrentBinaryPackageNames(archive, distroseries)
            )

        # remove the cache entries for binary packages we no longer want
        for cache in cls._find(distroseries, archive):
            if cache.binarypackagename not in bpns:
                log.debug(
                    "Removing binary cache for '%s' (%s)"
                    % (cache.name, cache.id)
                )
                IStore(cache).remove(cache)

    @classmethod
    def _update(cls, distroseries, binarypackagenames, archive, log):
        """Update the package cache for a given set of `IBinaryPackageName`s.

        'log' is required, it should be a logger object able to print
        DEBUG level messages.
        'ztm' is the current transaction manager used for partial commits
        (in full batches of 100 elements)
        """
        # get the set of published binarypackagereleases
        all_details = list(
            IStore(BinaryPackageRelease)
            .find(
                (
                    BinaryPackageRelease.binarypackagename_id,
                    BinaryPackageRelease.summary,
                    BinaryPackageRelease.description,
                    Max(BinaryPackageRelease.datecreated),
                ),
                BinaryPackageRelease.id
                == BinaryPackagePublishingHistory.binarypackagerelease_id,
                BinaryPackagePublishingHistory.binarypackagename_id.is_in(
                    [bpn.id for bpn in binarypackagenames]
                ),
                BinaryPackagePublishingHistory.distroarchseries_id.is_in(
                    Select(
                        DistroArchSeries.id,
                        tables=[DistroArchSeries],
                        where=DistroArchSeries.distroseries == distroseries,
                    )
                ),
                BinaryPackagePublishingHistory.archive == archive,
                BinaryPackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
            .group_by(
                BinaryPackageRelease.binarypackagename_id,
                BinaryPackageRelease.summary,
                BinaryPackageRelease.description,
            )
            .order_by(
                BinaryPackageRelease.binarypackagename_id,
                Desc(Max(BinaryPackageRelease.datecreated)),
            )
        )
        if not all_details:
            log.debug("No binary releases found.")
            return

        details_map = defaultdict(list)
        for bpn_id, summary, description, datecreated in all_details:
            bpn = IStore(BinaryPackageName).get(BinaryPackageName, bpn_id)
            details_map[bpn].append((summary, description))

        all_caches = IStore(cls).find(
            cls,
            cls.distroseries == distroseries,
            cls.archive == archive,
            cls.binarypackagename_id.is_in(
                [bpn.id for bpn in binarypackagenames]
            ),
        )
        cache_map = {cache.binarypackagename: cache for cache in all_caches}

        for bpn in set(binarypackagenames) - set(cache_map):
            cache_map[bpn] = cls(
                archive=archive,
                distroseries=distroseries,
                binarypackagename=bpn,
            )

        for bpn in binarypackagenames:
            if bpn not in details_map:
                log.debug(
                    "No active publishing details found for %s; perhaps "
                    "removed in parallel with update-pkgcache?  Skipping.",
                    bpn.name,
                )
                continue

            cache = cache_map[bpn]
            details = details_map[bpn]
            # make sure the cached name, summary and description are correct
            cache.name = bpn.name
            cache.summary = details[0][0]
            cache.description = details[0][1]

            # get the sets of binary package summaries, descriptions. there is
            # likely only one, but just in case...

            summaries = set()
            descriptions = set()
            for summary, description in details:
                summaries.add(summary)
                descriptions.add(description)

            # and update the caches
            cache.summaries = " ".join(sorted(summaries))
            cache.descriptions = " ".join(sorted(descriptions))

    @classmethod
    def updateAll(cls, distroseries, archive, log, ztm, commit_chunk=500):
        """Update the binary package cache

        Consider all binary package names published in this distro series
        and entirely skips updates for disabled archives

        :param archive: target `IArchive`;
        :param log: logger object for printing debug level information;
        :param ztm:  transaction used for partial commits, every chunk of
            'commit_chunk' updates is committed;
        :param commit_chunk: number of updates before commit, defaults to 500.

        :return the number of packages updated.
        """
        # Do not create cache entries for disabled archives.
        if not archive.enabled:
            return 0

        # Get the set of package names to deal with.
        bpns = list(
            sorted(
                cls.findCurrentBinaryPackageNames(archive, distroseries),
                key=attrgetter("name"),
            )
        )

        number_of_updates = 0
        chunks = []
        chunk = []
        for bpn in bpns:
            chunk.append(bpn)
            if len(chunk) == commit_chunk:
                chunks.append(chunk)
                chunk = []
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            bulk.load(BinaryPackageName, [bpn.id for bpn in chunk])
            log.debug(
                "Considering binaries %s",
                ", ".join([bpn.name for bpn in chunk]),
            )
            cls._update(distroseries, chunk, archive, log)
            number_of_updates += len(chunk)
            log.debug("Committing")
            ztm.commit()

        return number_of_updates
