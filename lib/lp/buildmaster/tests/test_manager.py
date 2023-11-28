# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the renovated worker scanner aka BuilddManager."""

import os
import signal
import time
import xmlrpc.client
from typing import Dict
from unittest import mock

import transaction
from testtools.matchers import Equals
from testtools.testcase import ExpectedException
from testtools.twistedsupport import AsynchronousDeferredRunTest
from twisted.internet import defer, reactor, task
from twisted.internet.task import deferLater
from twisted.python.failure import Failure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuildQueueStatus,
    BuildStatus,
)
from lp.buildmaster.interactor import (
    BuilderInteractor,
    BuilderWorker,
    extract_vitals_from_db,
    shut_down_default_process_pool,
)
from lp.buildmaster.interfaces.builder import (
    BuildDaemonIsolationError,
    BuildWorkerFailure,
    IBuilderSet,
)
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.manager import (
    BUILDER_FAILURE_THRESHOLD,
    JOB_RESET_THRESHOLD,
    SCAN_FAILURE_THRESHOLD,
    BuilddManager,
    BuilderFactory,
    PrefetchedBuilderFactory,
    WorkerScanner,
    judge_failure,
    recover_failure,
)
from lp.buildmaster.tests.harness import BuilddManagerTestSetup
from lp.buildmaster.tests.mock_workers import (
    BrokenWorker,
    BuildingWorker,
    LostBuildingBrokenWorker,
    MockBuilder,
    OkWorker,
    TrivialBehaviour,
    WaitingWorker,
    make_publisher,
)
from lp.buildmaster.tests.test_interactor import (
    FakeBuildQueue,
    MockBuilderFactory,
)
from lp.registry.interfaces.distribution import IDistributionSet
from lp.services.config import config
from lp.services.log.logger import BufferLogger
from lp.services.statsd.tests import StatsMixin
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.model.binarypackagebuildbehaviour import (
    BinaryPackageBuildBehaviour,
)
from lp.testing import (
    ANONYMOUS,
    StormStatementRecorder,
    TestCase,
    TestCaseWithFactory,
    login,
)
from lp.testing.dbuser import switch_dbuser
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import (
    LaunchpadScriptLayer,
    LaunchpadZopelessLayer,
    ZopelessDatabaseLayer,
)
from lp.testing.matchers import HasQueryCount
from lp.testing.sampledata import BOB_THE_BUILDER_NAME


class TestWorkerScannerScan(StatsMixin, TestCaseWithFactory):
    """Tests `WorkerScanner.scan` method.

    This method uses the old framework for scanning and dispatching builds.
    """

    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def setUp(self):
        """Make it possible to dispatch builds."""
        super().setUp()
        # Creating the required chroots needed for dispatching.
        self.test_publisher = make_publisher()
        ubuntu = getUtility(IDistributionSet).getByName("ubuntu")
        hoary = ubuntu.getSeries("hoary")
        self.test_publisher.setUpDefaultDistroSeries(hoary)
        self.test_publisher.addFakeChroots(db_only=True)
        self.addCleanup(shut_down_default_process_pool)
        self.setUpStats()

    def _resetBuilder(self, builder):
        """Reset the given builder and its job."""

        builder.builderok = True
        job = builder.currentjob
        if job is not None:
            job.reset()
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)

        transaction.commit()

    def assertBuildingJob(self, job, builder, logtail=None):
        """Assert the given job is building on the given builder."""
        if logtail is None:
            logtail = "Dummy sampledata entry, not processing"

        self.assertTrue(job is not None)
        self.assertEqual(job.builder, builder)
        self.assertTrue(job.date_started is not None)
        self.assertEqual(job.status, BuildQueueStatus.RUNNING)
        self.assertEqual(job.specific_build.status, BuildStatus.BUILDING)
        self.assertEqual(job.logtail, logtail)

    def _getScanner(
        self,
        builder_name=None,
        clock=None,
        builder_factory=None,
        scan_failure_count=0,
    ):
        """Instantiate a WorkerScanner object.

        Replace its default logging handler by a testing version.
        """
        if builder_name is None:
            builder_name = BOB_THE_BUILDER_NAME
        if builder_factory is None:
            builder_factory = BuilderFactory()
        manager = BuilddManager(builder_factory=builder_factory, clock=clock)
        manager.logger = BufferLogger()
        scanner = WorkerScanner(
            builder_name, builder_factory, manager, BufferLogger(), clock=clock
        )
        scanner.logger.name = "worker-scanner"
        scanner.scan_failure_count = scan_failure_count

        return scanner

    @defer.inlineCallbacks
    def testScanDispatchForResetBuilder(self):
        # A job gets dispatched to the sampledata builder after it's reset.

        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
        # Set this to 1 here so that _checkDispatch can make sure it's
        # reset to 0 after a successful dispatch.
        builder.failure_count = 1
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)

        # Run 'scan' and check its result.
        switch_dbuser(config.builddmaster.dbuser)
        scanner = self._getScanner()
        yield scanner.scan()
        self.assertEqual(0, builder.failure_count)
        self.assertTrue(builder.currentjob is not None)

    def _checkNoDispatch(self, builder):
        """Assert that no dispatch has occurred."""
        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertTrue(builder.builderok)
        self.assertTrue(builder.currentjob is None)

    def _checkJobRescued(self, builder, job):
        """`WorkerScanner.scan` rescued the job.

        Nothing gets dispatched,  the 'broken' builder remained disabled
        and the 'rescued' job is ready to be dispatched.
        """
        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertFalse(builder.builderok)

        job = getUtility(IBuildQueueSet).get(job.id)
        self.assertTrue(job.builder is None)
        self.assertTrue(job.date_started is None)
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(job)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    @defer.inlineCallbacks
    def testScanRescuesJobFromBrokenBuilder(self):
        # The job assigned to a broken builder is rescued.
        # Sampledata builder is enabled and is assigned to an active job.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self.patch(
            BuilderWorker,
            "makeBuilderWorker",
            FakeMethod(BuildingWorker(build_id="PACKAGEBUILD-8")),
        )
        self.assertTrue(builder.builderok)
        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        scanner = self._getScanner()
        yield scanner.scan()
        self.assertIsNot(None, builder.currentjob)

        # Disable the sampledata builder
        builder.builderok = False
        transaction.commit()

        # Run 'scan' and check its result.
        yield scanner.scan()
        self.assertIs(None, builder.currentjob)
        self._checkJobRescued(builder, job)

    def _checkJobUpdated(self, builder, job, logtail="This is a build log: 0"):
        """`WorkerScanner.scan` updates legitimate jobs.

        Job is kept assigned to the active builder and its 'logtail' is
        updated.
        """
        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertTrue(builder.builderok)

        job = getUtility(IBuildQueueSet).get(job.id)
        self.assertBuildingJob(job, builder, logtail=logtail)

    @defer.inlineCallbacks
    def testScanUpdatesBuildingJobs(self):
        # Enable sampledata builder attached to an appropriate testing
        # worker. It will respond as if it was building the sampledata job.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]

        login("foo.bar@canonical.com")
        builder.builderok = True
        self.patch(
            BuilderWorker,
            "makeBuilderWorker",
            FakeMethod(BuildingWorker(build_id="PACKAGEBUILD-8")),
        )
        transaction.commit()
        login(ANONYMOUS)

        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        # Run 'scan' and check its result.
        switch_dbuser(config.builddmaster.dbuser)
        scanner = self._getScanner()
        yield scanner.scan()
        scanner.manager.flushLogTails()
        self._checkJobUpdated(builder, job)

    @defer.inlineCallbacks
    def test_scan_with_nothing_to_dispatch(self):
        factory = LaunchpadObjectFactory()
        builder = factory.makeBuilder()
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
        transaction.commit()
        scanner = self._getScanner(builder_name=builder.name)
        yield scanner.scan()
        self._checkNoDispatch(builder)

    @defer.inlineCallbacks
    def test_scan_with_manual_builder(self):
        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
        builder.manual = True
        transaction.commit()
        scanner = self._getScanner()
        yield scanner.scan()
        self._checkNoDispatch(builder)

    @defer.inlineCallbacks
    def test_scan_with_not_ok_builder(self):
        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
        builder.builderok = False
        transaction.commit()
        scanner = self._getScanner()
        yield scanner.scan()
        # Because the builder is not ok, we can't use _checkNoDispatch.
        self.assertIsNone(builder.currentjob)

    @defer.inlineCallbacks
    def test_scan_of_broken_worker(self):
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        self.patch(
            BuilderWorker, "makeBuilderWorker", FakeMethod(BrokenWorker())
        )
        builder.failure_count = 0
        transaction.commit()
        scanner = self._getScanner(builder_name=builder.name)
        with ExpectedException(xmlrpc.client.Fault):
            yield scanner.scan()

    @defer.inlineCallbacks
    def test_scan_of_partial_utf8_logtail(self):
        # The builder returns a fixed number of bytes from the tail of the
        # log, so the first character can easily end up being invalid UTF-8.
        class BrokenUTF8Worker(BuildingWorker):
            @defer.inlineCallbacks
            def status(self):
                status = yield super().status()
                status["logtail"] = xmlrpc.client.Binary("───".encode()[1:])
                return status

        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        login("foo.bar@canonical.com")
        builder.builderok = True
        self.patch(
            BuilderWorker,
            "makeBuilderWorker",
            FakeMethod(BrokenUTF8Worker(build_id="PACKAGEBUILD-8")),
        )
        transaction.commit()
        login(ANONYMOUS)

        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        switch_dbuser(config.builddmaster.dbuser)
        scanner = self._getScanner()
        yield scanner.scan()
        scanner.manager.flushLogTails()
        self._checkJobUpdated(builder, job, logtail="\uFFFD\uFFFD──")

    @defer.inlineCallbacks
    def test_scan_of_logtail_containing_nul(self):
        # PostgreSQL text columns can't store ASCII NUL (\0) characters, so
        # we make sure to filter those out of the logtail.
        class NULWorker(BuildingWorker):
            @defer.inlineCallbacks
            def status(self):
                status = yield super().status()
                status["logtail"] = xmlrpc.client.Binary(b"foo\0bar\0baz")
                return status

        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        login("foo.bar@canonical.com")
        builder.builderok = True
        self.patch(
            BuilderWorker,
            "makeBuilderWorker",
            FakeMethod(NULWorker(build_id="PACKAGEBUILD-8")),
        )
        transaction.commit()
        login(ANONYMOUS)

        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        switch_dbuser(config.builddmaster.dbuser)
        scanner = self._getScanner()
        yield scanner.scan()
        scanner.manager.flushLogTails()
        self._checkJobUpdated(builder, job, logtail="foobarbaz")

    @defer.inlineCallbacks
    def test_scan_calls_builder_factory_prescanUpdate(self):
        # WorkerScanner.scan() starts by calling
        # BuilderFactory.prescanUpdate() to eg. perform necessary
        # transaction management.
        bf = BuilderFactory()
        bf.prescanUpdate = FakeMethod()
        scanner = self._getScanner(builder_factory=bf)

        # Disable the builder so we don't try to use the worker. It's not
        # relevant for this test.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        builder.builderok = False
        transaction.commit()

        yield scanner.scan()

        self.assertEqual(1, bf.prescanUpdate.call_count)

    @defer.inlineCallbacks
    def test_scan_skipped_if_builderfactory_stale(self):
        # singleCycle does nothing if the BuilderFactory's update
        # timestamp is older than the end of the previous scan. This
        # prevents eg. a scan after a dispatch from failing to notice
        # that a build has been dispatched.
        pbf = PrefetchedBuilderFactory()
        pbf.update()
        scanner = self._getScanner(builder_factory=pbf)
        fake_scan = FakeMethod()

        def _fake_scan():
            fake_scan()
            return defer.succeed(None)

        scanner.scan = _fake_scan
        self.assertEqual(0, fake_scan.call_count)

        # An initial cycle triggers a scan.
        yield scanner.singleCycle()
        self.assertEqual(1, fake_scan.call_count)

        # But a subsequent cycle without updating BuilderFactory's data
        # is a no-op.
        yield scanner.singleCycle()
        self.assertEqual(1, fake_scan.call_count)

        # Updating the BuilderFactory causes scans to resume.
        pbf.update()
        yield scanner.singleCycle()
        self.assertEqual(2, fake_scan.call_count)

    @defer.inlineCallbacks
    def test_scan_of_snap_build(self):
        # Snap builds return additional status information, which the scan
        # collects.
        class SnapBuildingWorker(BuildingWorker):
            revision_id = None

            @defer.inlineCallbacks
            def status(self):
                status = yield super().status()
                status["revision_id"] = self.revision_id
                return status

        build = self.factory.makeSnapBuild(
            distroarchseries=self.test_publisher.distroseries.architectures[0]
        )
        job = build.queueBuild()
        builder = self.factory.makeBuilder(
            processors=[job.processor], vm_host="fake_vm_host"
        )
        job.markAsBuilding(builder)
        worker = SnapBuildingWorker(build_id="SNAPBUILD-%d" % build.id)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(worker))
        transaction.commit()
        scanner = self._getScanner(builder_name=builder.name)
        yield scanner.scan()
        yield scanner.manager.flushLogTails()
        self.assertBuildingJob(job, builder, logtail="This is a build log: 0")
        self.assertIsNone(build.revision_id)
        worker.revision_id = "dummy"
        scanner = self._getScanner(builder_name=builder.name)
        yield scanner.scan()
        yield scanner.manager.flushLogTails()
        self.assertBuildingJob(job, builder, logtail="This is a build log: 1")
        self.assertEqual("dummy", build.revision_id)

    @defer.inlineCallbacks
    def _assertFailureCounting(
        self,
        scan_count,
        builder_count,
        job_count,
        expected_builder_count,
        expected_job_count,
    ):
        # If scan() fails with an exception, failure_counts should be
        # incremented.  What we do with the results of the failure
        # counts is tested below separately, this test just makes sure that
        # scan() is setting the counts.
        def failing_scan():
            return defer.fail(Exception("fake exception"))

        scanner = self._getScanner(scan_failure_count=scan_count)
        scanner.scan = failing_scan
        from lp.buildmaster import manager as manager_module

        self.patch(manager_module, "recover_failure", FakeMethod())
        builder = getUtility(IBuilderSet)[scanner.builder_name]

        builder.failure_count = builder_count
        naked_build = removeSecurityProxy(builder.current_build)
        naked_build.failure_count = job_count
        # The _scanFailed() calls abort, so make sure our existing
        # failure counts are persisted.
        transaction.commit()

        # singleCycle() calls scan() which is our fake one that throws an
        # exception.
        yield scanner.singleCycle()

        # Failure counts should be updated, and the assessment method
        # should have been called.  The actual behaviour is tested below
        # in TestFailureAssessments.
        self.assertEqual(expected_builder_count, builder.failure_count)
        self.assertEqual(
            expected_job_count, builder.current_build.failure_count
        )
        self.assertEqual(1, manager_module.recover_failure.call_count)

    @defer.inlineCallbacks
    def test_scan_persistent_failure_counts(self):
        # The first few scan exceptions just result in retries, not penalties
        # for the involved parties. A builder or job failure is only recorded
        # after several scan failures.
        scanner = self._getScanner()
        builder = getUtility(IBuilderSet)[scanner.builder_name]
        transaction.commit()

        self.patch(scanner, "scan", lambda: defer.fail(Exception("fake")))

        # Rack up almost enough failures.
        for i in range(1, SCAN_FAILURE_THRESHOLD):
            yield scanner.singleCycle()
            self.assertEqual(i, scanner.scan_failure_count)
            self.assertEqual(0, builder.failure_count)
            self.assertEqual(0, builder.current_build.failure_count)

        # Once we reach the consecutive failure threshold, the builder and
        # build each get a failure and the count is reset.
        yield scanner.singleCycle()
        self.assertEqual(0, scanner.scan_failure_count)
        self.assertEqual(1, builder.failure_count)
        self.assertEqual(1, builder.current_build.failure_count)

    @defer.inlineCallbacks
    def test_scan_intermittent_failure_retries(self):
        # A successful scan after a few failures resets the failure count.
        scanner = self._getScanner()
        builder = getUtility(IBuilderSet)[scanner.builder_name]
        transaction.commit()

        # Rack up a couple of failures.
        self.patch(scanner, "scan", lambda: defer.fail(Exception("fake")))

        yield scanner.singleCycle()
        self.assertEqual(1, scanner.scan_failure_count)
        self.assertEqual(0, builder.failure_count)
        self.assertEqual(0, builder.current_build.failure_count)
        self.assertEqual(
            [
                mock.call(
                    "builders.failure.scan_failed,arch=386,build=True,"
                    "builder_name=bob,env=test,job_type=PACKAGEBUILD,region=,"
                    "virtualized=False"
                ),
                mock.call(
                    "builders.failure.scan_retried,arch=386,build=True,"
                    "builder_name=bob,env=test,failures=1,"
                    "job_type=PACKAGEBUILD,region=,virtualized=False"
                ),
            ],
            self.stats_client.incr.mock_calls,
        )
        self.stats_client.incr.reset_mock()

        yield scanner.singleCycle()
        self.assertEqual(2, scanner.scan_failure_count)
        self.assertEqual(0, builder.failure_count)
        self.assertEqual(0, builder.current_build.failure_count)
        self.assertEqual(
            [
                mock.call(
                    "builders.failure.scan_failed,arch=386,build=True,"
                    "builder_name=bob,env=test,job_type=PACKAGEBUILD,"
                    "region=,virtualized=False"
                ),
                mock.call(
                    "builders.failure.scan_retried,arch=386,build=True,"
                    "builder_name=bob,env=test,failures=2,"
                    "job_type=PACKAGEBUILD,region=,virtualized=False"
                ),
            ],
            self.stats_client.incr.mock_calls,
        )
        self.stats_client.incr.reset_mock()

        # Since we didn't meet SCAN_FAILURE_THRESHOLD, a success just resets
        # the count and no harm is done to innocent bystanders.
        self.patch(scanner, "scan", lambda: defer.succeed(None))
        yield scanner.singleCycle()
        self.assertEqual(0, scanner.scan_failure_count)
        self.assertEqual(0, builder.failure_count)
        self.assertEqual(0, builder.current_build.failure_count)
        self.assertEqual([], self.stats_client.incr.mock_calls)
        self.stats_client.incr.reset_mock()

    def test_scan_first_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        return self._assertFailureCounting(
            scan_count=SCAN_FAILURE_THRESHOLD - 1,
            builder_count=0,
            job_count=0,
            expected_builder_count=1,
            expected_job_count=1,
        )

    def test_scan_second_builder_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        return self._assertFailureCounting(
            scan_count=SCAN_FAILURE_THRESHOLD - 1,
            builder_count=1,
            job_count=0,
            expected_builder_count=2,
            expected_job_count=1,
        )

    def test_scan_second_job_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        return self._assertFailureCounting(
            scan_count=SCAN_FAILURE_THRESHOLD - 1,
            builder_count=0,
            job_count=1,
            expected_builder_count=1,
            expected_job_count=2,
        )

    @defer.inlineCallbacks
    def test_scanFailed_handles_lack_of_a_job_on_the_builder(self):
        def failing_scan():
            return defer.fail(Exception("fake exception"))

        scanner = self._getScanner(
            scan_failure_count=SCAN_FAILURE_THRESHOLD - 1
        )
        scanner.scan = failing_scan
        builder = getUtility(IBuilderSet)[scanner.builder_name]
        builder.failure_count = BUILDER_FAILURE_THRESHOLD
        builder.currentjob.reset()
        transaction.commit()

        yield scanner.singleCycle()
        self.assertFalse(builder.builderok)

    @defer.inlineCallbacks
    def test_scanFailed_increments_counter(self):
        def failing_scan():
            return defer.fail(Exception("fake exception"))

        # TODO: Add and test metrics for retried scan failures.
        scanner = self._getScanner(
            scan_failure_count=SCAN_FAILURE_THRESHOLD - 1
        )
        scanner.scan = failing_scan
        builder = getUtility(IBuilderSet)[scanner.builder_name]
        builder.failure_count = BUILDER_FAILURE_THRESHOLD
        builder.currentjob.reset()
        transaction.commit()

        yield scanner.singleCycle()
        self.assertEqual(3, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "build.reset,arch=386,env=test,job_type=PACKAGEBUILD"
                ),
                mock.call(
                    "builders.failure.scan_failed,builder_name=bob,env=test,"
                    "region=,virtualized=False"
                ),
                mock.call(
                    "builders.failure.builder_failed,builder_name=bob,"
                    "env=test,region=,virtualized=False"
                ),
            ]
        )

    @defer.inlineCallbacks
    def test_fail_to_resume_leaves_it_dirty(self):
        # If an attempt to resume a worker fails, its failure count is
        # incremented and it is left DIRTY.

        # Make a worker with a failing resume() method.
        worker = OkWorker()
        worker.resume = lambda: deferLater(
            reactor, 0, defer.fail, Failure(("out", "err", 1))
        )

        # Reset sampledata builder.
        builder = removeSecurityProxy(
            getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        )
        self._resetBuilder(builder)
        builder.setCleanStatus(BuilderCleanStatus.DIRTY)
        builder.virtualized = True
        self.assertEqual(0, builder.failure_count)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(worker))
        builder.vm_host = "fake_vm_host"
        transaction.commit()

        # A spin of the scanner will see the DIRTY builder and reset it.
        # Our patched reset will fail.
        yield self._getScanner().singleCycle()

        # The failure_count will have been incremented on the builder,
        # and it will be left DIRTY.
        self.assertEqual(1, builder.failure_count)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

    @defer.inlineCallbacks
    def test_isolation_error_means_death(self):
        # Certain failures immediately kill both the job and the
        # builder. For example, a building builder that isn't dirty
        # probably indicates some potentially grave security bug.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        build = builder.current_build
        self.assertIsNotNone(build.buildqueue_record)
        self.assertEqual(BuildStatus.BUILDING, build.status)
        self.assertEqual(0, build.failure_count)
        self.assertEqual(0, builder.failure_count)
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        transaction.commit()
        yield self._getScanner().singleCycle()
        self.assertFalse(builder.builderok)
        self.assertEqual(
            "Non-dirty builder allegedly building.", builder.failnotes
        )
        self.assertIsNone(build.buildqueue_record)
        self.assertEqual(BuildStatus.FAILEDTOBUILD, build.status)

    @defer.inlineCallbacks
    def test_update_worker_version(self):
        # If the reported worker version differs from the DB's record of it,
        # then scanning the builder updates the DB.
        worker = OkWorker(version="100")
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        builder.version = "99"
        self._resetBuilder(builder)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(worker))
        scanner = self._getScanner()
        yield scanner.scan()
        self.assertEqual("100", builder.version)

    def test_updateVersion_no_op(self):
        # If the worker version matches the DB, then updateVersion does not
        # touch the DB.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        builder.version = "100"
        transaction.commit()
        vitals = extract_vitals_from_db(builder)
        scanner = self._getScanner()
        with StormStatementRecorder() as recorder:
            scanner.updateVersion(vitals, {"builder_version": "100"})
        self.assertThat(recorder, HasQueryCount(Equals(0)))

    @defer.inlineCallbacks
    def test_cancelling_a_build(self):
        # When scanning an in-progress build, if its state is CANCELLING
        # then the build should be aborted, and eventually stopped and moved
        # to the CANCELLED state if it does not abort by itself.

        # Set up a mock building worker.
        worker = BuildingWorker()

        # Set the sample data builder building with the worker from above.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        login("foo.bar@canonical.com")
        builder.builderok = True
        # For now, we can only cancel virtual builds.
        builder.virtualized = True
        builder.vm_host = "fake_vm_host"
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(worker))
        transaction.commit()
        login(ANONYMOUS)
        buildqueue = builder.currentjob
        worker.build_id = buildqueue.build_cookie
        self.assertBuildingJob(buildqueue, builder)

        # Now set the build to CANCELLING.
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(buildqueue)
        build.cancel()

        # Run 'scan' and check its results.
        switch_dbuser(config.builddmaster.dbuser)
        clock = task.Clock()
        scanner = self._getScanner(
            clock=clock, scan_failure_count=SCAN_FAILURE_THRESHOLD - 1
        )
        yield scanner.scan()

        # An abort request should be sent.
        self.assertEqual(1, worker.call_log.count("abort"))
        self.assertEqual(BuildStatus.CANCELLING, build.status)

        # Advance time a little.  Nothing much should happen.
        clock.advance(1)
        scanner.scan_failure_count = SCAN_FAILURE_THRESHOLD - 1
        yield scanner.scan()
        self.assertEqual(1, worker.call_log.count("abort"))
        self.assertEqual(BuildStatus.CANCELLING, build.status)

        # Advance past the timeout.  The build state should be cancelled and
        # we should have also called the resume() method on the worker that
        # resets the virtual machine.
        clock.advance(WorkerScanner.CANCEL_TIMEOUT)
        scanner.scan_failure_count = SCAN_FAILURE_THRESHOLD - 1
        yield scanner.singleCycle()
        self.assertEqual(1, worker.call_log.count("abort"))
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)
        self.assertEqual(BuildStatus.CANCELLED, build.status)


class TestWorkerScannerWithLibrarian(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def setUp(self):
        super().setUp()
        self.addCleanup(shut_down_default_process_pool)

    @defer.inlineCallbacks
    def test_end_to_end(self):
        # Test that WorkerScanner.scan() successfully finds, dispatches,
        # collects and cleans a build, and then makes a reasonable start on
        # a second build.
        build = self.factory.makeBinaryPackageBuild()
        build.distro_arch_series.addOrUpdateChroot(
            self.factory.makeLibraryFileAlias(db_only=True)
        )
        bq = build.queueBuild()
        bq.manualScore(9000)
        build2 = self.factory.makeBinaryPackageBuild(
            distroarchseries=build.distro_arch_series
        )
        bq2 = build2.queueBuild()
        bq2.manualScore(8900)

        builder = self.factory.makeBuilder(
            processors=[bq.processor], manual=False, vm_host="VMHOST"
        )
        transaction.commit()

        # Mock out the build behaviour's handleSuccess so it doesn't
        # try to upload things to the librarian or queue.
        def handleSuccess(self, worker_status, logger):
            return BuildStatus.UPLOADING

        self.patch(BinaryPackageBuildBehaviour, "handleSuccess", handleSuccess)

        # And create a WorkerScanner with a worker and a clock that we
        # control.
        get_worker = FakeMethod(OkWorker())
        clock = task.Clock()
        manager = BuilddManager(clock=clock)
        manager.logger = BufferLogger()
        scanner = WorkerScanner(
            builder.name,
            BuilderFactory(),
            manager,
            BufferLogger(),
            worker_factory=get_worker,
            clock=clock,
        )

        # The worker is idle and dirty, so the first scan will clean it
        # with a reset.
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)
        yield scanner.scan()
        self.assertEqual(["resume", "echo"], get_worker.result.method_log)
        self.assertEqual(BuilderCleanStatus.CLEAN, builder.clean_status)
        self.assertIs(None, builder.currentjob)

        # The worker is idle and clean, and there's a build candidate, so
        # the next scan will dispatch the build.
        get_worker.result = OkWorker()
        yield scanner.scan()
        self.assertEqual(
            ["status", "ensurepresent", "build"], get_worker.result.method_log
        )
        self.assertEqual(bq, builder.currentjob)
        self.assertEqual(BuildQueueStatus.RUNNING, bq.status)
        self.assertEqual(BuildStatus.BUILDING, build.status)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

        # build() has been called, so switch in a BUILDING worker.
        # Scans will now just do a status() each, as the logtail is
        # updated.
        get_worker.result = BuildingWorker(build.build_cookie)
        yield scanner.scan()
        yield scanner.manager.flushLogTails()
        self.assertEqual("This is a build log: 0", bq.logtail)
        yield scanner.scan()
        yield scanner.manager.flushLogTails()
        self.assertEqual("This is a build log: 1", bq.logtail)
        yield scanner.scan()
        yield scanner.manager.flushLogTails()
        self.assertEqual("This is a build log: 2", bq.logtail)
        self.assertEqual(
            ["status", "status", "status"], get_worker.result.method_log
        )

        # When the build finishes, the scanner will notice and call
        # handleStatus(). Our fake handleSuccess() doesn't do anything
        # special, but there'd usually be file retrievals in the middle,
        # and the log is retrieved by handleStatus() afterwards.
        # The builder remains dirty afterward.
        get_worker.result = WaitingWorker(build_id=build.build_cookie)
        yield scanner.scan()
        self.assertEqual(["status", "getFile"], get_worker.result.method_log)
        self.assertIs(None, builder.currentjob)
        self.assertEqual(BuildStatus.UPLOADING, build.status)
        self.assertEqual(builder, build.builder)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

        # We're idle and dirty, so let's flip back to an idle worker and
        # confirm that the worker gets cleaned.
        get_worker.result = OkWorker()
        yield scanner.scan()
        self.assertEqual(["resume", "echo"], get_worker.result.method_log)
        self.assertIs(None, builder.currentjob)
        self.assertEqual(BuilderCleanStatus.CLEAN, builder.clean_status)

        # Now we can go round the loop again with a second build.  (We only
        # go far enough to ensure that the lost-job check works on the
        # second iteration.)
        get_worker.result = OkWorker()
        yield scanner.scan()
        self.assertEqual(
            ["status", "ensurepresent", "build"], get_worker.result.method_log
        )
        self.assertEqual(bq2, builder.currentjob)
        self.assertEqual(BuildQueueStatus.RUNNING, bq2.status)
        self.assertEqual(BuildStatus.BUILDING, build2.status)
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

        get_worker.result = BuildingWorker(build2.build_cookie)
        yield scanner.scan()
        yield scanner.manager.flushLogTails()
        self.assertEqual("This is a build log: 0", bq2.logtail)


class TestPrefetchedBuilderFactory(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def test_get(self):
        # PrefetchedBuilderFactory.__getitem__ is unoptimised, just
        # querying and returning the named builder.
        builder = self.factory.makeBuilder()
        pbf = PrefetchedBuilderFactory()
        self.assertEqual(builder, pbf[builder.name])

    def test_update(self):
        # update grabs all of the Builders and their BuildQueues in a
        # single query, plus an additional two queries to grab all the
        # associated Processors.
        builders = [self.factory.makeBuilder() for i in range(5)]
        for i in range(3):
            bq = self.factory.makeBinaryPackageBuild().queueBuild()
            bq.markAsBuilding(builders[i])
        pbf = PrefetchedBuilderFactory()
        transaction.commit()
        pbf.update()
        with StormStatementRecorder() as recorder:
            pbf.update()
        self.assertThat(recorder, HasQueryCount(Equals(3)))

    def test_getVitals(self):
        # PrefetchedBuilderFactory.getVitals looks up the BuilderVitals
        # in a local cached map, without hitting the DB.
        builder = self.factory.makeBuilder()
        bq = self.factory.makeBinaryPackageBuild().queueBuild()
        bq.markAsBuilding(builder)
        transaction.commit()
        name = builder.name
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        def assertQuerylessVitals(comparator):
            expected_vitals = extract_vitals_from_db(builder)
            transaction.commit()
            with StormStatementRecorder() as recorder:
                got_vitals = pbf.getVitals(name)
                comparator(expected_vitals, got_vitals)
                comparator(expected_vitals.build_queue, got_vitals.build_queue)
            self.assertThat(recorder, HasQueryCount(Equals(0)))
            return got_vitals

        # We can get the vitals of a builder from the factory without
        # any DB queries.
        vitals = assertQuerylessVitals(self.assertEqual)
        self.assertIsNot(None, vitals.build_queue)

        # If we cancel the BuildQueue to unassign it, the factory
        # doesn't notice immediately.
        bq.markAsCancelled()
        vitals = assertQuerylessVitals(self.assertNotEqual)
        self.assertIsNot(None, vitals.build_queue)

        # But the vitals will show the builder as idle if we ask the
        # factory to refetch.
        pbf.update()
        vitals = assertQuerylessVitals(self.assertEqual)
        self.assertIs(None, vitals.build_queue)

    def test_iterVitals(self):
        # PrefetchedBuilderFactory.iterVitals looks up the details from
        # the local cached map, without hitting the DB.

        # Construct 5 new builders, 3 with builds. This is in addition
        # to the 2 in sampledata, 1 with a build.
        builders = [self.factory.makeBuilder() for i in range(5)]
        for i in range(3):
            bq = self.factory.makeBinaryPackageBuild().queueBuild()
            bq.markAsBuilding(builders[i])
        transaction.commit()
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        with StormStatementRecorder() as recorder:
            all_vitals = list(pbf.iterVitals())
        self.assertThat(recorder, HasQueryCount(Equals(0)))
        # Compare the counts with what we expect, and the full result
        # with the non-prefetching BuilderFactory.
        self.assertEqual(7, len(all_vitals))
        self.assertEqual(
            SCAN_FAILURE_THRESHOLD - 1,
            len([v for v in all_vitals if v.build_queue is not None]),
        )
        self.assertContentEqual(BuilderFactory().iterVitals(), all_vitals)

    def test_findBuildCandidate_avoids_duplicates(self):
        # findBuildCandidate removes the job it finds from its internal list
        # of candidates, so a second call returns a different job.
        das = self.factory.makeDistroArchSeries()
        builders = [
            self.factory.makeBuilder(processors=[das.processor])
            for _ in range(2)
        ]
        builder_names = [builder.name for builder in builders]
        for _ in range(5):
            self.factory.makeBinaryPackageBuild(
                distroarchseries=das
            ).queueBuild()
        transaction.commit()
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        candidate0 = pbf.findBuildCandidate(pbf.getVitals(builder_names[0]))
        self.assertIsNotNone(candidate0)
        transaction.abort()
        with StormStatementRecorder() as recorder:
            candidate1 = pbf.findBuildCandidate(
                pbf.getVitals(builder_names[1])
            )
        self.assertIsNotNone(candidate1)
        self.assertNotEqual(candidate0, candidate1)
        # The second call made only a single query, to fetch the candidate
        # by ID.
        self.assertThat(recorder, HasQueryCount(Equals(1)))

    def test_findBuildCandidate_honours_resources(self):
        das = self.factory.makeDistroArchSeries()
        builders = [
            self.factory.makeBuilder(
                processors=[das.processor],
                open_resources=open_resources,
                restricted_resources=restricted_resources,
            )
            for open_resources, restricted_resources in (
                (None, None),
                (None, None),
                (["large"], None),
                (["large"], None),
                (["large"], None),
                (None, ["gpu"]),
                (None, ["gpu"]),
            )
        ]
        repository_plain, repository_large, repository_gpu = (
            self.factory.makeGitRepository(builder_constraints=constraints)
            for constraints in (None, ["large"], ["gpu"])
        )
        bq_plain, bq_large, bq_gpu = (
            self.factory.makeCIBuild(
                git_repository=repository, distro_arch_series=das
            ).queueBuild()
            for repository in (
                repository_plain,
                repository_large,
                repository_gpu,
            )
        )
        transaction.commit()
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        # PrefetchedBuilderFactory.findBuildCandidate finds the next build
        # candidate and removes it from its prefetched list for that
        # builder's "vitals" (identical for each group of builders with the
        # same properties), but it doesn't mark the candidate as building;
        # that's left to PrefetchedBuilderFactory.acquireBuildCandidate.  We
        # can thus determine the effective queue of builds for each group by
        # repeatedly calling findBuildCandidate for each of a group of
        # builders, even if some of those queues overlap.
        for builder, bq in zip(
            builders, [bq_plain, None, bq_plain, bq_large, None, bq_gpu, None]
        ):
            self.assertEqual(
                bq, pbf.findBuildCandidate(pbf.getVitals(builder.name))
            )

    def test_acquireBuildCandidate_marks_building(self):
        # acquireBuildCandidate calls findBuildCandidate and marks the build
        # as building.
        builder = self.factory.makeBuilder(virtualized=False)
        self.factory.makeBinaryPackageBuild().queueBuild()
        transaction.commit()
        pbf = PrefetchedBuilderFactory()
        pbf.update()

        candidate = pbf.acquireBuildCandidate(
            pbf.getVitals(builder.name), builder
        )
        self.assertEqual(BuildQueueStatus.RUNNING, candidate.status)


class FakeBuilddManager:
    """A minimal fake version of `BuilddManager`."""

    pending_logtails: Dict[int, str] = {}

    def addLogTail(self, build_queue_id, logtail):
        self.pending_logtails[build_queue_id] = logtail


class TestWorkerScannerWithoutDB(TestCase):
    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest

    def setUp(self):
        super().setUp()
        self.addCleanup(shut_down_default_process_pool)

    def getScanner(
        self,
        builder_factory=None,
        interactor=None,
        worker=None,
        behaviour=None,
    ):
        if builder_factory is None:
            builder_factory = MockBuilderFactory(
                MockBuilder(virtualized=False), None
            )
        if interactor is None:
            interactor = BuilderInteractor()
            interactor.updateBuild = FakeMethod()
        if worker is None:
            worker = OkWorker()
        if behaviour is None:
            behaviour = TrivialBehaviour()
        return WorkerScanner(
            "mock",
            builder_factory,
            FakeBuilddManager(),
            BufferLogger(),
            interactor_factory=FakeMethod(interactor),
            worker_factory=FakeMethod(worker),
            behaviour_factory=FakeMethod(behaviour),
        )

    @defer.inlineCallbacks
    def test_scan_with_job(self):
        # WorkerScanner.scan calls updateBuild() when a job is building.
        worker = BuildingWorker("trivial")
        bq = FakeBuildQueue("trivial")
        scanner = self.getScanner(
            builder_factory=MockBuilderFactory(MockBuilder(), bq),
            worker=worker,
        )

        yield scanner.scan()
        self.assertEqual(["status"], worker.call_log)
        self.assertEqual(
            1, scanner.interactor_factory.result.updateBuild.call_count
        )
        self.assertEqual(0, bq.reset.call_count)

    @defer.inlineCallbacks
    def test_scan_recovers_lost_worker_with_job(self):
        # WorkerScanner.scan identifies workers that aren't building what
        # they should be, resets the jobs, and then aborts the workers.
        worker = BuildingWorker("nontrivial")
        bq = FakeBuildQueue("trivial")
        builder = MockBuilder(virtualized=False)
        scanner = self.getScanner(
            builder_factory=MockBuilderFactory(builder, bq), worker=worker
        )

        # A single scan will call status(), notice that the worker is lost,
        # and reset() the job without calling updateBuild().
        yield scanner.scan()
        self.assertEqual(["status"], worker.call_log)
        self.assertEqual(
            0, scanner.interactor_factory.result.updateBuild.call_count
        )
        self.assertEqual(1, bq.reset.call_count)
        # The reset would normally have unset build_queue.
        scanner.builder_factory.updateTestData(builder, None)

        # The next scan will see a dirty idle builder with a BUILDING
        # worker, and abort() it.
        yield scanner.scan()
        self.assertEqual(["status", "status", "abort"], worker.call_log)

    @defer.inlineCallbacks
    def test_scan_recovers_lost_worker_when_idle(self):
        # WorkerScanner.scan identifies workers that are building when
        # they shouldn't be and aborts them.
        worker = BuildingWorker()
        scanner = self.getScanner(worker=worker)
        yield scanner.scan()
        self.assertEqual(["status", "abort"], worker.call_log)

    @defer.inlineCallbacks
    def test_scan_building_but_not_dirty_builder_explodes(self):
        # Builders with a build assigned must be dirty for safety
        # reasons. If we run into one that's clean, we blow up.
        worker = BuildingWorker()
        builder = MockBuilder(clean_status=BuilderCleanStatus.CLEAN)
        bq = FakeBuildQueue()
        scanner = self.getScanner(
            worker=worker, builder_factory=MockBuilderFactory(builder, bq)
        )

        with ExpectedException(
            BuildDaemonIsolationError, "Non-dirty builder allegedly building."
        ):
            yield scanner.scan()
        self.assertEqual([], worker.call_log)

    @defer.inlineCallbacks
    def test_scan_clean_but_not_idle_worker_explodes(self):
        # Clean builders by definition have workers that are idle. If
        # an ostensibly clean worker isn't idle, blow up.
        worker = BuildingWorker()
        builder = MockBuilder(clean_status=BuilderCleanStatus.CLEAN)
        scanner = self.getScanner(
            worker=worker, builder_factory=MockBuilderFactory(builder, None)
        )

        with ExpectedException(
            BuildDaemonIsolationError,
            r"Allegedly clean worker not idle \(%r instead\)"
            % "BuilderStatus.BUILDING",
        ):
            yield scanner.scan()
        self.assertEqual(["status"], worker.call_log)

    def test_getExpectedCookie_caches(self):
        bq = FakeBuildQueue("trivial")
        bf = MockBuilderFactory(MockBuilder(), bq)
        manager = BuilddManager()
        manager.logger = BufferLogger()
        scanner = WorkerScanner(
            "mock",
            bf,
            manager,
            BufferLogger(),
            interactor_factory=FakeMethod(None),
            worker_factory=FakeMethod(None),
            behaviour_factory=FakeMethod(TrivialBehaviour()),
        )

        # The first call retrieves the cookie from the BuildQueue.
        cookie1 = scanner.getExpectedCookie(bf.getVitals("foo"))
        self.assertEqual("trivial", cookie1)

        # A second call with the same BuildQueue will not reretrieve it.
        bq.build_cookie = "nontrivial"
        cookie2 = scanner.getExpectedCookie(bf.getVitals("foo"))
        self.assertEqual("trivial", cookie2)

        # But a call with a new BuildQueue will regrab.
        bf.updateTestData(bf._builder, FakeBuildQueue("complicated"))
        cookie3 = scanner.getExpectedCookie(bf.getVitals("foo"))
        self.assertEqual("complicated", cookie3)

        # And unsetting the BuildQueue returns None again.
        bf.updateTestData(bf._builder, None)
        cookie4 = scanner.getExpectedCookie(bf.getVitals("foo"))
        self.assertIs(None, cookie4)


class TestJudgeFailure(TestCase):
    def test_same_count_below_threshold(self):
        # A few consecutive failures aren't any cause for alarm, as it
        # could just be a network glitch.
        self.assertEqual(
            (None, None),
            judge_failure(
                JOB_RESET_THRESHOLD - 1, JOB_RESET_THRESHOLD - 1, Exception()
            ),
        )

    def test_same_count_exceeding_threshold(self):
        # Several consecutive failures suggest that something might be
        # up. The job is retried elsewhere.
        self.assertEqual(
            (None, True),
            judge_failure(
                JOB_RESET_THRESHOLD, JOB_RESET_THRESHOLD, Exception()
            ),
        )

    def test_same_count_no_retries(self):
        # A single failure of both causes a job reset if retries are
        # forbidden.
        self.assertEqual(
            (None, True),
            judge_failure(
                JOB_RESET_THRESHOLD - 1,
                JOB_RESET_THRESHOLD - 1,
                Exception(),
                retry=False,
            ),
        )

    def test_bad_builder(self):
        # A bad builder resets its job and dirties itself. The next scan
        # will do what it can to recover it (resetting in the virtual
        # case, or just retrying for non-virts).
        self.assertEqual(
            (True, True),
            judge_failure(BUILDER_FAILURE_THRESHOLD - 1, 1, Exception()),
        )

    def test_bad_builder_gives_up(self):
        # A persistently bad builder resets its job and fails itself.
        self.assertEqual(
            (False, True),
            judge_failure(BUILDER_FAILURE_THRESHOLD, 1, Exception()),
        )

    def test_bad_job_fails(self):
        self.assertEqual((None, False), judge_failure(1, 2, Exception()))

    def test_isolation_violation_double_kills(self):
        self.assertEqual(
            (False, False), judge_failure(1, 1, BuildDaemonIsolationError())
        )


class TestCancellationChecking(TestCaseWithFactory):
    """Unit tests for the checkCancellation method."""

    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def setUp(self):
        super().setUp()
        builder_name = BOB_THE_BUILDER_NAME
        self.builder = getUtility(IBuilderSet)[builder_name]
        self.builder.virtualized = True
        self.addCleanup(shut_down_default_process_pool)

    @property
    def vitals(self):
        return extract_vitals_from_db(self.builder)

    def _getScanner(self, clock=None):
        manager = BuilddManager(clock=clock)
        manager.logger = BufferLogger()
        scanner = WorkerScanner(
            None, BuilderFactory(), manager, BufferLogger(), clock=clock
        )
        scanner.logger.name = "worker-scanner"
        return scanner

    def test_ignores_build_not_cancelling(self):
        # If the active build is not in a CANCELLING state, ignore it.
        worker = BuildingWorker()
        scanner = self._getScanner()
        yield scanner.checkCancellation(self.vitals, worker)
        self.assertEqual([], worker.call_log)

    @defer.inlineCallbacks
    def test_cancelling_build_is_aborted(self):
        # The first time we see a CANCELLING build, we abort the worker.
        worker = BuildingWorker()
        self.builder.current_build.cancel()
        scanner = self._getScanner()
        yield scanner.checkCancellation(self.vitals, worker)
        self.assertEqual(["abort"], worker.call_log)

        # A further scan is a no-op, as we remember that we've already
        # requested that the worker abort.
        yield scanner.checkCancellation(self.vitals, worker)
        self.assertEqual(["abort"], worker.call_log)

    @defer.inlineCallbacks
    def test_timed_out_cancel_errors(self):
        # If a BuildQueue is CANCELLING and the cancel timeout expires,
        # an exception is raised so the normal scan error handler can
        # finalise the build.
        worker = OkWorker()
        build = self.builder.current_build
        build.cancel()
        clock = task.Clock()
        scanner = self._getScanner(clock=clock)

        yield scanner.checkCancellation(self.vitals, worker)
        self.assertEqual(["abort"], worker.call_log)
        self.assertEqual(BuildStatus.CANCELLING, build.status)

        clock.advance(WorkerScanner.CANCEL_TIMEOUT)
        with ExpectedException(
            BuildWorkerFailure, "Timeout waiting for .* to cancel"
        ):
            yield scanner.checkCancellation(self.vitals, worker)

    @defer.inlineCallbacks
    def test_failed_abort_errors(self):
        # If the builder reports a fault while attempting to abort it,
        # an exception is raised so the build can be finalised.
        worker = LostBuildingBrokenWorker()
        self.builder.current_build.cancel()
        with ExpectedException(
            xmlrpc.client.Fault, "<Fault 8002: %r>" % "Could not abort"
        ):
            yield self._getScanner().checkCancellation(self.vitals, worker)


class TestBuilddManager(TestCase):
    layer = LaunchpadZopelessLayer

    def _stub_out_scheduleNextScanCycle(self):
        # stub out the code that adds a callLater, so that later tests
        # don't get surprises.
        self.patch(WorkerScanner, "startCycle", FakeMethod())

    def test_addScanForBuilders(self):
        # Test that addScanForBuilders generates WorkerScanner objects.
        self._stub_out_scheduleNextScanCycle()

        manager = BuilddManager()
        builder_names = {builder.name for builder in getUtility(IBuilderSet)}
        scanners = manager.addScanForBuilders(builder_names)
        scanner_names = {scanner.builder_name for scanner in scanners}
        self.assertEqual(builder_names, scanner_names)

    def test_startService_clears_grabbing(self):
        # When startService is called, the manager clears out the "grabbing"
        # directory.
        self._stub_out_scheduleNextScanCycle()
        tempdir = self.makeTemporaryDirectory()
        self.pushConfig("builddmaster", root=tempdir)
        os.makedirs(os.path.join(tempdir, "grabbing", "some-upload"))
        clock = task.Clock()
        manager = BuilddManager(clock=clock)

        manager.startService()

        self.assertFalse(os.path.exists(os.path.join(tempdir, "grabbing")))

    def test_startService_adds_scanBuilders_loop(self):
        # When startService is called, the manager will start up a
        # scanBuilders loop.
        self._stub_out_scheduleNextScanCycle()
        clock = task.Clock()
        manager = BuilddManager(clock=clock)

        # Replace scanBuilders() with FakeMethod so we can see if it was
        # called.
        manager.scanBuilders = FakeMethod()

        manager.startService()
        advance = BuilddManager.SCAN_BUILDERS_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, manager.scanBuilders.call_count)

    def test_startService_adds_flushLogTails_loop(self):
        # When startService is called, the manager will start up a
        # flushLogTails loop.
        self._stub_out_scheduleNextScanCycle()
        clock = task.Clock()
        manager = BuilddManager(clock=clock)

        # Replace flushLogTails() with FakeMethod so we can see if it was
        # called.
        manager.flushLogTails = FakeMethod()

        manager.startService()
        advance = BuilddManager.FLUSH_LOGTAILS_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, manager.flushLogTails.call_count)


class TestFailureAssessmentsAndStatsdMetrics(StatsMixin, TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.builder = self.factory.makeBuilder()
        self.build = self.factory.makeSourcePackageRecipeBuild()
        self.buildqueue = self.build.queueBuild()
        self.buildqueue.markAsBuilding(self.builder)
        self.worker = OkWorker()
        self.setUpStats()

    def _recover_failure(self, fail_notes, retry=True):
        # Helper for recover_failure boilerplate.
        logger = BufferLogger()
        recover_failure(
            logger,
            extract_vitals_from_db(self.builder),
            self.builder,
            retry,
            Exception(fail_notes),
        )
        return logger.getLogBuffer()

    def assert_statsd_metrics_requeue(self):
        build = removeSecurityProxy(self.build)
        self.assertEqual(2, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "builders.failure.job_reset,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region={},virtualized=True".format(
                        build.processor.name,
                        self.builder.name,
                        self.builder.region,
                    )
                ),
                mock.call(
                    "build.reset,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region={},"
                    "virtualized=True".format(
                        build.processor.name,
                        self.builder.name,
                        self.builder.region,
                    )
                ),
            ]
        )

    def test_job_reset_threshold_with_retry(self):
        naked_build = removeSecurityProxy(self.build)
        self.builder.failure_count = JOB_RESET_THRESHOLD - 1
        naked_build.failure_count = JOB_RESET_THRESHOLD - 1

        log = self._recover_failure("failnotes")
        self.assertNotIn("Requeueing job", log)
        self.assertIsNot(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.BUILDING)

        self.builder.failure_count += 1
        naked_build.failure_count += 1

        log = self._recover_failure("failnotes")
        self.assertIn("Requeueing job", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)
        self.assert_statsd_metrics_requeue()

    def test_job_reset_threshold_no_retry(self):
        naked_build = removeSecurityProxy(self.build)
        self.builder.failure_count = 1
        naked_build.failure_count = 1

        log = self._recover_failure("failnotes", retry=False)
        self.assertIn("Requeueing job", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.NEEDSBUILD)
        self.assert_statsd_metrics_requeue()

    def test_reset_during_cancellation_cancels(self):
        self.buildqueue.cancel()
        self.assertEqual(BuildStatus.CANCELLING, self.build.status)

        naked_build = removeSecurityProxy(self.build)
        self.builder.failure_count = 1
        naked_build.failure_count = 1

        log = self._recover_failure("failnotes")
        self.assertIn("Cancelling job", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)
        self.assertEqual(2, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "builders.failure.job_cancelled,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "build.finished,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region=builder-name,"
                    "status=CANCELLED,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
            ]
        )

    def test_job_failing_more_than_builder_fails_job(self):
        self.build.gotFailure()
        self.build.gotFailure()
        self.builder.gotFailure()
        naked_build = removeSecurityProxy(self.build)

        log = self._recover_failure("failnotes")
        self.assertIn("Failing job", log)
        self.assertIn("Resetting failure count of builder", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.FAILEDTOBUILD)
        self.assertEqual(0, self.builder.failure_count)
        self.assertEqual(2, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "build.finished,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region=builder-name,"
                    "status=FAILEDTOBUILD,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "builders.failure.job_failed,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
            ]
        )

    def test_bad_job_does_not_unsucceed(self):
        # If a FULLYBUILT build somehow ends up back in buildd-manager,
        # all manner of failures can occur as invariants are violated.
        # But we can't just fail and later retry the build as normal, as
        # a FULLYBUILT build has binaries. Instead, failure handling
        # just destroys the BuildQueue and leaves the status as
        # FULLYBUILT.
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.build.gotFailure()
        self.build.gotFailure()
        self.builder.gotFailure()
        naked_build = removeSecurityProxy(self.build)

        log = self._recover_failure("failnotes")
        self.assertIn("Failing job", log)
        self.assertIn("Build is already successful!", log)
        self.assertIn("Resetting failure count of builder", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(self.build.status, BuildStatus.FULLYBUILT)
        self.assertEqual(0, self.builder.failure_count)
        self.assertEqual(2, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "build.finished,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region=builder-name,"
                    "status=FULLYBUILT,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "builders.failure.job_failed,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
            ]
        )

    def test_failure_during_cancellation_cancels(self):
        self.buildqueue.cancel()
        self.assertEqual(BuildStatus.CANCELLING, self.build.status)

        self.build.gotFailure()
        self.build.gotFailure()
        self.builder.gotFailure()
        naked_build = removeSecurityProxy(self.build)
        log = self._recover_failure("failnotes")
        self.assertIn("Cancelling job", log)
        self.assertIn("Resetting failure count of builder", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)
        self.assertEqual(2, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "builders.failure.job_cancelled,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "build.finished,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region=builder-name,"
                    "status=CANCELLED,virtualized=True".format(
                        naked_build.processor.name,
                        self.builder.name,
                    )
                ),
            ]
        )

    def test_bad_builder(self):
        self.builder.setCleanStatus(BuilderCleanStatus.CLEAN)

        # The first few failures of a bad builder just reset the job and
        # mark the builder dirty. The next scan will reset a virtual
        # builder or attempt to clean up a non-virtual builder.
        self.builder.failure_count = BUILDER_FAILURE_THRESHOLD - 1
        self.assertIsNot(None, self.builder.currentjob)
        log = self._recover_failure("failnotes")
        self.assertIn("Requeueing job %s" % self.build.build_cookie, log)
        self.assertIn("Dirtying builder %s" % self.builder.name, log)
        self.assertIs(None, self.builder.currentjob)
        self.assertIs(None, self.build.builder)
        self.assertEqual(BuilderCleanStatus.DIRTY, self.builder.clean_status)
        self.assertTrue(self.builder.builderok)
        self.assertEqual(3, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "builders.failure.job_reset,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        self.build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "build.reset,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region=builder-name,"
                    "virtualized=True".format(
                        self.build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "builders.failure.builder_reset,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        self.build.processor.name,
                        self.builder.name,
                    )
                ),
            ]
        )
        self.stats_client.incr.reset_mock()

        # But if the builder continues to cause trouble, it will be
        # disabled.
        self.builder.failure_count = BUILDER_FAILURE_THRESHOLD
        self.buildqueue.markAsBuilding(self.builder)
        log = self._recover_failure("failnotes")
        self.assertIn("Requeueing job", log)
        self.assertIn("Failing builder", log)
        self.assertIs(None, self.builder.currentjob)
        self.assertIs(None, self.build.builder)
        self.assertEqual(BuilderCleanStatus.DIRTY, self.builder.clean_status)
        self.assertFalse(self.builder.builderok)
        self.assertEqual("failnotes", self.builder.failnotes)
        self.assertEqual(3, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "builders.failure.job_reset,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        self.build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "build.reset,arch={},builder_name={},env=test,"
                    "job_type=RECIPEBRANCHBUILD,region=builder-name,"
                    "virtualized=True".format(
                        self.build.processor.name,
                        self.builder.name,
                    )
                ),
                mock.call(
                    "builders.failure.builder_failed,arch={},build=True,"
                    "builder_name={},env=test,job_type=RECIPEBRANCHBUILD,"
                    "region=builder-name,virtualized=True".format(
                        self.build.processor.name,
                        self.builder.name,
                    )
                ),
            ]
        )
        self.stats_client.incr.reset_mock()

    def test_builder_failing_with_no_attached_job(self):
        self.buildqueue.reset()
        self.builder.failure_count = BUILDER_FAILURE_THRESHOLD
        self.stats_client.incr.reset_mock()

        log = self._recover_failure("failnotes")
        self.assertIn("with no job", log)
        self.assertIn("Failing builder", log)
        self.assertFalse(self.builder.builderok)
        self.assertEqual("failnotes", self.builder.failnotes)
        self.assertEqual(1, self.stats_client.incr.call_count)
        self.stats_client.incr.assert_has_calls(
            [
                mock.call(
                    "builders.failure.builder_failed,builder_name={},"
                    "env=test,region=builder-name,virtualized=True".format(
                        self.builder.name,
                    )
                ),
            ]
        )
        self.stats_client.incr.reset_mock()


class TestNewBuilders(TestCase):
    """Test detecting of new builders."""

    layer = LaunchpadZopelessLayer

    def _getManager(self, clock=None):
        manager = BuilddManager(clock=clock, builder_factory=BuilderFactory())
        manager.checkForNewBuilders()
        return manager

    def test_startService(self):
        # Test that startService calls the "scanBuilders" method.
        clock = task.Clock()
        manager = self._getManager(clock=clock)
        manager.scanBuilders = FakeMethod()
        manager.startService()
        self.addCleanup(manager.stopService)

        advance = manager.SCAN_BUILDERS_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(
            0,
            manager.scanBuilders.call_count,
            "startService did not schedule a scanBuilders loop",
        )

    def test_checkForNewBuilders(self):
        # Test that checkForNewBuilders() detects a new builder

        # The basic case, where no builders are added.
        manager = self._getManager()
        self.assertEqual([], manager.checkForNewBuilders())

        # Add two builders and ensure they're returned.
        new_builders = ["scooby", "lassie"]
        factory = LaunchpadObjectFactory()
        for builder_name in new_builders:
            factory.makeBuilder(name=builder_name)
        self.assertContentEqual(new_builders, manager.checkForNewBuilders())

    def test_checkForNewBuilders_detects_builder_only_once(self):
        # checkForNewBuilders() only detects a new builder once.
        manager = self._getManager()
        self.assertEqual([], manager.checkForNewBuilders())
        LaunchpadObjectFactory().makeBuilder(name="sammy")
        self.assertEqual(["sammy"], manager.checkForNewBuilders())
        self.assertEqual([], manager.checkForNewBuilders())

    def test_scanBuilders(self):
        # See if scanBuilders detects new builders.

        def fake_checkForNewBuilders():
            return "new_builders"

        def fake_addScanForBuilders(new_builders):
            self.assertEqual("new_builders", new_builders)

        clock = task.Clock()
        manager = self._getManager(clock=clock)
        manager.checkForNewBuilders = fake_checkForNewBuilders
        manager.addScanForBuilders = fake_addScanForBuilders
        manager.scheduleScan = FakeMethod()

        manager.scanBuilders()
        advance = manager.SCAN_BUILDERS_INTERVAL + 1
        clock.advance(advance)

    def test_scanBuilders_swallows_exceptions(self):
        # scanBuilders() swallows exceptions so the LoopingCall always
        # retries.
        clock = task.Clock()
        manager = self._getManager(clock=clock)
        manager.checkForNewBuilders = FakeMethod(
            failure=Exception("CHAOS REIGNS")
        )
        manager.startService()
        self.addCleanup(manager.stopService)
        self.assertEqual(1, manager.checkForNewBuilders.call_count)

        # Even though the previous checkForNewBuilders caused an
        # exception, a rescan will happen as normal.
        advance = manager.SCAN_BUILDERS_INTERVAL + 1
        clock.advance(advance)
        self.assertEqual(2, manager.checkForNewBuilders.call_count)
        clock.advance(advance)
        self.assertEqual(3, manager.checkForNewBuilders.call_count)


class TestFlushLogTails(TestCaseWithFactory):
    """Test flushing of log tail updates."""

    layer = LaunchpadZopelessLayer

    def _getManager(self, clock=None):
        return BuilddManager(clock=clock, builder_factory=BuilderFactory())

    def test_startService(self):
        # startService calls the "flushLogTails" method.
        clock = task.Clock()
        manager = self._getManager(clock=clock)
        manager.scanBuilders = FakeMethod()
        manager.flushLogTails = FakeMethod()
        manager.startService()
        self.addCleanup(manager.stopService)

        clock.advance(manager.FLUSH_LOGTAILS_INTERVAL + 1)
        self.assertNotEqual(
            0,
            manager.flushLogTails.call_count,
            "scheduleUpdate did not schedule a flushLogTails loop",
        )

    def test_flushLogTails(self):
        # flushLogTails flushes pending log tail updates to the database.
        manager = self._getManager()
        bqs = [
            self.factory.makeBinaryPackageBuild().queueBuild()
            for _ in range(3)
        ]
        manager.addLogTail(bqs[0].id, "A log tail")
        manager.addLogTail(bqs[1].id, "Another log tail")
        transaction.commit()

        manager.flushLogTails()
        self.assertEqual("A log tail", bqs[0].logtail)
        self.assertEqual("Another log tail", bqs[1].logtail)
        self.assertIsNone(bqs[2].logtail)

        self.assertEqual({}, manager.pending_logtails)
        manager.flushLogTails()
        self.assertEqual("A log tail", bqs[0].logtail)
        self.assertEqual("Another log tail", bqs[1].logtail)
        self.assertIsNone(bqs[2].logtail)

    def test_flushLogTails_swallows_exceptions(self):
        # flushLogTails swallows exceptions so the LoopingCall always
        # retries.
        clock = task.Clock()
        manager = self._getManager(clock=clock)
        manager.logger = BufferLogger()
        manager.scanBuilders = FakeMethod()
        bq = self.factory.makeBinaryPackageBuild().queueBuild()
        manager.addLogTail("nonsense", "A log tail")
        transaction.commit()

        manager.startService()
        self.addCleanup(manager.stopService)
        self.assertIn(
            "Failure while flushing log tail updates:",
            manager.logger.getLogBuffer(),
        )

        # Even though the previous flushUpdates raised an exception, further
        # updates will happen as normal.
        manager.addLogTail(bq.id, "Another log tail")
        advance = manager.FLUSH_LOGTAILS_INTERVAL + 1
        clock.advance(advance)
        self.assertEqual("Another log tail", bq.logtail)


def is_file_growing(filepath, poll_interval=1, poll_repeat=10):
    """Poll the file size to see if it grows.

    Checks the size of the file in given intervals and returns True as soon as
    it sees the size increase between two polls. If the size does not
    increase after a given number of polls, the function returns False.
    If the file does not exist, the function silently ignores that and waits
    for it to appear on the next pall. If it has not appeared by the last
    poll, the exception is propagated.
    Program execution is blocked during polling.

    :param filepath: The path to the file to be palled.
    :param poll_interval: The number of seconds in between two polls.
    :param poll_repeat: The number times to repeat the polling, so the size is
        polled a total of poll_repeat+1 times. The default values create a
        total poll time of 11 seconds. The BuilddManager logs
        "scanning cycles" every 5 seconds so these settings should see an
        increase if the process is logging to this file.
    """
    last_size = None
    for poll in range(poll_repeat + 1):
        try:
            statinfo = os.stat(filepath)
            if last_size is None:
                last_size = statinfo.st_size
            elif statinfo.st_size > last_size:
                return True
            else:
                # The file should not be shrinking.
                assert statinfo.st_size == last_size
        except OSError:
            if poll == poll_repeat:
                # Propagate only on the last loop, i.e. give up.
                raise
        time.sleep(poll_interval)
    return False


class TestBuilddManagerScript(TestCaseWithFactory):
    layer = LaunchpadScriptLayer

    def testBuilddManagerRuns(self):
        # The `buildd-manager.tac` starts and stops correctly.
        fixture = BuilddManagerTestSetup()
        fixture.setUp()
        fixture.tearDown()
        self.layer.force_dirty_database()

    # XXX Julian 2010-08-06 bug=614275
    # These next 2 tests are in the wrong place, they should be near the
    # implementation of RotatableFileLogObserver and not depend on the
    # behaviour of the buildd-manager.  I've disabled them here because
    # they prevented me from landing this branch which reduces the
    # logging output.

    def disabled_testBuilddManagerLogging(self):
        # The twistd process logs as execpected.
        test_setup = self.useFixture(BuilddManagerTestSetup())
        logfilepath = test_setup.logfile
        # The process logs to its logfile.
        self.assertTrue(is_file_growing(logfilepath))
        # After rotating the log, the process keeps using the old file, no
        # new file is created.
        rotated_logfilepath = logfilepath + ".1"
        os.rename(logfilepath, rotated_logfilepath)
        self.assertTrue(is_file_growing(rotated_logfilepath))
        self.assertFalse(os.access(logfilepath, os.F_OK))
        # Upon receiving the USR1 signal, the process will re-open its log
        # file at the old location.
        test_setup.sendSignal(signal.SIGUSR1)
        self.assertTrue(is_file_growing(logfilepath))
        self.assertTrue(os.access(rotated_logfilepath, os.F_OK))

    def disabled_testBuilddManagerLoggingNoRotation(self):
        # The twistd process does not perform its own rotation.
        # By default twistd will rotate log files that grow beyond
        # 1000000 bytes but this is deactivated for the buildd manager.
        test_setup = BuilddManagerTestSetup()
        logfilepath = test_setup.logfile
        rotated_logfilepath = logfilepath + ".1"
        # Prefill the log file to just under 1000000 bytes.
        test_setup.precreateLogfile(
            "2010-07-27 12:36:54+0200 [-] Starting scanning cycle.\n", 18518
        )
        self.useFixture(test_setup)
        # The process logs to the logfile.
        self.assertTrue(is_file_growing(logfilepath))
        # No rotation occurred.
        self.assertFalse(
            os.access(rotated_logfilepath, os.F_OK),
            "Twistd's log file was rotated by twistd.",
        )
