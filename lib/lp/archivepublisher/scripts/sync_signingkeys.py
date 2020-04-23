# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to inject archive keys into signing service."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type


__all__ = [
    'SyncSigningKeysScript',
    ]

import os

from lp.archivepublisher.config import getPubConfig
from lp.services.database.interfaces import IStore
from lp.services.scripts.base import LaunchpadScript
from lp.services.signing.enums import SigningKeyType
from lp.soyuz.model.archive import Archive


class SyncSigningKeysScript(LaunchpadScript):
    description = (
        "Injects into signing services all key files currently in this "
        "machine.")

    def __init__(self, name, dbuser=None, test_args=None):
        super(SyncSigningKeysScript, self).__init__(name, dbuser, test_args)

    def add_my_options(self):
        self.parser.add_option(
            "-l", "--limit", dest="limit", type=int,
            help="How many archives to fetch.")

        self.parser.add_option(
            "-o", "--offset", dest="offset", type=int,
            help="Offset on archives list.")

    def getArchives(self):
        archives = IStore(Archive).find(Archive).order_by(Archive.id)
        start = self.options.offset if self.options.offset else 0
        end = start + self.options.limit if self.options.limit else None
        return archives[start:end]

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
            SigningKeyType.FIT: ("fit.key", "fit.crt"),
        }
        for key_type in SigningKeyType.items:
            files = [os.path.join(dir, f) for f in keys_per_type[key_type]]
            if not all(os.path.exists(f) for f in files):
                del keys_per_type[key_type]
                continue
        return keys_per_type

    def getSeriesPaths(self, archive):
        """Returns the directory of each series containing signing keys.

        :param archive: The Archive object to search for signing keys.
        :return: A dict where keys are DistroSeries objects (or None for the
                 archive's root signing) and the values are the directories
                 where the keys for that series are stored."""
        series_paths = {}
        pubconf = getPubConfig(archive)
        for series in archive.distribution.series:
            path = os.path.join(pubconf.signingroot, series.name)
            if os.path.exists(path):
                series_paths[series] = path
        if os.path.exists(pubconf.signingroot):
            series_paths[None] = pubconf.signingroot
        return series_paths

    def inject(self, archive, key_type, series, priv_key, pub_key):
        pass

    def processArchive(self, archive):
        for series, path in self.getSeriesPaths(archive).items():
            keys_per_type = self.getKeysPerType(path)
            for key_type, (priv_key, pub_key) in keys_per_type.items():
                self.inject(archive, key_type, series, priv_key, pub_key)

    def main(self):
        for archive in self.getArchives():
            self.processArchive(archive)
