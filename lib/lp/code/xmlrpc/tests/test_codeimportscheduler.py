# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test for the methods of `ICodeImportScheduler`."""

import xmlrpc.client

import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.code.enums import CodeImportResultStatus
from lp.code.model.codeimportjob import CodeImportJob
from lp.code.tests.codeimporthelpers import make_running_import
from lp.code.xmlrpc.codeimportscheduler import CodeImportSchedulerAPI
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.webapp import canonical_url
from lp.testing import TestCaseWithFactory, run_with_login
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.xmlrpc.faults import NoSuchCodeImportJob


class TestCodeImportSchedulerAPI(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.api = CodeImportSchedulerAPI(None, None)
        self.machine = self.factory.makeCodeImportMachine(set_online=True)
        for job in IStore(CodeImportJob).find(CodeImportJob):
            job.destroySelf()

    def makeCodeImportJob(self, running):
        person = getUtility(ILaunchpadCelebrities).vcs_imports.teamowner
        if running:
            return removeSecurityProxy(
                run_with_login(person, make_running_import)
            ).import_job
        else:
            return run_with_login(person, self.factory.makeCodeImportJob)

    def test_getJobForMachine_no_job_waiting(self):
        # If no job is waiting getJobForMachine returns 0.
        job_id = self.api.getJobForMachine(self.machine.hostname, 10)
        self.assertEqual(0, job_id)

    def test_getJobForMachine_job_waiting(self):
        # If a job is waiting getJobForMachine returns its id.
        code_import_job = self.makeCodeImportJob(running=False)
        job_id = self.api.getJobForMachine(self.machine.hostname, 10)
        self.assertEqual(code_import_job.id, job_id)

    def test_getImportDataForJobID(self):
        # getImportDataForJobID returns the worker arguments, target url and
        # log file name for an import corresponding to a particular job.
        self.pushConfig(
            "codehosting", blacklisted_hostnames="localhost,127.0.0.1"
        )
        code_import_job = self.makeCodeImportJob(running=True)
        code_import = removeSecurityProxy(code_import_job).code_import
        data = self.api.getImportDataForJobID(code_import_job.id)
        expected_data = {
            "arguments": code_import_job.makeWorkerArguments(),
            "target_url": canonical_url(code_import.target),
            "log_file_name": "%s.log"
            % (code_import.target.unique_name[1:].replace("/", "-")),
            "blacklisted_hostnames": ["localhost", "127.0.0.1"],
        }
        self.assertEqual(expected_data, data)

    def test_getImportDataForJobID_not_found(self):
        # getImportDataForJobID returns a NoSuchCodeImportJob fault when there
        # is no code import job with the given ID.
        fault = self.api.getImportDataForJobID(-1)
        self.assertTrue(
            isinstance(fault, xmlrpc.client.Fault),
            "getImportDataForJobID(-1) returned %r, not a Fault." % (fault,),
        )
        self.assertEqual(NoSuchCodeImportJob, fault.__class__)

    def test_updateHeartbeat(self):
        # updateHeartbeat calls the updateHeartbeat job workflow method.
        code_import_job = self.makeCodeImportJob(running=True)
        log_tail = self.factory.getUniqueUnicode()
        self.api.updateHeartbeat(code_import_job.id, log_tail)
        self.assertSqlAttributeEqualsDate(
            code_import_job, "heartbeat", UTC_NOW
        )
        self.assertEqual(log_tail, code_import_job.logtail)

    def test_updateHeartbeat_not_found(self):
        # updateHeartbeat returns a NoSuchCodeImportJob fault when there is no
        # code import job with the given ID.
        fault = self.api.updateHeartbeat(-1, "")
        self.assertTrue(
            isinstance(fault, xmlrpc.client.Fault),
            "updateHeartbeat(-1, '') returned %r, not a Fault." % (fault,),
        )
        self.assertEqual(NoSuchCodeImportJob, fault.__class__)

    def test_finishJobID_no_log_file(self):
        # finishJobID calls the finishJobID job workflow method.  Passing ''
        # means no log file was uploaded to the librarian.
        code_import_job = self.makeCodeImportJob(running=True)
        code_import = code_import_job.code_import
        self.api.finishJobID(
            code_import_job.id, CodeImportResultStatus.SUCCESS.name, ""
        )
        # finishJob does many things, we just check one of them: setting
        # date_last_successful in the case of success.
        self.assertSqlAttributeEqualsDate(
            code_import, "date_last_successful", UTC_NOW
        )

    def test_finishJobID_with_log_file_data(self):
        # finishJobID calls the finishJobID job workflow method and uploads
        # log file data to the librarian.
        code_import_job = self.makeCodeImportJob(running=True)
        code_import = code_import_job.code_import
        self.api.finishJobID(
            code_import_job.id,
            CodeImportResultStatus.SUCCESS.name,
            xmlrpc.client.Binary(b"log file data\n"),
        )
        transaction.commit()
        self.assertEqual(
            b"log file data\n", code_import.results.last().log_file.read()
        )

    def test_finishJobID_with_empty_log_file_data(self):
        # finishJobID calls the finishJobID job workflow method, but does
        # not upload zero-byte log files to the librarian.
        code_import_job = self.makeCodeImportJob(running=True)
        code_import = code_import_job.code_import
        self.api.finishJobID(
            code_import_job.id,
            CodeImportResultStatus.SUCCESS.name,
            xmlrpc.client.Binary(b""),
        )
        self.assertIsNone(code_import.results.last().log_file)

    def test_finishJobID_not_found(self):
        # getImportDataForJobID returns a NoSuchCodeImportJob fault when there
        # is no code import job with the given ID.
        fault = self.api.finishJobID(
            -1, CodeImportResultStatus.SUCCESS.name, ""
        )
        self.assertTrue(
            isinstance(fault, xmlrpc.client.Fault),
            "finishJobID(-1, 'SUCCESS', 0) returned %r, not a Fault."
            % (fault,),
        )
        self.assertEqual(NoSuchCodeImportJob, fault.__class__)
