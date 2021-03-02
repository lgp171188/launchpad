#!/usr/bin/python2 -S
#
# Copyright 2010-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Request git repack for git repositories."""

__metaclass__ = type

import _pythonpath

import transaction
from zope.component import getUtility

from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.timeout import set_default_timeout_function
from lp.services.webapp.errorlog import globalErrorUtility


class RequestGitRepack(LaunchpadCronScript):
    """Run git repository repack job."""

    def __init__(self):
        name = 'request_git_repack'
        dbuser = config.request_git_repack.dbuser
        LaunchpadCronScript.__init__(self, name, dbuser)

    def main(self):
        globalErrorUtility.configure(self.name)
        self.logger.info(
            'Requesting automatic git repository repack.')
        set_default_timeout_function(
            lambda: config.request_git_repack.timeout)
        repackable_repos = getUtility(
            IGitRepository).getRepositoriesForRepack()

        for repo in repackable_repos:
            repo.repackRepository(self.logger)
            repo.date_last_repacked = UTC_NOW

        self.logger.info(
            'Requested %d automatic git repository repack.'
            % len(repackable_repos))

        transaction.commit()

        if __name__ == '__main__':
            script = RequestGitRepack()
            script.lock_and_run()
