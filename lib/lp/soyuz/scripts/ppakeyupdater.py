# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "PPAKeyUpdater",
]

from zope.component import getUtility

from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
)
from lp.services.scripts.base import LaunchpadCronScript
from lp.soyuz.interfaces.archive import IArchiveSet


class PPAKeyUpdater(LaunchpadCronScript):
    usage = "%prog [-L]"
    description = (
        "Generate a new 4096-bit RSA signing key for PPAs with only "
        "a 1024-bit RSA signing key."
    )

    def add_my_options(self):
        self.parser.add_option(
            "-L",
            "--limit",
            type=int,
            help="Number of PPAs to process per run.",
        )

    def generate4096BitRSASigningKey(self, archive):
        """Generate a new 4096-bit RSA signing key for the given archive."""
        self.logger.info(
            "Generating 4096-bit RSA signing key for %s (%s)"
            % (archive.reference, archive.displayname)
        )
        archive_signing_key = IArchiveGPGSigningKey(archive)
        archive_signing_key.generate4096BitRSASigningKey(log=self.logger)

    def main(self):
        """
        Generate 4096-bit RSA signing keys for the PPAs with only a 1024-bit
        RSA signing key.
        """
        archive_set = getUtility(IArchiveSet)

        archives = list(
            archive_set.getArchivesWith1024BitRSASigningKey(self.options.limit)
        )

        self.logger.info("Archives to update: %s" % (len(archives)))
        for archive in archives:
            self.generate4096BitRSASigningKey(archive)
            self.txn.commit()

        self.logger.info("Archives updated!")
