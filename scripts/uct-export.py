#!/usr/bin/python3 -S
#
# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
import _pythonpath  # noqa: F401

import logging
from pathlib import Path

from lp.bugs.scripts.uct import UCTExporter
from lp.services.scripts.base import LaunchpadScript


class UCTExportScript(LaunchpadScript):
    usage = "usage: %prog [options] BUG_ID OUTPUT_DIR"
    description = "Export bugs from to CVE entries used in ubuntu-cve-tracker."
    loglevel = logging.INFO

    def main(self):
        if len(self.args) != 2:
            self.parser.error(
                "Please specify the bug ID and the output directory."
            )

        bug_id, output_dir = self.args

        exporter = UCTExporter()
        exporter.export_bug_to_uct_file(int(bug_id), Path(output_dir))


if __name__ == "__main__":
    script = UCTExportScript("lp.services.scripts.uctexport")
    script.run()
