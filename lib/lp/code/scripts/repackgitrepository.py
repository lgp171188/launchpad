# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functions used with the repack Git repositories script."""

__metaclass__ = type

import transaction
from zope.component import getUtility

from lp.code.errors import CannotRepackRepository
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.services.config import config
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.timeout import set_default_timeout_function
from lp.services.webapp.errorlog import globalErrorUtility


class RepackGitRepository(LaunchpadCronScript):
    """Run git repository repack job."""

    def __init__(self, *args, **kwargs):
        super(RepackGitRepository, self).__init__(*args, **kwargs)
        self.failures = {}

    def get_repositories(self):
        return getUtility(
            IGitRepositorySet).getRepositoriesForRepack()

    def repack(self, repo):
        return repo.repackRepository(self.logger)

    def main(self):
        globalErrorUtility.configure(self.name)
        self.logger.info(
            'Requesting automatic git repository repack.')
        set_default_timeout_function(
            lambda: config.request_git_repack.timeout)

        repackable_repos = self.get_repositories()
        counter = 0
        repos_to_repack = len(list(repackable_repos))
        for repo in repackable_repos:
            try:
                self.repack(repo)
                counter += 1
            except CannotRepackRepository as e:
                self.logger.error(
                    'An error occurred while requesting repository repack %s'
                    % e.message)

        self.logger.info(
            'Requested %d automatic git repository repack out of the %d qualifying for repack.'
            % (counter, repos_to_repack))

        transaction.commit()
