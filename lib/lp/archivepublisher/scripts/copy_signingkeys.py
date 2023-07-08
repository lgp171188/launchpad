# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to copy signing keys between archives."""

__all__ = [
    "CopySigningKeysScript",
]

import sys

import transaction
from zope.component import getUtility

from lp.app.errors import NotFoundError
from lp.services.scripts.base import LaunchpadScript, LaunchpadScriptFailure
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.soyuz.interfaces.archive import IArchiveSet


class CopySigningKeysScript(LaunchpadScript):
    usage = "Usage: %prog [options] FROM_ARCHIVE TO_ARCHIVE"
    description = "Copy signing keys between archives."

    def add_my_options(self):
        self.parser.add_option(
            "-t",
            "--key-type",
            help="The type of keys to copy (default: all types).",
        )

        self.parser.add_option("-s", "--series", help="Series name.")

        self.parser.add_option(
            "-n",
            "--dry-run",
            action="store_true",
            default=False,
            help="Report what would be done, but don't actually copy keys.",
        )

        self.parser.add_option(
            "--overwrite",
            action="store_true",
            default=False,
            help="Overwrite existing keys when executing the copy.",
        )

    def getArchive(self, reference):
        archive = getUtility(IArchiveSet).getByReference(reference)
        if archive is None:
            raise LaunchpadScriptFailure(
                "Could not find archive '%s'." % reference
            )
        return archive

    def getKeyTypes(self, name):
        if name is not None:
            try:
                return [SigningKeyType.getTermByToken(name).value]
            except LookupError:
                raise LaunchpadScriptFailure(
                    "There is no signing key type named '%s'." % name
                )
        else:
            return list(SigningKeyType.items)

    def getSeries(self, series_name):
        if series_name is None:
            return None
        try:
            return self.from_archive.distribution[series_name]
        except NotFoundError:
            raise LaunchpadScriptFailure(
                "Could not find series '%s' in %s."
                % (series_name, self.from_archive.distribution.display_name)
            )

    def processOptions(self):
        if len(self.args) != 2:
            self.parser.print_help()
            sys.exit(1)
        self.from_archive = self.getArchive(self.args[0])
        self.to_archive = self.getArchive(self.args[1])
        self.key_types = self.getKeyTypes(self.options.key_type)
        self.series = self.getSeries(self.options.series)

    def copy(
        self, from_archive, to_archive, key_type, series=None, overwrite=False
    ):
        series_name = series.name if series else None
        from_archive_signing_key = getUtility(IArchiveSigningKeySet).get(
            key_type, from_archive, series, exact_match=True
        )
        if from_archive_signing_key is None:
            self.logger.info(
                "No %s signing key for %s / %s",
                key_type,
                from_archive.reference,
                series_name,
            )
            return
        to_archive_signing_key = getUtility(IArchiveSigningKeySet).get(
            key_type, to_archive, series, exact_match=True
        )
        if to_archive_signing_key is not None:
            if not overwrite:
                # If it already exists and we do not force overwrite,
                # abort this signing key copy.
                self.logger.warning(
                    "%s signing key for %s / %s already exists",
                    key_type,
                    to_archive.reference,
                    series_name,
                )
                return
            self.logger.warning(
                "%s signing key for %s / %s being overwritten",
                key_type,
                to_archive.reference,
                series_name,
            )
            to_archive_signing_key.destroySelf()
        self.logger.info(
            "Copying %s signing key %s from %s / %s to %s / %s",
            key_type,
            from_archive_signing_key.signing_key.fingerprint,
            from_archive.reference,
            series_name,
            to_archive.reference,
            series_name,
        )
        getUtility(IArchiveSigningKeySet).create(
            to_archive, series, from_archive_signing_key.signing_key
        )

    def main(self):
        self.processOptions()
        for key_type in self.key_types:
            self.copy(
                self.from_archive,
                self.to_archive,
                key_type,
                series=self.series,
                overwrite=self.options.overwrite,
            )
        if self.options.dry_run:
            self.logger.info("Dry run requested.  Not committing changes.")
            transaction.abort()
        else:
            transaction.commit()
