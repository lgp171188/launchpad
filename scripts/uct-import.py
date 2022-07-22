#!/usr/bin/python3 -S
#
# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import _pythonpath  # noqa: F401

import logging
from pathlib import Path

from lp.bugs.scripts.uctimport import UCTImporter
from lp.services.scripts.base import LaunchpadScript


class UCTImportScript(LaunchpadScript):

    description = (
        "Import bugs into Launchpad from CVE entries in ubuntu-cve-tracker."
    )
    loglevel = logging.INFO

    def main(self):
        if len(self.args) != 1:
            self.parser.error("Please specify a CVE file to import")

        importer = UCTImporter()

        cve_path = Path(self.args[0])
        importer.import_cve_from_file(cve_path)


if __name__ == "__main__":
    script = UCTImportScript("lp.services.scripts.uctimport")
    script.run()
