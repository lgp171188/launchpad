# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "PPAKeyGenerator",
]

from zope.component import getUtility

from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
)
from lp.services.scripts.base import (
    LaunchpadCronScript,
    LaunchpadScriptFailure,
)
from lp.soyuz.enums import ArchivePurpose
from lp.soyuz.interfaces.archive import IArchiveSet


class PPAKeyGenerator(LaunchpadCronScript):
    usage = "%prog [-A archive-reference]"
    description = "Generate a GPG signing key for PPAs."

    def add_my_options(self):
        self.parser.add_option(
            "-A",
            "--archive",
            help="The reference of the archive whose key should be generated.",
        )
        self.parser.add_option(
            "--copy-archives",
            action="store_true",
            default=False,
            help="Run only over COPY archives.",
        )

    def generateKey(self, archive):
        """Generate a signing key for the given archive."""
        self.logger.info(
            "Generating signing key for %s (%s)"
            % (archive.reference, archive.displayname)
        )
        archive_signing_key = IArchiveGPGSigningKey(archive)
        archive_signing_key.generateSigningKey(log=self.logger)
        self.logger.info("Key %s" % archive.signing_key_fingerprint)

    def main(self):
        """Generate signing keys for the selected PPAs."""
        archive_set = getUtility(IArchiveSet)
        if self.options.archive is not None:
            archive = archive_set.getByReference(self.options.archive)
            if archive is None:
                raise LaunchpadScriptFailure(
                    "No archive named '%s' could be found."
                    % self.options.archive
                )
            if archive.signing_key_fingerprint is not None:
                raise LaunchpadScriptFailure(
                    "%s (%s) already has a signing_key (%s)"
                    % (
                        archive.reference,
                        archive.displayname,
                        archive.signing_key_fingerprint,
                    )
                )
            archives = [archive]
        elif self.options.copy_archives:
            archives = list(
                archive_set.getArchivesPendingSigningKey(
                    purpose=ArchivePurpose.COPY
                )
            )
        else:
            archives = list(archive_set.getArchivesPendingSigningKey())

        for archive in archives:
            self.generateKey(archive)
            self.txn.commit()
