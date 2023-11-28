# Copyright 2012-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Celery-specific Job code.

Because celery sets up configuration at import time, code that is not designed
to use Celery may break if this is used.
"""

__all__ = [
    "celery_app",
    "celery_run_job",
    "celery_run_job_ignore_result",
    "find_missing_ready",
    "run_missing_ready",
]

import os
from logging import info
from uuid import uuid4

import transaction
from celery import Celery, Task
from lazr.jobrunner.celerytask import RunJob

from lp.code.model.branchjob import BranchScanJob
from lp.scripts.helpers import TransactionFreeOperation
from lp.services import scripts
from lp.services.config import dbconfig
from lp.services.database.sqlbase import disconnect_stores
from lp.services.features import (
    install_feature_controller,
    make_script_feature_controller,
)
from lp.services.job.model.job import UniversalJobSource
from lp.services.job.runner import BaseJobRunner, celery_enabled
from lp.services.mail.sendmail import set_immediate_mail_delivery

os.environ.setdefault("CELERY_CONFIG_MODULE", "lp.services.job.celeryconfig")

celery_app = Celery()


class CeleryRunJob(RunJob):
    """A Celery task that runs a job."""

    job_source = UniversalJobSource

    def getJobRunner(self):
        """Return a BaseJobRunner, to support customization."""
        return BaseJobRunner()

    def run(self, job_id, dbuser):
        """Run the specified job.

        :param job_id: The job to run, as expected by UniversalJobSource.
            (Job.id, module_name, class_name)
        :param dbuser: The database user to run under.  This should match the
            dbuser specified by the job's config.
        """
        self.dbuser = dbuser
        task_init(dbuser)
        # XXX cjwatson 2022-04-01: We'd normally use `super()` here, but
        # that fails on Python 3.6 (and newer?) because running tasks don't
        # seem to be instances of `CeleryRunJob`; it's not entirely clear
        # why not.  Celery tends to steer users away from class-based tasks
        # these days, so the right answer may be to rethink the interfaces
        # provided by `lazr.jobrunner`.
        RunJob.run(self, job_id)

    def reQueue(self, job_id, fallback_queue):
        self.apply_async(args=(job_id, self.dbuser), queue=fallback_queue)


class CeleryRunJobIgnoreResult(CeleryRunJob):
    """A Celery task that runs a job and ignores its result."""

    ignore_result = True


celery_run_job = celery_app.register_task(CeleryRunJob())
celery_run_job_ignore_result = celery_app.register_task(
    CeleryRunJobIgnoreResult()
)


class FindMissingReady:
    def __init__(self, job_source):
        from lazr.jobrunner.celerytask import list_queued

        self.job_source = job_source
        self.queue_contents = list_queued(celery_app, [job_source.task_queue])
        self.queued_job_ids = {task[1][0][0] for task in self.queue_contents}

    def find_missing_ready(self):
        return [
            job
            for job in self.job_source.iterReady()
            if job.job_id not in self.queued_job_ids
        ]


def find_missing_ready(job_source):
    """Find ready jobs that are not queued."""
    return FindMissingReady(job_source).find_missing_ready()


class PrefixedTask(Task):
    """A Task with more informative task_id defaults."""

    task_id_prefix = None

    def apply_async(
        self,
        args=None,
        kwargs=None,
        task_id=None,
        producer=None,
        link=None,
        link_error=None,
        shadow=None,
        **options,
    ):
        """Create a task_id if none is specified.

        Override the quite generic default task_id with one containing
        the task_id_prefix.

        See also `celery.task.Task.apply_async()`.
        """
        if task_id is None and self.task_id_prefix is not None:
            task_id = "%s_%s" % (self.task_id_prefix, uuid4())
        return super().apply_async(
            args=args,
            kwargs=kwargs,
            task_id=task_id,
            producer=producer,
            link=link,
            link_error=link_error,
            shadow=shadow,
            **options,
        )


@celery_app.task(
    base=PrefixedTask, task_id_prefix="RunMissingReady", ignore_result=True
)
def run_missing_ready(_no_init=False):
    """Task to run any jobs that are ready but not scheduled.

    Currently supports only BranchScanJob.
    :param _no_init: For tests.  If True, do not perform the initialization.
    """
    if not _no_init:
        task_init("run_missing_ready")
    with TransactionFreeOperation():
        count = 0
        for job in find_missing_ready(BranchScanJob):
            if not celery_enabled(job.__class__.__name__):
                continue
            job.extractJobState()
            job.celeryCommitHook(True)
            count += 1
        info("Scheduled %d missing jobs.", count)
        transaction.commit()


needs_zcml = True


def ensure_zcml():
    """Ensure the zcml has been executed for the current process."""
    global needs_zcml
    if not needs_zcml:
        return
    transaction.abort()
    scripts.execute_zcml_for_scripts(use_web_security=False)
    set_immediate_mail_delivery(True)
    needs_zcml = False


def task_init(dbuser):
    """Prepare to run a task.

    :param dbuser: The database user to use for running the task.
    """
    ensure_zcml()
    disconnect_stores()
    dbconfig.override(dbuser=dbuser, isolation_level="read_committed")
    install_feature_controller(make_script_feature_controller("celery"))
