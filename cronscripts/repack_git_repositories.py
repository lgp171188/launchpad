#!/usr/bin/python2 -S
#
# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import _pythonpath  # noqa: F401

from lp.code.scripts.repackgitrepository import RepackTunableLoop
from lp.services.config import config
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.timeout import set_default_timeout_function


class RepackGitRepositories(LaunchpadCronScript):

    def add_my_options(self):
        self.parser.add_option(
            "--dry-run", action="store_true",
            dest="dry_run", default=False,
            help="Reports which repositories would be repacked without "
                 "actually repacking the repositories.")

    def main(self):
        set_default_timeout_function(
            lambda: config.repack_git_repositories.timeout)
        updater = RepackTunableLoop(self.logger, self.options.dry_run)
        updater.run()


if __name__ == '__main__':
    script = RepackGitRepositories(
        'repack_git_repositories',  dbuser='branchscanner')
    script.lock_and_run()
