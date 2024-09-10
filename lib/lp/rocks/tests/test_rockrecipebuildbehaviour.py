# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test rock recipe build behaviour."""

import os.path

import transaction
from pymacaroons import Macaroon
from testtools import ExpectedException
from testtools.matchers import (
    Equals,
    Is,
    IsInstance,
    MatchesDict,
    MatchesListwise,
)
from testtools.twistedsupport import (
    AsynchronousDeferredRunTestForBrokenTwisted,
)
from twisted.internet import defer
from zope.component import getUtility
from zope.proxy import isProxy
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
)
from lp.buildmaster.enums import BuildBaseImageType, BuildStatus
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.tests.mock_workers import MockBuilder, OkWorker
from lp.buildmaster.tests.test_buildfarmjobbehaviour import (
    TestGetUploadMethodsMixin,
    TestHandleStatusMixin,
    TestVerifySuccessfulBuildMixin,
)
from lp.registry.interfaces.series import SeriesStatus
from lp.rocks.interfaces.rockrecipe import (
    ROCK_RECIPE_ALLOW_CREATE,
    ROCK_RECIPE_PRIVATE_FEATURE_FLAG,
)
from lp.rocks.model.rockrecipebuildbehaviour import RockRecipeBuildBehaviour
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.log.logger import BufferLogger, DevNullLogger
from lp.services.statsd.tests import StatsMixin
from lp.services.webapp import canonical_url
from lp.soyuz.adapters.archivedependencies import get_sources_list_for_building
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.tests.soyuz import Base64KeyMatches
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.gpgkeys import gpgkeysdir
from lp.testing.keyserver import InProcessKeyServerFixture
from lp.testing.layers import LaunchpadZopelessLayer


class TestRockRecipeBuildBehaviourBase(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))
        super().setUp()

    def makeJob(self, distribution=None, with_builder=False, **kwargs):
        """Create a sample `IRockRecipeBuildBehaviour`."""
        if distribution is None:
            distribution = self.factory.makeDistribution(name="distro")
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, name="unstable"
        )
        processor = getUtility(IProcessorSet).getByName("386")
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag="i386",
            processor=processor,
        )

        # Taken from test_archivedependencies.py
        for component_name in ("main", "universe"):
            self.factory.makeComponentSelection(distroseries, component_name)

        build = self.factory.makeRockRecipeBuild(
            distro_arch_series=distroarchseries, name="test-rock", **kwargs
        )
        job = IBuildFarmJobBehaviour(build)
        if with_builder:
            builder = MockBuilder()
            builder.processor = processor
            job.setBuilder(builder, None)
        return job


class TestRockRecipeBuildBehaviour(TestRockRecipeBuildBehaviourBase):
    layer = LaunchpadZopelessLayer

    def test_provides_interface(self):
        # RockRecipeBuildBehaviour provides IBuildFarmJobBehaviour.
        job = RockRecipeBuildBehaviour(None)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_adapts_IRockRecipeBuild(self):
        # IBuildFarmJobBehaviour adapts an IRockRecipeBuild.
        build = self.factory.makeRockRecipeBuild()
        job = IBuildFarmJobBehaviour(build)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_verifyBuildRequest_valid(self):
        # verifyBuildRequest doesn't raise any exceptions when called with a
        # valid builder set.
        job = self.makeJob()
        lfa = self.factory.makeLibraryFileAlias()
        transaction.commit()
        job.build.distro_arch_series.addOrUpdateChroot(lfa)
        builder = MockBuilder()
        job.setBuilder(builder, OkWorker())
        logger = BufferLogger()
        job.verifyBuildRequest(logger)
        self.assertEqual("", logger.getLogBuffer())

    def test_verifyBuildRequest_virtual_mismatch(self):
        # verifyBuildRequest raises on an attempt to build a virtualized
        # build on a non-virtual builder.
        job = self.makeJob()
        lfa = self.factory.makeLibraryFileAlias()
        transaction.commit()
        job.build.distro_arch_series.addOrUpdateChroot(lfa)
        builder = MockBuilder(virtualized=False)
        job.setBuilder(builder, OkWorker())
        logger = BufferLogger()
        e = self.assertRaises(AssertionError, job.verifyBuildRequest, logger)
        self.assertEqual(
            "Attempt to build virtual item on a non-virtual builder.", str(e)
        )

    def test_verifyBuildRequest_no_chroot(self):
        # verifyBuildRequest raises when the DAS has no chroot.
        job = self.makeJob()
        builder = MockBuilder()
        job.setBuilder(builder, OkWorker())
        logger = BufferLogger()
        e = self.assertRaises(CannotBuild, job.verifyBuildRequest, logger)
        self.assertIn("Missing chroot", str(e))


class TestAsyncRockRecipeBuildBehaviour(
    StatsMixin, TestRockRecipeBuildBehaviourBase
):

    run_tests_with = AsynchronousDeferredRunTestForBrokenTwisted.make_factory(
        timeout=30
    )

    def setUp(self):
        super().setUp()
        self.setUpStats()

    @defer.inlineCallbacks
    def test_composeBuildRequest(self):
        job = self.makeJob(with_builder=True)
        lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(lfa)
        build_request = yield job.composeBuildRequest(None)
        self.assertThat(
            build_request,
            MatchesListwise(
                [
                    Equals("rock"),
                    Equals(job.build.distro_arch_series),
                    Equals(job.build.pocket),
                    Equals({}),
                    IsInstance(dict),
                ]
            ),
        )

    @defer.inlineCallbacks
    def test_extraBuildArgs_git(self):
        # extraBuildArgs returns appropriate arguments if asked to build a
        # job for a Git branch.
        [ref] = self.factory.makeGitRefs()
        job = self.makeJob(git_ref=ref, with_builder=True)
        expected_archives, expected_trusted_keys = (
            yield get_sources_list_for_building(
                job, job.build.distro_arch_series, None
            )
        )
        for archive_line in expected_archives:
            self.assertIn("universe", archive_line)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertThat(
            args,
            MatchesDict(
                {
                    "archive_private": Is(False),
                    "archives": Equals(expected_archives),
                    "arch_tag": Equals("i386"),
                    "build_url": Equals(canonical_url(job.build)),
                    "builder_constraints": Equals([]),
                    "channels": Equals({}),
                    "fast_cleanup": Is(True),
                    "git_repository": Equals(ref.repository.git_https_url),
                    "git_path": Equals(ref.name),
                    "name": Equals("test-rock"),
                    "private": Is(False),
                    "series": Equals("unstable"),
                    "trusted_keys": Equals(expected_trusted_keys),
                }
            ),
        )

    @defer.inlineCallbacks
    def test_extraBuildArgs_git_HEAD(self):
        # extraBuildArgs returns appropriate arguments if asked to build a
        # job for the default branch in a Launchpad-hosted Git repository.
        [ref] = self.factory.makeGitRefs()
        removeSecurityProxy(ref.repository)._default_branch = ref.path
        job = self.makeJob(
            git_ref=ref.repository.getRefByPath("HEAD"), with_builder=True
        )
        expected_archives, expected_trusted_keys = (
            yield get_sources_list_for_building(
                job, job.build.distro_arch_series, None
            )
        )
        for archive_line in expected_archives:
            self.assertIn("universe", archive_line)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertThat(
            args,
            MatchesDict(
                {
                    "archive_private": Is(False),
                    "archives": Equals(expected_archives),
                    "arch_tag": Equals("i386"),
                    "build_url": Equals(canonical_url(job.build)),
                    "builder_constraints": Equals([]),
                    "channels": Equals({}),
                    "fast_cleanup": Is(True),
                    "git_repository": Equals(ref.repository.git_https_url),
                    "name": Equals("test-rock"),
                    "private": Is(False),
                    "series": Equals("unstable"),
                    "trusted_keys": Equals(expected_trusted_keys),
                }
            ),
        )

    @defer.inlineCallbacks
    def test_extraBuildArgs_prefers_store_name(self):
        # For the "name" argument, extraBuildArgs prefers
        # RockRecipe.store_name over RockRecipe.name if the former is set.
        job = self.makeJob(store_name="something-else", with_builder=True)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertEqual("something-else", args["name"])

    @defer.inlineCallbacks
    def test_extraBuildArgs_archive_trusted_keys(self):
        # If the archive has a signing key, extraBuildArgs sends it.
        yield self.useFixture(InProcessKeyServerFixture()).start()
        distribution = self.factory.makeDistribution()
        key_path = os.path.join(gpgkeysdir, "ppa-sample@canonical.com.sec")
        yield IArchiveGPGSigningKey(distribution.main_archive).setSigningKey(
            key_path, async_keyserver=True
        )
        job = self.makeJob(distribution=distribution, with_builder=True)
        self.factory.makeBinaryPackagePublishingHistory(
            distroarchseries=job.build.distro_arch_series,
            pocket=job.build.pocket,
            archive=distribution.main_archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertThat(
            args["trusted_keys"],
            MatchesListwise(
                [
                    Base64KeyMatches(
                        "0D57E99656BEFB0897606EE9A022DD1F5001B46D"
                    ),
                ]
            ),
        )

    @defer.inlineCallbacks
    def test_extraBuildArgs_channels(self):
        # If the build needs particular channels, extraBuildArgs sends them.
        job = self.makeJob(channels={"rockcraft": "edge"}, with_builder=True)
        expected_archives, expected_trusted_keys = (
            yield get_sources_list_for_building(
                job, job.build.distro_arch_series, None
            )
        )
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertFalse(isProxy(args["channels"]))
        self.assertEqual({"rockcraft": "edge"}, args["channels"])

    @defer.inlineCallbacks
    def test_extraBuildArgs_archives_primary(self):
        # The build uses the release, security, and updates pockets from the
        # primary archive.
        job = self.makeJob(with_builder=True)
        expected_archives = [
            "deb %s %s main universe"
            % (job.archive.archive_url, job.build.distro_series.name),
            "deb %s %s-security main universe"
            % (job.archive.archive_url, job.build.distro_series.name),
            "deb %s %s-updates main universe"
            % (job.archive.archive_url, job.build.distro_series.name),
        ]
        with dbuser(config.builddmaster.dbuser):
            extra_args = yield job.extraBuildArgs()
        self.assertEqual(expected_archives, extra_args["archives"])

    @defer.inlineCallbacks
    def test_extraBuildArgs_private(self):
        # If the recipe is private, extraBuildArgs sends the appropriate
        # arguments.
        self.useFixture(
            FeatureFixture(
                {
                    ROCK_RECIPE_ALLOW_CREATE: "on",
                    ROCK_RECIPE_PRIVATE_FEATURE_FLAG: "on",
                }
            )
        )
        job = self.makeJob(
            information_type=InformationType.PROPRIETARY, with_builder=True
        )
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertTrue(args["private"])

    @defer.inlineCallbacks
    def test_composeBuildRequest_git_ref_deleted(self):
        # If the source Git reference has been deleted, composeBuildRequest
        # raises CannotBuild.
        repository = self.factory.makeGitRepository()
        [ref] = self.factory.makeGitRefs(repository=repository)
        owner = self.factory.makePerson(name="rock-owner")
        project = self.factory.makeProduct(name="rock-project")
        job = self.makeJob(
            registrant=owner,
            owner=owner,
            project=project,
            git_ref=ref,
            with_builder=True,
        )
        repository.removeRefs([ref.path])
        self.assertIsNone(job.build.recipe.git_ref)
        expected_exception_msg = (
            r"Source repository for "
            r"~rock-owner/rock-project/\+rock/test-rock has been deleted."
        )
        with ExpectedException(CannotBuild, expected_exception_msg):
            yield job.composeBuildRequest(None)

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_prefers_lxd(self):
        job = self.makeJob()
        builder = MockBuilder()
        builder.processor = job.build.processor
        worker = OkWorker()
        job.setBuilder(builder, worker)
        chroot_lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(
            chroot_lfa, image_type=BuildBaseImageType.CHROOT
        )
        lxd_lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(
            lxd_lfa, image_type=BuildBaseImageType.LXD
        )
        yield job.dispatchBuildToWorker(DevNullLogger())
        self.assertEqual(
            ("ensurepresent", lxd_lfa.http_url, "", ""), worker.call_log[0]
        )
        self.assertEqual(1, self.stats_client.incr.call_count)
        self.assertEqual(
            self.stats_client.incr.call_args_list[0][0],
            (
                "build.count,builder_name={},env=test,"
                "job_type=ROCKRECIPEBUILD,region={}".format(
                    builder.name, builder.region
                ),
            ),
        )

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_falls_back_to_chroot(self):
        job = self.makeJob()
        builder = MockBuilder()
        builder.processor = job.build.processor
        worker = OkWorker()
        job.setBuilder(builder, worker)
        chroot_lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(
            chroot_lfa, image_type=BuildBaseImageType.CHROOT
        )
        yield job.dispatchBuildToWorker(DevNullLogger())
        self.assertEqual(
            ("ensurepresent", chroot_lfa.http_url, "", ""), worker.call_log[0]
        )


class MakeRockRecipeBuildMixin:
    """Provide the common makeBuild method returning a queued build."""

    def makeRockRecipe(self):
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))
        return self.factory.makeRockRecipe(
            store_upload=True,
            store_name=self.factory.getUniqueUnicode(),
            store_secrets={"root": Macaroon().serialize()},
        )

    def makeBuild(self):
        recipe = self.makeRockRecipe()
        build = self.factory.makeRockRecipeBuild(
            requester=recipe.registrant,
            recipe=recipe,
            status=BuildStatus.BUILDING,
        )
        build.queueBuild()
        return build

    def makeUnmodifiableBuild(self):
        recipe = self.makeRockRecipe()
        build = self.factory.makeRockRecipeBuild(
            requester=recipe.registrant,
            recipe=recipe,
            status=BuildStatus.BUILDING,
        )
        build.distro_series.status = SeriesStatus.OBSOLETE
        build.queueBuild()
        return build


class TestGetUploadMethodsForRockRecipeBuild(
    MakeRockRecipeBuildMixin, TestGetUploadMethodsMixin, TestCaseWithFactory
):
    """IPackageBuild.getUpload* methods work with rock recipe builds."""


class TestVerifySuccessfulBuildForRockRecipeBuild(
    MakeRockRecipeBuildMixin,
    TestVerifySuccessfulBuildMixin,
    TestCaseWithFactory,
):
    """IBuildFarmJobBehaviour.verifySuccessfulBuild works."""


class TestHandleStatusForRockRecipeBuild(
    MakeRockRecipeBuildMixin, TestHandleStatusMixin, TestCaseWithFactory
):
    """IPackageBuild.handleStatus works with rock recipe builds."""
