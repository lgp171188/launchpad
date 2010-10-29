# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for BinaryPackageBuildBehavior."""

__metaclass__ = type

import gzip
import os
import shutil
import tempfile
import transaction

from twisted.internet import defer
from twisted.trial import unittest as trialtest

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.config import config
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.scripts.logger import QuietFakeLogger
from canonical.testing.layers import TwistedLaunchpadZopelessLayer

from lp.buildmaster.enums import (
    BuildStatus,
    )
from lp.buildmaster.tests.mock_slaves import (
    AbortedSlave,
    AbortingSlave,
    BuildingSlave,
    OkSlave,
    WaitingSlave,
    )
from lp.registry.interfaces.pocket import (
    PackagePublishingPocket,
    pocketsuffix,
    )
from lp.registry.interfaces.series import SeriesStatus
from lp.services.job.interfaces.job import JobStatus
from lp.soyuz.adapters.archivedependencies import (
    get_sources_list_for_building,
    )
from lp.soyuz.enums import (
    ArchivePurpose,
    PackagePublishingStatus,
    )
from lp.testing import (
    ANONYMOUS,
    login_as,
    logout,
    )
from lp.testing.factory import LaunchpadObjectFactory


class TestBinaryBuildPackageBehavior(trialtest.TestCase):
    """Tests for the BinaryPackageBuildBehavior.

    In particular, these tests are about how the BinaryPackageBuildBehavior
    interacts with the build slave.  We test this by using a test double that
    implements the same interface as `BuilderSlave` but instead of actually
    making XML-RPC calls, just records any method invocations along with
    interesting parameters.
    """

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        super(TestBinaryBuildPackageBehavior, self).setUp()
        self.factory = LaunchpadObjectFactory()
        login_as(ANONYMOUS)
        self.addCleanup(logout)
        self.layer.switchDbUser('testadmin')

    def assertExpectedInteraction(self, ignored, call_log, builder, build,
                                  chroot, archive, archive_purpose,
                                  component=None, extra_urls=None,
                                  filemap_names=None):
        expected = self.makeExpectedInteraction(
            builder, build, chroot, archive, archive_purpose, component,
            extra_urls, filemap_names)
        self.assertEqual(call_log, expected)

    def makeExpectedInteraction(self, builder, build, chroot, archive,
                                archive_purpose, component=None,
                                extra_urls=None, filemap_names=None):
        """Build the log of calls that we expect to be made to the slave.

        :param builder: The builder we are using to build the binary package.
        :param build: The build being done on the builder.
        :param chroot: The `LibraryFileAlias` for the chroot in which we are
            building.
        :param archive: The `IArchive` into which we are building.
        :param archive_purpose: The ArchivePurpose we are sending to the
            builder. We specify this separately from the archive because
            sometimes the behavior object has to give a different purpose
            in order to trick the slave into building correctly.
        :return: A list of the calls we expect to be made.
        """
        job = removeSecurityProxy(builder.current_build_behavior).buildfarmjob
        build_id = job.generateSlaveBuildCookie()
        ds_name = build.distro_arch_series.distroseries.name
        suite = ds_name + pocketsuffix[build.pocket]
        archives = get_sources_list_for_building(
            build, build.distro_arch_series,
            build.source_package_release.name)
        arch_indep = build.distro_arch_series.isNominatedArchIndep
        if component is None:
            component = build.current_component.name
        if filemap_names is None:
            filemap_names = []
        if extra_urls is None:
            extra_urls = []

        upload_logs = [
            ('ensurepresent', url, '', '')
            for url in [chroot.http_url] + extra_urls]

        extra_args = {
            'arch_indep': arch_indep,
            'arch_tag': build.distro_arch_series.architecturetag,
            'archive_private': archive.private,
            'archive_purpose': archive_purpose.name,
            'archives': archives,
            'build_debug_symbols': archive.build_debug_symbols,
            'ogrecomponent': component,
            'suite': suite,
            }
        build_log = [
            ('build', build_id, 'binarypackage', chroot.content.sha1,
             filemap_names, extra_args)]
        return upload_logs + build_log

    def startBuild(self, builder, candidate):
        builder = removeSecurityProxy(builder)
        candidate = removeSecurityProxy(candidate)
        return defer.maybeDeferred(
            builder.startBuild, candidate, QuietFakeLogger())

    def test_non_virtual_ppa_dispatch(self):
        # When the BinaryPackageBuildBehavior dispatches PPA builds to
        # non-virtual builders, it stores the chroot on the server and
        # requests a binary package build, lying to say that the archive
        # purpose is "PRIMARY" because this ensures that the package mangling
        # tools will run over the built packages.
        archive = self.factory.makeArchive(virtualized=False)
        slave = OkSlave()
        builder = self.factory.makeBuilder(virtualized=False)
        builder.setSlaveForTesting(slave)
        build = self.factory.makeBinaryPackageBuild(
            builder=builder, archive=archive)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        build.distro_arch_series.addOrUpdateChroot(lf)
        candidate = build.queueBuild()
        d = self.startBuild(builder, candidate)
        d.addCallback(
            self.assertExpectedInteraction, slave.call_log,
            builder, build, lf, archive, ArchivePurpose.PRIMARY, 'universe')
        return d

    def test_virtual_ppa_dispatch(self):
        # Make sure the builder slave gets reset before a build is
        # dispatched to it.
        archive = self.factory.makeArchive(virtualized=True)
        slave = OkSlave()
        builder = self.factory.makeBuilder(
            virtualized=True, vm_host="foohost")
        builder.setSlaveForTesting(slave)
        build = self.factory.makeBinaryPackageBuild(
            builder=builder, archive=archive)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        build.distro_arch_series.addOrUpdateChroot(lf)
        candidate = build.queueBuild()
        d = self.startBuild(builder, candidate)
        def check_build(ignored):
            # We expect the first call to the slave to be a resume call,
            # followed by the rest of the usual calls we expect.
            expected_resume_call = slave.call_log.pop(0)
            self.assertEqual('resume', expected_resume_call)
            self.assertExpectedInteraction(
                ignored, slave.call_log,
                builder, build, lf, archive, ArchivePurpose.PPA)
        return d.addCallback(check_build)

    def test_partner_dispatch_no_publishing_history(self):
        archive = self.factory.makeArchive(
            virtualized=False, purpose=ArchivePurpose.PARTNER)
        slave = OkSlave()
        builder = self.factory.makeBuilder(virtualized=False)
        builder.setSlaveForTesting(slave)
        build = self.factory.makeBinaryPackageBuild(
            builder=builder, archive=archive)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        build.distro_arch_series.addOrUpdateChroot(lf)
        candidate = build.queueBuild()
        d = self.startBuild(builder, candidate)
        d.addCallback(
            self.assertExpectedInteraction, slave.call_log,
            builder, build, lf, archive, ArchivePurpose.PARTNER)
        return d

    def test_dont_dispatch_release_builds(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        builder = self.factory.makeBuilder()
        distroseries = self.factory.makeDistroSeries(
            status=SeriesStatus.CURRENT, distribution=archive.distribution)
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=distroseries)
        build = self.factory.makeBinaryPackageBuild(
            builder=builder, archive=archive,
            distroarchseries=distro_arch_series,
            pocket=PackagePublishingPocket.RELEASE)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        build.distro_arch_series.addOrUpdateChroot(lf)
        candidate = build.queueBuild()
        behavior = candidate.required_build_behavior
        behavior.setBuilder(builder)
        e = self.assertRaises(
            AssertionError, behavior.verifyBuildRequest, QuietFakeLogger())
        expected_message = (
            "%s (%s) can not be built for pocket %s: invalid pocket due "
            "to the series status of %s." % (
                build.title, build.id, build.pocket.name,
                build.distro_series.name))
        self.assertEqual(expected_message, str(e))

    def test_dont_dispatch_security_builds(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        builder = self.factory.makeBuilder()
        build = self.factory.makeBinaryPackageBuild(
            builder=builder, archive=archive,
            pocket=PackagePublishingPocket.SECURITY)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        build.distro_arch_series.addOrUpdateChroot(lf)
        candidate = build.queueBuild()
        behavior = candidate.required_build_behavior
        behavior.setBuilder(builder)
        e = self.assertRaises(
            AssertionError, behavior.verifyBuildRequest, QuietFakeLogger())
        self.assertEqual(
            'Soyuz is not yet capable of building SECURITY uploads.',
            str(e))

    def test_verifyBuildRequest(self):
        # Don't allow a virtual build on a non-virtual builder.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        builder = self.factory.makeBuilder(virtualized=False)
        build = self.factory.makeBinaryPackageBuild(
            builder=builder, archive=archive,
            pocket=PackagePublishingPocket.RELEASE)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        build.distro_arch_series.addOrUpdateChroot(lf)
        candidate = build.queueBuild()
        behavior = candidate.required_build_behavior
        behavior.setBuilder(builder)
        e = self.assertRaises(
            AssertionError, behavior.verifyBuildRequest, QuietFakeLogger())
        self.assertEqual(
            'Attempt to build virtual item on a non-virtual builder.',
            str(e))


class TestBinaryBuildPackageBehaviorBuildCollection(trialtest.TestCase):
    """Tests for the BinaryPackageBuildBehavior.

    Using various mock slaves, we check how updateBuild() behaves in
    various scenarios.
    """

    # XXX: These tests replace part of the old buildd-slavescanner.txt
    # It was checking that each call to updateBuild was sending 3 (!)
    # emails but this behaviour is so ill-defined and dependent on the
    # sample data that I've not replicated that here.  We need to
    # examine that behaviour separately somehow, but the old tests gave
    # NO clue as to what, exactly, they were testing.

    layer = TwistedLaunchpadZopelessLayer

    def setUp(self):
        super(TestBinaryBuildPackageBehaviorBuildCollection, self).setUp()
        self.factory = LaunchpadObjectFactory()
        login_as(ANONYMOUS)
        self.addCleanup(logout)
        self.layer.switchDbUser('testadmin')

        self.builder = self.factory.makeBuilder()
        self.build = self.factory.makeBinaryPackageBuild(
            builder=self.builder, pocket=PackagePublishingPocket.RELEASE)
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        self.build.distro_arch_series.addOrUpdateChroot(lf)
        self.candidate = self.build.queueBuild()
        self.candidate.markAsBuilding(self.builder)
        self.behavior = self.candidate.required_build_behavior
        self.behavior.setBuilder(self.builder)
        # This is required so that uploaded files from the buildd don't
        # hang around between test runs.
        self.addCleanup(shutil.rmtree, config.builddmaster.root)

    def assertBuildProperties(self, build):
        """Check that a build happened by making sure some of its properties
        are set."""
        self.assertNotIdentical(None, build.builder)
        self.assertNotIdentical(None, build.date_finished)
        self.assertNotIdentical(None, build.duration)
        self.assertNotIdentical(None, build.log)

    def test_packagefail_collection(self):
        # When a package fails to build, make sure the builder notes are
        # stored and the build status is set as failed.
        waiting_slave = WaitingSlave('BuildStatus.PACKAGEFAIL')
        self.builder.setSlaveForTesting(waiting_slave)

        def got_update(ignored):
            self.assertBuildProperties(self.build)
            self.assertEqual(BuildStatus.FAILEDTOBUILD, self.build.status)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_depwait_collection(self):
        # Package build was left in dependency wait.
        DEPENDENCIES = 'baz (>= 1.0.1)'
        waiting_slave = WaitingSlave('BuildStatus.DEPFAIL', DEPENDENCIES)
        self.builder.setSlaveForTesting(waiting_slave)

        def got_update(ignored):
            self.assertBuildProperties(self.build)
            self.assertEqual(BuildStatus.MANUALDEPWAIT, self.build.status)
            self.assertEqual(DEPENDENCIES, self.build.dependencies)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_chrootfail_collection(self):
        # There was a chroot problem for this build.
        waiting_slave = WaitingSlave('BuildStatus.CHROOTFAIL')
        self.builder.setSlaveForTesting(waiting_slave)

        def got_update(ignored):
            self.assertBuildProperties(self.build)
            self.assertEqual(BuildStatus.CHROOTWAIT, self.build.status)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_builderfail_collection(self):
        # The builder failed after we dispatched the build.
        waiting_slave = WaitingSlave('BuildStatus.BUILDERFAIL')
        self.builder.setSlaveForTesting(waiting_slave)

        def got_update(ignored):
            self.assertEqual(
                "Builder returned BUILDERFAIL when asked for its status",
                self.builder.failnotes)
            self.assertIdentical(None, self.candidate.builder)
            self.assertEqual(BuildStatus.NEEDSBUILD, self.build.status)
            job = self.candidate.specific_job.job
            self.assertEqual(JobStatus.WAITING, job.status)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_building_collection(self):
        # The builder is still building the package.
        self.builder.setSlaveForTesting(BuildingSlave())
        
        def got_update(ignored):
            # The fake log is returned from the BuildingSlave() mock.
            self.assertEqual("This is a build log", self.candidate.logtail)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_aborted_collection(self):
        # The builder aborted the job.
        self.builder.setSlaveForTesting(AbortedSlave())

        def got_update(ignored):
            self.assertEqual(BuildStatus.NEEDSBUILD, self.build.status)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_aborting_collection(self):
        # The builder is in the process of aborting.
        self.builder.setSlaveForTesting(AbortingSlave())

        def got_update(ignored):
            self.assertEqual(
                "Waiting for slave process to be terminated",
                self.candidate.logtail)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_uploading_collection(self):
        # After a successful build, the status should be UPLOADING.
        self.builder.setSlaveForTesting(WaitingSlave('BuildStatus.OK'))

        def got_update(ignored):
            self.assertEqual(self.build.status, BuildStatus.UPLOADING)
            # We do not store any upload log information when the binary
            # upload processing succeeded.
            self.assertIdentical(None, self.build.upload_log)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_givenback_collection(self):
        waiting_slave = WaitingSlave('BuildStatus.GIVENBACK')
        self.builder.setSlaveForTesting(waiting_slave)
        score = self.candidate.lastscore

        def got_update(ignored):       
            self.assertIdentical(None, self.candidate.builder)
            self.assertIdentical(None, self.candidate.date_started)
            self.assertEqual(score, self.candidate.lastscore)
            self.assertEqual(BuildStatus.NEEDSBUILD, self.build.status)
            job = self.candidate.specific_job.job
            self.assertEqual(JobStatus.WAITING, job.status)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

    def test_log_file_collection(self):
        self.builder.setSlaveForTesting(WaitingSlave('BuildStatus.OK'))
        self.build.status = BuildStatus.FULLYBUILT
        old_tmps = sorted(os.listdir('/tmp'))

        # Grabbing logs should not leave new files in /tmp (bug #172798)
        # XXX 2010-10-18 bug=662631
        # Change this to do non-blocking IO.
        logfile_lfa_id = self.build.getLogFromSlave(self.build)
        logfile_lfa = getUtility(ILibraryFileAliasSet)[logfile_lfa_id]
        new_tmps = sorted(os.listdir('/tmp'))
        self.assertEqual(old_tmps, new_tmps)

        # The new librarian file is stored compressed with a .gz
        # extension and text/plain file type for easy viewing in
        # browsers, as it decompresses and displays the file inline.
        self.assertTrue(logfile_lfa.filename).endswith('_FULLYBUILT.txt.gz')
        self.assertEqual('text/plain', logfile_lfa.mimetype)
        self.layer.txn.commit()

        # LibrarianFileAlias does not implement tell() or seek(), which
        # are required by gzip.open(), so we need to read the file out
        # of the librarian first.
        fd, fname = tempfile.mkstemp()
        self.addCleanup(os.remove, fname)
        tmp = os.fdopen(fd, 'wb')
        tmp.write(logfile_lfa.read())
        tmp.close()
        uncompressed_file = gzip.open(fname).read()

        # XXX: 2010-10-18 bug=662631
        # When the mock slave is changed to return a Deferred,
        # update this test too.
        orig_file = removeSecurityProxy(self.builder.slave).getFile(
            'buildlog').read()
        self.assertEqual(orig_file, uncompressed_file)

    def test_private_build_log_storage(self):
        # Builds in private archives should have their log uploaded to
        # the restricted librarian.
        self.builder.setSlaveForTesting(WaitingSlave('BuildStatus.OK'))

        # Un-publish the source so we don't trip the 'private' field
        # validator.
        from storm.store import Store
        for source in self.build.archive.getPublishedSources():
            Store.of(source).remove(source)
        self.build.archive.private = True
        self.build.archive.buildd_secret = "foo"

        def got_update(ignored):
            # Librarian needs a commit.  :(
            self.layer.txn.commit()
            self.assertTrue(self.build.log.restricted)

        d = self.builder.updateBuild(self.candidate)
        return d.addCallback(got_update)

