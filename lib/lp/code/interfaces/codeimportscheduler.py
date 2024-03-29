# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Code import scheduler interfaces."""

__all__ = [
    "ICodeImportScheduler",
    "ICodeImportSchedulerApplication",
]


from zope.interface import Interface

from lp.services.webapp.interfaces import ILaunchpadApplication


class ICodeImportSchedulerApplication(ILaunchpadApplication):
    """Code import scheduler application root."""


class ICodeImportScheduler(Interface):
    """The code import scheduler.

    The code import scheduler is responsible for allocating import jobs to
    machines.  Code import worker machines call the getJobForMachine()
    method when they need more work to do.
    """

    def getJobForMachine(hostname, worker_limit):
        """Get a job to run on the worker 'hostname'.

        This method selects the most appropriate job for the machine,
        mark it as having started on said machine and return its id,
        or 0 if there are no jobs pending.
        """

    def getImportDataForJobID(job_id):
        """Get data about the import with job id `job_id`.

        :return: ``(worker_arguments, target_url, log_file_name)`` where:
            * ``worker_arguments`` are the arguments to pass to the code
              import worker subprocess
            * ``target_url`` is the URL of the import branch/repository
              (only used in OOPS reports)
            * ``log_file_name`` is the name of the log file to create in the
              librarian.
        :raise NoSuchCodeImportJob: if no job with id `job_id` exists.
        """

    def updateHeartbeat(job_id, log_tail):
        """Call `ICodeImportJobWorkflow.updateHeartbeat` for job `job_id`.

        :raise NoSuchCodeImportJob: if no job with id `job_id` exists.
        """

    def finishJobID(job_id, status_name, log_file):
        """Call `ICodeImportJobWorkflow.finishJob` for job `job_id`.

        :param job_id: The ID of the code import job to finish.
        :param status_name: The outcome of the job as the name of a
            `CodeImportResultStatus` item.
        :param log_file: A log file to display for diagnostics, as an
            `xmlrpc.client.Binary` containing the log file data.
        :raise NoSuchCodeImportJob: if no job with id `job_id` exists.
        """
