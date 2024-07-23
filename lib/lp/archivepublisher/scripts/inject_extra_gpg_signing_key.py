# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to inject an extra archive GPG signing key into signing service."""

__all__ = [
    "InjectExtraGPGSigningKeyScript",
]

import os
from datetime import datetime, timezone

from zope.component import getUtility

from lp.services.gpg.interfaces import IGPGHandler
from lp.services.scripts.base import LaunchpadScript, LaunchpadScriptFailure
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import (
    IArchiveSigningKeySet,
    ISigningKeySet,
)
from lp.soyuz.interfaces.archive import IArchiveSet


class InjectExtraGPGSigningKeyScript(LaunchpadScript):
    description = (
        "Injects an extra GPG signing key in this machine for the "
        "specified archive into the signing service."
    )

    def add_my_options(self):
        self.parser.add_option(
            "-A",
            "--archive",
            help=(
                "The reference of the archive to process "
                "Format: ~user/distribution/archive-name. Example: "
                "~user/ubuntu/ppa."
            ),
        )
        self.parser.add_option(
            "-l",
            "--local-keys-directory",
            help="The local directory where keys are found.",
        )
        self.parser.add_option(
            "-f",
            "--fingerprint",
            help=(
                "The fingerprint of the GPG key to inject for "
                "the specified archive."
            ),
        )
        self.parser.add_option(
            "-n",
            "--dry-run",
            action="store_true",
            default=False,
            help=(
                "Report what would be done, but don't actually "
                "inject the key."
            ),
        )

    def getArchive(self):
        """Get the archive for the given archive reference."""
        archive = getUtility(IArchiveSet).getByReference(self.options.archive)
        if archive is None:
            raise LaunchpadScriptFailure(
                f"Archive '{self.options.archive}' could not be found."
            )
        return archive

    def injectGPG(self, archive, secret_key_path):
        """Inject the secret key at the given path into the signing service."""
        with open(secret_key_path, "rb") as key_file:
            secret_key_export = key_file.read()
        gpg_handler = getUtility(IGPGHandler)
        secret_key = gpg_handler.importSecretKey(secret_key_export)
        signing_key_set = getUtility(ISigningKeySet)

        if self.options.dry_run:
            self.logger.info(
                "Would inject signing key with fingerprint '%s' for '%s',",
                SigningKeyType.OPENPGP,
                archive.reference,
            )
        else:
            public_key = gpg_handler.retrieveKey(secret_key.fingerprint)
            now = datetime.now().replace(tzinfo=timezone.utc)
            signing_key = signing_key_set.inject(
                SigningKeyType.OPENPGP,
                secret_key.export(),
                public_key.export(),
                secret_key.uids[0].name,
                now,
            )
            self.logger.info("Injected signing key into the signing service.")
            getUtility(IArchiveSigningKeySet).create(
                archive, None, signing_key
            )
            self.logger.info(
                "Associated the signing key with archive '%s'.",
                archive.reference,
            )
            return signing_key

    def getSigningKey(self, fingerprint):
        return (
            getUtility(ISigningKeySet).get(SigningKeyType.OPENPGP, fingerprint)
            or None
        )

    def isSigningKeyAssociatedWithArchive(self, archive, fingerprint):
        return bool(
            getUtility(IArchiveSigningKeySet).getByArchiveAndFingerprint(
                archive, fingerprint
            )
        )

    def processArchive(self, archive):
        fingerprint = self.options.fingerprint
        existing_signing_key = self.getSigningKey(fingerprint)
        if existing_signing_key is not None:
            self.logger.error(
                "Signing key with fingerprint '%s' exists already.",
                fingerprint,
            )
            if not self.isSigningKeyAssociatedWithArchive(
                archive, fingerprint
            ):
                # If a signing key already in the signing service needs
                # to be associated with more than one archive, this
                # code path will allow doing that, without attempting to
                # inject the same key again.
                self.logger.info(
                    "Signing key with fingerprint '%s' not associated "
                    "with the archive '%s'. Adding the association.",
                    fingerprint,
                    archive.reference,
                )
                getUtility(IArchiveSigningKeySet).create(
                    archive, None, existing_signing_key
                )
            self.logger.error(
                "Aborting key injection into the signing service."
            )
            return
        secret_key_path = os.path.join(
            self.options.local_keys_directory, f"{fingerprint}.gpg"
        )
        if not os.path.exists(secret_key_path):
            self.logger.error(
                "Could not find key file at '%s'.", secret_key_path
            )
            return
        else:
            self.logger.info("Found key file at '%s'.", secret_key_path)
        self.injectGPG(archive, secret_key_path)

    def _validateOptions(self):
        if not self.options.archive:
            raise LaunchpadScriptFailure("Specify an archive.")
        if not self.options.local_keys_directory:
            raise LaunchpadScriptFailure(
                "Specify the directory containing the private keys."
            )
        if not self.options.fingerprint:
            raise LaunchpadScriptFailure(
                "Specify the fingerprint of the GPG key to inject."
            )

    def main(self):
        self._validateOptions()
        archive = self.getArchive()
        if not archive.signing_key_fingerprint:
            self.logger.error(
                "Archive '%s' does not have a signing key generated "
                "by Launchpad yet. Cannot inject an extra key without "
                "an existing key. Aborting.",
                archive.reference,
            )
            return
        self.logger.debug("Processing keys for archive %s.", archive.reference)
        self.processArchive(archive)
        if self.options.dry_run:
            self.logger.info(
                "Aborting the transaction since this is a dry run."
            )
            self.txn.abort()
        else:
            self.logger.info("Archive processed; committing.")
            self.txn.commit()
