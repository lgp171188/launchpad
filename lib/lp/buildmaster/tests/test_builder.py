# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Builder features."""

import errno
import os
import signal
import socket
import xmlrpclib

from twisted.web.client import getPage

from twisted.internet.task import Clock
from twisted.python.failure import Failure
from twisted.trial.unittest import TestCase as TrialTestCase

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.buildd.slave import BuilderStatus
from canonical.config import config
from canonical.database.sqlbase import flush_database_updates
from canonical.launchpad.scripts import QuietFakeLogger
from canonical.launchpad.webapp.interfaces import (
    DEFAULT_FLAVOR,
    IStoreSelector,
    MAIN_STORE,
    )
from canonical.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    TwistedLaunchpadZopelessLayer,
    TwistedLayer,
    )
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.builder import (
    CannotFetchFile,
    IBuilder,
    IBuilderSet,
    )
from lp.buildmaster.interfaces.buildfarmjobbehavior import (
    IBuildFarmJobBehavior,
    )
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.interfaces.builder import CannotResumeHost
from lp.buildmaster.model.buildfarmjobbehavior import IdleBuildBehavior
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.tests.mock_slaves import (
    AbortedSlave,
    LostBuildingBrokenSlave,
    MockBuilder,
    SlaveTestHelpers,
    )
from lp.soyuz.enums import (
    ArchivePurpose,
    PackagePublishingStatus,
    )
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.model.binarypackagebuildbehavior import (
    BinaryPackageBuildBehavior,
    )
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import (
    ANONYMOUS,
    login_as,
    logout,
    TestCaseWithFactory,
    )
from lp.testing.factory import LaunchpadObjectFactory
from lp.testing.fakemethod import FakeMethod


class TestBuilder(TestCaseWithFactory):
    """Basic unit tests for `Builder`."""

    layer = DatabaseFunctionalLayer

    def test_providesInterface(self):
        # Builder provides IBuilder
        builder = self.factory.makeBuilder()
        self.assertProvides(builder, IBuilder)

    def test_default_values(self):
        builder = self.factory.makeBuilder()
        # Make sure the Storm cache gets the values that the database
        # initialises.
        flush_database_updates()
        self.assertEqual(0, builder.failure_count)

    def test_getCurrentBuildFarmJob(self):
        bq = self.factory.makeSourcePackageRecipeBuildJob(3333)
        builder = self.factory.makeBuilder()
        bq.markAsBuilding(builder)
        self.assertEqual(
            bq, builder.getCurrentBuildFarmJob().buildqueue_record)

    def test_getBuildQueue(self):
        buildqueueset = getUtility(IBuildQueueSet)
        active_jobs = buildqueueset.getActiveBuildJobs()
        [active_job] = active_jobs
        builder = active_job.builder

        bq = builder.getBuildQueue()
        self.assertEqual(active_job, bq)

        active_job.builder = None
        bq = builder.getBuildQueue()
        self.assertIs(None, bq)


class TestBuilderWithTrial(TrialTestCase):

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        super(TestBuilderWithTrial, self)
        self.slave_helper = SlaveTestHelpers()
        self.slave_helper.setUp()
        self.addCleanup(self.slave_helper.cleanUp)
        self.factory = LaunchpadObjectFactory()
        login_as(ANONYMOUS)
        self.addCleanup(logout)

    def test_updateBuilderStatus_catches_repeated_EINTR(self):
        # A single EINTR return from a socket operation should cause the
        # operation to be retried, not fail/reset the builder.
        builder = removeSecurityProxy(self.factory.makeBuilder())
        builder.handleTimeout = FakeMethod()
        builder.rescueIfLost = FakeMethod()

        def _fake_checkSlaveAlive():
            # Raise an EINTR error for all invocations.
            raise socket.error(errno.EINTR, "fake eintr")

        builder.checkSlaveAlive = _fake_checkSlaveAlive
        d = builder.updateStatus()
        return d.addCallback(
            lambda ignored:
                self.assertEqual(1, builder.handleTimeout.call_count))

    def test_updateBuilderStatus_catches_single_EINTR(self):
        builder = removeSecurityProxy(self.factory.makeBuilder())
        builder.handleTimeout = FakeMethod()
        builder.rescueIfLost = FakeMethod()
        self.eintr_returned = False

        def _fake_checkSlaveAlive():
            # raise an EINTR error for the first invocation only.
            if not self.eintr_returned:
                self.eintr_returned = True
                raise socket.error(errno.EINTR, "fake eintr")

        builder.checkSlaveAlive = _fake_checkSlaveAlive
        d = builder.updateStatus()
        # builder.updateStatus should never call handleTimeout() for a
        # single EINTR.
        return d.addCallback(
            lambda ignored:
            self.assertEqual(0, builder.handleTimeout.call_count))

    def test_updateStatus_deactivates_builder_when_abort_fails(self):
        from lp.buildmaster.interfaces.builder import CorruptBuildCookie
        from lp.testing.fakemethod import FakeMethod
        slave = LostBuildingBrokenSlave()
        lostbuilding_builder = MockBuilder('Lost Building Broken Slave', slave)
        behavior = removeSecurityProxy(
            lostbuilding_builder.current_build_behavior)
        behavior.verifySlaveBuildCookie = FakeMethod(
            failure=CorruptBuildCookie("Hopelessly lost!"))
        d = lostbuilding_builder.updateStatus(QuietFakeLogger())
        def check_slave_status(ignored):
            self.assertIn('abort', slave.call_log)
            self.assertFalse(lostbuilding_builder.builderok)
        return d.addCallback(check_slave_status)

    def test_resumeSlaveHost_nonvirtual(self):
        builder = self.factory.makeBuilder(virtualized=False)
        d = builder.resumeSlaveHost()
        return self.assertFailure(d, CannotResumeHost)

    def test_resumeSlaveHost_no_vmhost(self):
        builder = self.factory.makeBuilder(virtualized=True, vm_host=None)
        d = builder.resumeSlaveHost()
        return self.assertFailure(d, CannotResumeHost)

    def test_resumeSlaveHost_success(self):
        reset_config = """
            [builddmaster]
            vm_resume_command: /bin/echo -n parp"""
        config.push('reset', reset_config)
        self.addCleanup(config.pop, 'reset')

        builder = self.factory.makeBuilder(virtualized=True, vm_host="pop")
        d = builder.resumeSlaveHost()
        def got_resume(output):
            self.assertEqual(('parp', ''), output)
        return d.addCallback(got_resume)

    def test_resumeSlaveHost_command_failed(self):
        reset_fail_config = """
            [builddmaster]
            vm_resume_command: /bin/false"""
        config.push('reset fail', reset_fail_config)
        self.addCleanup(config.pop, 'reset fail')
        builder = self.factory.makeBuilder(virtualized=True, vm_host="pop")
        d = builder.resumeSlaveHost()
        return self.assertFailure(d, CannotResumeHost)

    def test_handleTimeout(self):
        reset_fail_config = """
            [builddmaster]
            vm_resume_command: /bin/false"""
        config.push('reset fail', reset_fail_config)
        self.addCleanup(config.pop, 'reset fail')
        builder = self.factory.makeBuilder(virtualized=True, vm_host="pop")
        builder.builderok = True
        d = builder.handleTimeout(QuietFakeLogger(), 'blah')
        return d.addCallback(
            lambda ignored: self.assertFalse(builder.builderok))

    def test_findAndStartJob_returns_candidate(self):
        # findAndStartJob finds the next queued job using _findBuildCandidate.
        builder = self.factory.makeBuilder(virtualized=True, vm_host="bladh")
        # We don't care about the type of build at all.
        build = self.factory.makeSourcePackageRecipeBuild()
        candidate = build.queueBuild()
        # _findBuildCandidate is tested elsewhere, we just make sure that
        # findAndStartJob delegates to it.
        removeSecurityProxy(builder)._findBuildCandidate = FakeMethod(
            result=candidate)
        d = builder.findAndStartJob()
        return d.addCallback(self.assertEqual, candidate)

    def test_findAndStartJob_starts_job(self):
        # findAndStartJob finds the next queued job using _findBuildCandidate
        # and then starts it.
        builder = self.factory.makeBuilder(virtualized=True, vm_host="bladh")
        # We don't care about the type of build at all.
        build = self.factory.makeSourcePackageRecipeBuild()
        candidate = build.queueBuild()
        removeSecurityProxy(builder)._findBuildCandidate = FakeMethod(
            result=candidate)
        d = builder.findAndStartJob()
        def check_build_started(candidate):
            self.assertEqual(candidate.builder, builder)
            self.assertEqual(BuildStatus.BUILDING, build.status)
        return d.addCallback(check_build_started)


class Test_rescueBuilderIfLost(TestCaseWithFactory):
    """Tests for lp.buildmaster.model.builder.rescueBuilderIfLost."""

    layer = LaunchpadZopelessLayer

    def test_recovery_of_aborted_slave(self):
        # If a slave is in the ABORTED state, rescueBuilderIfLost should
        # clean it if we don't think it's currently building anything.
        # See bug 463046.
        aborted_slave = AbortedSlave()
        # The slave's clean() method is normally an XMLRPC call, so we
        # can just stub it out and check that it got called.
        aborted_slave.clean = FakeMethod()
        builder = MockBuilder("mock_builder", aborted_slave)
        builder.currentjob = None
        builder.rescueIfLost()

        self.assertEqual(1, aborted_slave.clean.call_count)


class TestFindBuildCandidateBase(TestCaseWithFactory):
    """Setup the test publisher and some builders."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestFindBuildCandidateBase, self).setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        # Create some i386 builders ready to build PPA builds.  Two
        # already exist in sampledata so we'll use those first.
        self.builder1 = getUtility(IBuilderSet)['bob']
        self.frog_builder = getUtility(IBuilderSet)['frog']
        self.builder3 = self.factory.makeBuilder(name='builder3')
        self.builder4 = self.factory.makeBuilder(name='builder4')
        self.builder5 = self.factory.makeBuilder(name='builder5')
        self.builders = [
            self.builder1,
            self.frog_builder,
            self.builder3,
            self.builder4,
            self.builder5,
            ]

        # Ensure all builders are operational.
        for builder in self.builders:
            builder.builderok = True
            builder.manual = False


class TestFindBuildCandidatePPAWithSingleBuilder(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestFindBuildCandidatePPAWithSingleBuilder, self).setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        self.bob_builder = getUtility(IBuilderSet)['bob']
        self.frog_builder = getUtility(IBuilderSet)['frog']

        # Disable bob so only frog is available.
        self.bob_builder.manual = True
        self.bob_builder.builderok = True
        self.frog_builder.manual = False
        self.frog_builder.builderok = True

        # Make a new PPA and give it some builds.
        self.ppa_joe = self.factory.makeArchive(name="joesppa")
        self.publisher.getPubSource(
            sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
            archive=self.ppa_joe).createMissingBuilds()

    def test_findBuildCandidate_first_build_started(self):
        # The allocation rule for PPA dispatching doesn't apply when
        # there's only one builder available.

        # Asking frog to find a candidate should give us the joesppa build.
        next_job = removeSecurityProxy(
            self.frog_builder)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.assertEqual('joesppa', build.archive.name)

        # If bob is in a failed state the joesppa build is still
        # returned.
        self.bob_builder.builderok = False
        self.bob_builder.manual = False
        next_job = removeSecurityProxy(
            self.frog_builder)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.assertEqual('joesppa', build.archive.name)


class TestFindBuildCandidatePPABase(TestFindBuildCandidateBase):

    ppa_joe_private = False
    ppa_jim_private = False

    def _setBuildsBuildingForArch(self, builds_list, num_builds,
                                  archtag="i386"):
        """Helper function.

        Set the first `num_builds` in `builds_list` with `archtag` as
        BUILDING.
        """
        count = 0
        for build in builds_list[:num_builds]:
            if build.distro_arch_series.architecturetag == archtag:
                build.status = BuildStatus.BUILDING
                build.builder = self.builders[count]
            count += 1

    def setUp(self):
        """Publish some builds for the test archive."""
        super(TestFindBuildCandidatePPABase, self).setUp()

        # Create two PPAs and add some builds to each.
        self.ppa_joe = self.factory.makeArchive(
            name="joesppa", private=self.ppa_joe_private)
        self.ppa_jim = self.factory.makeArchive(
            name="jimsppa", private=self.ppa_jim_private)

        self.joe_builds = []
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe).createMissingBuilds())
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe).createMissingBuilds())
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="cobblers",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe).createMissingBuilds())
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="thunderpants",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe).createMissingBuilds())

        self.jim_builds = []
        self.jim_builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_jim).createMissingBuilds())
        self.jim_builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_jim).createMissingBuilds())

        # Set the first three builds in joe's PPA as building, which
        # leaves two builders free.
        self._setBuildsBuildingForArch(self.joe_builds, 3)
        num_active_builders = len(
            [build for build in self.joe_builds if build.builder is not None])
        num_free_builders = len(self.builders) - num_active_builders
        self.assertEqual(num_free_builders, 2)


class TestFindBuildCandidatePPA(TestFindBuildCandidatePPABase):

    def test_findBuildCandidate_first_build_started(self):
        # A PPA cannot start a build if it would use 80% or more of the
        # builders.
        next_job = removeSecurityProxy(self.builder4)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.failIfEqual('joesppa', build.archive.name)

    def test_findBuildCandidate_first_build_finished(self):
        # When joe's first ppa build finishes, his fourth i386 build
        # will be the next build candidate.
        self.joe_builds[0].status = BuildStatus.FAILEDTOBUILD
        next_job = removeSecurityProxy(self.builder4)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.failUnlessEqual('joesppa', build.archive.name)


class TestFindBuildCandidatePrivatePPA(TestFindBuildCandidatePPABase):

    ppa_joe_private = True

    def test_findBuildCandidate_for_private_ppa(self):
        # If a ppa is private it will be able to have parallel builds
        # for the one architecture.
        next_job = removeSecurityProxy(self.builder4)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.failUnlessEqual('joesppa', build.archive.name)


class TestFindBuildCandidateDistroArchive(TestFindBuildCandidateBase):

    def setUp(self):
        """Publish some builds for the test archive."""
        super(TestFindBuildCandidateDistroArchive, self).setUp()
        # Create a primary archive and publish some builds for the
        # queue.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY)

        self.gedit_build = self.publisher.getPubSource(
            sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
            archive=self.non_ppa).createMissingBuilds()[0]
        self.firefox_build = self.publisher.getPubSource(
            sourcename="firefox", status=PackagePublishingStatus.PUBLISHED,
            archive=self.non_ppa).createMissingBuilds()[0]

    def test_findBuildCandidate_for_non_ppa(self):
        # Normal archives are not restricted to serial builds per
        # arch.

        next_job = removeSecurityProxy(
            self.frog_builder)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.failUnlessEqual('primary', build.archive.name)
        self.failUnlessEqual('gedit', build.source_package_release.name)

        # Now even if we set the build building, we'll still get the
        # second non-ppa build for the same archive as the next candidate.
        build.status = BuildStatus.BUILDING
        build.builder = self.frog_builder
        next_job = removeSecurityProxy(
            self.frog_builder)._findBuildCandidate()
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.failUnlessEqual('primary', build.archive.name)
        self.failUnlessEqual('firefox', build.source_package_release.name)

    def test_findBuildCandidate_for_recipe_build(self):
        # Recipe builds with a higher score are selected first.
        # This test is run in a context with mixed recipe and binary builds.

        self.assertIsNot(self.frog_builder.processor, None)
        self.assertEqual(self.frog_builder.virtualized, True)

        self.assertEqual(self.gedit_build.buildqueue_record.lastscore, 2505)
        self.assertEqual(self.firefox_build.buildqueue_record.lastscore, 2505)

        recipe_build_job = self.factory.makeSourcePackageRecipeBuildJob(9999)

        self.assertEqual(recipe_build_job.lastscore, 9999)

        next_job = removeSecurityProxy(
            self.frog_builder)._findBuildCandidate()

        self.failUnlessEqual(recipe_build_job, next_job)


class TestFindRecipeBuildCandidates(TestFindBuildCandidateBase):
    # These tests operate in a "recipe builds only" setting.
    # Please see also bug #507782.

    def clearBuildQueue(self):
        """Delete all `BuildQueue`, XXXJOb and `Job` instances."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        for bq in store.find(BuildQueue):
            bq.destroySelf()

    def setUp(self):
        """Publish some builds for the test archive."""
        super(TestFindRecipeBuildCandidates, self).setUp()
        # Create a primary archive and publish some builds for the
        # queue.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY)

        self.clearBuildQueue()
        self.bq1 = self.factory.makeSourcePackageRecipeBuildJob(3333)
        self.bq2 = self.factory.makeSourcePackageRecipeBuildJob(4333)

    def test_findBuildCandidate_with_highest_score(self):
        # The recipe build with the highest score is selected first.
        # This test is run in a "recipe builds only" context.

        self.assertIsNot(self.frog_builder.processor, None)
        self.assertEqual(self.frog_builder.virtualized, True)

        next_job = removeSecurityProxy(
            self.frog_builder)._findBuildCandidate()

        self.failUnlessEqual(self.bq2, next_job)


class TestCurrentBuildBehavior(TestCaseWithFactory):
    """This test ensures the get/set behavior of IBuilder's
    current_build_behavior property.
    """

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Create a new builder ready for testing."""
        super(TestCurrentBuildBehavior, self).setUp()
        self.builder = self.factory.makeBuilder(name='builder')

        # Have a publisher and a ppa handy for some of the tests below.
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()
        self.ppa_joe = self.factory.makeArchive(name="joesppa")

        self.build = self.publisher.getPubSource(
            sourcename="gedit", status=PackagePublishingStatus.PUBLISHED,
            archive=self.ppa_joe).createMissingBuilds()[0]

        self.buildfarmjob = self.build.buildqueue_record.specific_job

    def test_idle_behavior_when_no_current_build(self):
        """We return an idle behavior when there is no behavior specified
        nor a current build.
        """
        self.assertIsInstance(
            self.builder.current_build_behavior, IdleBuildBehavior)

    def test_set_behavior_sets_builder(self):
        """Setting a builder's behavior also associates the behavior with the
        builder."""
        behavior = IBuildFarmJobBehavior(self.buildfarmjob)
        self.builder.current_build_behavior = behavior

        self.assertEqual(behavior, self.builder.current_build_behavior)
        self.assertEqual(behavior._builder, self.builder)

    def test_current_job_behavior(self):
        """The current behavior is set automatically from the current job."""
        # Set the builder attribute on the buildqueue record so that our
        # builder will think it has a current build.
        self.build.buildqueue_record.builder = self.builder

        self.assertIsInstance(
            self.builder.current_build_behavior, BinaryPackageBuildBehavior)


class TestSlave(TrialTestCase):
    """
    Integration tests for BuilderSlave that verify how it works against a
    real slave server.
    """

    layer = TwistedLayer

    def setUp(self):
        super(TestSlave, self).setUp()
        self.slave_helper = SlaveTestHelpers()
        self.slave_helper.setUp()
        self.addCleanup(self.slave_helper.cleanUp)

    # XXX: JonathanLange 2010-09-20 bug=643521: There are also tests for
    # BuilderSlave in buildd-slave.txt and in other places. The tests here
    # ought to become the canonical tests for BuilderSlave vs running buildd
    # XML-RPC server interaction.

    def test_abort(self):
        slave = self.slave_helper.getClientSlave()
        # We need to be in a BUILDING state before we can abort.
        self.slave_helper.triggerGoodBuild(slave)
        result = slave.abort()
        self.assertEqual(result, BuilderStatus.ABORTING)

    def test_build(self):
        # Calling 'build' with an expected builder type, a good build id,
        # valid chroot & filemaps works and returns a BuilderStatus of
        # BUILDING.
        build_id = 'some-id'
        slave = self.slave_helper.getClientSlave()
        result = self.slave_helper.triggerGoodBuild(slave, build_id)
        self.assertEqual([BuilderStatus.BUILDING, build_id], result)

    def test_clean(self):
        slave = self.slave_helper.getClientSlave()
        # XXX: JonathanLange 2010-09-21: Calling clean() on the slave requires
        # it to be in either the WAITING or ABORTED states, and both of these
        # states are very difficult to achieve in a test environment. For the
        # time being, we'll just assert that a clean attribute exists.
        self.assertNotEqual(getattr(slave, 'clean', None), None)

    def test_echo(self):
        # Calling 'echo' contacts the server which returns the arguments we
        # gave it.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        result = slave.echo('foo', 'bar', 42)
        self.assertEqual(['foo', 'bar', 42], result)

    def test_info(self):
        # Calling 'info' gets some information about the slave.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        result = slave.info()
        # We're testing the hard-coded values, since the version is hard-coded
        # into the remote slave, the supported build managers are hard-coded
        # into the tac file for the remote slave and config is returned from
        # the configuration file.
        self.assertEqual(
            ['1.0',
             'i386',
             ['sourcepackagerecipe',
              'translation-templates', 'binarypackage', 'debian']],
            result)

    def test_initial_status(self):
        # Calling 'status' returns the current status of the slave. The
        # initial status is IDLE.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        status = slave.status()
        self.assertEqual([BuilderStatus.IDLE, ''], status)

    def test_status_after_build(self):
        # Calling 'status' returns the current status of the slave. After a
        # build has been triggered, the status is BUILDING.
        slave = self.slave_helper.getClientSlave()
        build_id = 'status-build-id'
        self.slave_helper.triggerGoodBuild(slave, build_id)
        status = slave.status()
        self.assertEqual([BuilderStatus.BUILDING, build_id], status[:2])
        [log_file] = status[2:]
        self.assertIsInstance(log_file, xmlrpclib.Binary)

    def test_ensurepresent_not_there(self):
        # ensurepresent checks to see if a file is there.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        d = slave.ensurepresent('blahblah', None, None, None)
        d.addCallback(self.assertEqual, [False, 'No URL'])
        return d

    def test_ensurepresent_actually_there(self):
        # ensurepresent checks to see if a file is there.
        tachandler = self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        self.slave_helper.makeCacheFile(tachandler, 'blahblah')
        d = slave.ensurepresent('blahblah', None, None, None)
        d.addCallback(self.assertEqual, [True, 'No URL'])
        return d

    def test_sendFileToSlave_not_there(self):
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        d = slave.sendFileToSlave('blahblah', None, None, None)
        return self.assertFailure(d, CannotFetchFile)

    def test_sendFileToSlave_actually_there(self):
        tachandler = self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        self.slave_helper.makeCacheFile(tachandler, 'blahblah')
        d = slave.sendFileToSlave('blahblah', None, None, None)
        def check_present(ignored):
            d = slave.ensurepresent('blahblah', None, None, None)
            return d.addCallback(self.assertEqual, [True, 'No URL'])
        d.addCallback(check_present)
        return d

    def test_resumeHost_success(self):
        # On a successful resume resume() fires the returned deferred
        # callback with 'None'.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()

        # The configuration testing command-line.
        self.assertEqual(
            'echo %(vm_host)s', config.builddmaster.vm_resume_command)

        # On success the response is None.
        def check_resume_success(response):
            out, err, code = response
            self.assertEqual(os.EX_OK, code)
            # XXX: JonathanLange 2010-09-23: We should instead pass the
            # expected vm_host into the client slave. Not doing this now,
            # since the SlaveHelper is being moved around.
            self.assertEqual("%s\n" % slave._vm_host, out)
        d = slave.resume()
        d.addBoth(check_resume_success)
        return d

    def test_resumeHost_failure(self):
        # On a failed resume, 'resumeHost' fires the returned deferred
        # errorback with the `ProcessTerminated` failure.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()

        # Override the configuration command-line with one that will fail.
        failed_config = """
        [builddmaster]
        vm_resume_command: test "%(vm_host)s = 'no-sir'"
        """
        config.push('failed_resume_command', failed_config)
        self.addCleanup(config.pop, 'failed_resume_command')

        # On failures, the response is a twisted `Failure` object containing
        # a tuple.
        def check_resume_failure(failure):
            out, err, code = failure.value
            # The process will exit with a return code of "1".
            self.assertEqual(code, 1)
        d = slave.resume()
        d.addBoth(check_resume_failure)
        return d

    def test_resumeHost_timeout(self):
        # On a resume timeouts, 'resumeHost' fires the returned deferred
        # errorback with the `TimeoutError` failure.
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()

        # Override the configuration command-line with one that will timeout.
        timeout_config = """
        [builddmaster]
        vm_resume_command: sleep 5
        socket_timeout: 1
        """
        config.push('timeout_resume_command', timeout_config)
        self.addCleanup(config.pop, 'timeout_resume_command')

        # On timeouts, the response is a twisted `Failure` object containing
        # a `TimeoutError` error.
        def check_resume_timeout(failure):
            self.assertIsInstance(failure, Failure)
            out, err, code = failure.value
            self.assertEqual(code, signal.SIGKILL)
        clock = Clock()
        d = slave.resume(clock=clock)
        # Move the clock beyond the socket_timeout but earlier than the
        # sleep 5.  This stops the test having to wait for the timeout.
        # Fast tests FTW!
        clock.advance(2)
        d.addBoth(check_resume_timeout)
        return d


class TestSlaveWithLibrarian(TrialTestCase):
    """Tests that need more of Launchpad to run."""

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        super(TestSlaveWithLibrarian, self)
        self.slave_helper = SlaveTestHelpers()
        self.slave_helper.setUp()
        self.addCleanup(self.slave_helper.cleanUp)
        self.factory = LaunchpadObjectFactory()
        login_as(ANONYMOUS)
        self.addCleanup(logout)

    def test_ensurepresent_librarian(self):
        # ensurepresent, when given an http URL for a file will download the
        # file from that URL and report that the file is present, and it was
        # downloaded.

        # Use the Librarian because it's a "convenient" web server.
        lf = self.factory.makeLibraryFileAlias(
            'HelloWorld.txt', content="Hello World")
        self.layer.txn.commit()
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        d = slave.ensurepresent(
            lf.content.sha1, lf.http_url, "", "")
        d.addCallback(self.assertEqual, [True, 'Download'])
        return d

    def test_retrieve_files_from_filecache(self):
        # Files that are present on the slave can be downloaded with a
        # filename made from the sha1 of the content underneath the
        # 'filecache' directory.
        content = "Hello World"
        lf = self.factory.makeLibraryFileAlias(
            'HelloWorld.txt', content=content)
        self.layer.txn.commit()
        expected_url = '%s/filecache/%s' % (
            self.slave_helper.BASE_URL, lf.content.sha1)
        self.slave_helper.getServerSlave()
        slave = self.slave_helper.getClientSlave()
        d = slave.ensurepresent(
            lf.content.sha1, lf.http_url, "", "")
        def check_file(ignored):
            d = getPage(expected_url.encode('utf8'))
            return d.addCallback(self.assertEqual, content)
        return d.addCallback(check_file)
