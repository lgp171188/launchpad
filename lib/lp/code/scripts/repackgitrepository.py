# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Functions used with the repack Git repositories script."""

__metaclass__ = type

import transaction
from zope.component import getUtility

from lp.code.errors import CannotRepackRepository
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.services.config import config
from lp.services.looptuner import TunableLoop, LoopTuner
from lp.services.timeout import set_default_timeout_function
from lp.services.webapp.errorlog import globalErrorUtility


class RepackTunableLoop(TunableLoop):
    tuner_class = LoopTuner

    maximum_chunk_size = 5

    def __init__(self, log, dry_run, abort_time=None):
        super(RepackTunableLoop, self).__init__(log, abort_time)
        self.dry_run = dry_run
        self.start_at = 1

    def findRepackCandidates(self):
        return getUtility(
            IGitRepositorySet).getRepositoriesForRepack()

    def isDone(self):
        return self.findRepackCandidates().is_empty()

    def __call__(self, chunk_size):
        globalErrorUtility.configure(self.name)
        self.logger.info(
            'Requesting automatic git repository repack.')
        set_default_timeout_function(
            lambda: config.request_git_repack.timeout)

        repackable_repos = list(self.findRepackCandidates()[:chunk_size])
        counter = 0
        for repo in repackable_repos:
            try:
                repo.repackRepository()
                counter += 1
            except CannotRepackRepository as e:
                self.logger.error(
                    'An error occurred while requesting repository repack %s'
                    % e.message)
                continue
        self.logger.info(
            'Requested %d automatic git repository repacks out of the %d qualifying for repack.'
            % (counter, repackable_repos))

        self.start_at = repackable_repos[-1].id + 1

        if not self.dry_run:
            transaction.commit()
        else:
            transaction.abort()
