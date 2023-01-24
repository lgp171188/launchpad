import logging
from pathlib import Path

from lp.app.validators.cve import CVEREF_PATTERN
from lp.bugs.scripts.uct import UCTImporter
from lp.services.scripts.base import LaunchpadScript

logger = logging.getLogger(__name__)


class UCTImportScript(LaunchpadScript):
    """CLI for UCTImport

    Command line options:
    The filter option takes a glob-style pattern.
    Example: `2007*` filters all CVEs from the year 2007.
    """

    usage = "usage: %prog [options] PATH"
    description = (
        "Import bugs into Launchpad from CVE entries in ubuntu-cve-tracker. "
        "PATH is either path to a CVE file, or path to a directory "
        "containing the CVE files."
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
        self.parser.add_option(
            "--filter",
            action="store",
            dest="filter",
            default="*",
            help="Apply given glob-style pattern to filter CVEs.",
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
                for p in path.rglob("CVE-%s" % self.options.filter)
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
