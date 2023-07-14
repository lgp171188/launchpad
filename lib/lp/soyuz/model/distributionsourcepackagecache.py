# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "DistributionSourcePackageCache",
]

from collections import defaultdict
from operator import attrgetter, itemgetter

from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.code.model.seriessourcepackagebranch import SeriesSourcePackageBranch
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database import bulk
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.interfaces.distributionsourcepackagecache import (
    IDistributionSourcePackageCache,
)
from lp.soyuz.interfaces.publishing import active_publishing_status
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.publishing import SourcePackagePublishingHistory
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease

_DEFAULT = object()


@implementer(IDistributionSourcePackageCache)
class DistributionSourcePackageCache(StormBase):
    __storm_table__ = "DistributionSourcePackageCache"

    id = Int(primary=True)
    archive_id = Int(name="archive", allow_none=True)
    archive = Reference(archive_id, "Archive.id")
    distribution_id = Int(name="distribution", allow_none=False)
    distribution = Reference(distribution_id, "Distribution.id")
    sourcepackagename_id = Int(name="sourcepackagename", allow_none=False)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")

    name = Unicode(allow_none=True, default=None)
    binpkgnames = Unicode(allow_none=True, default=None)
    binpkgsummaries = Unicode(allow_none=True, default=None)
    binpkgdescriptions = Unicode(allow_none=True, default=None)
    changelog = Unicode(allow_none=True, default=None)

    def __init__(
        self,
        archive,
        distribution,
        sourcepackagename,
        name=None,
        binpkgnames=None,
        binpkgsummaries=None,
    ):
        super().__init__()
        self.archive = archive
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
        self.name = name
        self.binpkgnames = binpkgnames
        self.binpkgsummaries = binpkgsummaries

    @property
    def distributionsourcepackage(self):
        """See IDistributionSourcePackageCache."""

        # import here to avoid circular imports
        from lp.registry.model.distributionsourcepackage import (
            DistributionSourcePackage,
        )

        return DistributionSourcePackage(
            self.distribution, self.sourcepackagename
        )

    @classmethod
    def findCurrentSourcePackageNames(cls, distro, archive):
        if archive is None:
            spn_ids = IStore(SeriesSourcePackageBranch).find(
                SeriesSourcePackageBranch.sourcepackagenameID,
                DistroSeries.distribution == distro.id,
                SeriesSourcePackageBranch.distroseriesID == DistroSeries.id,
            )
        else:
            spn_ids = IStore(SourcePackagePublishingHistory).find(
                SourcePackagePublishingHistory.sourcepackagename_id,
                SourcePackagePublishingHistory.archive == archive,
                SourcePackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
        return bulk.load(SourcePackageName, spn_ids.config(distinct=True))

    @classmethod
    def _find(cls, distro, archive=_DEFAULT):
        """The set of all source package info caches for this distribution.

        If 'archive' is not given it will return all caches stored for the
        distribution main archives (PRIMARY and PARTNER).
        """
        archive_column = DistributionSourcePackageCache.archive_id
        if archive is _DEFAULT:
            archive_clause = archive_column.is_in(
                distro.all_distro_archive_ids
            )
        elif archive is not None:
            archive_clause = archive_column == archive.id
        else:
            archive_clause = archive_column == None

        result = (
            IStore(DistributionSourcePackageCache)
            .find(
                (DistributionSourcePackageCache, SourcePackageName),
                DistributionSourcePackageCache.distribution == distro,
                archive_clause,
                SourcePackageName.id
                == DistributionSourcePackageCache.sourcepackagename_id,
            )
            .order_by(DistributionSourcePackageCache.name)
        )
        return DecoratedResultSet(result, itemgetter(0))

    @classmethod
    def removeOld(cls, distro, archive, log):
        """Delete any cache records for removed packages.

        Also purges all existing cache records for disabled archives.

        :param archive: target `IArchive`, or None to consider official
            branches.
        :param log: the context logger object able to print DEBUG level
            messages.
        """

        # Get the set of source package names to deal with.
        if archive is not None and not archive.enabled:
            spns = set()
        else:
            spns = set(cls.findCurrentSourcePackageNames(distro, archive))

        # Remove the cache entries for packages we no longer publish.
        for cache in cls._find(distro, archive):
            if cache.sourcepackagename not in spns:
                log.debug(
                    "Removing source cache for '%s' (%s)"
                    % (cache.name, cache.id)
                )
                IStore(cache).remove(cache)

    @classmethod
    def update(
        cls, distro, sourcepackagenames, archive, with_binaries=True, log=None
    ):
        """Update the package cache for a given set of `ISourcePackageName`s.

        Cached details include generated binarypackage names, summary
        and description fti.
        """

        # Get the set of published sourcepackage releases.
        all_sprs = list(
            IStore(SourcePackageRelease)
            .find(
                (
                    SourcePackageRelease.sourcepackagenameID,
                    SourcePackageRelease.id,
                    SourcePackageRelease.version,
                ),
                SourcePackageRelease.id
                == SourcePackagePublishingHistory.sourcepackagerelease_id,
                SourcePackagePublishingHistory.sourcepackagename_id.is_in(
                    [spn.id for spn in sourcepackagenames]
                ),
                SourcePackagePublishingHistory.archive == archive,
                SourcePackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
            .config(distinct=True)
            .order_by(SourcePackageRelease.id)
        )
        if len(all_sprs) == 0:
            if log is not None:
                log.debug("No sources releases found.")
            return

        all_caches = IStore(cls).find(
            cls,
            cls.distribution == distro,
            cls.archive == archive,
            cls.sourcepackagename_id.is_in(
                [spn.id for spn in sourcepackagenames]
            ),
        )
        cache_map = {cache.sourcepackagename: cache for cache in all_caches}

        for spn in set(sourcepackagenames) - set(cache_map):
            cache_map[spn] = cls(
                archive=archive, distribution=distro, sourcepackagename=spn
            )

        if with_binaries:
            spr_map = defaultdict(list)
            for spn_id, spr_id, spr_version in all_sprs:
                spn = IStore(SourcePackageName).get(SourcePackageName, spn_id)
                spr_map[spn].append((spr_id, spr_version))

            # Query BinaryPackageBuilds and their BinaryPackageReleases
            # separately, since the big and inconsistent intermediates can
            # confuse postgres into a seq scan over BPR, which never ends
            # well for anybody.
            #
            # Beware: the sets expand much faster than you might expect for
            # the primary archive; COPY archive builds are caught too, of
            # which there are dozens for most SPRs, and there's no easy way
            # to exclude them!
            all_builds = list(
                IStore(BinaryPackageBuild).find(
                    (
                        BinaryPackageBuild.source_package_release_id,
                        BinaryPackageBuild.id,
                    ),
                    BinaryPackageBuild.source_package_release_id.is_in(
                        [row[1] for row in all_sprs]
                    ),
                )
            )
            all_binaries = list(
                IStore(BinaryPackageRelease).find(
                    (
                        BinaryPackageRelease.build_id,
                        BinaryPackageRelease.binarypackagename_id,
                        BinaryPackageRelease.summary,
                        BinaryPackageRelease.description,
                    ),
                    BinaryPackageRelease.build_id.is_in(
                        [row[1] for row in all_builds]
                    ),
                )
            )
            sprs_by_build = {
                build_id: spr_id for spr_id, build_id in all_builds
            }

            bulk.load(BinaryPackageName, [row[1] for row in all_binaries])
            binaries_by_spr = defaultdict(list)
            for bpb_id, bpn_id, summary, description in all_binaries:
                spr_id = sprs_by_build[bpb_id]
                binaries_by_spr[spr_id].append(
                    (
                        IStore(BinaryPackageName).get(
                            BinaryPackageName, bpn_id
                        ),
                        summary,
                        description,
                    )
                )

        for spn in sourcepackagenames:
            cache = cache_map[spn]
            cache.name = spn.name

            if with_binaries:
                binpkgnames = set()
                binpkgsummaries = set()
                binpkgdescriptions = set()
                for spr_id, spr_version in spr_map.get(spn, []):
                    if log is not None:
                        log.debug(
                            "Considering source %s %s", spn.name, spr_version
                        )
                    binpkgs = binaries_by_spr.get(spr_id, [])
                    for bpn, summary, description in binpkgs:
                        binpkgnames.add(bpn.name)
                        binpkgsummaries.add(summary)
                        binpkgdescriptions.add(description)

                # Update the caches.
                cache.binpkgnames = " ".join(sorted(binpkgnames))
                cache.binpkgsummaries = " ".join(sorted(binpkgsummaries))
                cache.binpkgdescriptions = " ".join(sorted(binpkgdescriptions))

            # Column due for deletion.
            cache.changelog = None

    @classmethod
    def updateOfficialBranches(cls, distro, sourcepackagenames):
        """Update the package cache for official branches with given names.

        We just cache the names for these.
        """
        all_caches = IStore(cls).find(
            cls,
            cls.distribution == distro,
            cls.archive == None,
            cls.sourcepackagename_id.is_in(
                [spn.id for spn in sourcepackagenames]
            ),
        )
        cache_map = {cache.sourcepackagename: cache for cache in all_caches}

        for spn in set(sourcepackagenames) - set(cache_map):
            cache_map[spn] = cls(
                archive=None,
                distribution=distro,
                sourcepackagename=spn,
                name=spn.name,
            )

    @classmethod
    def updateAll(cls, distro, archive, log, ztm, commit_chunk=500):
        """Update the source package cache.

        Consider every non-REMOVED sourcepackage and entirely skips updates
        for disabled archives.

        :param archive: target `IArchive`;
        :param log: logger object for printing debug level information;
        :param ztm:  transaction used for partial commits, every chunk of
            'commit_chunk' updates is committed;
        :param commit_chunk: number of updates before commit, defaults to 500.

        :return the number packages updated done
        """
        # Do not create cache entries for disabled archives.
        if archive is not None and not archive.enabled:
            return 0

        # Get the set of source package names to deal with.
        spns = list(
            sorted(
                cls.findCurrentSourcePackageNames(distro, archive),
                key=attrgetter("name"),
            )
        )

        number_of_updates = 0
        chunks = []
        chunk = []
        for spn in spns:
            chunk.append(spn)
            if len(chunk) == commit_chunk:
                chunks.append(chunk)
                chunk = []
        if chunk:
            chunks.append(chunk)
        for chunk in chunks:
            bulk.load(SourcePackageName, [spn.id for spn in chunk])
            log.debug(
                "Considering sources %s",
                ", ".join([spn.name for spn in chunk]),
            )
            if archive is None:
                cls.updateOfficialBranches(distro, chunk)
            else:
                cls.update(distro, chunk, archive, log)
            number_of_updates += len(chunk)
            log.debug("Committing")
            ztm.commit()

        return number_of_updates
