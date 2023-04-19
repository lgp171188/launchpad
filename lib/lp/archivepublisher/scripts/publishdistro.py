# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Publisher script class."""

__all__ = [
    "PublishDistro",
]

import os
from filecmp import dircmp
from optparse import OptionValueError
from pathlib import Path
from subprocess import CalledProcessError, check_call

from storm.store import Store
from zope.component import getUtility

from lp.app.errors import NotFoundError
from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.publishing import (
    GLOBAL_PUBLISHER_LOCK,
    cannot_modify_suite,
    getPublisher,
)
from lp.archivepublisher.scripts.base import PublisherScript
from lp.registry.interfaces.distribution import IDistributionSet
from lp.services.config import config
from lp.services.limitedlist import LimitedList
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.services.webapp.adapter import (
    clear_request_started,
    set_request_started,
)
from lp.soyuz.enums import (
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveStatus,
)
from lp.soyuz.interfaces.archive import MAIN_ARCHIVE_PURPOSES, IArchiveSet


def is_ppa_private(ppa):
    """Is `ppa` private?"""
    return ppa.private


def is_ppa_public(ppa):
    """Is `ppa` public?"""
    return not ppa.private


def has_oval_data_changed(incoming_dir, published_dir):
    """Compare the incoming data with the already published one."""
    return bool(dircmp(incoming_dir, published_dir).diff_files)


class PublishDistro(PublisherScript):
    """Distro publisher."""

    lockfilename = GLOBAL_PUBLISHER_LOCK

    def add_my_options(self):
        self.addDistroOptions()

        self.parser.add_option(
            "-C",
            "--careful",
            action="store_true",
            dest="careful",
            default=False,
            help="Turns on all the below careful options.",
        )

        self.parser.add_option(
            "-P",
            "--careful-publishing",
            action="store_true",
            dest="careful_publishing",
            default=False,
            help="Make the package publishing process careful.",
        )

        self.parser.add_option(
            "-D",
            "--careful-domination",
            action="store_true",
            dest="careful_domination",
            default=False,
            help="Make the domination process careful.",
        )

        self.parser.add_option(
            "-A",
            "--careful-apt",
            action="store_true",
            dest="careful_apt",
            default=False,
            help="Make index generation (e.g. apt-ftparchive) careful.",
        )

        self.parser.add_option(
            "--careful-release",
            action="store_true",
            dest="careful_release",
            default=False,
            help="Make the Release file generation process careful.",
        )

        self.parser.add_option(
            "--disable-publishing",
            action="store_false",
            dest="enable_publishing",
            default=True,
            help="Disable the package publishing process.",
        )

        self.parser.add_option(
            "--disable-domination",
            action="store_false",
            dest="enable_domination",
            default=True,
            help="Disable the domination process.",
        )

        self.parser.add_option(
            "--disable-apt",
            action="store_false",
            dest="enable_apt",
            default=True,
            help="Disable index generation (e.g. apt-ftparchive).",
        )

        self.parser.add_option(
            "--disable-release",
            action="store_false",
            dest="enable_release",
            default=True,
            help="Disable the Release file generation process.",
        )

        self.parser.add_option(
            "--include-non-pending",
            action="store_true",
            dest="include_non_pending",
            default=False,
            help=(
                "When publishing PPAs, also include those that do not have "
                "pending publications."
            ),
        )

        self.parser.add_option(
            "-s",
            "--suite",
            metavar="SUITE",
            dest="suite",
            action="append",
            type="string",
            default=[],
            help="The suite to publish",
        )

        self.parser.add_option(
            "--dirty-suite",
            metavar="SUITE",
            dest="dirty_suites",
            action="append",
            default=[],
            help="Consider this suite dirty regardless of publications.",
        )

        self.parser.add_option(
            "-R",
            "--distsroot",
            dest="distsroot",
            metavar="SUFFIX",
            default=None,
            help=(
                "Override the dists path for generation of the PRIMARY and "
                "PARTNER archives only."
            ),
        )

        self.parser.add_option(
            "--ppa",
            action="store_true",
            dest="ppa",
            default=False,
            help="Only run over PPA archives.",
        )

        self.parser.add_option(
            "--private-ppa",
            action="store_true",
            dest="private_ppa",
            default=False,
            help="Only run over private PPA archives.",
        )

        self.parser.add_option(
            "--partner",
            action="store_true",
            dest="partner",
            default=False,
            help="Only run over the partner archive.",
        )

        self.parser.add_option(
            "--copy-archive",
            action="store_true",
            dest="copy_archive",
            default=False,
            help="Only run over the copy archives.",
        )

        self.parser.add_option(
            "--archive",
            dest="archive",
            metavar="REFERENCE",
            help="Only run over the archive identified by this reference.",
        )

    def isCareful(self, option):
        """Is the given "carefulness" option enabled?

        Yes if the option is True, but also if the global "careful" option
        is set.

        :param option: The specific "careful" option to test, e.g.
            `self.options.careful_publishing`.
        :return: Whether the option should be treated as asking us to be
            careful.
        """
        return option or self.options.careful

    def describeCare(self, option):
        """Helper: describe carefulness setting of given option.

        Produces a human-readable string saying whether the option is set
        to careful mode; or "overridden" to careful mode by the global
        "careful" option; or is left in normal mode.
        """
        if self.options.careful:
            return "Careful (Overridden)"
        elif option:
            return "Careful"
        else:
            return "Normal"

    def logOption(self, name, value):
        """Describe the state of `option` to the debug log."""
        self.logger.debug("%14s: %s", name, value)

    def countExclusiveOptions(self):
        """Return the number of exclusive "mode" options that were set.

        In valid use, at most one of them should be set.
        """
        exclusive_options = [
            self.options.partner,
            self.options.ppa,
            self.options.private_ppa,
            self.options.copy_archive,
            self.options.archive,
        ]
        return len(list(filter(None, exclusive_options)))

    def logOptions(self):
        """Dump the selected options to the debug log."""
        if self.countExclusiveOptions() == 0:
            indexing_engine = "Apt-FTPArchive"
        else:
            indexing_engine = "Indexing"
        self.logOption("Distribution", self.options.distribution)
        log_items = [
            ("Publishing", self.options.careful_publishing),
            ("Domination", self.options.careful_domination),
            (indexing_engine, self.options.careful_apt),
            ("Release", self.options.careful_release),
        ]
        for name, option in log_items:
            self.logOption(name, self.describeCare(option))

    def validateOptions(self):
        """Check given options for user interface violations."""
        if len(self.args) > 0:
            raise OptionValueError(
                "publish-distro takes no arguments, only options."
            )
        if self.countExclusiveOptions() > 1:
            raise OptionValueError(
                "Can only specify one of partner, ppa, private-ppa, "
                "copy-archive, archive."
            )

        if self.options.all_derived and self.options.distribution is not None:
            raise OptionValueError(
                "Specify --distribution or --all-derived, but not both."
            )

        for_ppa = self.options.ppa or self.options.private_ppa
        if for_ppa and self.options.distsroot:
            raise OptionValueError(
                "We should not define 'distsroot' in PPA mode!",
            )

    def findSuite(self, distribution, suite):
        """Find the named `suite` in the selected `Distribution`.

        :param suite: The suite name to look for.
        :return: A tuple of distroseries and pocket.
        """
        try:
            series, pocket = distribution.getDistroSeriesAndPocket(suite)
        except NotFoundError as e:
            raise OptionValueError(e)
        return series, pocket

    def findAllowedSuites(self, distribution):
        """Find the selected suite(s)."""
        suites = set()
        for suite in self.options.suite:
            series, pocket = self.findSuite(distribution, suite)
            suites.add(series.getSuite(pocket))
        return suites

    def findExplicitlyDirtySuites(self, archive):
        """Find the suites that have been explicitly marked as dirty."""
        for suite in self.options.dirty_suites:
            yield self.findSuite(archive.distribution, suite)
        if archive.dirty_suites is not None:
            for suite in archive.dirty_suites:
                try:
                    yield archive.distribution.getDistroSeriesAndPocket(suite)
                except NotFoundError:
                    self.logger.exception(
                        "Failed to parse dirty suite '%s' for archive '%s'"
                        % (suite, archive.reference)
                    )

    def getCopyArchives(self, distribution):
        """Find copy archives for the selected distribution."""
        copy_archives = list(
            getUtility(IArchiveSet).getArchivesForDistribution(
                distribution, purposes=[ArchivePurpose.COPY]
            )
        )
        if copy_archives == []:
            raise LaunchpadScriptFailure("Could not find any COPY archives")
        return copy_archives

    def getPPAs(self, distribution):
        """Find private package archives for the selected distribution."""
        if (
            self.isCareful(self.options.careful_publishing)
            or self.options.include_non_pending
        ):
            return distribution.getAllPPAs()
        else:
            return distribution.getPendingPublicationPPAs()

    def getTargetArchives(self, distribution):
        """Find the archive(s) selected by the script's options."""
        if self.options.archive:
            archive = getUtility(IArchiveSet).getByReference(
                self.options.archive
            )
            if archive.distribution == distribution:
                return [archive]
            else:
                return []
        elif self.options.partner:
            return [distribution.getArchiveByComponent("partner")]
        elif self.options.ppa:
            return filter(is_ppa_public, self.getPPAs(distribution))
        elif self.options.private_ppa:
            return filter(is_ppa_private, self.getPPAs(distribution))
        elif self.options.copy_archive:
            return self.getCopyArchives(distribution)
        else:
            return [distribution.main_archive]

    def getPublisher(self, distribution, archive, allowed_suites):
        """Get a publisher for the given options."""
        if archive.purpose in MAIN_ARCHIVE_PURPOSES:
            description = "%s %s" % (distribution.name, archive.displayname)
            # Only let the primary/partner archives override the distsroot.
            distsroot = self.options.distsroot
        else:
            description = archive.archive_url
            distsroot = None

        self.logger.info("Processing %s", description)
        return getPublisher(archive, allowed_suites, self.logger, distsroot)

    def deleteArchive(self, archive, publisher):
        """Ask `publisher` to delete `archive`."""
        if (
            archive.purpose == ArchivePurpose.PPA
            and archive.publishing_method == ArchivePublishingMethod.LOCAL
        ):
            publisher.deleteArchive()
            return True
        else:
            # Other types of archives do not currently support deletion.
            self.logger.warning(
                "Deletion of %s skipped: operation not supported on %s",
                archive.displayname,
                archive.purpose.title,
            )
            return False

    def publishArchive(self, archive, publisher):
        """Ask `publisher` to publish `archive`.

        Commits transactions along the way.
        """
        publishing_method = archive.publishing_method

        for distroseries, pocket in self.findExplicitlyDirtySuites(archive):
            if not cannot_modify_suite(archive, distroseries, pocket):
                publisher.markSuiteDirty(distroseries, pocket)
        if archive.dirty_suites is not None:
            # Clear the explicit dirt indicator before we start doing
            # time-consuming publishing, which might race with an
            # Archive.markSuiteDirty call.
            archive.dirty_suites = None
            self.txn.commit()

        publisher.setupArchiveDirs()
        if self.options.enable_publishing:
            publisher.A_publish(
                self.isCareful(self.options.careful_publishing)
            )
            self.txn.commit()

        if self.options.enable_domination:
            # Flag dirty pockets for any outstanding deletions.
            publisher.A2_markPocketsWithDeletionsDirty()
            publisher.B_dominate(
                self.isCareful(self.options.careful_domination)
            )
            self.txn.commit()

        if self.options.enable_apt:
            careful_indexing = self.isCareful(self.options.careful_apt)
            if publishing_method == ArchivePublishingMethod.LOCAL:
                # The primary and copy archives use apt-ftparchive to
                # generate the indexes, everything else uses the newer
                # internal LP code.
                if archive.purpose in (
                    ArchivePurpose.PRIMARY,
                    ArchivePurpose.COPY,
                ):
                    publisher.C_doFTPArchive(careful_indexing)
                else:
                    publisher.C_writeIndexes(careful_indexing)
            elif publishing_method == ArchivePublishingMethod.ARTIFACTORY:
                publisher.C_updateArtifactoryProperties(careful_indexing)
            else:
                raise AssertionError(
                    "Unhandled publishing method: %r" % publishing_method
                )
            self.txn.commit()

        if (
            self.options.enable_release
            and publishing_method == ArchivePublishingMethod.LOCAL
        ):
            publisher.D_writeReleaseFiles(
                self.isCareful(
                    self.options.careful_apt or self.options.careful_release
                )
            )
            # The caller will commit this last step.

        if (
            self.options.enable_apt
            and publishing_method == ArchivePublishingMethod.LOCAL
        ):
            publisher.createSeriesAliases()

    def processArchive(self, archive_id, reset_store=True):
        set_request_started(
            request_statements=LimitedList(10000),
            txn=self.txn,
            enable_timeout=False,
        )
        try:
            archive = getUtility(IArchiveSet).get(archive_id)
            distribution = archive.distribution
            allowed_suites = self.findAllowedSuites(distribution)
            if archive.status == ArchiveStatus.DELETING:
                publisher = self.getPublisher(
                    distribution, archive, allowed_suites
                )
                work_done = self.deleteArchive(archive, publisher)
            elif archive.can_be_published:
                publisher = self.getPublisher(
                    distribution, archive, allowed_suites
                )
                self.publishArchive(archive, publisher)
                work_done = True
            else:
                work_done = False
        finally:
            clear_request_started()

        if work_done:
            self.txn.commit()
            if reset_store:
                # Reset the store after processing each dirty archive, as
                # otherwise the process of publishing large archives can
                # accumulate a large number of alive objects in the Storm
                # store and cause performance problems.
                Store.of(archive).reset()

    def rsyncOVALData(self):
        # Ensure that the rsync paths have a trailing slash.
        rsync_src = os.path.join(
            config.archivepublisher.oval_data_rsync_endpoint, ""
        )
        rsync_dest = os.path.join(config.archivepublisher.oval_data_root, "")
        rsync_command = [
            "/usr/bin/rsync",
            "-a",
            "-q",
            "--timeout={}".format(
                config.archivepublisher.oval_data_rsync_timeout
            ),
            "--delete",
            "--delete-after",
            rsync_src,
            rsync_dest,
        ]
        try:
            self.logger.info(
                "Attempting to rsync the OVAL data from '%s' to '%s'",
                rsync_src,
                rsync_dest,
            )
            check_call(rsync_command)
        except CalledProcessError:
            self.logger.exception(
                "Failed to rsync OVAL data from '%s' to '%s'",
                rsync_src,
                rsync_dest,
            )
            raise

    def checkForUpdatedOVALData(self):
        """Compare the published OVAL files with the incoming one."""
        start_dir = Path(config.archivepublisher.oval_data_root)
        for owner_path in start_dir.iterdir():
            for distribution_path in owner_path.iterdir():
                distribution = getUtility(IDistributionSet).getByName(
                    distribution_path.name
                )
                for archive_path in start_dir.iterdir():
                    for suite_path in archive_path.iterdir():
                        incoming_dir = suite_path / "main"
                        series, pocket = self.findSuite(
                            distribution=distribution, suite=suite_path.name
                        )
                        archive = getUtility(IArchiveSet).getByReference(
                            "~"
                            + owner_path.name
                            + "/"
                            + distribution_path.name
                            + "/"
                            + archive_path.name
                        )
                        published_dir = os.path.join(
                            getPubConfig(archive).distsroot,
                            series,
                            "main",
                            "oval",
                        )
                        if has_oval_data_changed(
                            incoming_dir=incoming_dir,
                            published_dir=published_dir,
                        ):
                            archive.markSuiteDirty(
                                distroseries=distribution.getSeries(series),
                                pocket=pocket,
                            )

    def main(self, reset_store_between_archives=True):
        """See `LaunchpadScript`."""
        self.validateOptions()
        self.logOptions()

        if config.archivepublisher.oval_data_rsync_endpoint:
            self.rsyncOVALData()
            self.checkForUpdatedOVALData()
        else:
            self.logger.info(
                "Skipping the OVAL data sync as no rsync endpoint"
                " has been configured."
            )

        archive_ids = []
        for distribution in self.findDistros():
            for archive in self.getTargetArchives(distribution):
                if archive.distribution != distribution:
                    raise AssertionError(
                        "Archive %s does not match distribution %r"
                        % (archive.reference, distribution)
                    )
                archive_ids.append(archive.id)

        for archive_id in archive_ids:
            self.processArchive(
                archive_id, reset_store=reset_store_between_archives
            )

        self.logger.debug("Ciao")
