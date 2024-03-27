#! /usr/bin/python3
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the sendbranchmail script"""

import os.path

import transaction
from testtools.matchers import MatchesRegex

from lp.code.model.tests.test_branchmergeproposaljobs import (
    make_runnable_incremental_diff_job,
)
from lp.code.model.tests.test_diff import DiffTestCase
from lp.services.config import config
from lp.services.job.interfaces.job import JobStatus
from lp.testing.layers import ZopelessAppServerLayer
from lp.testing.script import run_script


class TestMergeProposalJobScript(DiffTestCase):
    layer = ZopelessAppServerLayer

    def test_script_runs(self):
        """Ensure merge-proposal-jobs script runs."""
        job = make_runnable_incremental_diff_job(self)
        transaction.commit()
        retcode, stdout, stderr = run_script(
            os.path.join(config.root, "cronscripts", "process-job-source.py"),
            args=["--log-twisted", "IBranchMergeProposalJobSource"],
        )
        self.assertEqual(0, retcode)
        self.assertEqual("", stdout)
        matches_expected = MatchesRegex(
            r"INFO    Creating lockfile: /var/lock/launchpad-process-job-"
            r"source-IBranchMergeProposalJobSource.lock\n"
            r"INFO    Running through Twisted.\n"
            r"Log opened.\n"
            r"INFO    Log opened.\n"
            r"ProcessPool stats:\n"
            r"    workers:       0\n"
            r"(.|\n)*"
            r"INFO    ProcessPool stats:\n"
            r"    workers:       0\n"
            r"(.|\n)*"
            r"INFO    Running "
            r"<GENERATE_INCREMENTAL_DIFF job for merge .*?> \(ID %d\).\n"
            r"(.|\n)*"
            r"INFO    STOPPING: \n"
            r"Main loop terminated.\n"
            r"INFO    Main loop terminated.\n"
            r"INFO    Ran 1 GenerateIncrementalDiffJob jobs.\n" % job.job.id
        )
        self.assertThat(stderr, matches_expected)
        self.assertEqual(JobStatus.COMPLETED, job.status)
