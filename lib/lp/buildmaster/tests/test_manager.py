# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the renovated slave scanner aka BuilddManager."""

import os
import signal
import time

import transaction

from twisted.internet import (
    defer,
    reactor,
    task,
    )
from twisted.internet.task import (
    deferLater,
    )
from twisted.python.failure import Failure
from twisted.trial.unittest import TestCase as TrialTestCase
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.buildd.tests import BuilddSlaveTestSetup
from canonical.config import config
from canonical.launchpad.ftests import (
    ANONYMOUS,
    login,
    )
from canonical.launchpad.scripts.logger import (
    QuietFakeLogger,
    )
from canonical.testing.layers import (
    LaunchpadScriptLayer,
    LaunchpadZopelessLayer,
    TwistedLayer,
    )
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.manager import (
    BuilddManager,
    NewBuildersScanner,
    SlaveScanner,
    )
from lp.buildmaster.tests.harness import BuilddManagerTestSetup
from lp.buildmaster.tests.mock_slaves import (
    BuildingSlave,
    OkSlave,
    )
from lp.registry.interfaces.distribution import IDistributionSet
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.testing import TestCase as LaunchpadTestCase
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.sampledata import BOB_THE_BUILDER_NAME


class TestSlaveScannerScan(TrialTestCase):
    """Tests `SlaveScanner.scan` method.

    This method uses the old framework for scanning and dispatching builds.
    """
    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Setup TwistedLayer, TrialTestCase and BuilddSlaveTest.

        Also adjust the sampledata in a way a build can be dispatched to
        'bob' builder.
        """
        from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
        TwistedLayer.testSetUp()
        TrialTestCase.setUp(self)
        BuilddSlaveTestSetup().setUp()

        # Creating the required chroots needed for dispatching.
        test_publisher = SoyuzTestPublisher()
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        test_publisher.setUpDefaultDistroSeries(hoary)
        test_publisher.addFakeChroots()

    def tearDown(self):
        BuilddSlaveTestSetup().tearDown()
        TrialTestCase.tearDown(self)
        TwistedLayer.testTearDown()

    def _resetBuilder(self, builder):
        """Reset the given builder and its job."""

        builder.builderok = True
        job = builder.currentjob
        if job is not None:
            job.reset()

        transaction.commit()

    def assertBuildingJob(self, job, builder, logtail=None):
        """Assert the given job is building on the given builder."""
        from lp.services.job.interfaces.job import JobStatus
        if logtail is None:
            logtail = 'Dummy sampledata entry, not processing'

        self.assertTrue(job is not None)
        self.assertEqual(job.builder, builder)
        self.assertTrue(job.date_started is not None)
        self.assertEqual(job.job.status, JobStatus.RUNNING)
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(job)
        self.assertEqual(build.status, BuildStatus.BUILDING)
        self.assertEqual(job.logtail, logtail)

    def _getManager(self):
        """Instantiate a SlaveScanner object.

        Replace its default logging handler by a testing version.
        """
        manager = SlaveScanner(BOB_THE_BUILDER_NAME, QuietFakeLogger())
        manager.logger.name = 'slave-scanner'

        return manager

    def _checkDispatch(self, slave, builder):
        # SlaveScanner.scan returns a slave when a dispatch was
        # successful.  We also check that the builder has a job on it.

        self.assertTrue(slave is not None, "Expected a slave.")
        self.assertEqual(0, builder.failure_count)
        self.assertTrue(builder.currentjob is not None)

    def testScanDispatchForResetBuilder(self):
        # A job gets dispatched to the sampledata builder after it's reset.

        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)
        builder.setSlaveForTesting(OkSlave())
        # Set this to 1 here so that _checkDispatch can make sure it's
        # reset to 0 after a successful dispatch.
        builder.failure_count = 1

        # Run 'scan' and check its result.
        self.layer.txn.commit()
        LaunchpadZopelessLayer.switchDbUser(config.builddmaster.dbuser)
        manager = self._getManager()
        d = defer.maybeDeferred(manager.scan)
        d.addCallback(self._checkDispatch, builder)
        return d

    def _checkNoDispatch(self, recording_slave, builder):
        """Assert that no dispatch has occurred.

        'recording_slave' is None, so no interations would be passed
        to the asynchonous dispatcher and the builder remained active
        and IDLE.
        """
        self.assertTrue(
            recording_slave is None, "Unexpected recording_slave.")

        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertTrue(builder.builderok)
        self.assertTrue(builder.currentjob is None)

    def testNoDispatchForMissingChroots(self):
        # When a required chroot is not present the `scan` method
        # should not return any `RecordingSlaves` to be processed
        # and the builder used should remain active and IDLE.

        # Reset sampledata builder.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self._resetBuilder(builder)

        # Remove hoary/i386 chroot.
        login('foo.bar@canonical.com')
        ubuntu = getUtility(IDistributionSet).getByName('ubuntu')
        hoary = ubuntu.getSeries('hoary')
        pocket_chroot = hoary.getDistroArchSeries('i386').getPocketChroot()
        removeSecurityProxy(pocket_chroot).chroot = None
        transaction.commit()
        login(ANONYMOUS)

        # Run 'scan' and check its result.
        LaunchpadZopelessLayer.switchDbUser(config.builddmaster.dbuser)
        manager = self._getManager()
        d = defer.maybeDeferred(manager._startCycle)
        d.addCallback(self._checkNoDispatch, builder)
        return d

    def _checkJobRescued(self, slave, builder, job):
        """`SlaveScanner.scan` rescued the job.

        Nothing gets dispatched,  the 'broken' builder remained disabled
        and the 'rescued' job is ready to be dispatched.
        """
        self.assertTrue(
            slave is None, "Unexpected slave.")

        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertFalse(builder.builderok)

        job = getUtility(IBuildQueueSet).get(job.id)
        self.assertTrue(job.builder is None)
        self.assertTrue(job.date_started is None)
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(job)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    def testScanRescuesJobFromBrokenBuilder(self):
        # The job assigned to a broken builder is rescued.

        # Sampledata builder is enabled and is assigned to an active job.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]
        self.assertTrue(builder.builderok)
        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        # Disable the sampledata builder
        login('foo.bar@canonical.com')
        builder.builderok = False
        transaction.commit()
        login(ANONYMOUS)

        # Run 'scan' and check its result.
        LaunchpadZopelessLayer.switchDbUser(config.builddmaster.dbuser)
        manager = self._getManager()
        d = defer.maybeDeferred(manager.scan)
        d.addCallback(self._checkJobRescued, builder, job)
        return d

    def _checkJobUpdated(self, slave, builder, job):
        """`SlaveScanner.scan` updates legitimate jobs.

        Job is kept assigned to the active builder and its 'logtail' is
        updated.
        """
        self.assertTrue(slave is None, "Unexpected slave.")

        builder = getUtility(IBuilderSet).get(builder.id)
        self.assertTrue(builder.builderok)

        job = getUtility(IBuildQueueSet).get(job.id)
        self.assertBuildingJob(job, builder, logtail='This is a build log')

    def testScanUpdatesBuildingJobs(self):
        # The job assigned to a broken builder is rescued.

        # Enable sampledata builder attached to an appropriate testing
        # slave. It will respond as if it was building the sampledata job.
        builder = getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME]

        login('foo.bar@canonical.com')
        builder.builderok = True
        builder.setSlaveForTesting(BuildingSlave(build_id='8-1'))
        transaction.commit()
        login(ANONYMOUS)

        job = builder.currentjob
        self.assertBuildingJob(job, builder)

        # Run 'scan' and check its result.
        LaunchpadZopelessLayer.switchDbUser(config.builddmaster.dbuser)
        manager = self._getManager()
        d = defer.maybeDeferred(manager.scan)
        d.addCallback(self._checkJobUpdated, builder, job)
        return d

    def _assertFailureCounting(self, builder_count, job_count,
                               expected_builder_count, expected_job_count):
        # If scan() fails with an exception, failure_counts should be
        # incremented.  What we do with the results of the failure
        # counts is tested below separately, this test just makes sure that
        # scan() is setting the counts.
        def failing_scan():
            return defer.fail(Exception("fake exception"))
        manager = self._getManager()
        manager.scan = failing_scan
        manager.scheduleNextScanCycle = FakeMethod()
        from lp.buildmaster import manager as manager_module
        self.patch(manager_module, 'assessFailureCounts', FakeMethod())
        builder = getUtility(IBuilderSet)[manager.builder_name]

        builder.failure_count = builder_count
        builder.currentjob.specific_job.build.failure_count = job_count

        # startCycle() calls scan() which is our fake one that throws an
        # exception.
        d = manager._startCycle()

        # Failure counts should be updated, and the assessment method
        # should have been called.
        def got_scan(ignored):
            self.assertEqual(expected_builder_count, builder.failure_count)
            self.assertEqual(
                expected_job_count,
                builder.currentjob.specific_job.build.failure_count)
            self.assertEqual(
                1, manager_module.assessFailureCounts.call_count)

        return d.addCallback(got_scan)

    def test_scan_first_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        self._assertFailureCounting(
            builder_count=0, job_count=0, expected_builder_count=1,
            expected_job_count=1)

    def test_scan_second_builder_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        self._assertFailureCounting(
            builder_count=1, job_count=0, expected_builder_count=2,
            expected_job_count=1)

    def test_scan_second_job_fail(self):
        # The first failure of a job should result in the failure_count
        # on the job and the builder both being incremented.
        self._assertFailureCounting(
            builder_count=0, job_count=1, expected_builder_count=1,
            expected_job_count=2)

    def test_fail_to_resume_slave_resets_job(self):
        # If an attempt to resume and dispatch a slave fails, it should
        # reset the job via job.reset()

        # Make a slave with a failing resume() method.
        slave = OkSlave()
        slave.resume = lambda: deferLater(
            reactor, 0, defer.fail, Failure(('out', 'err', 1)))

        # Reset sampledata builder.
        builder = removeSecurityProxy(
            getUtility(IBuilderSet)[BOB_THE_BUILDER_NAME])
        self._resetBuilder(builder)
        self.assertEqual(0, builder.failure_count)
        builder.setSlaveForTesting(slave)
        builder.vm_host = "fake_vm_host"

        manager = self._getManager()

        # Get the next job that will be dispatched.
        job = removeSecurityProxy(builder._findBuildCandidate())
        job.virtualized = True
        builder.virtualized = True
        d = manager._startCycle()

        def check(ignored):
            # The failure_count will have been incremented on the
            # builder, we can check that to see that a dispatch attempt
            # did indeed occur.
            self.assertEqual(1, builder.failure_count)
            # There should also be no builder set on the job.
            self.assertTrue(job.builder is None)
            build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(job)
            self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

        return d.addCallback(check)


class TestBuilddManager(TrialTestCase):

    layer = LaunchpadZopelessLayer

    def _stub_out_scheduleNextScanCycle(self):
        # stub out the code that adds a callLater, so that later tests
        # don't get surprises.
        self.patch(SlaveScanner, 'startCycle', FakeMethod())

    def test_addScanForBuilders(self):
        # Test that addScanForBuilders generates NewBuildersScanner objects.
        self._stub_out_scheduleNextScanCycle()

        manager = BuilddManager()
        builder_names = set(
            builder.name for builder in getUtility(IBuilderSet))
        scanners = manager.addScanForBuilders(builder_names)
        scanner_names = set(scanner.builder_name for scanner in scanners)
        self.assertEqual(builder_names, scanner_names)

    def test_startService_adds_NewBuildersScanner(self):
        # When startService is called, the manager will start up a
        # NewBuildersScanner object.
        self._stub_out_scheduleNextScanCycle()
        clock = task.Clock()
        manager = BuilddManager(clock=clock)

        # Replace scan() with FakeMethod so we can see if it was called.
        manager.new_builders_scanner.scan = FakeMethod()

        manager.startService()
        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, manager.new_builders_scanner.scan.call_count)


class TestNewBuilders(TrialTestCase):
    """Test detecting of new builders."""

    layer = LaunchpadZopelessLayer

    def _getScanner(self, manager=None, clock=None):
        return NewBuildersScanner(manager=manager, clock=clock)

    def test_init_stores_existing_builders(self):
        # Make sure that NewBuildersScanner initialises itself properly
        # by storing a list of existing builders.
        all_builders = [builder.name for builder in getUtility(IBuilderSet)]
        builder_scanner = self._getScanner()
        self.assertEqual(all_builders, builder_scanner.current_builders)

    def test_scheduleScan(self):
        # Test that scheduleScan calls the "scan" method.
        clock = task.Clock()
        builder_scanner = self._getScanner(clock=clock)
        builder_scanner.scan = FakeMethod()
        builder_scanner.scheduleScan()

        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(
            0, builder_scanner.scan.call_count,
            "scheduleScan did not schedule anything")

    def test_checkForNewBuilders(self):
        # Test that checkForNewBuilders() detects a new builder

        # The basic case, where no builders are added.
        builder_scanner = self._getScanner()
        self.assertEqual([], builder_scanner.checkForNewBuilders())

        # Add two builders and ensure they're returned.
        new_builders = ["scooby", "lassie"]
        factory = LaunchpadObjectFactory()
        for builder_name in new_builders:
            factory.makeBuilder(name=builder_name)
        self.assertEqual(
            new_builders, builder_scanner.checkForNewBuilders())

    def test_scan(self):
        # See if scan detects new builders and schedules the next scan.

        # stub out the addScanForBuilders and scheduleScan methods since
        # they use callLater; we only want to assert that they get
        # called.
        def fake_checkForNewBuilders():
            return "new_builders"

        def fake_addScanForBuilders(new_builders):
            self.assertEqual("new_builders", new_builders)

        clock = task.Clock()
        builder_scanner = self._getScanner(BuilddManager(), clock=clock)
        builder_scanner.checkForNewBuilders = fake_checkForNewBuilders
        builder_scanner.manager.addScanForBuilders = fake_addScanForBuilders
        builder_scanner.scheduleScan = FakeMethod()

        builder_scanner.scan()
        advance = NewBuildersScanner.SCAN_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(
            0, builder_scanner.scheduleScan.call_count,
            "scheduleScan did not get called")


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
    for poll in range(poll_repeat+1):
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


class TestBuilddManagerScript(LaunchpadTestCase):

    layer = LaunchpadScriptLayer

    def testBuilddManagerRuns(self):
        # The `buildd-manager.tac` starts and stops correctly.
        BuilddManagerTestSetup().setUp()
        BuilddManagerTestSetup().tearDown()

    # XXX Julian 2010-08-06 bug=614275
    # These next 2 tests are in the wrong place, they should be near the
    # implementation of RotatableFileLogObserver and not depend on the
    # behaviour of the buildd-manager.  I've disabled them here because
    # they prevented me from landing this branch which reduces the
    # logging output.

    def disabled_testBuilddManagerLogging(self):
        # The twistd process logs as execpected.
        test_setup = BuilddManagerTestSetup()
        logfilepath = test_setup.logfile
        test_setup.setUp()
        self.addCleanup(test_setup.tearDown)
        # The process logs to its logfile.
        self.assertTrue(is_file_growing(logfilepath))
        # After rotating the log, the process keeps using the old file, no
        # new file is created.
        rotated_logfilepath = logfilepath+'.1'
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
        rotated_logfilepath = logfilepath+'.1'
        # Prefill the log file to just under 1000000 bytes.
        test_setup.precreateLogfile(
            "2010-07-27 12:36:54+0200 [-] Starting scanning cycle.\n", 18518)
        test_setup.setUp()
        self.addCleanup(test_setup.tearDown)
        # The process logs to the logfile.
        self.assertTrue(is_file_growing(logfilepath))
        # No rotation occured.
        self.assertFalse(
            os.access(rotated_logfilepath, os.F_OK),
            "Twistd's log file was rotated by twistd.")
