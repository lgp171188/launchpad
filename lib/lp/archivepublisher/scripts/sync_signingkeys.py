# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to inject archive keys into signing service."""

__all__ = [
    "SyncSigningKeysScript",
]

import os
from datetime import datetime, timezone

import transaction
from storm.locals import Store
from zope.component import getUtility

from lp.archivepublisher.config import getPubConfig
from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    ISignableArchive,
)
from lp.archivepublisher.model.publisherconfig import PublisherConfig
from lp.services.database.interfaces import IStore
from lp.services.gpg.interfaces import IGPGHandler
from lp.services.scripts.base import LaunchpadScript, LaunchpadScriptFailure
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import (
    IArchiveSigningKeySet,
    ISigningKeySet,
)
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.model.archive import Archive


class SyncSigningKeysScript(LaunchpadScript):
    description = (
        "Injects into signing services all key files currently in this "
        "machine."
    )

    def add_my_options(self):
        self.parser.add_option(
            "-A",
            "--archive",
            help=(
                "The reference of the archive to process "
                "(default: all archives)."
            ),
        )
        self.parser.add_option(
            "-t",
            "--type",
            help="The type of keys to process (default: all types).",
        )
        self.parser.add_option(
            "--local-keys",
            help="Override directory where local keys are found.",
        )

        self.parser.add_option(
            "-l",
            "--limit",
            dest="limit",
            type=int,
            help="How many archives to fetch.",
        )
        self.parser.add_option(
            "-o",
            "--offset",
            dest="offset",
            type=int,
            help="Offset on archives list.",
        )

        self.parser.add_option(
            "--overwrite",
            action="store_true",
            default=False,
            help="Overwrite keys that already exist on the signing service.",
        )
        self.parser.add_option(
            "-n",
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would be done, but don't actually inject keys.",
        )

    def getArchives(self):
        """Gets the list of archives that should be processed."""
        if self.options.archive is not None:
            archive = getUtility(IArchiveSet).getByReference(
                self.options.archive
            )
            if archive is None:
                raise LaunchpadScriptFailure(
                    "No archive named '%s' could be found."
                    % self.options.archive
                )
            archives = [archive]
        else:
            archives = IStore(Archive).find(
                Archive,
                PublisherConfig.distribution_id == Archive.distribution_id,
            )
            archives = archives.order_by(Archive.id)
        start = self.options.offset if self.options.offset else 0
        end = start + self.options.limit if self.options.limit else None
        return archives[start:end]

    def getKeyTypes(self):
        """Gets the list of key types that should be processed."""
        if self.options.type is not None:
            try:
                key_type = SigningKeyType.getTermByToken(
                    self.options.type
                ).value
            except LookupError:
                raise LaunchpadScriptFailure(
                    "There is no signing key type named '%s'."
                    % self.options.type
                )
            key_types = [key_type]
        else:
            key_types = [
                SigningKeyType.UEFI,
                SigningKeyType.KMOD,
                SigningKeyType.OPAL,
                SigningKeyType.SIPL,
                SigningKeyType.FIT,
                SigningKeyType.OPENPGP,
            ]
        return key_types

    def getKeysPerType(self, dir):
        """Returns the existing key files per type in the given directory.

        :param dir: The directory path to scan for keys
        :return: A dict where keys are SigningKeyTypes and the value is a
                 tuple of (key, cert) files names."""
        keys_per_type = {
            SigningKeyType.UEFI: ("uefi.key", "uefi.crt"),
            SigningKeyType.KMOD: ("kmod.pem", "kmod.x509"),
            SigningKeyType.OPAL: ("opal.pem", "opal.x509"),
            SigningKeyType.SIPL: ("sipl.pem", "sipl.x509"),
            SigningKeyType.FIT: (
                os.path.join("fit", "fit.key"),
                os.path.join("fit", "fit.crt"),
            ),
        }
        found_keys_per_type = {}
        for key_type in self.getKeyTypes():
            if key_type == SigningKeyType.OPENPGP:
                # OpenPGP keys are handled separately.
                continue
            files = [os.path.join(dir, f) for f in keys_per_type[key_type]]
            self.logger.debug("Checking files %s...", ", ".join(files))
            if all(os.path.exists(f) for f in files):
                found_keys_per_type[key_type] = tuple(files)
        return found_keys_per_type

    def getSeriesPaths(self, archive):
        """Returns the directory of each series containing signing keys.

        :param archive: The Archive object to search for signing keys.
        :return: A dict where keys are DistroSeries objects (or None for the
                 archive's root signing) and the values are the directories
                 where the keys for that series are stored."""
        series_paths = {}
        if self.options.local_keys is not None:
            local_keys = self.options.local_keys
        else:
            pubconf = getPubConfig(archive)
            if pubconf is None or pubconf.signingroot is None:
                self.logger.debug(
                    "Skipping %s: no pubconfig or no signing root."
                    % archive.reference
                )
                return {}
            local_keys = pubconf.signingroot
        for series in archive.distribution.series:
            path = os.path.join(local_keys, series.name)
            self.logger.debug("\tChecking if %s exists.", path)
            if os.path.exists(path):
                series_paths[series] = path
        self.logger.debug("\tChecking if root dir %s exists.", local_keys)
        if os.path.exists(local_keys):
            series_paths[None] = local_keys
        return series_paths

    def inject(self, archive, key_type, series, priv_key_path, pub_key_path):
        arch_signing_key_set = getUtility(IArchiveSigningKeySet)
        existing_archive_signing_key = arch_signing_key_set.get(
            key_type, archive, series, exact_match=True
        )
        if existing_archive_signing_key is not None:
            if self.options.overwrite:
                self.logger.info(
                    "Overwriting existing signing key for %s / %s / %s",
                    key_type,
                    archive.reference,
                    series.name if series else None,
                )
                Store.of(existing_archive_signing_key).remove(
                    existing_archive_signing_key
                )
            else:
                self.logger.info(
                    "Signing key for %s / %s / %s already exists",
                    key_type,
                    archive.reference,
                    series.name if series else None,
                )
                return existing_archive_signing_key

        if self.options.dry_run:
            self.logger.info(
                "Would inject signing key for %s / %s / %s",
                key_type,
                archive.reference,
                series.name if series else None,
            )
        else:
            with open(priv_key_path, "rb") as fd:
                private_key = fd.read()
            with open(pub_key_path, "rb") as fd:
                public_key = fd.read()

            now = datetime.now().replace(tzinfo=timezone.utc)
            description = "%s key for %s" % (key_type.name, archive.reference)
            return arch_signing_key_set.inject(
                key_type,
                private_key,
                public_key,
                description,
                now,
                archive,
                earliest_distro_series=series,
            )

    def injectGPG(self, archive, secret_key_path):
        with open(secret_key_path, "rb") as key_file:
            secret_key_export = key_file.read()
        gpg_handler = getUtility(IGPGHandler)
        secret_key = gpg_handler.importSecretKey(secret_key_export)
        signing_key_set = getUtility(ISigningKeySet)
        existing_signing_key = signing_key_set.get(
            SigningKeyType.OPENPGP, secret_key.fingerprint
        )
        if existing_signing_key is not None:
            # There's no point in honouring self.options.overwrite here,
            # because we know we'll just end up with the same fingerprint
            # anyway, and lp-signing will reject attempts to update an
            # existing key with new key material.
            self.logger.info(
                "Signing key for %s / %s already exists",
                SigningKeyType.OPENPGP,
                archive.reference,
            )
            return existing_signing_key

        if self.options.dry_run:
            self.logger.info(
                "Would inject signing key for %s / %s",
                SigningKeyType.OPENPGP,
                archive.reference,
            )
        else:
            public_key = gpg_handler.retrieveKey(secret_key.fingerprint)
            now = datetime.now().replace(tzinfo=timezone.utc)
            return signing_key_set.inject(
                SigningKeyType.OPENPGP,
                secret_key.export(),
                public_key.export(),
                secret_key.uids[0].name,
                now,
            )

    def processArchive(self, archive):
        for series, path in self.getSeriesPaths(archive).items():
            keys_per_type = self.getKeysPerType(path)
            for key_type, (priv_key, pub_key) in keys_per_type.items():
                self.logger.info(
                    "Found key files %s / %s (type=%s, series=%s).",
                    priv_key,
                    pub_key,
                    key_type,
                    series.name if series else None,
                )
                self.inject(archive, key_type, series, priv_key, pub_key)
        if (
            SigningKeyType.OPENPGP in self.getKeyTypes()
            and archive.signing_key is not None
        ):
            secret_key_path = ISignableArchive(archive).getPathForSecretKey(
                archive.signing_key
            )
            if os.path.exists(secret_key_path):
                self.logger.info(
                    "Found key file %s (type=%s).",
                    secret_key_path,
                    SigningKeyType.OPENPGP,
                )
                self.injectGPG(archive, secret_key_path)

    def _maybeCommit(self, count):
        if self.options.dry_run:
            transaction.abort()
        else:
            self.logger.info(
                "%d %s processed; committing.",
                count,
                "archive" if count == 1 else "archives",
            )
            transaction.commit()

    def main(self):
        total = 0
        for i, archive in enumerate(self.getArchives()):
            if i != 0 and i % 100 == 0:
                self._maybeCommit(i)
            self.logger.debug(
                "#%s - Processing keys for archive %s.", i, archive.reference
            )
            self.processArchive(archive)
            total = i + 1
        self._maybeCommit(total)
        self.logger.info("Finished processing archives injections.")
