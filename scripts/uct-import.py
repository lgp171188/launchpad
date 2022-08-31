#!/usr/bin/python3 -S
#
# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import _pythonpath  # noqa: F401

import logging
from pathlib import Path

from lp.app.validators.cve import CVEREF_PATTERN
from lp.bugs.scripts.uct import UCTImporter
from lp.services.scripts.base import LaunchpadScript

logger = logging.getLogger(__name__)


class UCTImportScript(LaunchpadScript):

    usage = "usage: %prog [options] PATH"
    description = (
        "Import bugs into Launchpad from CVE entries in ubuntu-cve-tracker. "
        "PATH is either path to a CVE file, or path to a directory "
        "containing the CVE files"
    )
    loglevel = logging.INFO

    def add_my_options(self):
        self.parser.add_option(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            default=False,
            help="Don't commit changes to the DB.",
        )

    def main(self):
        if len(self.args) != 1:
            self.parser.error("Please specify a path to import")

        path = Path(self.args[0])
        if path.is_dir():
            logger.info(
                "Importing CVE files from directory: %s", path.resolve()
            )
            cve_paths = sorted(
                p
                for p in path.rglob("CVE-*")
                if p.is_file() and CVEREF_PATTERN.match(p.name)
            )
            if not cve_paths:
                logger.warning("Could not find CVE files in %s", path)
                return
        else:
            cve_paths = [path]

        importer = UCTImporter(dry_run=self.options.dry_run)
        for cve_path in cve_paths:
            importer.import_cve_from_file(cve_path)


if __name__ == "__main__":
    script = UCTImportScript("lp.services.scripts.uctimport")
    script.run()
