# Copyright 2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for running jobs via Celery."""


from datetime import datetime
import pytz
from time import (
    sleep,
    time,
    )
import transaction
from lazr.delegates import delegates
from zope.interface import implements

from lp.services.config import config
from lp.services.database.lpstorm import IStore
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import (
    IJob,
    IRunnableJob,
    )
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import Job
from lp.services.job.runner import BaseRunnableJob
from lp.services.job.tests import block_on_job
from lp.testing import TestCaseWithFactory
from lp.testing.layers import CeleryJobLayer


class TestJob(BaseRunnableJob):
    """A dummy job."""

    implements(IRunnableJob)
    delegates(IJob, 'job')

    config = config.launchpad

    def __init__(self, job_id=None):
        if job_id is not None:
            store = IStore(Job)
            self.job = store.find(Job, id=job_id)[0]
        else:
            self.job = Job(max_retries=2)

    def run(self):
        pass

    @classmethod
    def makeInstance(cls, job_id):
        return cls(job_id)

    @classmethod
    def getDBClass(cls):
        return cls


class RetryException(Exception):
    """An exception used as a retry exception in TestJobWithRetryError."""


class TestJobWithRetryError(TestJob):
    """A dummy job."""

    retry_error_types = (RetryException, )

    def run(self):
        """Raise a retry exception on the the first attempt to run the job."""
        if self.job.attempt_count < 2:
            # Shorten the lease time: We don't want to wait the
            # default 300 seconds until the job is queued again.
            self.job.lease_expires = datetime.fromtimestamp(
                time() + 1, pytz.timezone('UTC'))
            raise RetryException


class TestRetryJobsViaCelery(TestCaseWithFactory):
    """Tests for running jobs via Celery."""

    layer = CeleryJobLayer

    def test_TestJob(self):
        # TestJob can be run via Celery.
        self.useFixture(FeatureFixture({
            'jobs.celery.enabled_classes': 'TestJob'
        }))
        with block_on_job(self):
            job = TestJob()
            job.celeryRunOnCommit()
            job_id = job.job_id
            transaction.commit()
        store = IStore(Job)
        dbjob = store.find(Job, id=job_id)[0]
        self.assertEqual(JobStatus.COMPLETED, dbjob.status)

    def test_jobs_with_retry_exceptions_are_queued_again(self):
        # A job that raises a retry error is automatically queued
        # and executed again.
        self.useFixture(FeatureFixture({
            'jobs.celery.enabled_classes': 'TestJobWithRetryError'
        }))
        with block_on_job(self):
            job = TestJobWithRetryError()
            job.celeryRunOnCommit()
            job_id = job.job_id
            transaction.commit()
            store = IStore(Job)

            # block_on_job() is not aware of the Celery request
            # issued when the retry exception occurs, but we can
            # check the status of the job in the database.
            def job_finished():
                transaction.abort()
                dbjob = store.find(Job, id=job_id)[0]
                return (
                    dbjob.status == JobStatus.COMPLETED and
                    dbjob.attempt_count == 2)
            count = 0
            while count < 50 and not job_finished():
                sleep(0.2)
                count += 1

        dbjob = store.find(Job, id=job_id)[0]
        self.assertEqual(2, dbjob.attempt_count)
        self.assertEqual(JobStatus.COMPLETED, dbjob.status)
