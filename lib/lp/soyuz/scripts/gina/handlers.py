# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Gina db handlers.

Classes to handle and create entries on launchpad db.
"""

__all__ = [
    "ImporterHandler",
    "BinaryPackageHandler",
    "BinaryPackagePublisher",
    "DataSetupError",
    "MultiplePackageReleaseError",
    "NoSourcePackageError",
    "SourcePackageHandler",
    "SourcePackagePublisher",
    "DistroHandler",
]

import io
import os
import re
from pathlib import Path

from storm.exceptions import NotOneError
from storm.expr import Cast, Desc
from zope.component import getUtility

from lp.app.errors import NotFoundError
from lp.archivepublisher.diskpool import poolify
from lp.archiveuploader.changesfile import ChangesFile
from lp.archiveuploader.tagfiles import parse_tagfile
from lp.archiveuploader.utils import determine_binary_file_type
from lp.buildmaster.enums import BuildStatus
from lp.registry.interfaces.person import IPersonSet, PersonCreationRationale
from lp.registry.interfaces.sourcepackage import SourcePackageType
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.registry.model.distribution import Distribution
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.scripts import log
from lp.soyuz.enums import (
    BinaryPackageFormat,
    BinarySourceReferenceType,
    PackagePublishingStatus,
)
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.binarysourcereference import (
    IBinarySourceReferenceSet,
    UnparsableBuiltUsing,
)
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.publishing import (
    IPublishingSet,
    active_publishing_status,
)
from lp.soyuz.interfaces.section import ISectionSet
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagerelease import BinaryPackageRelease
from lp.soyuz.model.distroarchseries import DistroArchSeries
from lp.soyuz.model.files import BinaryPackageFile
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
)
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease
from lp.soyuz.scripts.gina.library import getLibraryAlias
from lp.soyuz.scripts.gina.packages import (
    PoolFileNotFound,
    SourcePackageData,
    get_dsc_path,
    prioritymap,
)


def check_not_in_librarian(files, archive_root, directory):
    to_upload = []
    for fname in files:
        path = os.path.join(archive_root, directory)
        if not os.path.exists(os.path.join(path, fname)):
            # XXX kiko 2005-10-22: Untested
            raise PoolFileNotFound(
                "Package %s not found in archive " "%s" % (fname, path)
            )
        # XXX kiko 2005-10-23: <stub> Until I or someone else completes
        # LibrarianGarbageCollection (the first half of which is
        # awaiting review)
        # if checkLibraryForFile(path, fname):
        #    # XXX kiko 2005-10-23: Untested
        #    raise LibrarianHasFileError('File %s already exists in the '
        #                                'librarian' % fname)
        to_upload.append((fname, path))
    return to_upload


BINARYPACKAGE_EXTENSIONS = {
    BinaryPackageFormat.DEB: ".deb",
    BinaryPackageFormat.UDEB: ".udeb",
    BinaryPackageFormat.RPM: ".rpm",
}


class UnrecognizedBinaryFormat(Exception):
    def __init__(self, fname, *args):
        Exception.__init__(self, *args)
        self.fname = fname

    def __str__(self):
        return "%s is not recognized as a binary file." % self.fname


def getBinaryPackageFormat(fname):
    """Return the BinaryPackageFormat for the given filename.

    >>> getBinaryPackageFormat("mozilla-firefox_0.9_i386.deb").name
    'DEB'
    >>> getBinaryPackageFormat("debian-installer.9_all.udeb").name
    'UDEB'
    >>> getBinaryPackageFormat("network-manager.9_i386.rpm").name
    'RPM'
    """
    for key, value in BINARYPACKAGE_EXTENSIONS.items():
        if fname.endswith(value):
            return key

    raise UnrecognizedBinaryFormat(fname)


class DataSetupError(Exception):
    """Raised when required data is found to be missing in the database"""


class MultiplePackageReleaseError(Exception):
    """
    Raised when multiple package releases of the same version are
    found for a single distribution, indicating database corruption.
    """


class LibrarianHasFileError(MultiplePackageReleaseError):
    """
    Raised when the librarian already contains a file we are trying
    to import. This indicates database corruption.
    """


class MultipleBuildError(MultiplePackageReleaseError):
    """Raised when we have multiple builds for the same package"""


class NoSourcePackageError(Exception):
    """Raised when a Binary Package has no matching Source Package"""


class ImporterHandler:
    """Import Handler class

    This class is used to handle the import process.
    """

    def __init__(
        self,
        ztm,
        distro_name,
        distroseries_name,
        archive_root,
        pocket,
        component_override,
    ):
        self.pocket = pocket
        self.component_override = component_override
        self.ztm = ztm

        self.distro = self._get_distro(distro_name)
        self.distroseries = self._get_distroseries(distroseries_name)

        self.arch_map = {}
        self.imported_sources = []
        self.imported_bins = {}

        self.sphandler = SourcePackageHandler(
            distro_name, archive_root, pocket, component_override
        )
        self.bphandler = BinaryPackageHandler(
            self.sphandler, archive_root, pocket
        )

        self.sppublisher = SourcePackagePublisher(
            self.distroseries, pocket, self.component_override
        )
        # This is initialized in ensure_arch
        self.bppublishers = {}

    def commit(self):
        """Commit to the database."""
        self.ztm.commit()

    def abort(self):
        """Rollback changes to the database."""
        self.ztm.abort()

    def ensure_arch(self, archtag):
        """Append retrieved distroarchseries info to a dict."""
        if archtag in self.arch_map:
            return

        # Get distroarchseries and processor from the architecturetag.
        das = (
            IStore(DistroArchSeries)
            .find(
                DistroArchSeries,
                distroseries=self.distroseries,
                architecturetag=archtag,
            )
            .one()
        )
        if not das:
            raise DataSetupError(
                "Error finding distroarchseries for %s/%s"
                % (self.distroseries.name, archtag)
            )

        self.arch_map[archtag] = das

        self.bppublishers[archtag] = BinaryPackagePublisher(
            das, self.pocket, self.component_override
        )
        self.imported_bins[archtag] = []

    #
    # Distro Stuff: Should go to DistroHandler
    #

    def _get_distro(self, name):
        """Return the distro database object by name."""
        distro = IStore(Distribution).find(Distribution, name=name).one()
        if not distro:
            raise DataSetupError("Error finding distribution %r" % name)
        return distro

    def _get_distroseries(self, name):
        """Return the distroseries database object by name."""
        dr = (
            IStore(DistroSeries)
            .find(DistroSeries, name=name, distribution=self.distro)
            .one()
        )
        if not dr:
            raise DataSetupError("Error finding distroseries %r" % name)
        return dr

    #
    # Package stuff
    #

    def preimport_sourcecheck(self, sourcepackagedata):
        """
        Check if this SourcePackageRelease already exists. This can
        happen, for instance, if a source package didn't change over
        releases, or if Gina runs multiple times over the same release
        """
        sourcepackagerelease = self.sphandler.checkSource(
            sourcepackagedata.package,
            sourcepackagedata.version,
            self.distroseries,
        )
        if not sourcepackagerelease:
            log.debug(
                "SPR not found in preimport: %r %r"
                % (sourcepackagedata.package, sourcepackagedata.version)
            )
            return None

        self.publish_sourcepackage(sourcepackagerelease, sourcepackagedata)
        return sourcepackagerelease

    def import_sourcepackage(self, sourcepackagedata):
        """Handler the sourcepackage import process"""
        assert not self.sphandler.checkSource(
            sourcepackagedata.package,
            sourcepackagedata.version,
            self.distroseries,
        )
        handler = self.sphandler.createSourcePackageRelease
        sourcepackagerelease = handler(sourcepackagedata, self.distroseries)

        self.publish_sourcepackage(sourcepackagerelease, sourcepackagedata)
        return sourcepackagerelease

    def preimport_binarycheck(self, archtag, binarypackagedata):
        """
        Check if this BinaryPackageRelease already exists. This can
        happen, for instance, if a binary package didn't change over
        releases, or if Gina runs multiple times over the same release
        """
        binarypackagerelease = self.bphandler.checkBin(
            binarypackagedata, self.arch_map[archtag]
        )
        if not binarypackagerelease:
            log.debug(
                "BPR not found in preimport: %r %r %r"
                % (
                    binarypackagedata.package,
                    binarypackagedata.version,
                    binarypackagedata.architecture,
                )
            )
            return None

        self.publish_binarypackage(
            binarypackagerelease, binarypackagedata, archtag
        )
        return binarypackagerelease

    def import_binarypackage(self, archtag, binarypackagedata):
        """Handler the binarypackage import process"""
        # We know that preimport_binarycheck has run
        assert not self.bphandler.checkBin(
            binarypackagedata, self.arch_map[archtag]
        )

        # Find the sourcepackagerelease that generated this binarypackage.
        distroseries = self.arch_map[archtag].distroseries
        sourcepackage = self.locate_sourcepackage(
            binarypackagedata, distroseries
        )
        if not sourcepackage:
            # XXX kiko 2005-10-23: Untested
            # If the sourcepackagerelease is not imported, not way to import
            # this binarypackage. Warn and giveup.
            raise NoSourcePackageError(
                "No source package %s (%s) found "
                "for %s (%s)"
                % (
                    binarypackagedata.package,
                    binarypackagedata.version,
                    binarypackagedata.source,
                    binarypackagedata.source_version,
                )
            )

        binarypackagerelease = self.bphandler.createBinaryPackage(
            binarypackagedata, sourcepackage, self.arch_map[archtag], archtag
        )
        self.publish_binarypackage(
            binarypackagerelease, binarypackagedata, archtag
        )

    binnmu_re = re.compile(r"^(.+)\.\d+$")
    binnmu_re2 = re.compile(r"^(.+)\.\d+\.\d+$")

    def locate_sourcepackage(self, binarypackagedata, distroseries):
        # This function uses a list of versions to deal with the fact
        # that we may need to munge the version number as we search for
        # bin-only-NMUs. The fast path is dealt with the first cycle of
        # the loop; we only cycle more than once if the source package
        # is really missing.
        versions = [binarypackagedata.source_version]

        is_binnmu = self.binnmu_re2.match(binarypackagedata.source_version)
        if is_binnmu:
            # DEB is jikes-sablevm_1.1.5-1.0.1_all.deb
            #   bin version is 1.1.5-1.0.1
            # DSC is sablevm_1.1.5-1.dsc
            #   src version is 1.1.5-1
            versions.append(is_binnmu.group(1))

        is_binnmu = self.binnmu_re.match(binarypackagedata.source_version)
        if is_binnmu:
            # DEB is jikes-sablevm_1.1.5-1.1_all.deb
            #   bin version is 1.1.5-1.1
            # DSC is sablevm_1.1.5-1.dsc
            #   src version is 1.1.5-1
            versions.append(is_binnmu.group(1))

        for version in versions:
            sourcepackage = self.sphandler.checkSource(
                binarypackagedata.source, version, distroseries
            )
            if sourcepackage:
                return sourcepackage

            # We couldn't find a sourcepackagerelease in the database.
            # Perhaps we can opportunistically pick one out of the archive.
            log.warning(
                "No source package %s (%s) listed for %s (%s), "
                "scrubbing archive..."
                % (
                    binarypackagedata.source,
                    version,
                    binarypackagedata.package,
                    binarypackagedata.version,
                )
            )

            # XXX kiko 2005-11-03: I question whether
            # binarypackagedata.section here is actually correct -- but
            # where can we obtain this information from introspecting
            # the archive?
            sourcepackage = self.sphandler.findUnlistedSourcePackage(
                binarypackagedata.source,
                version,
                binarypackagedata.component,
                binarypackagedata.section,
                distroseries,
            )
            if sourcepackage:
                return sourcepackage

            log.warning(
                "Nope, couldn't find it. Could it be a "
                "bin-only-NMU? Checking version %s" % version
            )

            # XXX kiko 2005-11-03: Testing a third cycle of this loop
            # isn't done.

        return None

    def publish_sourcepackage(self, sourcepackagerelease, sourcepackagedata):
        """Append to the sourcepackagerelease imported list."""
        self.sppublisher.publish(sourcepackagerelease, sourcepackagedata)
        self.imported_sources.append((sourcepackagerelease, sourcepackagedata))

    def publish_binarypackage(
        self, binarypackagerelease, binarypackagedata, archtag
    ):
        self.bppublishers[archtag].publish(
            binarypackagerelease, binarypackagedata
        )
        self.imported_bins[archtag].append(
            (binarypackagerelease, binarypackagedata)
        )


class DistroHandler:
    """Handles distro related information."""

    def __init__(self):
        # Components and sections are cached to avoid redoing the same
        # database queries over and over again.
        self.compcache = {}
        self.sectcache = {}

    def getComponentByName(self, component):
        """Returns a component object by its name."""
        if component in self.compcache:
            return self.compcache[component]

        try:
            ret = getUtility(IComponentSet)[component]
        except NotFoundError:
            raise ValueError("Component %s not found" % component)

        self.compcache[component] = ret
        return ret

    def ensureSection(self, section):
        """Returns a section object by its name. Create and return if it
        doesn't exist.
        """
        if section in self.sectcache:
            return self.sectcache[section]

        ret = getUtility(ISectionSet).ensure(section)
        self.sectcache[section] = ret
        return ret


class SourcePackageHandler:
    """SourcePackageRelease Handler class

    This class has methods to make the sourcepackagerelease access
    on the launchpad db a little easier.
    """

    def __init__(self, distro_name, archive_root, pocket, component_override):
        self.distro_handler = DistroHandler()
        self.distro_name = distro_name
        self.archive_root = archive_root
        self.pocket = pocket
        self.component_override = component_override

    def ensureSourcePackageName(self, name):
        return SourcePackageName.ensure(name)

    def findUnlistedSourcePackage(
        self, sp_name, sp_version, sp_component, sp_section, distroseries
    ):
        """Try to find a sourcepackagerelease in the archive for the
        provided binarypackage data.

        The binarypackage data refers to a source package which we
        cannot find either in the database or in the input data.

        This commonly happens when the source package is no longer part
        of the distribution but a binary built from it is and thus the
        source is not in Sources.gz but is on the disk. This may also
        happen if the package has not built yet.

        If we fail to find it we return None and the binary importer
        will handle this in the same way as if the package simply wasn't
        in the database. I.E. the binary import will fail but the
        process as a whole will continue okay.
        """
        assert not self.checkSource(sp_name, sp_version, distroseries)

        log.debug(
            "Looking for source package %r (%r) in %r"
            % (sp_name, sp_version, sp_component)
        )

        sp_data = self._getSourcePackageDataFromDSC(
            sp_name, sp_version, sp_component, sp_section
        )
        if not sp_data:
            return None

        # Process the package
        sp_data.process_package(self.distro_name, self.archive_root)
        sp_data.ensure_complete()

        spr = self.createSourcePackageRelease(sp_data, distroseries)

        # Publish it because otherwise we'll have problems later.
        # Essentially this routine is only ever called when a binary
        # is encountered for which the source was not found.
        # Now that we have found and imported the source, we need
        # to be sure to publish it because the binary import code
        # assumes that the sources have been imported properly before
        # the binary import is started. Thusly since this source is
        # being imported "late" in the process, we publish it immediately
        # to make sure it doesn't get lost.
        SourcePackagePublisher(
            distroseries, self.pocket, self.component_override
        ).publish(spr, sp_data)
        return spr

    def _getSourcePackageDataFromDSC(
        self, sp_name, sp_version, sp_component, sp_section
    ):
        try:
            dsc_name, dsc_path, sp_component = get_dsc_path(
                sp_name, sp_version, sp_component, self.archive_root
            )
        except PoolFileNotFound:
            # Aah well, no source package in archive either.
            return None

        log.debug(
            "Found a source package for %s (%s) in %s"
            % (sp_name, sp_version, sp_component)
        )
        dsc_contents = parse_tagfile(dsc_path)
        dsc_contents = {
            name.lower(): value for (name, value) in dsc_contents.items()
        }

        # Since the dsc doesn't know, we add in the directory, package
        # component and section
        dsc_contents["directory"] = bytes(
            Path("pool") / poolify(sp_name, sp_component)
        )
        dsc_contents["package"] = sp_name.encode("ASCII")
        dsc_contents["component"] = sp_component.encode("ASCII")
        dsc_contents["section"] = sp_section.encode("ASCII")

        # the dsc doesn't list itself so add it ourselves
        if "files" not in dsc_contents:
            log.error(
                "DSC for %s didn't contain a files entry: %r"
                % (dsc_name, dsc_contents)
            )
            return None
        if not dsc_contents["files"].endswith(b"\n"):
            dsc_contents["files"] += b"\n"
        # XXX kiko 2005-10-21: Why do we hack the md5sum and size of the DSC?
        # Should probably calculate it properly.
        dsc_contents["files"] += ("xxx 000 %s" % dsc_name).encode("ASCII")

        # SourcePackageData requires capitals
        capitalized_dsc = {}
        for k, v in dsc_contents.items():
            capitalized_dsc[k.capitalize()] = v

        return SourcePackageData(**capitalized_dsc)

    def checkSource(self, source, version, distroseries):
        """Check if a sourcepackagerelease is already on lp db.

        Returns the sourcepackagerelease if exists or none if not.
        """
        spname = getUtility(ISourcePackageNameSet).queryByName(source)
        if spname is None:
            return None

        # Check if this sourcepackagerelease already exists using name and
        # version
        return self._getSource(spname, version, distroseries)

    def _getSource(self, sourcepackagename, version, distroseries):
        """Returns a sourcepackagerelease by its name and version."""
        # XXX kiko 2005-11-05: we use the source package publishing tables
        # here, but I think that's a bit flawed. We should have a way of
        # saying "my distroseries overlays the version namespace of that
        # distroseries" and use that to decide on whether we've seen
        # this package before or not. The publishing tables may be
        # wrong, for instance, in the context of proper derivation.

        # Check here to see if this release has ever been published in
        # the distribution, no matter what status.
        SPR = SourcePackageRelease
        SPPH = SourcePackagePublishingHistory
        rows = IStore(SPR).find(
            SPR,
            SPR.sourcepackagename == sourcepackagename,
            Cast(SPR.version, "text") == version,
            SPPH.sourcepackagerelease == SPR.id,
            SPPH.distroseries == DistroSeries.id,
            SPPH.archive == distroseries.main_archive,
            SPPH.sourcepackagename == sourcepackagename,
            DistroSeries.distribution == distroseries.distribution,
        )
        return rows.order_by(
            Desc(SourcePackagePublishingHistory.datecreated)
        ).first()

    def createSourcePackageRelease(self, src, distroseries):
        """Create a SourcePackagerelease and db dependencies if needed.

        Returns the created SourcePackageRelease, or None if it failed.
        """
        displayname, emailaddress = src.maintainer
        comment = "when the %s package was imported into %s" % (
            src.package,
            distroseries.displayname,
        )
        maintainer = getUtility(IPersonSet).ensurePerson(
            emailaddress,
            displayname,
            PersonCreationRationale.SOURCEPACKAGEIMPORT,
            comment=comment,
        )

        # XXX Debonzi 2005-05-16: Check it later.
        #         if src.dsc_signing_key_owner:
        #             key = self.getGPGKey(src.dsc_signing_key,
        #                                  *src.dsc_signing_key_owner)
        #         else:
        key = None

        to_upload = check_not_in_librarian(
            src.files, src.archive_root, src.directory
        )

        # Create the SourcePackageRelease (SPR)
        component = self.distro_handler.getComponentByName(src.component)
        section = self.distro_handler.ensureSection(src.section)
        maintainer_line = "%s <%s>" % (displayname, emailaddress)
        name = self.ensureSourcePackageName(src.package)
        kwargs = {}
        if src._user_defined:
            kwargs["user_defined_fields"] = src._user_defined
        spr = SourcePackageRelease(
            section=section,
            creator=maintainer,
            component=component,
            sourcepackagename=name,
            maintainer=maintainer,
            signing_key_owner=key.owner if key else None,
            signing_key_fingerprint=key.fingerprint if key else None,
            urgency=ChangesFile.urgency_map[src.urgency],
            dateuploaded=src.date_uploaded,
            dsc=src.dsc,
            copyright=src.copyright,
            version=src.version,
            changelog_entry=src.changelog_entry,
            builddepends=src.build_depends,
            builddependsindep=src.build_depends_indep,
            build_conflicts=src.build_conflicts,
            build_conflicts_indep=src.build_conflicts_indep,
            architecturehintlist=src.architecture,
            format=SourcePackageType.DPKG,
            upload_distroseries=distroseries.id,
            dsc_format=src.format,
            dsc_maintainer_rfc822=maintainer_line,
            dsc_standards_version=src.standards_version,
            dsc_binaries=", ".join(src.binaries),
            upload_archive=distroseries.main_archive,
            **kwargs,
        )
        log.info(
            "Source Package Release %s (%s) created" % (name.name, src.version)
        )

        # Upload the changelog to the Librarian
        if src.changelog is not None:
            changelog_lfa = getUtility(ILibraryFileAliasSet).create(
                "changelog",
                len(src.changelog),
                io.BytesIO(src.changelog),
                "text/x-debian-source-changelog",
            )
            spr.changelog = changelog_lfa

        # Insert file into the library and create the
        # SourcePackageReleaseFile entry on lp db.
        for fname, path in to_upload:
            spr.addFile(getLibraryAlias(path, fname))
            log.info("Package file %s included into library" % fname)

        return spr


class SourcePackagePublisher:
    """Class to handle the sourcepackagerelease publishing process."""

    def __init__(self, distroseries, pocket, component_override):
        # Get the distroseries where the sprelease will be published.
        self.distroseries = distroseries
        self.pocket = pocket
        self.component_override = component_override
        self.distro_handler = DistroHandler()

    def publish(self, sourcepackagerelease, spdata):
        """Create the publishing entry on db if does not exist."""
        # Check if the sprelease is already published and if so, just
        # report it.

        if self.component_override:
            component = self.distro_handler.getComponentByName(
                self.component_override
            )
            log.info(
                "Overriding source %s component"
                % sourcepackagerelease.sourcepackagename.name
            )
        else:
            component = self.distro_handler.getComponentByName(
                spdata.component
            )
        archive = self.distroseries.distribution.getArchiveByComponent(
            component.name
        )
        section = self.distro_handler.ensureSection(spdata.section)

        source_publishinghistory = self._checkPublishing(sourcepackagerelease)
        if source_publishinghistory:
            if (
                source_publishinghistory.section,
                source_publishinghistory.component,
            ) == (section, component):
                # If nothing has changed in terms of publication
                # (overrides) we are free to let this one go
                log.info(
                    "SourcePackageRelease already published with no "
                    "changes as %s" % source_publishinghistory.status.title
                )
                return

        entry = getUtility(IPublishingSet).newSourcePublication(
            distroseries=self.distroseries,
            sourcepackagerelease=sourcepackagerelease,
            pocket=self.pocket,
            component=component,
            section=section,
            archive=archive,
        )
        entry.setPublished()
        log.info(
            "Source package %s (%s) published"
            % (
                entry.sourcepackagerelease.sourcepackagename.name,
                entry.sourcepackagerelease.version,
            )
        )

    def _checkPublishing(self, sourcepackagerelease):
        """Query for the publishing entry"""
        return (
            IStore(SourcePackagePublishingHistory)
            .find(
                SourcePackagePublishingHistory,
                SourcePackagePublishingHistory.sourcepackagerelease
                == sourcepackagerelease,
                SourcePackagePublishingHistory.distroseries
                == self.distroseries,
                SourcePackagePublishingHistory.archive
                == self.distroseries.main_archive,
                SourcePackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
            .order_by(SourcePackagePublishingHistory)
            .last()
        )


class BinaryPackageHandler:
    """Handler to deal with binarypackages."""

    def __init__(self, sphandler, archive_root, pocket):
        # Create other needed object handlers.
        self.distro_handler = DistroHandler()
        self.source_handler = sphandler
        self.archive_root = archive_root
        self.pocket = pocket

    def checkBin(self, binarypackagedata, distroarchseries):
        """Returns a binarypackage -- if it exists."""
        binaryname = getUtility(IBinaryPackageNameSet).queryByName(
            binarypackagedata.package
        )
        if binaryname is None:
            # If the binary package's name doesn't exist, don't even
            # bother looking for a binary package.
            return None

        version = binarypackagedata.version
        architecture = binarypackagedata.architecture

        distroseries = distroarchseries.distroseries

        # When looking for binaries, we need to remember that they are
        # shared between distribution releases, so match on the
        # distribution and the architecture tag of the distroarchseries
        # they were built for
        BPR = BinaryPackageRelease
        BPPH = BinaryPackagePublishingHistory
        BPB = BinaryPackageBuild
        clauses = [
            BPPH.archive == distroseries.main_archive,
            BPPH.binarypackagename == binaryname,
            BPPH.binarypackagerelease == BPR.id,
            BPR.binarypackagename == binaryname,
            Cast(BPR.version, "text") == version,
            BPR.build == BPB.id,
            BPB.distro_arch_series == DistroArchSeries.id,
            DistroArchSeries.distroseries == DistroSeries.id,
            DistroSeries.distribution == distroseries.distribution,
        ]

        if architecture != "all":
            clauses.append(DistroArchSeries.architecturetag == architecture)

        try:
            bpr = IStore(BPR).find(BPR, *clauses).config(distinct=True).one()
        except NotOneError:
            # XXX kiko 2005-10-27: Untested
            raise MultiplePackageReleaseError(
                "Found more than one "
                "entry for %s (%s) for %s in %s"
                % (
                    binaryname.name,
                    version,
                    architecture,
                    distroseries.distribution.name,
                )
            )
        return bpr

    def createBinaryPackage(self, bin, srcpkg, distroarchseries, archtag):
        """Create a new binarypackage."""
        fdir, fname = os.path.split(bin.filename)
        to_upload = check_not_in_librarian([fname], bin.archive_root, fdir)
        fname, path = to_upload[0]

        component = self.distro_handler.getComponentByName(bin.component)
        section = self.distro_handler.ensureSection(bin.section)
        architecturespecific = bin.architecture != "all"

        bin_name = getUtility(IBinaryPackageNameSet).ensure(bin.package)
        build = self.ensureBuild(bin, srcpkg, distroarchseries, archtag)

        # Create the binarypackage entry on lp db.
        kwargs = {}
        if bin._user_defined:
            kwargs["user_defined_fields"] = bin._user_defined
        binpkg = BinaryPackageRelease(
            binarypackagename=bin_name,
            component=component,
            version=bin.version,
            description=bin.description,
            summary=bin.summary,
            build=build.id,
            binpackageformat=getBinaryPackageFormat(bin.filename),
            section=section,
            priority=prioritymap[bin.priority],
            shlibdeps=bin.shlibs,
            depends=bin.depends,
            suggests=bin.suggests,
            recommends=bin.recommends,
            conflicts=bin.conflicts,
            replaces=bin.replaces,
            provides=bin.provides,
            pre_depends=bin.pre_depends,
            enhances=bin.enhances,
            breaks=bin.breaks,
            essential=bin.essential,
            installedsize=bin.installed_size,
            architecturespecific=architecturespecific,
            **kwargs,
        )
        try:
            getUtility(IBinarySourceReferenceSet).createFromRelationship(
                binpkg, bin.built_using, BinarySourceReferenceType.BUILT_USING
            )
        except UnparsableBuiltUsing:
            # XXX cjwatson 2020-02-03: It might be nice if we created
            # BinarySourceReference rows at least for those relations that
            # can be parsed and resolved to SourcePackageReleases.  It's not
            # worth spending much time on given that we don't use binary
            # imports much, though.
            pass
        log.info(
            "Binary Package Release %s (%s) created"
            % (bin_name.name, bin.version)
        )

        alias = getLibraryAlias(path, fname)
        BinaryPackageFile(
            binarypackagerelease=binpkg,
            libraryfile=alias,
            filetype=determine_binary_file_type(fname),
        )
        log.info("Package file %s included into library" % fname)

        # Return the binarypackage object.
        return binpkg

    def ensureBuild(self, binary, srcpkg, distroarchseries, archtag):
        """Ensure a build record."""
        distribution = distroarchseries.distroseries.distribution

        # XXX kiko 2006-02-03:
        # This method doesn't work for real bin-only NMUs that are
        # new versions of packages that were picked up by Gina before.
        # The reason for that is that these bin-only NMUs' corresponding
        # source package release will already have been built at least
        # once, and the two checks below will of course blow up when
        # doing it the second time.

        clauses = [
            BinaryPackageBuild.source_package_release == srcpkg,
            BinaryPackageBuild.archive == distribution.main_archive,
            BinaryPackageBuild.distro_arch_series == DistroArchSeries.id,
            DistroArchSeries.distroseries == DistroSeries.id,
            DistroSeries.distribution == distribution,
        ]

        if archtag != "all":
            clauses.append(DistroArchSeries.architecturetag == archtag)

        try:
            build = (
                IStore(BinaryPackageBuild)
                .find(BinaryPackageBuild, *clauses)
                .one()
            )
        except NotOneError:
            # XXX kiko 2005-10-27: Untested.
            raise MultipleBuildError(
                "More than one build was found "
                "for package %s (%s)" % (binary.package, binary.version)
            )

        if build:
            for bpr in build.binarypackages:
                if bpr.binarypackagename.name == binary.package:
                    # XXX kiko 2005-10-27: Untested.
                    raise MultipleBuildError(
                        "Build %d was already found "
                        "for package %s (%s)"
                        % (build.id, binary.package, binary.version)
                    )
        else:
            build = getUtility(IBinaryPackageBuildSet).new(
                srcpkg,
                distroarchseries.main_archive,
                distroarchseries,
                self.pocket,
                status=BuildStatus.FULLYBUILT,
            )
        return build


class BinaryPackagePublisher:
    """Binarypackage publisher class."""

    def __init__(self, distroarchseries, pocket, component_override):
        self.distroarchseries = distroarchseries
        self.pocket = pocket
        self.component_override = component_override
        self.distro_handler = DistroHandler()

    def publish(self, binarypackage, bpdata):
        """Create the publishing entry on db if does not exist."""
        # These need to be pulled from the binary package data, not the
        # binary package release: the data represents data from /this
        # specific distroseries/, whereas the package represents data
        # from when it was first built.
        if self.component_override is not None:
            component = self.distro_handler.getComponentByName(
                self.component_override
            )
            log.info(
                "Overriding binary %s component"
                % binarypackage.binarypackagename.name
            )
        else:
            component = self.distro_handler.getComponentByName(
                bpdata.component
            )
        distribution = self.distroarchseries.distroseries.distribution
        archive = distribution.getArchiveByComponent(component.name)
        section = self.distro_handler.ensureSection(bpdata.section)
        priority = prioritymap[bpdata.priority]

        # Check if the binarypackage is already published and if yes,
        # just report it.
        binpkg_publishinghistory = self._checkPublishing(binarypackage)
        if binpkg_publishinghistory:
            if (
                binpkg_publishinghistory.section,
                binpkg_publishinghistory.priority,
                binpkg_publishinghistory.component,
            ) == (section, priority, component):
                # If nothing has changed in terms of publication
                # (overrides) we are free to let this one go
                log.info(
                    "BinaryPackageRelease already published with no "
                    "changes as %s" % binpkg_publishinghistory.status.title
                )
                return

        BinaryPackagePublishingHistory(
            binarypackagerelease=binarypackage.id,
            binarypackagename=binarypackage.binarypackagename,
            binarypackageformat=binarypackage.binpackageformat,
            component=component.id,
            section=section.id,
            priority=priority,
            distroarchseries=self.distroarchseries.id,
            status=PackagePublishingStatus.PUBLISHED,
            datecreated=UTC_NOW,
            datepublished=UTC_NOW,
            pocket=self.pocket,
            archive=archive,
            sourcepackagename=binarypackage.build.source_package_name,
        )

        log.info(
            "BinaryPackage %s-%s published into %s."
            % (
                binarypackage.binarypackagename.name,
                binarypackage.version,
                self.distroarchseries.architecturetag,
            )
        )

    def _checkPublishing(self, binarypackage):
        """Query for the publishing entry"""
        return (
            IStore(BinaryPackagePublishingHistory)
            .find(
                BinaryPackagePublishingHistory,
                BinaryPackagePublishingHistory.binarypackagerelease
                == binarypackage,
                BinaryPackagePublishingHistory.distroarchseries
                == self.distroarchseries,
                BinaryPackagePublishingHistory.archive
                == self.distroarchseries.main_archive,
                BinaryPackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
            .order_by(BinaryPackagePublishingHistory.datecreated)
            .last()
        )
