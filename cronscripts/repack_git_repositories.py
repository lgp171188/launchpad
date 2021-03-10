#!/usr/bin/python2 -S
#
# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath

from lp.code.scripts.repackgitrepository import RepackTunableLoop
from lp.services.scripts.base import LaunchpadCronScript


class RepackGitRepository(LaunchpadCronScript):

    def add_my_options(self):
        self.parser.add_option(
            "-n", "--dry-run", action="store_true",
            dest="dry_run", default=False,
            help="Don't commit changes to the DB.")

    def main(self):
        updater = RepackTunableLoop(self.logger, self.options.dry_run)
        updater.run()


if __name__ == '__main__':
    script = RepackGitRepository(
        'repack_git_repositories',  dbuser='branchscanner')
    script.lock_and_run()
