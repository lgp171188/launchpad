# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BY_HASH_STAY_OF_EXECUTION",
    "cannot_modify_suite",
    "DirectoryHash",
    "FORMAT_TO_SUBCOMPONENT",
    "GLOBAL_PUBLISHER_LOCK",
    "Publisher",
    "getPublisher",
]

import bz2
import gzip
import hashlib
import lzma
import os
import re
import shutil
from collections import defaultdict
from datetime import datetime, timedelta
from functools import partial
from itertools import chain, groupby
from operator import attrgetter

from artifactory import ArtifactoryPath
from debian.deb822 import Release, _multivalued
from storm.expr import Desc
from zope.component import getUtility
from zope.interface import Attribute, Interface, implementer

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher import HARDCODED_COMPONENT_ORDER
from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.domination import Dominator
from lp.archivepublisher.indices import (
    build_binary_stanza_fields,
    build_source_stanza_fields,
    build_translations_stanza_fields,
)
from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    ISignableArchive,
)
from lp.archivepublisher.model.ftparchive import FTPArchiveHandler
from lp.archivepublisher.utils import RepositoryIndexFile, get_ppa_reference
from lp.registry.interfaces.pocket import PackagePublishingPocket, pocketsuffix
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.model.distroseries import DistroSeries
from lp.services.database.bulk import load
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.helpers import filenameToContentType
from lp.services.librarian.client import LibrarianClient
from lp.services.osutils import ensure_directory_exists, open_for_writing
from lp.services.utils import file_exists
from lp.soyuz.enums import (
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveStatus,
    BinaryPackageFormat,
    PackagePublishingStatus,
)
from lp.soyuz.interfaces.archive import NoSuchPPA
from lp.soyuz.interfaces.archivefile import IArchiveFileSet
from lp.soyuz.interfaces.publishing import (
    IPublishingSet,
    active_publishing_status,
)
from lp.soyuz.model.archivefile import ArchiveFile
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.distroarchseries import DistroArchSeries
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
)
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease

# Use this as the lock file name for all scripts that may manipulate
# archives in the filesystem.  In a Launchpad(Cron)Script, set
# lockfilename to this value to make it use the shared lock.
GLOBAL_PUBLISHER_LOCK = "launchpad-publisher.lock"


FORMAT_TO_SUBCOMPONENT = {
    BinaryPackageFormat.UDEB: "debian-installer",
    BinaryPackageFormat.DDEB: "debug",
}


# Number of days before unreferenced files are removed from by-hash.
BY_HASH_STAY_OF_EXECUTION = 1


def reorder_components(components):
    """Return a list of the components provided.

    The list will be ordered by the semi arbitrary rules of ubuntu.
    Over time this method needs to be removed and replaced by having
    component ordering codified in the database.
    """
    remaining = list(components)
    ordered = []
    for comp in HARDCODED_COMPONENT_ORDER:
        if comp in remaining:
            ordered.append(comp)
            remaining.remove(comp)
    ordered.extend(remaining)
    return ordered


def remove_suffix(path):
    """Return `path` but with any compression suffix removed."""
    if path.endswith(".gz"):
        return path[: -len(".gz")]
    elif path.endswith(".bz2"):
        return path[: -len(".bz2")]
    elif path.endswith(".xz"):
        return path[: -len(".xz")]
    else:
        return path


def get_suffixed_indices(path):
    """Return a set of paths to compressed copies of the given index."""
    return {path + suffix for suffix in ("", ".gz", ".bz2", ".xz")}


def getPublisher(archive, allowed_suites, log, distsroot=None):
    """Return an initialized Publisher instance for the given context.

    The callsites can override the location where the archive indexes will
    be stored via 'distroot' argument.
    """
    if archive.purpose != ArchivePurpose.PPA:
        log.debug(
            "Finding configuration for %s %s."
            % (archive.distribution.name, archive.displayname)
        )
    else:
        log.debug("Finding configuration for '%s' PPA." % archive.owner.name)
    pubconf = getPubConfig(archive)

    disk_pool = pubconf.getDiskPool(log)

    if distsroot is not None:
        log.debug("Overriding dists root with %s." % distsroot)
        pubconf.distsroot = distsroot

    log.debug("Preparing publisher.")

    return Publisher(log, pubconf, disk_pool, archive, allowed_suites)


def get_sources_path(config, suite_name, component):
    """Return path to Sources file for the given arguments."""
    return os.path.join(
        config.distsroot, suite_name, component.name, "source", "Sources"
    )


def get_packages_path(config, suite_name, component, arch, subcomp=None):
    """Return path to Packages file for the given arguments."""
    component_root = os.path.join(config.distsroot, suite_name, component.name)
    arch_path = "binary-%s" % arch.architecturetag
    if subcomp is None:
        return os.path.join(component_root, arch_path, "Packages")
    else:
        return os.path.join(component_root, subcomp, arch_path, "Packages")


def cannot_modify_suite(archive, distroseries, pocket):
    """Return True for Release pockets of stable series in primary archives."""
    return (
        not distroseries.isUnstable()
        and not archive.allowUpdatesToReleasePocket()
        and pocket == PackagePublishingPocket.RELEASE
    )


class I18nIndex(_multivalued):
    """Represents an i18n/Index file."""

    _multivalued_fields = {
        "sha1": ["sha1", "size", "name"],
    }

    @property
    def _fixed_field_lengths(self):
        fixed_field_lengths = {}
        for key in self._multivalued_fields:
            length = self._get_size_field_length(key)
            fixed_field_lengths[key] = {"size": length}
        return fixed_field_lengths

    def _get_size_field_length(self, key):
        return max(len(str(item["size"])) for item in self[key])


class IArchiveHash(Interface):
    """Represents a hash algorithm used for index files."""

    hash_factory = Attribute("A hashlib class suitable for this algorithm.")
    deb822_name = Attribute(
        "Algorithm name expected by debian.deb822.Release."
    )
    apt_name = Attribute(
        "Algorithm name used by apt in Release files and by-hash "
        "subdirectories."
    )
    lfc_name = Attribute(
        "LibraryFileContent attribute name corresponding to this algorithm."
    )
    dh_name = Attribute(
        "Filename for use when checksumming directories with this algorithm."
    )
    write_by_hash = Attribute(
        "Whether to write by-hash subdirectories for this algorithm."
    )
    write_directory_hash = Attribute(
        "Whether to write *SUM files for this algorithm for directories."
    )


@implementer(IArchiveHash)
class MD5ArchiveHash:
    hash_factory = hashlib.md5
    deb822_name = "md5sum"
    apt_name = "MD5Sum"
    lfc_name = "md5"
    dh_name = "MD5SUMS"
    write_by_hash = False
    write_directory_hash = False


@implementer(IArchiveHash)
class SHA1ArchiveHash:
    hash_factory = hashlib.sha1
    deb822_name = "sha1"
    apt_name = "SHA1"
    lfc_name = "sha1"
    dh_name = "SHA1SUMS"
    write_by_hash = False
    write_directory_hash = False


@implementer(IArchiveHash)
class SHA256ArchiveHash:
    hash_factory = hashlib.sha256
    deb822_name = "sha256"
    apt_name = "SHA256"
    lfc_name = "sha256"
    dh_name = "SHA256SUMS"
    write_by_hash = True
    write_directory_hash = True


archive_hashes = [
    MD5ArchiveHash(),
    SHA1ArchiveHash(),
    SHA256ArchiveHash(),
]


class ByHash:
    """Represents a single by-hash directory tree."""

    def __init__(self, root, key, log):
        self.root = root
        self.path = os.path.join(root, key, "by-hash")
        self.log = log
        self.known_digests = defaultdict(lambda: defaultdict(set))

    @property
    def _usable_archive_hashes(self):
        usable = []
        for archive_hash in archive_hashes:
            if archive_hash.write_by_hash:
                usable.append(archive_hash)
        return usable

    def add(self, name, lfa, copy_from_path=None):
        """Ensure that by-hash entries for a single file exist.

        :param name: The name of the file under this directory tree.
        :param lfa: The `ILibraryFileAlias` to add.
        :param copy_from_path: If not None, copy file content from here
            rather than fetching it from the librarian.  This can be used
            for newly-added files to avoid needing to commit the transaction
            before calling this method.
        """
        best_hash = self._usable_archive_hashes[-1]
        best_digest = getattr(lfa.content, best_hash.lfc_name)
        for archive_hash in reversed(self._usable_archive_hashes):
            digest = getattr(lfa.content, archive_hash.lfc_name)
            digest_path = os.path.join(
                self.path, archive_hash.apt_name, digest
            )
            self.known_digests[archive_hash.apt_name][digest].add(name)
            if not os.path.lexists(digest_path):
                self.log.debug(
                    "by-hash: Creating %s for %s" % (digest_path, name)
                )
                ensure_directory_exists(os.path.dirname(digest_path))
                if archive_hash != best_hash:
                    os.symlink(
                        os.path.join(
                            os.pardir, best_hash.apt_name, best_digest
                        ),
                        digest_path,
                    )
                elif copy_from_path is not None:
                    os.link(
                        os.path.join(self.root, copy_from_path), digest_path
                    )
                else:
                    with open(digest_path, "wb") as outfile:
                        lfa.open()
                        try:
                            shutil.copyfileobj(lfa, outfile, 4 * 1024 * 1024)
                        finally:
                            lfa.close()

    def known(self, name, hashname, digest):
        """Do we know about a file with this name and digest?"""
        names = self.known_digests[hashname].get(digest)
        return names is not None and name in names

    def prune(self):
        """Remove all by-hash entries that we have not been told to add.

        This also removes the by-hash directory itself if no entries remain.
        """
        prune_directory = True
        for archive_hash in archive_hashes:
            hash_path = os.path.join(self.path, archive_hash.apt_name)
            if os.path.exists(hash_path):
                prune_hash_directory = True
                for entry in list(os.scandir(hash_path)):
                    if (
                        entry.name
                        not in self.known_digests[archive_hash.apt_name]
                    ):
                        self.log.debug(
                            "by-hash: Deleting unreferenced %s" % entry.path
                        )
                        os.unlink(entry.path)
                    else:
                        prune_hash_directory = False
                if prune_hash_directory:
                    os.rmdir(hash_path)
                else:
                    prune_directory = False
        if prune_directory and os.path.exists(self.path):
            os.rmdir(self.path)


class ByHashes:
    """Represents all by-hash directory trees in an archive."""

    def __init__(self, root, log):
        self.root = root
        self.log = log
        self.children = {}

    def registerChild(self, dirpath):
        """Register a single by-hash directory.

        Only directories that have been registered here will be pruned by
        the `prune` method.
        """
        if dirpath not in self.children:
            self.children[dirpath] = ByHash(self.root, dirpath, self.log)
        return self.children[dirpath]

    def add(self, path, lfa, copy_from_path=None):
        dirpath, name = os.path.split(path)
        self.registerChild(dirpath).add(
            name, lfa, copy_from_path=copy_from_path
        )

    def known(self, path, hashname, digest):
        dirpath, name = os.path.split(path)
        return self.registerChild(dirpath).known(name, hashname, digest)

    def prune(self):
        for child in self.children.values():
            child.prune()


class Publisher:
    """Publisher is the class used to provide the facility to publish
    files in the pool of a Distribution. The publisher objects will be
    instantiated by the archive build scripts and will be used throughout
    the processing of each DistroSeries and DistroArchSeries in question
    """

    def __init__(
        self, log, config, diskpool, archive, allowed_suites=None, library=None
    ):
        """Initialize a publisher.

        Publishers need the pool root dir and a DiskPool object.

        Optionally we can pass a list of suite names which will restrict the
        publisher actions; only suites listed in allowed_suites will be
        modified.
        """
        self.log = log
        self._config = config
        self.distro = archive.distribution
        self.archive = archive
        self.allowed_suites = (
            None if allowed_suites is None else set(allowed_suites)
        )

        self._diskpool = diskpool

        if library is None:
            self._library = LibrarianClient()
        else:
            self._library = library

        # Track which suites have been dirtied by a change, and therefore
        # need domination/apt-ftparchive work.  This is a set of suite names
        # as returned by DistroSeries.getSuite.
        self.dirty_suites = set()

        # Track which suites need release files.  This will contain more
        # than dirty_suites in the case of a careful index run.
        # This is a set of suite names as returned by DistroSeries.getSuite.
        self.release_files_needed = set()

    def setupArchiveDirs(self):
        self.log.debug("Setting up archive directories.")
        self._config.setupArchiveDirs()

    def isDirty(self, distroseries, pocket):
        """True if a publication has happened in this release and pocket."""
        return distroseries.getSuite(pocket) in self.dirty_suites

    def markSuiteDirty(self, distroseries, pocket):
        """Mark a suite dirty only if it's allowed."""
        if self.isAllowed(distroseries, pocket):
            self.dirty_suites.add(distroseries.getSuite(pocket))

    def isAllowed(self, distroseries, pocket):
        """Whether or not the given suite should be considered.

        Return True either if the self.allowed_suite is empty (was not
        specified in command line) or if the given suite is included in it.

        Otherwise, return False.
        """
        return (
            not self.allowed_suites
            or distroseries.getSuite(pocket) in self.allowed_suites
        )

    @property
    def subcomponents(self):
        subcomps = []
        if self.archive.purpose != ArchivePurpose.PARTNER:
            subcomps.append("debian-installer")
        if self.archive.publish_debug_symbols:
            subcomps.append("debug")
        return subcomps

    @property
    def consider_series(self):
        if self.archive.purpose in (
            ArchivePurpose.PRIMARY,
            ArchivePurpose.PARTNER,
        ):
            # For PRIMARY and PARTNER archives, skip OBSOLETE and FUTURE
            # series.  We will never want to publish anything in them, so it
            # isn't worth thinking about whether they have pending
            # publications.
            return [
                series
                for series in self.distro.series
                if series.status
                not in (
                    SeriesStatus.OBSOLETE,
                    SeriesStatus.FUTURE,
                )
            ]
        else:
            # Other archives may have reasons to continue building at least
            # for OBSOLETE series.  For example, a PPA may be continuing to
            # provide custom builds for users who haven't upgraded yet.
            return self.distro.series

    def checkLegalPocket(self, distroseries, pocket, is_careful):
        """Check if the publication can happen in the archive."""
        if distroseries not in self.consider_series:
            return False
        # 'careful' mode re-publishes everything:
        if is_careful:
            return True
        return self.archive.canModifySuite(distroseries, pocket)

    def getPendingSourcePublications(self, is_careful):
        """Return the specific group of source records to be published."""
        # Careful publishing should include all rows in active statuses
        # regardless of whether they have previously been published; a
        # normal run only includes rows in active statuses that have never
        # been published.
        clauses = [
            SourcePackagePublishingHistory.archive == self.archive,
            SourcePackagePublishingHistory.status.is_in(
                active_publishing_status
            ),
        ]
        if not is_careful:
            clauses.append(
                SourcePackagePublishingHistory.datepublished == None
            )

        publications = IStore(SourcePackagePublishingHistory).find(
            SourcePackagePublishingHistory, *clauses
        )
        return publications.order_by(
            SourcePackagePublishingHistory.distroseries_id,
            SourcePackagePublishingHistory.pocket,
            Desc(SourcePackagePublishingHistory.id),
        )

    def publishSources(self, distroseries, pocket, spphs):
        """Publish sources for a given distroseries and pocket."""
        self.log.debug(
            "* Publishing pending sources for %s"
            % distroseries.getSuite(pocket)
        )
        for spph in spphs:
            spph.publish(self._diskpool, self.log)

    def findAndPublishSources(self, is_careful=False):
        """Search for and publish all pending sources.

        :param is_careful: If True, republish all published records (system
            will DTRT checking the hash of all published files).

        Consider records returned by getPendingSourcePublications.
        """
        dirty_suites = set()
        all_spphs = self.getPendingSourcePublications(is_careful)
        for (distroseries, pocket), spphs in groupby(
            all_spphs, attrgetter("distroseries", "pocket")
        ):
            if not self.isAllowed(distroseries, pocket):
                self.log.debug("* Skipping %s", distroseries.getSuite(pocket))
            elif not self.checkLegalPocket(distroseries, pocket, is_careful):
                for spph in spphs:
                    self.log.error(
                        "Tried to publish %s (%s) into %s (%s), skipping"
                        % (
                            spph.displayname,
                            spph.id,
                            distroseries.getSuite(pocket),
                            distroseries.status.name,
                        )
                    )
            else:
                self.publishSources(distroseries, pocket, spphs)
                dirty_suites.add(distroseries.getSuite(pocket))
        return dirty_suites

    def getPendingBinaryPublications(self, is_careful):
        """Return the specific group of binary records to be published."""
        clauses = [
            BinaryPackagePublishingHistory.archive == self.archive,
            BinaryPackagePublishingHistory.distroarchseries_id
            == DistroArchSeries.id,
            BinaryPackagePublishingHistory.status.is_in(
                active_publishing_status
            ),
        ]
        if not is_careful:
            clauses.append(
                BinaryPackagePublishingHistory.datepublished == None
            )

        publications = IStore(BinaryPackagePublishingHistory).find(
            BinaryPackagePublishingHistory, *clauses
        )
        return publications.order_by(
            DistroArchSeries.distroseries_id,
            BinaryPackagePublishingHistory.pocket,
            DistroArchSeries.architecturetag,
            Desc(BinaryPackagePublishingHistory.id),
        )

    def publishBinaries(self, distroarchseries, pocket, bpphs):
        """Publish binaries for a given distroarchseries and pocket."""
        self.log.debug(
            "* Publishing pending binaries for %s/%s"
            % (
                distroarchseries.distroseries.getSuite(pocket),
                distroarchseries.architecturetag,
            )
        )
        for bpph in bpphs:
            bpph.publish(self._diskpool, self.log)

    def findAndPublishBinaries(self, is_careful=False):
        """Search for and publish all pending binaries.

        :param is_careful: If True, republish all published records (system
            will DTRT checking the hash of all published files).

        Consider records returned by getPendingBinaryPublications.
        """
        dirty_suites = set()
        all_bpphs = self.getPendingBinaryPublications(is_careful)
        for (distroarchseries, pocket), bpphs in groupby(
            all_bpphs, attrgetter("distroarchseries", "pocket")
        ):
            distroseries = distroarchseries.distroseries
            if not self.isAllowed(distroseries, pocket):
                pass  # Already logged by publishSources.
            elif not self.checkLegalPocket(distroseries, pocket, is_careful):
                for bpph in bpphs:
                    self.log.error(
                        "Tried to publish %s (%s) into %s (%s), skipping"
                        % (
                            bpph.displayname,
                            bpph.id,
                            distroseries.getSuite(pocket),
                            distroseries.status.name,
                        )
                    )
            else:
                self.publishBinaries(distroarchseries, pocket, bpphs)
                dirty_suites.add(distroseries.getSuite(pocket))
        return dirty_suites

    def A_publish(self, force_publishing):
        """First step in publishing: actual package publishing.

        Publish each DistroSeries, which causes publishing records to be
        updated, and files to be placed on disk where necessary.
        If self.allowed_suites is set, restrict the publication procedure
        to them.
        """
        self.log.debug("* Step A: Publishing packages")

        self.dirty_suites.update(
            self.findAndPublishSources(is_careful=force_publishing)
        )
        self.dirty_suites.update(
            self.findAndPublishBinaries(is_careful=force_publishing)
        )

    def A2_markPocketsWithDeletionsDirty(self):
        """An intermediate step in publishing to detect deleted packages.

        Mark pockets containing deleted packages (status DELETED or
        OBSOLETE), scheduledeletiondate NULL and dateremoved NULL as
        dirty, to ensure that they are processed in death row.
        """
        self.log.debug("* Step A2: Mark pockets with deletions as dirty")

        # Query part that is common to both queries below.
        def base_conditions(table):
            return [
                table.archive == self.archive,
                table.status == PackagePublishingStatus.DELETED,
                table.scheduleddeletiondate == None,
                table.dateremoved == None,
            ]

        # We need to get a set of suite names that have publications that
        # are waiting to be deleted.  Each suite name is added to the
        # dirty_suites set.

        # Make the source publications query.
        conditions = base_conditions(SourcePackagePublishingHistory)
        conditions.append(
            SourcePackagePublishingHistory.distroseries_id == DistroSeries.id
        )
        source_suites = (
            IStore(SourcePackagePublishingHistory)
            .find(
                (DistroSeries, SourcePackagePublishingHistory.pocket),
                *conditions,
            )
            .config(distinct=True)
            .order_by(DistroSeries.id, SourcePackagePublishingHistory.pocket)
        )

        # Make the binary publications query.
        conditions = base_conditions(BinaryPackagePublishingHistory)
        conditions.extend(
            [
                BinaryPackagePublishingHistory.distroarchseries_id
                == DistroArchSeries.id,
                DistroArchSeries.distroseries == DistroSeries.id,
            ]
        )
        binary_suites = (
            IStore(BinaryPackagePublishingHistory)
            .find(
                (DistroSeries, BinaryPackagePublishingHistory.pocket),
                *conditions,
            )
            .config(distinct=True)
            .order_by(DistroSeries.id, BinaryPackagePublishingHistory.pocket)
        )

        for distroseries, pocket in chain(source_suites, binary_suites):
            if self.isDirty(distroseries, pocket):
                continue
            if cannot_modify_suite(
                self.archive, distroseries, pocket
            ) or not self.isAllowed(distroseries, pocket):
                # We don't want to mark release pockets dirty in a
                # stable distroseries, no matter what other bugs
                # that precede here have dirtied it.
                continue
            self.markSuiteDirty(distroseries, pocket)

    def B_dominate(self, force_domination):
        """Second step in publishing: domination."""
        self.log.debug("* Step B: dominating packages")
        judgejudy = Dominator(self.log, self.archive)
        for distroseries in self.distro.series:
            for pocket in self.archive.getPockets():
                # XXX cjwatson 2022-05-19: Channels are handled in the
                # dominator instead; see the comment in
                # Dominator._sortPackages.
                if not self.isAllowed(distroseries, pocket):
                    continue
                if not force_domination:
                    if not self.isDirty(distroseries, pocket):
                        self.log.debug(
                            "Skipping domination for %s/%s"
                            % (distroseries.name, pocket.name)
                        )
                        continue
                    self.checkDirtySuiteBeforePublishing(distroseries, pocket)
                judgejudy.judgeAndDominate(distroseries, pocket)

    def C_doFTPArchive(self, is_careful):
        """Does the ftp-archive step: generates Sources and Packages."""
        self.log.debug("* Step C: Set apt-ftparchive up and run it")
        apt_handler = FTPArchiveHandler(
            self.log, self._config, self._diskpool, self.distro, self
        )
        apt_handler.run(is_careful)

    def C_writeIndexes(self, is_careful):
        """Write Index files (Packages & Sources) using LP information.

        Iterates over all distroseries and its pockets and components.
        """
        self.log.debug("* Step C': write indexes directly from DB")
        for distroseries in self.distro:
            for pocket in self.archive.getPockets():
                if not is_careful:
                    if not self.isDirty(distroseries, pocket):
                        self.log.debug(
                            "Skipping index generation for %s/%s"
                            % (distroseries.name, pocket.name)
                        )
                        continue
                    self.checkDirtySuiteBeforePublishing(distroseries, pocket)

                self.release_files_needed.add(distroseries.getSuite(pocket))

                components = self.archive.getComponentsForSeries(distroseries)
                for component in components:
                    self._writeComponentIndexes(
                        distroseries, pocket, component
                    )

    def C_updateArtifactoryProperties(self, is_careful):
        """Update Artifactory properties to match our database."""
        self.log.debug("* Step C'': Updating properties in Artifactory")
        # We don't currently have a more efficient approach available than
        # just syncing up the entire repository.  At the moment it's
        # difficult to do better, since Launchpad's publishing model
        # normally assumes that the disk pool only needs to know about
        # removals once they get to the point of being removed entirely from
        # disk, as opposed to just being removed from a single
        # suite/channel.  A more complete overhaul of the
        # publisher/dominator might be able to deal with this.
        publishing_set = getUtility(IPublishingSet)
        releases_by_id = {}
        pubs_by_id = defaultdict(list)
        spphs_by_spr = defaultdict(list)
        bpphs_by_bpr = defaultdict(list)
        for spph in publishing_set.getSourcesForPublishing(
            archive=self.archive
        ):
            spphs_by_spr[spph.sourcepackagerelease_id].append(spph)
            release_id = "source:%d" % spph.sourcepackagerelease_id
            releases_by_id.setdefault(release_id, spph.sourcepackagerelease)
            self.log.debug(
                "Collecting %s for %s", release_id, spph.sourcepackagename
            )
            pubs_by_id[release_id].append(spph)
        for bpph in publishing_set.getBinariesForPublishing(
            archive=self.archive
        ):
            bpphs_by_bpr[bpph.binarypackagerelease_id].append(bpph)
            release_id = "binary:%d" % bpph.binarypackagerelease_id
            self.log.debug(
                "Collecting %s for %s", release_id, bpph.binarypackagename
            )
            releases_by_id.setdefault(release_id, bpph.binarypackagerelease)
            pubs_by_id[release_id].append(bpph)
        artifacts = self._diskpool.getAllArtifacts(
            self.archive.name, self.archive.repository_format
        )

        plan = []
        for path, properties in sorted(artifacts.items()):
            release_id = properties.get("launchpad.release-id")
            source_name = properties.get("launchpad.source-name")
            source_version = properties.get("launchpad.source-version")
            if not release_id or not source_name or not source_version:
                # Skip any files that Launchpad didn't put in Artifactory.
                continue
            plan.append(
                (
                    source_name[0],
                    source_version[0],
                    release_id[0],
                    path,
                    properties,
                )
            )

        # Releases that have been removed may still have corresponding
        # artifacts but no corresponding publishing history rows.  Bulk-load
        # any of these that we find so that we can track down the
        # corresponding pool entries.
        missing_sources = set()
        missing_binaries = set()
        for _, _, release_id, _, _ in plan:
            if release_id in releases_by_id:
                continue
            match = re.match(r"^source:(\d+)$", release_id)
            if match is not None:
                missing_sources.add(int(match.group(1)))
            else:
                match = re.match(r"^binary:(\d+)$", release_id)
                if match is not None:
                    missing_binaries.add(int(match.group(1)))
        for spr in load(SourcePackageRelease, missing_sources):
            releases_by_id["source:%d" % spr.id] = spr
        for bpr in load(BinaryPackageRelease, missing_binaries):
            releases_by_id["binary:%d" % bpr.id] = bpr

        # Work out the publication files and publications that each path
        # belongs to (usually just one, but there are cases where one file
        # may be shared among multiple releases, such as .orig.tar.* files
        # in Debian-format source packages).
        pub_files_by_path = defaultdict(set)
        pubs_by_path = defaultdict(set)
        for source_name, source_version, release_id, _, _ in plan:
            for pub_file in releases_by_id[release_id].files:
                path = self._diskpool.pathFor(
                    None, source_name, source_version, pub_file
                )
                pub_files_by_path[path].add(pub_file)
                if release_id in pubs_by_id:
                    pubs_by_path[path].update(pubs_by_id[release_id])

        root_path = ArtifactoryPath(self._config.archiveroot)
        for source_name, source_version, _, path, properties in plan:
            full_path = root_path / path
            # For now, any of the possible publication files matching this
            # path should do just as well; it's only used to work out the
            # artifact path.  Just to make sure things are deterministic,
            # use the one with the lowest ID.
            pub_file = sorted(
                pub_files_by_path[full_path], key=attrgetter("id")
            )[0]
            # Tell the pool about all the publications that refer to this
            # file, since it may set some properties to describe the union
            # of all of them.
            publications = sorted(
                pubs_by_path.get(full_path, []), key=attrgetter("id")
            )
            # Use the name and version from the first publication if we can,
            # but if there aren't any then fall back to the property values
            # from Artifactory.
            if publications:
                source_name = publications[0].pool_name
                source_version = publications[0].pool_version
            self.log.debug(
                "Updating properties for %s:%s, # publications: %s",
                source_name,
                source_version,
                len(publications),
            )
            self._diskpool.updateProperties(
                source_name,
                source_version,
                pub_file,
                publications,
                old_properties=properties,
            )

    def D_writeReleaseFiles(self, is_careful):
        """Write out the Release files for the provided distribution.

        If is_careful is specified, we include all suites.

        Otherwise we include only suites flagged as true in dirty_suites.
        """
        self.log.debug("* Step D: Generating Release files.")

        archive_file_suites = set()
        for container in getUtility(IArchiveFileSet).getContainersToReap(
            self.archive, container_prefix="release:"
        ):
            distroseries, pocket = self.distro.getDistroSeriesAndPocket(
                container[len("release:") :]
            )
            archive_file_suites.add(distroseries.getSuite(pocket))

        for distroseries in self.distro:
            for pocket in self.archive.getPockets():
                suite = distroseries.getSuite(pocket)
                suite_path = os.path.join(self._config.distsroot, suite)
                release_path = os.path.join(suite_path, "Release")

                if is_careful:
                    if not self.isAllowed(distroseries, pocket):
                        continue
                    # If we were asked for careful Release file generation
                    # but not careful indexing, then we may not have the raw
                    # material needed to generate Release files for all
                    # suites.  Only force those suites that already have
                    # Release files.
                    if file_exists(release_path):
                        self.release_files_needed.add(suite)

                write_release = suite in self.release_files_needed
                if not is_careful:
                    if not self.isDirty(distroseries, pocket):
                        self.log.debug(
                            "Skipping release files for %s/%s"
                            % (distroseries.name, pocket.name)
                        )
                        write_release = False
                    else:
                        self.checkDirtySuiteBeforePublishing(
                            distroseries, pocket
                        )

                if write_release:
                    self._writeSuite(distroseries, pocket)
                elif (
                    suite in archive_file_suites
                    and distroseries.publish_by_hash
                ):
                    # We aren't publishing a new Release file for this
                    # suite, probably because it's immutable, but we still
                    # need to prune by-hash files from it.
                    extra_by_hash_files = {
                        filename: filename
                        for filename in ("Release", "Release.gpg", "InRelease")
                        if file_exists(os.path.join(suite_path, filename))
                    }
                    self._updateByHash(suite, "Release", extra_by_hash_files)

    def _allIndexFiles(self, distroseries):
        """Return all index files on disk for a distroseries.

        For each index file, this yields a tuple of (function to open file
        in uncompressed form, path to file).
        """
        components = self.archive.getComponentsForSeries(distroseries)
        for pocket in self.archive.getPockets():
            suite_name = distroseries.getSuite(pocket)
            for component in components:
                yield gzip.open, get_sources_path(
                    self._config, suite_name, component
                ) + ".gz"
                for arch in distroseries.architectures:
                    if not arch.enabled:
                        continue
                    yield gzip.open, get_packages_path(
                        self._config, suite_name, component, arch
                    ) + ".gz"
                    for subcomp in self.subcomponents:
                        yield gzip.open, get_packages_path(
                            self._config, suite_name, component, arch, subcomp
                        ) + ".gz"

    def _latestNonEmptySeries(self):
        """Find the latest non-empty series in an archive.

        Doing this properly (series with highest version and any active
        publications) is expensive.  However, we just went to the effort of
        publishing everything; so a quick-and-dirty approach is to look
        through what we published on disk.
        """
        for distroseries in self.distro:
            for open_func, index in self._allIndexFiles(distroseries):
                try:
                    with open_func(index) as index_file:
                        if index_file.read(1):
                            return distroseries
                except OSError:
                    pass

    def createSeriesAliases(self):
        """Ensure that any series aliases exist.

        The natural implementation would be to point the alias at
        self.distro.currentseries, but that works poorly for PPAs, where
        it's possible that no packages have been published for the current
        series.  We also don't want to have to go through and republish all
        PPAs when we create a new series.  Thus, we instead do the best we
        can by pointing the alias at the latest series with any publications
        in the archive, which is the best approximation to a development
        series for that PPA.

        This does mean that the published alias might point to an older
        series, then you upload something to the alias and find that the
        alias has now moved to a newer series.  What can I say?  The
        requirements are not entirely coherent for PPAs given that packages
        are not automatically copied forward.
        """
        alias = self.distro.development_series_alias
        if alias is not None:
            current = self._latestNonEmptySeries()
            if current is None:
                return
            for pocket in self.archive.getPockets():
                alias_suite = "%s%s" % (alias, pocketsuffix[pocket])
                current_suite = current.getSuite(pocket)
                current_suite_path = os.path.join(
                    self._config.distsroot, current_suite
                )
                if not os.path.isdir(current_suite_path):
                    continue
                alias_suite_path = os.path.join(
                    self._config.distsroot, alias_suite
                )
                if os.path.islink(alias_suite_path):
                    if os.readlink(alias_suite_path) == current_suite:
                        continue
                elif os.path.isdir(alias_suite_path):
                    # Perhaps somebody did something misguided ...
                    self.log.warning(
                        "Alias suite path %s is a directory!" % alias_suite
                    )
                    continue
                try:
                    os.unlink(alias_suite_path)
                except OSError:
                    pass
                os.symlink(current_suite, alias_suite_path)

    def _writeComponentIndexes(self, distroseries, pocket, component):
        """Write Index files for single distroseries + pocket + component.

        Iterates over all supported architectures and 'sources', no
        support for installer-* yet.
        Write contents using LP info to an extra plain file (Packages.lp
        and Sources.lp .
        """
        suite_name = distroseries.getSuite(pocket)
        self.log.debug(
            "Generate Indexes for %s/%s" % (suite_name, component.name)
        )

        self.log.debug("Generating Sources")

        separate_long_descriptions = False
        # Must match DdtpTarballUpload.shouldInstall.
        if not distroseries.include_long_descriptions:
            # If include_long_descriptions is False, create a Translation-en
            # file.  build_binary_stanza_fields will also omit long
            # descriptions from the Packages.
            separate_long_descriptions = True
            packages = set()
            translation_en = RepositoryIndexFile(
                os.path.join(
                    self._config.distsroot,
                    suite_name,
                    component.name,
                    "i18n",
                    "Translation-en",
                ),
                self._config.temproot,
                distroseries.index_compressors,
            )

        source_index = RepositoryIndexFile(
            get_sources_path(self._config, suite_name, component),
            self._config.temproot,
            distroseries.index_compressors,
        )

        for spp in getUtility(IPublishingSet).getSourcesForPublishing(
            archive=self.archive,
            distroseries=distroseries,
            pocket=pocket,
            component=component,
        ):
            stanza = build_source_stanza_fields(
                spp.sourcepackagerelease, spp.component, spp.section
            )
            source_index.write(stanza.makeOutput().encode("utf-8") + b"\n\n")

        source_index.close()

        for arch in distroseries.architectures:
            if not arch.enabled:
                continue

            arch_path = "binary-%s" % arch.architecturetag

            self.log.debug("Generating Packages for %s" % arch_path)

            indices = {}
            indices[None] = RepositoryIndexFile(
                get_packages_path(self._config, suite_name, component, arch),
                self._config.temproot,
                distroseries.index_compressors,
            )

            for subcomp in self.subcomponents:
                indices[subcomp] = RepositoryIndexFile(
                    get_packages_path(
                        self._config, suite_name, component, arch, subcomp
                    ),
                    self._config.temproot,
                    distroseries.index_compressors,
                )

            for bpp in getUtility(IPublishingSet).getBinariesForPublishing(
                archive=self.archive,
                distroarchseries=arch,
                pocket=pocket,
                component=component,
            ):
                subcomp = FORMAT_TO_SUBCOMPONENT.get(
                    bpp.binarypackagerelease.binpackageformat
                )
                if subcomp not in indices:
                    # Skip anything that we're not generating indices
                    # for, eg. ddebs where publish_debug_symbols is
                    # disabled.
                    continue
                stanza = build_binary_stanza_fields(
                    bpp.binarypackagerelease,
                    bpp.component,
                    bpp.section,
                    bpp.priority,
                    bpp.phased_update_percentage,
                    separate_long_descriptions,
                )
                indices[subcomp].write(
                    stanza.makeOutput().encode("utf-8") + b"\n\n"
                )
                if separate_long_descriptions:
                    # If the (Package, Description-md5) pair already exists
                    # in the set, build_translations_stanza_fields will
                    # return None. Otherwise it will add the pair to
                    # the set and return a stanza to be written to
                    # Translation-en.
                    translation_stanza = build_translations_stanza_fields(
                        bpp.binarypackagerelease, packages
                    )
                    if translation_stanza is not None:
                        translation_en.write(
                            translation_stanza.makeOutput().encode("utf-8")
                            + b"\n\n"
                        )

            for index in indices.values():
                index.close()

        if separate_long_descriptions:
            translation_en.close()

    def checkDirtySuiteBeforePublishing(self, distroseries, pocket):
        """Last check before publishing a dirty suite.

        If the distroseries is stable and the archive doesn't allow updates
        in RELEASE pocket (primary archives) we certainly have a problem,
        better stop.
        """
        if cannot_modify_suite(self.archive, distroseries, pocket):
            raise AssertionError(
                "Oops, tainting RELEASE pocket of %s." % distroseries
            )

    def _getLabel(self):
        """Return the contents of the Release file Label field.

        :return: a text that should be used as the value of the Release file
            'Label' field.
        """
        if self.archive.is_ppa:
            return self.archive.displayname
        elif self.archive.purpose == ArchivePurpose.PARTNER:
            return "Partner archive"
        else:
            return self.distro.displayname

    def _getOrigin(self):
        """Return the contents of the Release file Origin field.

        Primary, Partner and Copy archives use the distribution displayname.
        For PPAs we use a more specific value that follows
        `get_ppa_reference`.

        :return: a text that should be used as the value of the Release file
            'Origin' field.
        """
        # XXX al-maisan, 2008-11-19, bug=299981. If this file is released
        # from a copy archive then modify the origin to indicate so.
        if self.archive.purpose == ArchivePurpose.PARTNER:
            return "Canonical"
        if not self.archive.is_ppa:
            return self.distro.displayname
        return "LP-PPA-%s" % get_ppa_reference(self.archive)

    def _getMetadataOverrides(self):
        """Return the contents of the Release file Metadata overrides field.

        :return: a dictionnary that should be used as the value for various
            keys of the Release file.
        """
        return (
            (self.archive.metadata_overrides or {})
            if self.archive.purpose == ArchivePurpose.PPA
            else {}
        )

    def _getCurrentFiles(self, suite, release_file_name, extra_files):
        # Gather information on entries in the current Release file.
        release_path = os.path.join(
            self._config.distsroot, suite, release_file_name
        )
        with open(release_path) as release_file:
            release_data = Release(release_file)

        extra_data = {}
        for filename, real_filename in extra_files.items():
            hashes = self._readIndexFileHashes(
                suite, filename, real_file_name=real_filename
            )
            if hashes is None:
                continue
            for archive_hash in archive_hashes:
                extra_data.setdefault(archive_hash.apt_name, []).append(
                    hashes[archive_hash.deb822_name]
                )

        suite_dir = os.path.relpath(
            os.path.join(self._config.distsroot, suite), self._config.distsroot
        )
        current_files = {}
        for current_entry in release_data["SHA256"] + extra_data.get(
            "SHA256", []
        ):
            path = os.path.join(suite_dir, current_entry["name"])
            real_name = current_entry.get("real_name", current_entry["name"])
            real_path = os.path.join(suite_dir, real_name)
            full_path = os.path.join(self._config.distsroot, real_path)
            # Release files include entries for uncompressed versions of
            # Packages and Sources files (which don't exist on disk, but
            # allow clients to check them after decompressing) as well as
            # for the compressed versions which do exist on disk.  As a
            # result, it's routine that `full_path` may not exist; we skip
            # those cases silently.
            if os.path.exists(full_path):
                current_files[path] = (
                    int(current_entry["size"]),
                    current_entry["sha256"],
                    real_path,
                )
        return current_files

    def _updateByHash(self, suite, release_file_name, extra_files):
        """Update by-hash files for a suite.

        This takes Release file data which references a set of on-disk
        files, injects any newly-modified files from that set into the
        librarian and the ArchiveFile table, and updates the on-disk by-hash
        directories to be in sync with ArchiveFile.  Any on-disk by-hash
        entries that ceased to be current sufficiently long ago are removed.
        """
        archive_file_set = getUtility(IArchiveFileSet)
        container = "release:%s" % suite

        by_hashes = ByHashes(self._config.distsroot, self.log)
        existing_live_files = {}
        existing_nonlive_files = {}
        reapable_files = set()

        def strip_dists(path):
            assert path.startswith("dists/")
            return path[len("dists/") :]

        # Record all published files from the database.
        db_now = get_transaction_timestamp(IStore(ArchiveFile))
        for db_file in archive_file_set.getByArchive(
            self.archive,
            container=container,
            only_published=True,
            eager_load=True,
        ):
            file_key = (
                strip_dists(db_file.path),
                db_file.library_file.content.sha256,
            )
            # Ensure any subdirectories are registered early on, in case we're
            # about to delete the only file and need to know to prune it.
            by_hashes.registerChild(os.path.dirname(strip_dists(db_file.path)))

            # XXX cjwatson 2022-12-13: This should check
            # db_file.date_superseded instead once that column has been
            # backfilled.
            if db_file.scheduled_deletion_date is None:
                # XXX wgrant 2020-09-16: Once we have
                # ArchiveFile.date_superseded in place, this should be a DB
                # constraint - i.e. there should only be a single
                # non-superseded row for each path/content pair.
                assert file_key not in existing_live_files
                existing_live_files[file_key] = db_file
            else:
                existing_nonlive_files[file_key] = db_file

            if (
                db_file.scheduled_deletion_date is not None
                and db_file.scheduled_deletion_date < db_now
            ):
                # File has expired. Mark it for reaping.
                reapable_files.add(db_file)
            else:
                # File should still be on disk.
                by_hashes.add(strip_dists(db_file.path), db_file.library_file)

        # Record all files from the archive on disk.
        current_files = self._getCurrentFiles(
            suite, release_file_name, extra_files
        )
        new_live_files = {
            (path, sha256) for path, (_, sha256, _) in current_files.items()
        }

        # Schedule the deletion of any ArchiveFiles which are current in the
        # DB but weren't current in the archive this round.
        old_files = [
            af
            for key, af in existing_live_files.items()
            if key not in new_live_files
        ]
        if old_files:
            archive_file_set.scheduleDeletion(
                old_files, timedelta(days=BY_HASH_STAY_OF_EXECUTION)
            )
            for db_file in old_files:
                self.log.debug(
                    "by-hash: Scheduled %s for %s in %s for deletion"
                    % (
                        db_file.library_file.content.sha256,
                        db_file.path,
                        db_file.container,
                    )
                )

        # Ensure that all the current index files are in by-hash and have
        # corresponding ArchiveFiles.
        # XXX cjwatson 2016-03-15: This should possibly use bulk creation,
        # although we can only avoid about a third of the queries since the
        # librarian client has no bulk upload methods.
        for path, (size, sha256, real_path) in current_files.items():
            file_key = (path, sha256)
            full_path = os.path.join(self._config.distsroot, real_path)
            assert os.path.exists(full_path)  # guaranteed by _getCurrentFiles
            # If there isn't a matching live ArchiveFile row, create one.
            if file_key not in existing_live_files:
                with open(full_path, "rb") as fileobj:
                    db_file = archive_file_set.newFromFile(
                        self.archive,
                        container,
                        os.path.join("dists", path),
                        fileobj,
                        size,
                        filenameToContentType(path),
                    )
            # And ensure the by-hash links exist on disk.
            if not by_hashes.known(path, "SHA256", sha256):
                by_hashes.add(
                    path, db_file.library_file, copy_from_path=real_path
                )

        # Remove any files from disk that aren't recorded in the database.
        by_hashes.prune()

        # And mark expired ArchiveFiles as deleted in the DB now that we've
        # pruned them and their directories from disk.
        if reapable_files:
            archive_file_set.markDeleted(reapable_files)
            for db_file in reapable_files:
                self.log.debug(
                    "by-hash: Marked %s for %s in %s as deleted"
                    % (
                        db_file.library_file.content.sha256,
                        db_file.path,
                        db_file.container,
                    )
                )

    def _writeReleaseFile(self, suite, release_data):
        """Write a Release file to the archive (as Release.new).

        :param suite: The name of the suite whose Release file is to be
            written.
        :param release_data: A `debian.deb822.Release` object to write
            to the filesystem.
        """
        release_path = os.path.join(
            self._config.distsroot, suite, "Release.new"
        )
        with open_for_writing(release_path, "wb") as release_file:
            release_data.dump(release_file, "utf-8")

    def _syncTimestamps(self, suite, all_files):
        """Make sure the timestamps on all files in a suite match."""
        location = os.path.join(self._config.distsroot, suite)
        paths = [os.path.join(location, path) for path in all_files]
        paths = [path for path in paths if os.path.exists(path)]
        latest_timestamp = max(os.stat(path).st_mtime for path in paths)
        for path in paths:
            os.utime(path, (latest_timestamp, latest_timestamp))

    def _writeSuite(self, distroseries, pocket):
        """Write out the Release files for the provided suite."""
        # XXX: kiko 2006-08-24: Untested method.
        suite = distroseries.getSuite(pocket)
        suite_dir = os.path.join(self._config.distsroot, suite)
        all_components = [
            comp.name
            for comp in self.archive.getComponentsForSeries(distroseries)
        ]
        all_architectures = [
            a.architecturetag for a in distroseries.enabled_architectures
        ]
        # Core files are those that are normally updated when a suite
        # changes, and which therefore receive special treatment with
        # caching headers on mirrors.
        core_files = set()
        # Extra files are updated occasionally from other sources.  They are
        # still checksummed and indexed, but they do not receive special
        # treatment with caching headers on mirrors.  We must not play any
        # special games with timestamps here, as it will interfere with the
        # "staging" mechanism used to update these files.
        extra_files = set()
        # Extra by-hash files are not listed in the Release file, but we
        # still want to include them in by-hash directories.
        extra_by_hash_files = {}
        for component in all_components:
            self._writeSuiteSource(distroseries, pocket, component, core_files)
            for architecture in all_architectures:
                self._writeSuiteArch(
                    distroseries, pocket, component, architecture, core_files
                )
            self._writeSuiteI18n(distroseries, pocket, component, core_files)
            dep11_dir = os.path.join(suite_dir, component, "dep11")
            try:
                for entry in os.scandir(dep11_dir):
                    if entry.name.startswith(
                        "Components-"
                    ) or entry.name.startswith("icons-"):
                        dep11_path = os.path.join(
                            component, "dep11", entry.name
                        )
                        extra_files.add(remove_suffix(dep11_path))
                        extra_files.add(dep11_path)
            except FileNotFoundError:
                pass
            cnf_dir = os.path.join(suite_dir, component, "cnf")
            try:
                for cnf_file in os.listdir(cnf_dir):
                    if cnf_file.startswith("Commands-"):
                        cnf_path = os.path.join(component, "cnf", cnf_file)
                        extra_files.add(remove_suffix(cnf_path))
                        extra_files.add(cnf_path)
            except FileNotFoundError:
                pass
            oval_dir = os.path.join(suite_dir, component, "oval")
            try:
                for oval_file in os.listdir(oval_dir):
                    if ".oval.xml" in oval_file:
                        oval_path = os.path.join(component, "oval", oval_file)
                        extra_files.add(remove_suffix(oval_path))
                        extra_files.add(oval_path)
            except FileNotFoundError:
                pass
        for architecture in all_architectures:
            for contents_path in get_suffixed_indices(
                "Contents-" + architecture
            ):
                if os.path.exists(os.path.join(suite_dir, contents_path)):
                    extra_files.add(remove_suffix(contents_path))
                    extra_files.add(contents_path)
        all_files = core_files | extra_files

        drsummary = "%s %s " % (
            self.distro.displayname,
            distroseries.displayname,
        )
        if pocket == PackagePublishingPocket.RELEASE:
            drsummary += distroseries.version
        else:
            drsummary += pocket.name.capitalize()

        self.log.debug("Writing Release file for %s" % suite)
        metadata_overrides = self._getMetadataOverrides()
        release_file = Release()
        release_file["Origin"] = metadata_overrides.get(
            "Origin", self._getOrigin()
        )
        release_file["Label"] = metadata_overrides.get(
            "Label", self._getLabel()
        )
        release_file["Suite"] = metadata_overrides.get("Suite", suite).replace(
            "{series}", distroseries.name
        )
        if "Snapshots" in metadata_overrides:
            release_file["Snapshots"] = metadata_overrides["Snapshots"]
        release_file["Version"] = distroseries.version
        release_file["Codename"] = distroseries.name
        release_file["Date"] = datetime.utcnow().strftime(
            "%a, %d %b %Y %k:%M:%S UTC"
        )
        release_file["Architectures"] = " ".join(sorted(all_architectures))
        release_file["Components"] = " ".join(
            reorder_components(all_components)
        )
        release_file["Description"] = drsummary
        if (
            pocket == PackagePublishingPocket.BACKPORTS
            and distroseries.backports_not_automatic
        ) or (
            pocket == PackagePublishingPocket.PROPOSED
            and distroseries.proposed_not_automatic
        ):
            release_file["NotAutomatic"] = "yes"
            release_file["ButAutomaticUpgrades"] = "yes"

        for filename in sorted(all_files):
            hashes = self._readIndexFileHashes(suite, filename)
            if hashes is None:
                continue
            for archive_hash in archive_hashes:
                release_file.setdefault(archive_hash.apt_name, []).append(
                    hashes[archive_hash.deb822_name]
                )

        if distroseries.publish_by_hash and distroseries.advertise_by_hash:
            release_file["Acquire-By-Hash"] = "yes"

        self._writeReleaseFile(suite, release_file)
        core_files.add("Release")
        extra_by_hash_files["Release"] = "Release.new"

        signable_archive = ISignableArchive(self.archive)
        if signable_archive.can_sign:
            # Sign the repository.
            self.log.debug("Signing Release file for %s" % suite)
            for signed_name in signable_archive.signRepository(
                suite, pubconf=self._config, suffix=".new", log=self.log
            ):
                core_files.add(signed_name)
                extra_by_hash_files[signed_name] = signed_name + ".new"
        else:
            # Skip signature if the archive is not set up for signing.
            self.log.debug("No signing key available, skipping signature.")

        if distroseries.publish_by_hash:
            self._updateByHash(suite, "Release.new", extra_by_hash_files)

        for name in ("Release", "Release.gpg", "InRelease"):
            if name in core_files:
                os.rename(
                    os.path.join(suite_dir, "%s.new" % name),
                    os.path.join(suite_dir, name),
                )

        # Make sure all the timestamps match, to make it easier to insert
        # caching headers on mirrors.
        self._syncTimestamps(suite, core_files)

    def _writeSuiteArchOrSource(
        self,
        distroseries,
        pocket,
        component,
        file_stub,
        arch_name,
        arch_path,
        all_series_files,
    ):
        """Write out a Release file for an architecture or source."""
        # XXX kiko 2006-08-24: Untested method.

        suite = distroseries.getSuite(pocket)
        suite_dir = os.path.join(self._config.distsroot, suite)
        self.log.debug(
            "Writing Release file for %s/%s/%s" % (suite, component, arch_path)
        )

        # Now, grab the actual (non-di) files inside each of
        # the suite's architectures
        file_stub = os.path.join(component, arch_path, file_stub)

        for path in get_suffixed_indices(file_stub):
            if os.path.exists(os.path.join(suite_dir, path)):
                all_series_files.add(remove_suffix(path))
                all_series_files.add(path)
        all_series_files.add(os.path.join(component, arch_path, "Release"))

        metadata_overrides = self._getMetadataOverrides()
        release_file = Release()
        release_file["Archive"] = metadata_overrides.get(
            "Suite", suite
        ).replace("{series}", distroseries.name)
        release_file["Version"] = distroseries.version
        release_file["Component"] = component
        release_file["Origin"] = metadata_overrides.get(
            "Origin", self._getOrigin()
        )
        release_file["Label"] = metadata_overrides.get(
            "Label", self._getLabel()
        )
        release_file["Architecture"] = arch_name

        release_path = os.path.join(suite_dir, component, arch_path, "Release")
        with open_for_writing(release_path, "wb") as f:
            release_file.dump(f, "utf-8")

    def _writeSuiteSource(
        self, distroseries, pocket, component, all_series_files
    ):
        """Write out a Release file for a suite's sources."""
        self._writeSuiteArchOrSource(
            distroseries,
            pocket,
            component,
            "Sources",
            "source",
            "source",
            all_series_files,
        )

    def _writeSuiteArch(
        self, distroseries, pocket, component, arch_name, all_series_files
    ):
        """Write out a Release file for an architecture in a suite."""
        suite = distroseries.getSuite(pocket)
        suite_dir = os.path.join(self._config.distsroot, suite)

        file_stub = "Packages"
        arch_path = "binary-" + arch_name

        for subcomp in self.subcomponents:
            # Set up the subcomponent paths.
            sub_path = os.path.join(component, subcomp, arch_path)
            sub_file_stub = os.path.join(sub_path, file_stub)
            for path in get_suffixed_indices(sub_file_stub):
                if os.path.exists(os.path.join(suite_dir, path)):
                    all_series_files.add(remove_suffix(path))
                    all_series_files.add(path)
        self._writeSuiteArchOrSource(
            distroseries,
            pocket,
            component,
            "Packages",
            arch_name,
            arch_path,
            all_series_files,
        )

    def _writeSuiteI18n(
        self, distroseries, pocket, component, all_series_files
    ):
        """Write out an Index file for translation files in a suite."""
        suite = distroseries.getSuite(pocket)
        self.log.debug(
            "Writing Index file for %s/%s/i18n" % (suite, component)
        )

        i18n_subpath = os.path.join(component, "i18n")
        i18n_dir = os.path.join(self._config.distsroot, suite, i18n_subpath)
        i18n_files = set()
        try:
            for entry in os.scandir(i18n_dir):
                if not entry.name.startswith("Translation-"):
                    continue
                i18n_files.add(remove_suffix(entry.name))
                i18n_files.add(entry.name)
        except FileNotFoundError:
            pass
        if not i18n_files:
            # If the i18n directory doesn't exist or is empty, we don't need
            # to index it.
            return

        i18n_index = I18nIndex()
        for i18n_file in sorted(i18n_files):
            hashes = self._readIndexFileHashes(
                suite, i18n_file, subpath=i18n_subpath
            )
            if hashes is None:
                continue
            i18n_index.setdefault("SHA1", []).append(hashes["sha1"])
            # Schedule i18n files for inclusion in the Release file.
            all_series_files.add(os.path.join(i18n_subpath, i18n_file))

        i18n_file_name = os.path.join(i18n_dir, "Index")
        if distroseries.publish_i18n_index:
            with open(i18n_file_name, "wb") as f:
                i18n_index.dump(f, "utf-8")

            # Schedule this for inclusion in the Release file.
            all_series_files.add(os.path.join(component, "i18n", "Index"))
        else:
            if os.path.exists(i18n_file_name):
                os.unlink(i18n_file_name)

    def _readIndexFileHashes(
        self, suite, file_name, subpath=None, real_file_name=None
    ):
        """Read an index file and return its hashes.

        :param suite: Suite name.
        :param file_name: Filename relative to the parent container directory.
        :param subpath: Optional subpath within the suite root.  Generated
            indexes will not include this path.  If omitted, filenames are
            assumed to be relative to the suite root.
        :param real_file_name: The actual filename to open when reading
            data (`file_name` will still be the name used in the returned
            dictionary).  If this is passed, then the returned hash
            component dictionaries will include it in additional "real_name"
            items.
        :return: A dictionary mapping hash field names to dictionaries of
            their components as defined by debian.deb822.Release (e.g.
            {"md5sum": {"md5sum": ..., "size": ..., "name": ...}}), or None
            if the file could not be found.
        """
        open_func = partial(open, mode="rb")
        full_name = os.path.join(
            self._config.distsroot,
            suite,
            subpath or ".",
            real_file_name or file_name,
        )
        if not os.path.exists(full_name):
            if os.path.exists(full_name + ".gz"):
                open_func = gzip.open
                full_name = full_name + ".gz"
            elif os.path.exists(full_name + ".bz2"):
                open_func = bz2.BZ2File
                full_name = full_name + ".bz2"
            elif os.path.exists(full_name + ".xz"):
                open_func = partial(lzma.LZMAFile, format=lzma.FORMAT_XZ)
                full_name = full_name + ".xz"
            else:
                # The file we were asked to write out doesn't exist.
                # Most likely we have an incomplete archive (e.g. no sources
                # for a given distroseries). This is a non-fatal issue.
                self.log.debug("Failed to find " + full_name)
                return None

        hashes = {
            archive_hash.deb822_name: archive_hash.hash_factory()
            for archive_hash in archive_hashes
        }
        size = 0
        with open_func(full_name) as in_file:
            for chunk in iter(lambda: in_file.read(256 * 1024), b""):
                for hashobj in hashes.values():
                    hashobj.update(chunk)
                size += len(chunk)
        ret = {}
        for alg, hashobj in hashes.items():
            digest = hashobj.hexdigest()
            ret[alg] = {alg: digest, "name": file_name, "size": size}
            if real_file_name:
                ret[alg]["real_name"] = real_file_name
        return ret

    def deleteArchive(self):
        """Delete the archive.

        Physically remove the entire archive from disk and set the archive's
        status to DELETED.

        Any errors encountered while removing the archive from disk will
        be caught and an OOPS report generated.
        """
        assert self.archive.is_ppa
        if self.archive.publishing_method != ArchivePublishingMethod.LOCAL:
            raise NotImplementedError(
                "Don't know how to delete archives published using %s"
                % self.archive.publishing_method.title
            )
        self.log.info(
            "Attempting to delete archive '%s/%s' at '%s'."
            % (
                self.archive.owner.name,
                self.archive.name,
                self._config.archiveroot,
            )
        )

        # Set all the publications to DELETED.
        sources = self.archive.getPublishedSources(
            status=active_publishing_status
        )
        getUtility(IPublishingSet).requestDeletion(
            sources,
            removed_by=getUtility(ILaunchpadCelebrities).janitor,
            removal_comment="Removed when deleting archive",
        )

        # Deleting the sources will have killed the corresponding
        # binaries too, but there may be orphaned leftovers (eg. NBS).
        binaries = self.archive.getAllPublishedBinaries(
            status=active_publishing_status
        )
        getUtility(IPublishingSet).requestDeletion(
            binaries,
            removed_by=getUtility(ILaunchpadCelebrities).janitor,
            removal_comment="Removed when deleting archive",
        )

        # Now set dateremoved on any publication that doesn't already
        # have it set, so things can expire from the librarian.
        for pub in self.archive.getPublishedSources(include_removed=False):
            pub.dateremoved = UTC_NOW
        for pub in self.archive.getAllPublishedBinaries(include_removed=False):
            pub.dateremoved = UTC_NOW

        for directory in (self._config.archiveroot, self._config.metaroot):
            if directory is None or not os.path.exists(directory):
                continue
            try:
                shutil.rmtree(directory)
            except (shutil.Error, OSError) as e:
                self.log.warning(
                    "Failed to delete directory '%s' for archive "
                    "'%s/%s'\n%s"
                    % (
                        directory,
                        self.archive.owner.name,
                        self.archive.name,
                        e,
                    )
                )

        self.archive.status = ArchiveStatus.DELETED
        self.archive.publish = False

        # Now that it's gone from disk we can rename the archive to free
        # up the namespace.
        new_name = base_name = "%s-deletedppa" % self.archive.name
        count = 1
        while True:
            try:
                self.archive.owner.getPPAByName(
                    self.archive.distribution, new_name
                )
            except NoSuchPPA:
                break
            new_name = "%s%d" % (base_name, count)
            count += 1
        self.archive.name = new_name
        self.log.info("Renamed deleted archive '%s'.", self.archive.reference)


class DirectoryHash:
    """Represents a directory hierarchy for hashing."""

    def __init__(self, root, tmpdir):
        self.root = root
        self.tmpdir = tmpdir
        self.checksum_hash = []

        for usable in self._usable_archive_hashes:
            csum_path = os.path.join(self.root, usable.dh_name)
            self.checksum_hash.append(
                (
                    csum_path,
                    RepositoryIndexFile(csum_path, self.tmpdir),
                    usable,
                )
            )

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()

    @property
    def _usable_archive_hashes(self):
        for archive_hash in archive_hashes:
            if archive_hash.write_directory_hash:
                yield archive_hash

    @property
    def checksum_paths(self):
        for checksum_path, _, _ in self.checksum_hash:
            yield checksum_path

    def add(self, path):
        """Add a path to be checksummed."""
        hashes = [
            (checksum_file, archive_hash.hash_factory())
            for (_, checksum_file, archive_hash) in self.checksum_hash
        ]
        with open(path, "rb") as in_file:
            for chunk in iter(lambda: in_file.read(256 * 1024), b""):
                for _, hashobj in hashes:
                    hashobj.update(chunk)

        for checksum_file, hashobj in hashes:
            checksum_line = "%s *%s\n" % (
                hashobj.hexdigest(),
                path[len(self.root) + 1 :],
            )
            checksum_file.write(checksum_line.encode("UTF-8"))

    def add_dir(self, path):
        """Recursively add a directory path to be checksummed."""
        for dirpath, _, filenames in os.walk(path):
            for filename in filenames:
                self.add(os.path.join(dirpath, filename))

    def close(self):
        for _, checksum_file, _ in self.checksum_hash:
            checksum_file.close()
