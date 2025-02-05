# Copyright 2009-2013 Canonical Ltd.  This software is licensed under
# the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Publisher script class."""

__all__ = [
    "PublisherScript",
]

from optparse import OptionValueError

from zope.component import getUtility

from lp.registry.interfaces.distribution import IDistributionSet
from lp.services.scripts.base import LaunchpadCronScript
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.interfaces.archive import IArchiveSet


class PublisherScript(LaunchpadCronScript):
    def addDistroOptions(self):
        self.parser.add_option(
            "-d",
            "--distribution",
            dest="distribution",
            metavar="DISTRO",
            default=None,
            help="The distribution to publish.",
        )

        self.parser.add_option(
            "-a",
            "--all-derived",
            action="store_true",
            dest="all_derived",
            default=False,
            help="Publish all Ubuntu-derived distributions.",
        )

    def addBasePublisherOptions(self):
        self.parser.add_option(
            "--archive",
            action="append",
            dest="archives",
            metavar="REFERENCE",
            default=[],
            help="Only run over the archives identified by this reference. "
            "You can specify multiple archives by repeating the option",
        )

        self.parser.add_option(
            "--exclude",
            action="append",
            dest="excluded_archives",
            metavar="REFERENCE",
            default=[],
            help="Skip the archives identified by this reference in the "
            "publisher run. You can specify multiple archives by repeating "
            "the option",
        )

        self.parser.add_option(
            "--lockfilename",
            dest="lockfilename",
            help="Specify a custom lock filename to be used by the script, "
            "overriding the default.",
        )

    def findSelectedDistro(self):
        """Find the `Distribution` named by the --distribution option.

        Defaults to Ubuntu if no name was given.
        """
        self.logger.debug("Finding distribution object.")
        name = self.options.distribution
        if name is None:
            # Default to publishing Ubuntu.
            name = "ubuntu"
        distro = getUtility(IDistributionSet).getByName(name)
        if distro is None:
            raise OptionValueError("Distribution '%s' not found." % name)
        return distro

    def findDerivedDistros(self):
        """Find all Ubuntu-derived distributions."""
        self.logger.debug("Finding derived distributions.")
        return getUtility(IDistributionSet).getDerivedDistributions()

    def findDistros(self):
        """Find the selected distribution(s)."""
        if self.options.all_derived:
            return self.findDerivedDistros()
        else:
            return [self.findSelectedDistro()]

    def findArchives(self, archive_references, distribution=None):
        """
        Retrieve a list of archives based on the provided references and
        optional distribution.

        Args:
            archive_references (list): A list of archive references to
            retrieve.
            distribution (IDistributionSet, optional): The distribution
            to filter archives by. Defaults to None.

        Returns:
            list: A list of archives that match the provided references and
            distribution.
        """
        if not archive_references:
            return []

        # XXX tushar5526 2025-02-04: Instead of iterating over each reference,
        # it will be better to use bulk queries to reduce the number of SQL
        # calls.
        archives = []
        for reference in archive_references:
            archive = getUtility(IArchiveSet).getByReference(reference)
            if not archive:
                self.logger.warning(
                    "Cannot find the archive with reference: '%s'" % reference
                )
                continue
            if archive.purpose != ArchivePurpose.PPA:
                self.logger.warning(
                    "Skipping '%s'. Archive reference of type '%s' specified. "
                    "Only PPAs are allowed."
                    % (reference, archive.purpose.name)
                )
                continue
            if distribution and archive.distribution != distribution:
                continue
            archives.append(archive)
        return archives
