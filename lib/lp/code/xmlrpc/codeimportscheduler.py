# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The code import scheduler XML-RPC API."""

__all__ = [
    "CodeImportSchedulerAPI",
]

import io

import six
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.code.enums import CodeImportResultStatus
from lp.code.interfaces.branch import get_blacklisted_hostnames
from lp.code.interfaces.codeimportjob import (
    ICodeImportJobSet,
    ICodeImportJobWorkflow,
)
from lp.code.interfaces.codeimportscheduler import ICodeImportScheduler
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.webapp import LaunchpadXMLRPCView, canonical_url
from lp.xmlrpc.faults import NoSuchCodeImportJob
from lp.xmlrpc.helpers import return_fault


@implementer(ICodeImportScheduler)
class CodeImportSchedulerAPI(LaunchpadXMLRPCView):
    """See `ICodeImportScheduler`."""

    def getJobForMachine(self, hostname, worker_limit):
        """See `ICodeImportScheduler`."""
        job = getUtility(ICodeImportJobSet).getJobForMachine(
            six.ensure_text(hostname), worker_limit
        )
        if job is not None:
            return job.id
        else:
            return 0

    def _getJob(self, job_id):
        job_set = removeSecurityProxy(getUtility(ICodeImportJobSet))
        job = removeSecurityProxy(job_set.getById(job_id))
        if job is None:
            raise NoSuchCodeImportJob(job_id)
        return job

    # Because you can't use a decorated function as the implementation of a
    # method exported over XML-RPC, the implementations just thunk to an
    # implementation wrapped with @return_fault.

    def getImportDataForJobID(self, job_id):
        """See `ICodeImportScheduler`."""
        return self._getImportDataForJobID(job_id)

    def updateHeartbeat(self, job_id, log_tail):
        """See `ICodeImportScheduler`."""
        return self._updateHeartbeat(job_id, six.ensure_text(log_tail))

    def finishJobID(self, job_id, status_name, log_file):
        """See `ICodeImportScheduler`."""
        return self._finishJobID(
            job_id, six.ensure_text(status_name), log_file
        )

    @return_fault
    def _getImportDataForJobID(self, job_id):
        job = self._getJob(job_id)
        target = job.code_import.target
        return {
            "arguments": job.makeWorkerArguments(),
            "target_url": canonical_url(target),
            "log_file_name": "%s.log"
            % (target.unique_name[1:].replace("/", "-")),
            "blacklisted_hostnames": get_blacklisted_hostnames(),
        }

    @return_fault
    def _updateHeartbeat(self, job_id, log_tail):
        job = self._getJob(job_id)
        workflow = removeSecurityProxy(getUtility(ICodeImportJobWorkflow))
        workflow.updateHeartbeat(job, log_tail)
        return 0

    @return_fault
    def _finishJobID(self, job_id, status_name, log_file):
        job = self._getJob(job_id)
        status = CodeImportResultStatus.items[status_name]
        workflow = removeSecurityProxy(getUtility(ICodeImportJobWorkflow))
        if log_file and log_file.data:
            log_file_name = "%s.log" % (
                job.code_import.target.unique_name[1:].replace("/", "-")
            )
            log_file_alias = getUtility(ILibraryFileAliasSet).create(
                log_file_name,
                len(log_file.data),
                io.BytesIO(log_file.data),
                "text/plain",
            )
        else:
            log_file_alias = None
        workflow.finishJob(job, status, log_file_alias)
