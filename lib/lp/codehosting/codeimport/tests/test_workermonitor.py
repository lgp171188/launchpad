# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the CodeImportWorkerMonitor and related classes."""

from __future__ import absolute_import, print_function

__metaclass__ = type

import io
import os
import shutil
import subprocess
import tempfile
from textwrap import dedent

from bzrlib.branch import Branch
from bzrlib.tests import TestCaseInTempDir
from dulwich.repo import Repo as GitRepo
from fixtures import MockPatchObject
import oops_twisted
from pymacaroons import Macaroon
from six.moves import xmlrpc_client
from testtools.matchers import (
    AnyMatch,
    Equals,
    IsInstance,
    MatchesListwise,
    )
from testtools.twistedsupport import (
    assert_fails_with,
    AsynchronousDeferredRunTest,
    )
from twisted.internet import (
    defer,
    error,
    protocol,
    reactor,
    )
from twisted.web import (
    server,
    xmlrpc,
    )

from lp.code.enums import CodeImportResultStatus
from lp.code.tests.helpers import GitHostingFixture
from lp.codehosting.codeimport.tests.servers import (
    BzrServer,
    CVSServer,
    GitServer,
    SubversionServer,
    )
from lp.codehosting.codeimport.tests.test_worker import (
    clean_up_default_stores_for_import,
    )
from lp.codehosting.codeimport.worker import (
    CodeImportWorkerExitCode,
    get_default_bazaar_branch_store,
    )
from lp.codehosting.codeimport.workermonitor import (
    CodeImportWorkerMonitor,
    CodeImportWorkerMonitorProtocol,
    ExitQuietly,
    )
from lp.services.config import config
from lp.services.config.fixture import (
    ConfigFixture,
    ConfigUseFixture,
    )
from lp.services.log.logger import BufferLogger
from lp.services.twistedsupport import suppress_stderr
from lp.services.twistedsupport.tests.test_processmonitor import (
    makeFailure,
    ProcessTestsMixin,
    )
from lp.services.webapp import errorlog
from lp.testing import TestCase
from lp.xmlrpc.faults import NoSuchCodeImportJob


class TestWorkerMonitorProtocol(ProcessTestsMixin, TestCase):

    class StubWorkerMonitor:

        def __init__(self):
            self.calls = []

        def updateHeartbeat(self, tail):
            self.calls.append(('updateHeartbeat', tail))

    def setUp(self):
        self.worker_monitor = self.StubWorkerMonitor()
        self.log_file = io.BytesIO()
        super(TestWorkerMonitorProtocol, self).setUp()

    def makeProtocol(self):
        """See `ProcessTestsMixin.makeProtocol`."""
        return CodeImportWorkerMonitorProtocol(
            self.termination_deferred, self.worker_monitor, self.log_file,
            self.clock)

    def test_callsUpdateHeartbeatInConnectionMade(self):
        # The protocol calls updateHeartbeat() as it is connected to the
        # process.
        # connectionMade() is called during setUp().
        self.assertEqual(
            self.worker_monitor.calls,
            [('updateHeartbeat', '')])

    def test_callsUpdateHeartbeatRegularly(self):
        # The protocol calls 'updateHeartbeat' on the worker_monitor every
        # config.codeimportworker.heartbeat_update_interval seconds.
        # Forget the call in connectionMade()
        self.worker_monitor.calls = []
        # Advance the simulated time a little to avoid fencepost errors.
        self.clock.advance(0.1)
        # And check that updateHeartbeat is called at the frequency we expect:
        for i in range(4):
            self.protocol.resetTimeout()
            self.assertEqual(
                self.worker_monitor.calls,
                [('updateHeartbeat', '')] * i)
            self.clock.advance(
                config.codeimportworker.heartbeat_update_interval)

    def test_updateHeartbeatStopsOnProcessExit(self):
        # updateHeartbeat is not called after the process has exited.
        # Forget the call in connectionMade()
        self.worker_monitor.calls = []
        self.simulateProcessExit()
        # Advance the simulated time past the time the next update is due.
        self.clock.advance(
            config.codeimportworker.heartbeat_update_interval + 1)
        # Check that updateHeartbeat was not called.
        self.assertEqual(self.worker_monitor.calls, [])

    def test_outReceivedWritesToLogFile(self):
        # outReceived writes the data it is passed into the log file.
        output = [b'some data\n', b'some more data\n']
        self.protocol.outReceived(output[0])
        self.assertEqual(self.log_file.getvalue(), output[0])
        self.protocol.outReceived(output[1])
        self.assertEqual(self.log_file.getvalue(), output[0] + output[1])

    def test_outReceivedUpdatesTail(self):
        # outReceived updates the tail of the log, currently and arbitrarily
        # defined to be the last 5 lines of the log.
        lines = ['line %d' % number for number in range(1, 7)]
        self.protocol.outReceived('\n'.join(lines[:3]) + '\n')
        self.assertEqual(
            self.protocol._tail, 'line 1\nline 2\nline 3\n')
        self.protocol.outReceived('\n'.join(lines[3:]) + '\n')
        self.assertEqual(
            self.protocol._tail, 'line 3\nline 4\nline 5\nline 6\n')


class FakeCodeImportScheduler(xmlrpc.XMLRPC, object):
    """A fake implementation of `ICodeImportScheduler`.

    The constructor takes a dictionary mapping job ids to information that
    should be returned by getImportDataForJobID and the fault to return if
    getImportDataForJobID is called with a job id not in the passed-in
    dictionary, defaulting to a fault with the same code as
    NoSuchCodeImportJob (because the class of the fault is lost when you go
    through XML-RPC serialization).
    """

    def __init__(self, jobs_dict, no_such_job_fault=None):
        super(FakeCodeImportScheduler, self).__init__(allowNone=True)
        self.calls = []
        self.jobs_dict = jobs_dict
        if no_such_job_fault is None:
            no_such_job_fault = xmlrpc.Fault(
                faultCode=NoSuchCodeImportJob.error_code, faultString='')
        self.no_such_job_fault = no_such_job_fault

    def xmlrpc_getImportDataForJobID(self, job_id):
        self.calls.append(('getImportDataForJobID', job_id))
        if job_id in self.jobs_dict:
            return self.jobs_dict[job_id]
        else:
            return self.no_such_job_fault

    def xmlrpc_updateHeartbeat(self, job_id, log_tail):
        self.calls.append(('updateHeartbeat', job_id, log_tail))
        return 0

    def xmlrpc_finishJobID(self, job_id, status_name, log_file):
        self.calls.append(('finishJobID', job_id, status_name, log_file))


class FakeCodeImportSchedulerMixin:

    def makeFakeCodeImportScheduler(self, jobs_dict, no_such_job_fault=None):
        """Start a `FakeCodeImportScheduler` and return its URL."""
        scheduler = FakeCodeImportScheduler(
            jobs_dict, no_such_job_fault=no_such_job_fault)
        scheduler_listener = reactor.listenTCP(0, server.Site(scheduler))
        self.addCleanup(scheduler_listener.stopListening)
        scheduler_port = scheduler_listener.getHost().port
        return scheduler, 'http://localhost:%d/' % scheduler_port


class TestWorkerMonitorUnit(FakeCodeImportSchedulerMixin, TestCase):
    """Unit tests for most of the `CodeImportWorkerMonitor` class.

    We have to pay attention to the fact that several of the methods of the
    `CodeImportWorkerMonitor` class are wrapped in decorators that create and
    commit a transaction, and have to start our own transactions to check what
    they did.
    """

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def makeWorkerMonitorWithJob(self, job_id=1, job_data={}):
        self.scheduler, scheduler_url = self.makeFakeCodeImportScheduler(
            {job_id: job_data})
        return CodeImportWorkerMonitor(
            job_id, BufferLogger(), xmlrpc.Proxy(scheduler_url), "anything")

    def makeWorkerMonitorWithoutJob(self, fault=None):
        self.scheduler, scheduler_url = self.makeFakeCodeImportScheduler(
            {}, fault)
        return CodeImportWorkerMonitor(
            1, BufferLogger(), xmlrpc.Proxy(scheduler_url), None)

    def test_getWorkerArguments(self):
        # getWorkerArguments returns a deferred that fires with the
        # 'arguments' part of what getImportDataForJobID returns.
        args = [self.factory.getUniqueString(),
                self.factory.getUniqueString()]
        data = {'arguments': args}
        worker_monitor = self.makeWorkerMonitorWithJob(1, data)
        return worker_monitor.getWorkerArguments().addCallback(
            self.assertEqual, args)

    def test_getWorkerArguments_job_not_found_raises_exit_quietly(self):
        # When getImportDataForJobID signals a fault indicating that
        # getWorkerArguments didn't find the supplied job, getWorkerArguments
        # translates this to an 'ExitQuietly' exception.
        worker_monitor = self.makeWorkerMonitorWithoutJob()
        return assert_fails_with(
            worker_monitor.getWorkerArguments(), ExitQuietly)

    def test_getWorkerArguments_endpoint_failure_raises(self):
        # When getImportDataForJobID raises an arbitrary exception, it is not
        # handled in any special way by getWorkerArguments.
        self.useFixture(MockPatchObject(
            xmlrpc_client, 'loads', side_effect=ZeroDivisionError()))
        worker_monitor = self.makeWorkerMonitorWithoutJob()
        return assert_fails_with(
            worker_monitor.getWorkerArguments(), ZeroDivisionError)

    def test_getWorkerArguments_arbitrary_fault_raises(self):
        # When getImportDataForJobID signals an arbitrary fault, it is not
        # handled in any special way by getWorkerArguments.
        worker_monitor = self.makeWorkerMonitorWithoutJob(
            fault=xmlrpc.Fault(1, ''))
        return assert_fails_with(
            worker_monitor.getWorkerArguments(), xmlrpc.Fault)

    def test_updateHeartbeat(self):
        # updateHeartbeat calls the updateHeartbeat XML-RPC method.
        log_tail = self.factory.getUniqueString()
        job_id = self.factory.getUniqueInteger()
        worker_monitor = self.makeWorkerMonitorWithJob(job_id)

        def check_updated_details(result):
            self.assertEqual(
                [('updateHeartbeat', job_id, log_tail)],
                self.scheduler.calls)

        return worker_monitor.updateHeartbeat(log_tail).addCallback(
            check_updated_details)

    def test_finishJob_calls_finishJobID_empty_log_file(self):
        # When the log file is empty, finishJob calls finishJobID with the
        # name of the status enum and an empty binary string.
        job_id = self.factory.getUniqueInteger()
        worker_monitor = self.makeWorkerMonitorWithJob(job_id)
        self.assertEqual(worker_monitor._log_file.tell(), 0)

        def check_finishJob_called(result):
            self.assertEqual(
                [('finishJobID', job_id, 'SUCCESS',
                  xmlrpc_client.Binary(b''))],
                self.scheduler.calls)

        return worker_monitor.finishJob(
            CodeImportResultStatus.SUCCESS).addCallback(
            check_finishJob_called)

    def test_finishJob_sends_nonempty_file_to_scheduler(self):
        # finishJob method calls finishJobID with the contents of the log
        # file.
        job_id = self.factory.getUniqueInteger()
        log_bytes = self.factory.getUniqueBytes()
        worker_monitor = self.makeWorkerMonitorWithJob(job_id)
        worker_monitor._log_file.write(log_bytes)

        def check_finishJob_called(result):
            self.assertEqual(
                [('finishJobID', job_id, 'SUCCESS',
                  xmlrpc_client.Binary(log_bytes))],
                self.scheduler.calls)

        return worker_monitor.finishJob(
            CodeImportResultStatus.SUCCESS).addCallback(
            check_finishJob_called)

    def patchOutFinishJob(self, worker_monitor):
        """Replace `worker_monitor.finishJob` with a `FakeMethod`-alike stub.

        :param worker_monitor: CodeImportWorkerMonitor to patch up.
        :return: A list of statuses that `finishJob` has been called with.
            Future calls will be appended to this list.
        """
        calls = []

        def finishJob(status):
            calls.append(status)
            return defer.succeed(None)

        worker_monitor.finishJob = finishJob
        return calls

    def test_callFinishJobCallsFinishJobSuccess(self):
        # callFinishJob calls finishJob with CodeImportResultStatus.SUCCESS if
        # its argument is not a Failure.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        worker_monitor.callFinishJob(None)
        self.assertEqual(calls, [CodeImportResultStatus.SUCCESS])

    @suppress_stderr
    def test_callFinishJobCallsFinishJobFailure(self):
        # callFinishJob calls finishJob with CodeImportResultStatus.FAILURE
        # and swallows the failure if its argument indicates that the
        # subprocess exited with an exit code of
        # CodeImportWorkerExitCode.FAILURE.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(
            makeFailure(
                error.ProcessTerminated,
                exitCode=CodeImportWorkerExitCode.FAILURE))
        self.assertEqual(calls, [CodeImportResultStatus.FAILURE])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    def test_callFinishJobCallsFinishJobSuccessNoChange(self):
        # If the argument to callFinishJob indicates that the subprocess
        # exited with a code of CodeImportWorkerExitCode.SUCCESS_NOCHANGE, it
        # calls finishJob with a status of SUCCESS_NOCHANGE.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(
            makeFailure(
                error.ProcessTerminated,
                exitCode=CodeImportWorkerExitCode.SUCCESS_NOCHANGE))
        self.assertEqual(calls, [CodeImportResultStatus.SUCCESS_NOCHANGE])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    @suppress_stderr
    def test_callFinishJobCallsFinishJobArbitraryFailure(self):
        # If the argument to callFinishJob indicates that there was some other
        # failure that had nothing to do with the subprocess, it records
        # failure.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(makeFailure(RuntimeError))
        self.assertEqual(calls, [CodeImportResultStatus.FAILURE])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    def test_callFinishJobCallsFinishJobPartial(self):
        # If the argument to callFinishJob indicates that the subprocess
        # exited with a code of CodeImportWorkerExitCode.SUCCESS_PARTIAL, it
        # calls finishJob with a status of SUCCESS_PARTIAL.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(
            makeFailure(
                error.ProcessTerminated,
                exitCode=CodeImportWorkerExitCode.SUCCESS_PARTIAL))
        self.assertEqual(calls, [CodeImportResultStatus.SUCCESS_PARTIAL])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    def test_callFinishJobCallsFinishJobInvalid(self):
        # If the argument to callFinishJob indicates that the subprocess
        # exited with a code of CodeImportWorkerExitCode.FAILURE_INVALID, it
        # calls finishJob with a status of FAILURE_INVALID.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(
            makeFailure(
                error.ProcessTerminated,
                exitCode=CodeImportWorkerExitCode.FAILURE_INVALID))
        self.assertEqual(calls, [CodeImportResultStatus.FAILURE_INVALID])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    def test_callFinishJobCallsFinishJobUnsupportedFeature(self):
        # If the argument to callFinishJob indicates that the subprocess
        # exited with a code of FAILURE_UNSUPPORTED_FEATURE, it
        # calls finishJob with a status of FAILURE_UNSUPPORTED_FEATURE.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(makeFailure(
            error.ProcessTerminated,
            exitCode=CodeImportWorkerExitCode.FAILURE_UNSUPPORTED_FEATURE))
        self.assertEqual(
            calls, [CodeImportResultStatus.FAILURE_UNSUPPORTED_FEATURE])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    def test_callFinishJobCallsFinishJobRemoteBroken(self):
        # If the argument to callFinishJob indicates that the subprocess
        # exited with a code of FAILURE_REMOTE_BROKEN, it
        # calls finishJob with a status of FAILURE_REMOTE_BROKEN.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        ret = worker_monitor.callFinishJob(
            makeFailure(
                error.ProcessTerminated,
                exitCode=CodeImportWorkerExitCode.FAILURE_REMOTE_BROKEN))
        self.assertEqual(
            calls, [CodeImportResultStatus.FAILURE_REMOTE_BROKEN])
        # We return the deferred that callFinishJob returns -- if
        # callFinishJob did not swallow the error, this will fail the test.
        return ret

    @suppress_stderr
    def test_callFinishJobLogsTracebackOnFailure(self):
        # When callFinishJob is called with a failure, it dumps the traceback
        # of the failure into the log file.
        worker_monitor = self.makeWorkerMonitorWithJob()
        ret = worker_monitor.callFinishJob(makeFailure(RuntimeError))

        def check_log_file(ignored):
            worker_monitor._log_file.seek(0)
            log_bytes = worker_monitor._log_file.read()
            self.assertIn(b'Traceback (most recent call last)', log_bytes)
            self.assertIn(b'RuntimeError', log_bytes)
        return ret.addCallback(check_log_file)

    def test_callFinishJobRespects_call_finish_job(self):
        # callFinishJob does not call finishJob if _call_finish_job is False.
        # This is to support exiting without fuss when the job we are working
        # on is deleted in the web UI.
        worker_monitor = self.makeWorkerMonitorWithJob()
        calls = self.patchOutFinishJob(worker_monitor)
        worker_monitor._call_finish_job = False
        worker_monitor.callFinishJob(None)
        self.assertEqual(calls, [])


class TestWorkerMonitorRunNoProcess(FakeCodeImportSchedulerMixin, TestCase):
    """Tests for `CodeImportWorkerMonitor.run` that don't launch a subprocess.
    """

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    class WorkerMonitor(CodeImportWorkerMonitor):
        """See `CodeImportWorkerMonitor`.

        Override _launchProcess to return a deferred that we can
        callback/errback as we choose.  Passing ``has_job=False`` to the
        constructor will cause getWorkerArguments() to raise ExitQuietly (this
        bit is tested above).
        """

        def __init__(self, job_id, logger, codeimport_endpoint, access_policy,
                     process_deferred):
            CodeImportWorkerMonitor.__init__(
                self, job_id, logger, codeimport_endpoint, access_policy)
            self.result_status = None
            self.process_deferred = process_deferred

        def _launchProcess(self, worker_arguments):
            return self.process_deferred

        def finishJob(self, status):
            assert self.result_status is None, "finishJob called twice!"
            self.result_status = status
            return defer.succeed(None)

    def makeWorkerMonitor(self, process_deferred, has_job=True):
        if has_job:
            job_data = {1: {'arguments': []}}
        else:
            job_data = {}
        _, scheduler_url = self.makeFakeCodeImportScheduler(job_data)
        return self.WorkerMonitor(
            1, BufferLogger(), xmlrpc.Proxy(scheduler_url), "anything",
            process_deferred)

    def assertFinishJobCalledWithStatus(self, ignored, worker_monitor,
                                        status):
        """Assert that finishJob was called with the given status."""
        self.assertEqual(worker_monitor.result_status, status)

    def assertFinishJobNotCalled(self, ignored, worker_monitor):
        """Assert that finishJob was called with the given status."""
        self.assertFinishJobCalledWithStatus(ignored, worker_monitor, None)

    def test_success(self):
        # In the successful case, finishJob is called with
        # CodeImportResultStatus.SUCCESS.
        worker_monitor = self.makeWorkerMonitor(defer.succeed(None))
        return worker_monitor.run().addCallback(
            self.assertFinishJobCalledWithStatus, worker_monitor,
            CodeImportResultStatus.SUCCESS)

    def test_failure(self):
        # If the process deferred is fired with a failure, finishJob is called
        # with CodeImportResultStatus.FAILURE, but the call to run() still
        # succeeds.
        # Need a twisted error reporting stack (normally set up by
        # loggingsupport.set_up_oops_reporting).
        errorlog.globalErrorUtility.configure(
            config_factory=oops_twisted.Config,
            publisher_adapter=oops_twisted.defer_publisher,
            publisher_helpers=oops_twisted.publishers)
        self.addCleanup(errorlog.globalErrorUtility.configure)
        worker_monitor = self.makeWorkerMonitor(defer.fail(RuntimeError()))
        return worker_monitor.run().addCallback(
            self.assertFinishJobCalledWithStatus, worker_monitor,
            CodeImportResultStatus.FAILURE)

    def test_quiet_exit(self):
        # If the process deferred fails with ExitQuietly, the call to run()
        # succeeds, and finishJob is not called at all.
        worker_monitor = self.makeWorkerMonitor(
            defer.succeed(None), has_job=False)
        return worker_monitor.run().addCallback(
            self.assertFinishJobNotCalled, worker_monitor)

    def test_quiet_exit_from_finishJob(self):
        # If finishJob fails with ExitQuietly, the call to run() still
        # succeeds.
        worker_monitor = self.makeWorkerMonitor(defer.succeed(None))

        def finishJob(reason):
            raise ExitQuietly
        worker_monitor.finishJob = finishJob
        return worker_monitor.run()

    def test_callFinishJob_logs_failure(self):
        # callFinishJob logs a failure from the child process.
        errorlog.globalErrorUtility.configure(
            config_factory=oops_twisted.Config,
            publisher_adapter=oops_twisted.defer_publisher,
            publisher_helpers=oops_twisted.publishers)
        self.addCleanup(errorlog.globalErrorUtility.configure)
        failure_msg = b"test_callFinishJob_logs_failure expected failure"
        worker_monitor = self.makeWorkerMonitor(
            defer.fail(RuntimeError(failure_msg)))
        d = worker_monitor.run()

        def check_log_file(ignored):
            worker_monitor._log_file.seek(0)
            log_bytes = worker_monitor._log_file.read()
            self.assertIn(
                b"Failure: exceptions.RuntimeError: " + failure_msg,
                log_bytes)

        d.addCallback(check_log_file)
        return d


class CIWorkerMonitorProtocolForTesting(CodeImportWorkerMonitorProtocol):
    """A `CodeImportWorkerMonitorProtocol` that counts `resetTimeout` calls.
    """

    def __init__(self, deferred, worker_monitor, log_file, clock=None):
        """See `CodeImportWorkerMonitorProtocol.__init__`."""
        CodeImportWorkerMonitorProtocol.__init__(
            self, deferred, worker_monitor, log_file, clock)
        self.reset_calls = 0

    def resetTimeout(self):
        """See `ProcessMonitorProtocolWithTimeout.resetTimeout`."""
        CodeImportWorkerMonitorProtocol.resetTimeout(self)
        self.reset_calls += 1


class CIWorkerMonitorForTesting(CodeImportWorkerMonitor):
    """A `CodeImportWorkerMonitor` that hangs on to the process protocol."""

    def _makeProcessProtocol(self, deferred):
        """See `CodeImportWorkerMonitor._makeProcessProtocol`.

        We hang on to the constructed object for later inspection -- see
        `TestWorkerMonitorIntegration.assertImported`.
        """
        protocol = CIWorkerMonitorProtocolForTesting(
            deferred, self, self._log_file)
        self._protocol = protocol
        return protocol


class TestWorkerMonitorIntegration(FakeCodeImportSchedulerMixin,
                                   TestCaseInTempDir, TestCase):

    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=60)

    def setUp(self):
        super(TestWorkerMonitorIntegration, self).setUp()
        self.repo_path = tempfile.mkdtemp()
        self.disable_directory_isolation()
        self.addCleanup(shutil.rmtree, self.repo_path)
        self.foreign_commit_count = 0

    def makeCVSCodeImport(self):
        """Make arguments that point to a real CVS repository."""
        cvs_server = CVSServer(self.repo_path)
        cvs_server.start_server()
        self.addCleanup(cvs_server.stop_server)

        cvs_server.makeModule('trunk', [('README', 'original\n')])
        self.foreign_commit_count = 2

        return [
            str(self.factory.getUniqueInteger()), 'cvs', 'bzr',
            cvs_server.getRoot(), '--cvs-module', 'trunk',
            ]

    def makeBzrSvnCodeImport(self):
        """Make arguments that point to a real Subversion repository."""
        self.subversion_server = SubversionServer(
            self.repo_path, use_svn_serve=True)
        self.subversion_server.start_server()
        self.addCleanup(self.subversion_server.stop_server)
        url = self.subversion_server.makeBranch(
            'trunk', [('README', b'contents')])
        self.foreign_commit_count = 2

        return [
            str(self.factory.getUniqueInteger()), 'bzr-svn', 'bzr',
            url,
            ]

    def makeGitCodeImport(self, target_rcs_type='bzr'):
        """Make arguments that point to a real Git repository."""
        self.git_server = GitServer(self.repo_path, use_server=False)
        self.git_server.start_server()
        self.addCleanup(self.git_server.stop_server)

        self.git_server.makeRepo('source', [('README', 'contents')])
        self.foreign_commit_count = 1

        target_id = (
            str(self.factory.getUniqueInteger()) if target_rcs_type == 'bzr'
            else self.factory.getUniqueUnicode())
        arguments = [
            target_id, 'git', target_rcs_type,
            self.git_server.get_url('source'),
            ]
        if target_rcs_type == 'git':
            arguments.extend(['--macaroon', Macaroon().serialize()])
        return arguments

    def makeBzrCodeImport(self):
        """Make arguments that point to a real Bazaar branch."""
        self.bzr_server = BzrServer(self.repo_path)
        self.bzr_server.start_server()
        self.addCleanup(self.bzr_server.stop_server)

        self.bzr_server.makeRepo([('README', 'contents')])
        self.foreign_commit_count = 1

        return [
            str(self.factory.getUniqueInteger()), 'bzr', 'bzr',
            self.bzr_server.get_url(),
            ]

    def getStartedJobForImport(self, arguments):
        """Get a started `CodeImportJob` for `code_import`.

        This method returns a job ID and job data, imitating an approved job
        on Launchpad.  It also makes sure there are no branches or foreign
        trees in the default stores to interfere with processing this job.
        """
        if arguments[2] == 'bzr':
            target_id = int(arguments[0])
            clean_up_default_stores_for_import(target_id)
            self.addCleanup(clean_up_default_stores_for_import, target_id)
        return (1, {'arguments': arguments})

    def makeTargetGitServer(self):
        """Set up a target Git server that can receive imports."""
        self.target_store = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.target_store)
        self.target_git_server = GitServer(self.target_store, use_server=True)
        self.target_git_server.start_server()
        self.addCleanup(self.target_git_server.stop_server)
        config_name = self.factory.getUniqueUnicode()
        config_fixture = self.useFixture(ConfigFixture(
            config_name, os.environ['LPCONFIG']))
        setting_lines = [
            "[codehosting]",
            "git_browse_root: %s" % self.target_git_server.get_url(""),
            "",
            "[launchpad]",
            "internal_macaroon_secret_key: some-secret",
            ]
        config_fixture.add_section("\n" + "\n".join(setting_lines))
        self.useFixture(ConfigUseFixture(config_name))
        self.useFixture(GitHostingFixture())

    def assertBranchImportedOKForCodeImport(self, target_id):
        """Assert that a branch was pushed into the default branch store."""
        if target_id.isdigit():
            url = get_default_bazaar_branch_store()._getMirrorURL(
                int(target_id))
            branch = Branch.open(url)
            commit_count = branch.revno()
        else:
            repo_path = os.path.join(self.target_store, target_id)
            commit_count = int(subprocess.check_output(
                ["git", "rev-list", "--count", "HEAD"],
                cwd=repo_path, universal_newlines=True))
        self.assertEqual(self.foreign_commit_count, commit_count)

    def assertImported(self, job_id, job_data):
        """Assert that the code import with the given job id was imported.

        Since we don't have a full Launchpad appserver instance here, we
        just check that the code import worker has made the correct XML-RPC
        calls via the given worker monitor.
        """
        # In the in-memory tests, check that resetTimeout on the
        # CodeImportWorkerMonitorProtocol was called at least once.
        if self._protocol is not None:
            self.assertPositive(self._protocol.reset_calls)
        self.assertThat(self.scheduler.calls, AnyMatch(
            MatchesListwise([
                Equals('finishJobID'),
                Equals(job_id),
                Equals('SUCCESS'),
                IsInstance(xmlrpc_client.Binary),
                ])))
        self.assertBranchImportedOKForCodeImport(job_data['arguments'][0])

    @defer.inlineCallbacks
    def performImport(self, job_id, job_data):
        """Perform the import job with ID job_id and data job_data.

        Return a Deferred that fires when the job is done.

        This implementation does it in-process.
        """
        logger = BufferLogger()
        self.scheduler, scheduler_url = self.makeFakeCodeImportScheduler(
            {job_id: job_data})
        worker_monitor = CIWorkerMonitorForTesting(
            job_id, logger, xmlrpc.Proxy(scheduler_url), "anything")
        result = yield worker_monitor.run()
        self._protocol = worker_monitor._protocol
        defer.returnValue(result)

    @defer.inlineCallbacks
    def test_import_cvs(self):
        # Create a CVS CodeImport and import it.
        job_id, job_data = self.getStartedJobForImport(
            self.makeCVSCodeImport())
        yield self.performImport(job_id, job_data)
        self.assertImported(job_id, job_data)

    @defer.inlineCallbacks
    def test_import_git(self):
        # Create a Git CodeImport and import it.
        job_id, job_data = self.getStartedJobForImport(
            self.makeGitCodeImport())
        yield self.performImport(job_id, job_data)
        self.assertImported(job_id, job_data)

    @defer.inlineCallbacks
    def test_import_git_to_git(self):
        # Create a Git-to-Git CodeImport and import it.
        self.makeTargetGitServer()
        job_id, job_data = self.getStartedJobForImport(
            self.makeGitCodeImport(target_rcs_type='git'))
        target_repo_path = os.path.join(
            self.target_store, job_data['arguments'][0])
        os.makedirs(target_repo_path)
        self.target_git_server.createRepository(target_repo_path, bare=True)
        yield self.performImport(job_id, job_data)
        self.assertImported(job_id, job_data)
        target_repo = GitRepo(target_repo_path)
        self.assertContentEqual(
            ["heads/master"], target_repo.refs.keys(base="refs"))
        self.assertEqual(
            "ref: refs/heads/master", target_repo.refs.read_ref("HEAD"))

    @defer.inlineCallbacks
    def test_import_git_to_git_refs_changed(self):
        # Create a Git-to-Git CodeImport and import it incrementally with
        # ref and HEAD changes.
        self.makeTargetGitServer()
        job_id, job_data = self.getStartedJobForImport(
            self.makeGitCodeImport(target_rcs_type='git'))
        source_repo = GitRepo(os.path.join(self.repo_path, "source"))
        commit = source_repo.refs["refs/heads/master"]
        source_repo.refs["refs/heads/one"] = commit
        source_repo.refs["refs/heads/two"] = commit
        source_repo.refs.set_symbolic_ref("HEAD", "refs/heads/one")
        del source_repo.refs["refs/heads/master"]
        target_repo_path = os.path.join(
            self.target_store, job_data['arguments'][0])
        self.target_git_server.makeRepo(
            job_data['arguments'][0], [("NEWS", "contents")])
        yield self.performImport(job_id, job_data)
        self.assertImported(job_id, job_data)
        target_repo = GitRepo(target_repo_path)
        self.assertContentEqual(
            ["heads/one", "heads/two"], target_repo.refs.keys(base="refs"))
        self.assertEqual(
            "ref: refs/heads/one",
            GitRepo(target_repo_path).refs.read_ref("HEAD"))

    @defer.inlineCallbacks
    def test_import_bzr(self):
        # Create a Bazaar CodeImport and import it.
        job_id, job_data = self.getStartedJobForImport(
            self.makeBzrCodeImport())
        yield self.performImport(job_id, job_data)
        self.assertImported(job_id, job_data)

    @defer.inlineCallbacks
    def test_import_bzrsvn(self):
        # Create a Subversion-via-bzr-svn CodeImport and import it.
        job_id, job_data = self.getStartedJobForImport(
            self.makeBzrSvnCodeImport())
        yield self.performImport(job_id, job_data)
        self.assertImported(job_id, job_data)


class DeferredOnExit(protocol.ProcessProtocol):

    def __init__(self, deferred):
        self._deferred = deferred

    def processEnded(self, reason):
        if reason.check(error.ProcessDone):
            self._deferred.callback(None)
        else:
            self._deferred.errback(reason)


class TestWorkerMonitorIntegrationScript(TestWorkerMonitorIntegration):
    """Tests for CodeImportWorkerMonitor that execute a child process."""

    def setUp(self):
        super(TestWorkerMonitorIntegrationScript, self).setUp()
        self._protocol = None

    def performImport(self, job_id, job_data):
        """Perform the import job with ID job_id and data job_data.

        Return a Deferred that fires when the job is done.

        This implementation does it in a child process.
        """
        self.scheduler, scheduler_url = self.makeFakeCodeImportScheduler(
            {job_id: job_data})
        config_name = self.factory.getUniqueUnicode()
        config_fixture = self.useFixture(
            ConfigFixture(config_name, os.environ['LPCONFIG']))
        config_fixture.add_section(dedent("""
            [codeimportdispatcher]
            codeimportscheduler_url: %s
            """) % scheduler_url)
        self.useFixture(ConfigUseFixture(config_name))
        script_path = os.path.join(
            config.root, 'scripts', 'code-import-worker-monitor.py')
        process_end_deferred = defer.Deferred()
        # The "childFDs={0:0, 1:1, 2:2}" means that any output from the script
        # goes to the test runner's console rather than to pipes that noone is
        # listening too.
        interpreter = '%s/bin/py' % config.root
        reactor.spawnProcess(
            DeferredOnExit(process_end_deferred), interpreter, [
                interpreter,
                script_path,
                '--access-policy=anything',
                str(job_id),
                '-q',
                ], childFDs={0: 0, 1: 1, 2: 2}, env=os.environ)
        return process_end_deferred
