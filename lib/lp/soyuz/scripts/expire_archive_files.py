#!/usr/bin/python3
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import absolute_import, print_function, unicode_literals

from storm.expr import (
    And,
    Cast,
    Except,
    Not,
    Or,
    Select,
    )

from lp.registry.model.person import Person
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import (
    Concatenate,
    IsTrue,
    )
from lp.services.librarian.model import LibraryFileAlias
from lp.services.scripts.base import LaunchpadCronScript
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.model.archive import Archive
from lp.soyuz.model.files import (
    BinaryPackageFile,
    SourcePackageReleaseFile,
    )
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
    )

# PPA owners or particular PPAs that we never want to expire.
NEVER_EXPIRE_PPAS = """
bzr
bzr-beta-ppa
bzr-nightly-ppa
canonical-foundations/ubuntu-image
canonical-foundations/uc20-build-ppa
canonical-foundations/uc20-staging-ppa
chelsea-team
ci-train-ppa-service/stable-phone-overlay
dennis-team
elvis-team
fluendo-isv
natick-team
netbook-remix-team
netbook-team
oem-solutions-group
payson
snappy-dev/edge
snappy-dev/image
snappy-dev/tools
transyl
ubuntu-cloud-archive
ubuntu-mobile
wheelbarrow
""".split()

# Particular PPAs (not owners, unlike the never-expire list) that should be
# expired even if they're private.
ALWAYS_EXPIRE_PPAS = """
adobe-isv/flash64
adobe-isv/ppa
kubuntu-ninjas/ppa
landscape/lds-trunk
moblin/moblin-private-beta
""".split()


class ArchiveExpirer(LaunchpadCronScript):
    """Helper class for expiring old PPA binaries.

    Any PPA binary older than 30 days that is superseded or deleted
    will be marked for immediate expiry.
    """
    never_expire = NEVER_EXPIRE_PPAS
    always_expire = ALWAYS_EXPIRE_PPAS

    def add_my_options(self):
        """Add script command line options."""
        self.parser.add_option(
            "-n", "--dry-run", action="store_true",
            dest="dryrun", metavar="DRY_RUN", default=False,
            help="If set, no transactions are committed")
        self.parser.add_option(
            "-e", "--expire-after", action="store", type="int",
            dest="num_days", metavar="DAYS", default=15,
            help=("The number of days after which to expire binaries. "
                  "Must be specified."))

    def _determineExpirables(self, num_days, binary):
        stay_of_execution = Cast('%d days' % num_days, 'interval')
        archive_types = (ArchivePurpose.PPA, ArchivePurpose.PARTNER)

        LFA = LibraryFileAlias
        if binary:
            xPF = BinaryPackageFile
            xPPH = BinaryPackagePublishingHistory
            xPR_join = xPF.binarypackagerelease == xPPH.binarypackagereleaseID
        else:
            xPF = SourcePackageReleaseFile
            xPPH = SourcePackagePublishingHistory
            xPR_join = xPF.sourcepackagerelease == xPPH.sourcepackagereleaseID
        full_archive_name = Concatenate(
            Person.name, Concatenate('/', Archive.name))

        # The subquery here has to repeat the checks for privacy and expiry
        # control on *other* publications that are also done in the main
        # loop for the archive being considered.
        eligible = Select(
            LFA.id,
            where=And(
                xPF.libraryfile == LFA.id,
                xPR_join,
                xPPH.dateremoved < UTC_NOW - stay_of_execution,
                xPPH.archive == Archive.id,
                Archive.purpose.is_in(archive_types),
                LFA.expires == None))
        denied = Select(
            xPF.libraryfileID,
            where=And(
                xPR_join,
                xPPH.archive == Archive.id,
                Archive.owner == Person.id,
                Or(
                    And(
                        Or(
                            Person.name.is_in(self.never_expire),
                            full_archive_name.is_in(self.never_expire)),
                        Archive.purpose == ArchivePurpose.PPA),
                    And(
                        IsTrue(Archive.private),
                        Not(full_archive_name.is_in(self.always_expire))),
                    Not(Archive.purpose.is_in(archive_types)),
                    xPPH.dateremoved > UTC_NOW - stay_of_execution,
                    xPPH.dateremoved == None)))
        return list(self.store.execute(Except(eligible, denied)))

    def determineSourceExpirables(self, num_days):
        """Return expirable libraryfilealias IDs."""
        return self._determineExpirables(num_days=num_days, binary=False)

    def determineBinaryExpirables(self, num_days):
        """Return expirable libraryfilealias IDs."""
        return self._determineExpirables(num_days=num_days, binary=True)

    def main(self):
        self.logger.info('Starting the PPA binary expiration')
        num_days = self.options.num_days
        self.logger.info("Expiring files up to %d days ago" % num_days)

        self.store = IStore(Archive)

        lfa_ids = self.determineSourceExpirables(num_days)
        lfa_ids.extend(self.determineBinaryExpirables(num_days))
        batch_count = 0
        batch_limit = 500
        for id in lfa_ids:
            self.logger.info("Expiring libraryfilealias %s" % id)
            self.store.execute("""
                UPDATE libraryfilealias
                SET expires = CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
                WHERE id = %s
                """ % id)
            batch_count += 1
            if batch_count % batch_limit == 0:
                if self.options.dryrun:
                    self.logger.info(
                        "%s done, not committing (dryrun mode)" % batch_count)
                    self.txn.abort()
                else:
                    self.logger.info(
                        "%s done, committing transaction" % batch_count)
                    self.txn.commit()

        if self.options.dryrun:
            self.txn.abort()
        else:
            self.txn.commit()

        self.logger.info('Finished PPA binary expiration')
