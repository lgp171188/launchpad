# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Code to talk to the database about what the worker script is doing."""

from __future__ import absolute_import, print_function

__metaclass__ = type
__all__ = []


import os
import tempfile

import six
from six.moves import xmlrpc_client
from twisted.internet import (
    defer,
    error,
    reactor,
    task,
    )
from twisted.python import failure
from twisted.web import xmlrpc

from lp.code.enums import CodeImportResultStatus
from lp.codehosting.codeimport.worker import CodeImportWorkerExitCode
from lp.services.config import config
from lp.services.twistedsupport.processmonitor import (
    ProcessMonitorProtocolWithTimeout,
    )
from lp.xmlrpc.faults import NoSuchCodeImportJob


class CodeImportWorkerMonitorProtocol(ProcessMonitorProtocolWithTimeout):
    """The protocol by which the child process talks to the monitor.

    In terms of bytes, the protocol is extremely simple: any output is stored
    in the log file and seen as timeout-resetting activity.  Every
    config.codeimportworker.heartbeat_update_interval seconds we ask the
    monitor to update the heartbeat of the job we are working on and pass the
    tail of the log output.
    """

    def __init__(self, deferred, worker_monitor, log_file, clock=None):
        """Construct an instance.

        :param deferred: See `ProcessMonitorProtocol.__init__` -- the deferred
            that will be fired when the process has exited.
        :param worker_monitor: A `CodeImportWorkerMonitor` instance.
        :param log_file: A file object that the output of the child
            process will be logged to.
        :param clock: A provider of Twisted's IReactorTime.  This parameter
            exists to allow testing that does not depend on an external clock.
            If a clock is not passed in explicitly the reactor is used.
        """
        ProcessMonitorProtocolWithTimeout.__init__(
            self, deferred, clock=clock,
            timeout=config.codeimport.worker_inactivity_timeout)
        self.worker_monitor = worker_monitor
        self._tail = b''
        self._log_file = log_file
        self._looping_call = task.LoopingCall(self._updateHeartbeat)
        self._looping_call.clock = self._clock

    def connectionMade(self):
        """See `BaseProtocol.connectionMade`.

        We call updateHeartbeat for the first time when we are connected to
        the process and every
        config.codeimportworker.heartbeat_update_interval seconds thereafter.
        """
        ProcessMonitorProtocolWithTimeout.connectionMade(self)
        self._looping_call.start(
            config.codeimportworker.heartbeat_update_interval)

    def _updateHeartbeat(self):
        """Ask the monitor to update the heartbeat.

        We use runNotification() to serialize the updates and ensure
        that any errors are handled properly.  We do not return the
        deferred, as we want this function to be called at a frequency
        independent of how long it takes to update the heartbeat."""
        self.runNotification(
            self.worker_monitor.updateHeartbeat, self._tail)

    def outReceived(self, data):
        """See `ProcessProtocol.outReceived`.

        Any output resets the timeout, is stored in the logfile and
        updates the tail of the log.
        """
        self.resetTimeout()
        self._log_file.write(data)
        self._tail = b'\n'.join((self._tail + data).split(b'\n')[-5:])

    errReceived = outReceived

    def processEnded(self, reason):
        """See `ProcessMonitorProtocolWithTimeout.processEnded`.

        We stop updating the heartbeat when the process exits.
        """
        ProcessMonitorProtocolWithTimeout.processEnded(self, reason)
        self._looping_call.stop()


class ExitQuietly(Exception):
    """Raised to indicate that we should abort and exit without fuss.

    Raised when the job we are working on disappears, as we assume
    this is the result of the job being killed or reclaimed.
    """
    pass


class CodeImportWorkerMonitor:
    """Controller for a single import job.

    An instance of `CodeImportWorkerMonitor` runs a child process to
    perform an import and communicates status to the database.
    """

    path_to_script = os.path.join(
        config.root, 'scripts', 'code-import-worker.py')

    def __init__(self, job_id, logger, codeimport_endpoint, access_policy):
        """Construct an instance.

        :param job_id: The ID of the CodeImportJob we are to work on.
        :param logger: A `Logger` object.
        """
        self._job_id = job_id
        self._logger = logger
        self.codeimport_endpoint = codeimport_endpoint
        self._call_finish_job = True
        self._log_file = tempfile.TemporaryFile()
        self._access_policy = access_policy

    def _trap_nosuchcodeimportjob(self, failure):
        failure.trap(xmlrpc.Fault)
        if failure.value.faultCode == NoSuchCodeImportJob.error_code:
            self._call_finish_job = False
            raise ExitQuietly
        else:
            raise failure.value

    def getWorkerArguments(self):
        """Get arguments for the worker for the import we are working on."""
        deferred = self.codeimport_endpoint.callRemote(
            'getImportDataForJobID', self._job_id)

        def _processResult(result):
            code_import_arguments = result['arguments']
            self._logger.info(
                'Found source details: %s', code_import_arguments)
            return code_import_arguments
        return deferred.addCallbacks(
            _processResult, self._trap_nosuchcodeimportjob)

    def updateHeartbeat(self, tail):
        """Call the updateHeartbeat method for the job we are working on."""
        self._logger.debug("Updating heartbeat.")
        # The log tail is really bytes, but it's stored in the database as a
        # text column, so it's easiest to convert it to text now; passing
        # text over XML-RPC requires less boilerplate than bytes anyway.
        deferred = self.codeimport_endpoint.callRemote(
            'updateHeartbeat', self._job_id,
            six.ensure_text(tail, errors='replace'))
        return deferred.addErrback(self._trap_nosuchcodeimportjob)

    def finishJob(self, status):
        """Call the finishJobID method for the job we are working on."""
        self._log_file.seek(0)
        return self.codeimport_endpoint.callRemote(
            'finishJobID', self._job_id, status.name,
            xmlrpc_client.Binary(self._log_file.read())
            ).addErrback(self._trap_nosuchcodeimportjob)

    def _makeProcessProtocol(self, deferred):
        """Make an `CodeImportWorkerMonitorProtocol` for a subprocess."""
        return CodeImportWorkerMonitorProtocol(deferred, self, self._log_file)

    def _launchProcess(self, worker_arguments):
        """Launch the code-import-worker.py child process."""
        deferred = defer.Deferred()
        protocol = self._makeProcessProtocol(deferred)
        interpreter = '%s/bin/py' % config.root
        args = [interpreter, self.path_to_script]
        if self._access_policy is not None:
            args.append("--access-policy=%s" % self._access_policy)
        args.append('--')
        command = args + worker_arguments
        self._logger.info(
            "Launching worker child process %s.", command)
        reactor.spawnProcess(
            protocol, interpreter, command, env=os.environ, usePTY=True)
        return deferred

    def run(self):
        """Perform the import."""
        return self.getWorkerArguments().addCallback(
            self._launchProcess).addBoth(
            self.callFinishJob).addErrback(
            self._silenceQuietExit)

    def _silenceQuietExit(self, failure):
        """Quietly swallow a ExitQuietly failure."""
        failure.trap(ExitQuietly)
        return None

    def _reasonToStatus(self, reason):
        """Translate the 'reason' for process exit into a result status.

        Different exit codes are presumed by Twisted to be errors, but are
        different kinds of success for us.
        """
        exit_code_map = {
            CodeImportWorkerExitCode.SUCCESS_NOCHANGE:
                CodeImportResultStatus.SUCCESS_NOCHANGE,
            CodeImportWorkerExitCode.SUCCESS_PARTIAL:
                CodeImportResultStatus.SUCCESS_PARTIAL,
            CodeImportWorkerExitCode.FAILURE_UNSUPPORTED_FEATURE:
                CodeImportResultStatus.FAILURE_UNSUPPORTED_FEATURE,
            CodeImportWorkerExitCode.FAILURE_INVALID:
                CodeImportResultStatus.FAILURE_INVALID,
            CodeImportWorkerExitCode.FAILURE_FORBIDDEN:
                CodeImportResultStatus.FAILURE_FORBIDDEN,
            CodeImportWorkerExitCode.FAILURE_REMOTE_BROKEN:
                CodeImportResultStatus.FAILURE_REMOTE_BROKEN,
                }
        if isinstance(reason, failure.Failure):
            if reason.check(error.ProcessTerminated):
                return exit_code_map.get(reason.value.exitCode,
                    CodeImportResultStatus.FAILURE)
            return CodeImportResultStatus.FAILURE
        else:
            return CodeImportResultStatus.SUCCESS

    def callFinishJob(self, reason):
        """Call finishJob() with the appropriate status."""
        if not self._call_finish_job:
            return reason
        status = self._reasonToStatus(reason)
        if status == CodeImportResultStatus.FAILURE:
            self._log_file.write(b"Import failed:\n")
            self._log_file.write(reason.getTraceback().encode("UTF-8"))
            self._logger.info(
                "Import failed: %s: %s" % (reason.type, reason.value))
        else:
            self._logger.info('Import succeeded.')
        return self.finishJob(status)
