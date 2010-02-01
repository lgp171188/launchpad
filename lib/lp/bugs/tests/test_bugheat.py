# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for BugJobs."""

__metaclass__ = type

import transaction
import unittest

from zope.component import getUtility

from canonical.launchpad.scripts.tests import run_script
from canonical.testing import LaunchpadZopelessLayer

from lp.bugs.interfaces.bugjob import ICalculateBugHeatJobSource
from lp.bugs.model.bugheat import CalculateBugHeatJob
from lp.bugs.scripts.bugheat import BugHeatCalculator
from lp.testing import TestCaseWithFactory


class CalculateBugHeatJobTestCase(TestCaseWithFactory):
    """Test case for CalculateBugHeatJob."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(CalculateBugHeatJobTestCase, self).setUp()
        self.bug = self.factory.makeBug()

    def test_run(self):
        # CalculateBugHeatJob.run() sets calculates and sets the heat
        # for a bug.
        job = CalculateBugHeatJob.create(self.bug)
        bug_heat_calculator = BugHeatCalculator(self.bug)

        job.run()
        self.assertEqual(
            bug_heat_calculator.getBugHeat(), self.bug.heat)

    def test_utility(self):
        # CalculateBugHeatJobSource is a utility for acquiring
        # CalculateBugHeatJobs.
        utility = getUtility(ICalculateBugHeatJobSource)
        self.assertTrue(
            ICalculateBugHeatJobSource.providedBy(utility))

    def test_create_only_creates_one(self):
        # If there's already a CalculateBugHeatJob for a bug,
        # CalculateBugHeatJob.create() won't create a new one.
        job = CalculateBugHeatJob.create(self.bug)

        # There will now be one job in the queue.
        self.assertEqual(
            1, len(list(CalculateBugHeatJob.iterReady())))

        new_job = CalculateBugHeatJob.create(self.bug)

        # The two jobs will in fact be the same job.
        self.assertEqual(job, new_job)

        # And the queue will still have a length of 1.
        self.assertEqual(
            1, len(list((CalculateBugHeatJob.iterReady()))))

    def test_cronscript_succeeds(self):
        # The calculate-bug-heat cronscript will run all pending
        # CalculateBugHeatJobs.
        CalculateBugHeatJob.create(self.bug)
        transaction.commit()

        retcode, stdout, stderr = run_script(
            'cronscripts/calculate-bug-heat.py', [],
            expect_returncode=0)
        self.assertEqual('', stdout)
        self.assertIn(
            'INFO    Ran 1 ICalculateBugHeatJobSource jobs.\n', stderr)

    def test_getOopsVars(self):
        # BugJobDerived.getOopsVars() returns the variables to be used
        # when logging an OOPS for a bug job. We test this using
        # CalculateBugHeatJob because BugJobDerived doesn't let us
        # create() jobs.
        job = CalculateBugHeatJob.create(self.bug)
        vars = job.getOopsVars()

        # The Bug ID, BugJob ID and BugJob type will be returned by
        # getOopsVars().
        self.assertIn(('bug_id', self.bug.id), vars)
        self.assertIn(('bug_job_id', job.context.id), vars)
        self.assertIn(('bug_job_type', job.context.job_type.title), vars)


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
