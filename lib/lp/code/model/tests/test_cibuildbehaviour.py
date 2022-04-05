# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test CI build behaviour."""

import base64
from datetime import datetime
import json
import os.path
import re
from textwrap import dedent
import time
from urllib.parse import urlsplit
import uuid

from fixtures import MockPatch
from testtools import ExpectedException
from testtools.matchers import (
    ContainsDict,
    Equals,
    Is,
    IsInstance,
    MatchesDict,
    MatchesListwise,
    StartsWith,
    )
from testtools.twistedsupport import (
    AsynchronousDeferredRunTestForBrokenTwisted,
    )
from twisted.internet import defer
from zope.component import getUtility

from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
    )
from lp.buildmaster.enums import (
    BuildBaseImageType,
    BuildStatus,
    )
from lp.buildmaster.interactor import shut_down_default_process_pool
from lp.buildmaster.interfaces.builder import CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
    )
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.tests.builderproxy import (
    InProcessProxyAuthAPIFixture,
    ProxyURLMatcher,
    RevocationEndpointMatcher,
    )
from lp.buildmaster.tests.mock_workers import (
    MockBuilder,
    OkWorker,
    WorkerTestHelpers,
    )
from lp.buildmaster.tests.test_buildfarmjobbehaviour import (
    TestGetUploadMethodsMixin,
    TestHandleStatusMixin,
    TestVerifySuccessfulBuildMixin,
    )
from lp.code.errors import GitRepositoryBlobNotFound
from lp.code.model.cibuildbehaviour import CIBuildBehaviour
from lp.code.tests.helpers import GitHostingFixture
from lp.services.config import config
from lp.services.log.logger import (
    BufferLogger,
    DevNullLogger,
    )
from lp.services.statsd.tests import StatsMixin
from lp.services.webapp import canonical_url
from lp.soyuz.adapters.archivedependencies import (
    get_sources_list_for_building,
    )
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.tests.soyuz import Base64KeyMatches
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.gpgkeys import gpgkeysdir
from lp.testing.keyserver import InProcessKeyServerFixture
from lp.testing.layers import ZopelessDatabaseLayer


class TestCIBuildBehaviourBase(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def makeJob(self, **kwargs):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distroseries = self.factory.makeDistroSeries(distribution=ubuntu)
        processor = getUtility(IProcessorSet).getByName("386")
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries, architecturetag="i386",
            processor=processor)

        # Taken from test_archivedependencies.py
        for component_name in ("main", "universe"):
            self.factory.makeComponentSelection(distroseries, component_name)

        build = self.factory.makeCIBuild(
            distro_arch_series=distroarchseries, **kwargs)
        return IBuildFarmJobBehaviour(build)


class TestCIBuildBehaviour(TestCIBuildBehaviourBase):

    def test_provides_interface(self):
        # CIBuildBehaviour provides IBuildFarmJobBehaviour.
        job = CIBuildBehaviour(None)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_adapts_ICIBuild(self):
        # IBuildFarmJobBehaviour adapts an ICIBuild.
        build = self.factory.makeCIBuild()
        job = IBuildFarmJobBehaviour(build)
        self.assertProvides(job, IBuildFarmJobBehaviour)

    def test_verifyBuildRequest_valid(self):
        # verifyBuildRequest doesn't raise any exceptions when called with a
        # valid builder set.
        job = self.makeJob()
        lfa = self.factory.makeLibraryFileAlias(db_only=True)
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
        lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(lfa)
        builder = MockBuilder(virtualized=False)
        job.setBuilder(builder, OkWorker())
        logger = BufferLogger()
        e = self.assertRaises(AssertionError, job.verifyBuildRequest, logger)
        self.assertEqual(
            "Attempt to build virtual item on a non-virtual builder.", str(e))

    def test_verifyBuildRequest_no_chroot(self):
        # verifyBuildRequest raises when the DAS has no chroot.
        job = self.makeJob()
        builder = MockBuilder()
        job.setBuilder(builder, OkWorker())
        logger = BufferLogger()
        e = self.assertRaises(CannotBuild, job.verifyBuildRequest, logger)
        self.assertIn("Missing chroot", str(e))


_unset = object()


class TestAsyncCIBuildBehaviour(StatsMixin, TestCIBuildBehaviourBase):

    run_tests_with = AsynchronousDeferredRunTestForBrokenTwisted.make_factory(
        timeout=30)

    @defer.inlineCallbacks
    def setUp(self):
        super().setUp()
        build_username = "CIBUILD-1"
        self.token = {"secret": uuid.uuid4().hex,
                      "username": build_username,
                      "timestamp": datetime.utcnow().isoformat()}
        self.proxy_url = ("http://{username}:{password}"
                          "@{host}:{port}".format(
                            username=self.token["username"],
                            password=self.token["secret"],
                            host=config.builddmaster.builder_proxy_host,
                            port=config.builddmaster.builder_proxy_port))
        self.proxy_api = self.useFixture(InProcessProxyAuthAPIFixture())
        yield self.proxy_api.start()
        self.now = time.time()
        self.useFixture(MockPatch("time.time", return_value=self.now))
        self.addCleanup(shut_down_default_process_pool)
        self.setUpStats()

    def makeJob(self, configuration=_unset, **kwargs):
        # We need a builder in these tests, in order that requesting a proxy
        # token can piggyback on its reactor and pool.
        job = super().makeJob(**kwargs)
        builder = MockBuilder()
        builder.processor = job.build.processor
        worker = self.useFixture(WorkerTestHelpers()).getClientWorker()
        job.setBuilder(builder, worker)
        self.addCleanup(worker.pool.closeCachedConnections)
        if configuration is _unset:
            # Skeleton configuration defining a single job.
            configuration = dedent("""\
                pipeline:
                    - [test]
                jobs:
                    test:
                        series: {}
                        architectures: [{}]
                """.format(
                    job.build.distro_arch_series.distroseries.name,
                    job.build.distro_arch_series.architecturetag)).encode()
        hosting_fixture = self.useFixture(
            GitHostingFixture(blob=configuration, enforce_timeout=True))
        if configuration is None:
            hosting_fixture.getBlob.failure = GitRepositoryBlobNotFound(
                job.build.git_repository.getInternalPath(), ".launchpad.yaml",
                rev=job.build.commit_sha1)
        return job

    @defer.inlineCallbacks
    def test_composeBuildRequest(self):
        job = self.makeJob()
        lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(lfa)
        build_request = yield job.composeBuildRequest(None)
        self.assertThat(build_request, MatchesListwise([
            Equals("ci"),
            Equals(job.build.distro_arch_series),
            Equals(job.build.pocket),
            Equals({}),
            IsInstance(dict),
            ]))

    @defer.inlineCallbacks
    def test_requestProxyToken_unconfigured(self):
        self.pushConfig(
            "builddmaster", builder_proxy_auth_api_admin_secret=None)
        job = self.makeJob()
        expected_exception_msg = (
            "builder_proxy_auth_api_admin_secret is not configured.")
        with ExpectedException(CannotBuild, expected_exception_msg):
            yield job.extraBuildArgs()

    @defer.inlineCallbacks
    def test_requestProxyToken(self):
        job = self.makeJob()
        yield job.extraBuildArgs()
        expected_uri = urlsplit(
            config.builddmaster.builder_proxy_auth_api_endpoint
            ).path.encode("UTF-8")
        self.assertThat(self.proxy_api.tokens.requests, MatchesListwise([
            MatchesDict({
                "method": Equals(b"POST"),
                "uri": Equals(expected_uri),
                "headers": ContainsDict({
                    b"Authorization": MatchesListwise([
                        Equals(b"Basic " + base64.b64encode(
                            b"admin-launchpad.test:admin-secret"))]),
                    b"Content-Type": MatchesListwise([
                        Equals(b"application/json"),
                        ]),
                    }),
                "json": MatchesDict({
                    "username": StartsWith(job.build.build_cookie + "-"),
                    }),
                }),
            ]))

    @defer.inlineCallbacks
    def test_extraBuildArgs_git(self):
        # extraBuildArgs returns appropriate arguments if asked to build a
        # job for a Git commit.
        job = self.makeJob()
        expected_archives, expected_trusted_keys = (
            yield get_sources_list_for_building(
                job, job.build.distro_arch_series, None))
        for archive_line in expected_archives:
            self.assertIn("universe", archive_line)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertThat(args, MatchesDict({
            "archive_private": Is(False),
            "archives": Equals(expected_archives),
            "arch_tag": Equals("i386"),
            "build_url": Equals(canonical_url(job.build)),
            "fast_cleanup": Is(True),
            "git_path": Equals(job.build.commit_sha1),
            "git_repository": Equals(job.build.git_repository.git_https_url),
            "jobs": Equals([[("test", 0)]]),
            "private": Is(False),
            "proxy_url": ProxyURLMatcher(job, self.now),
            "revocation_endpoint": RevocationEndpointMatcher(job, self.now),
            "series": Equals(job.build.distro_series.name),
            "trusted_keys": Equals(expected_trusted_keys),
            }))

    @defer.inlineCallbacks
    def test_extraBuildArgs_archive_trusted_keys(self):
        # If the archive has a signing key, extraBuildArgs sends it.
        yield self.useFixture(InProcessKeyServerFixture()).start()
        job = self.makeJob()
        distribution = job.build.distribution
        key_path = os.path.join(gpgkeysdir, "ppa-sample@canonical.com.sec")
        yield IArchiveGPGSigningKey(distribution.main_archive).setSigningKey(
            key_path, async_keyserver=True)
        self.factory.makeBinaryPackagePublishingHistory(
            distroarchseries=job.build.distro_arch_series,
            pocket=job.build.pocket, archive=distribution.main_archive,
            status=PackagePublishingStatus.PUBLISHED)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertThat(args["trusted_keys"], MatchesListwise([
            Base64KeyMatches("0D57E99656BEFB0897606EE9A022DD1F5001B46D"),
            ]))

    @defer.inlineCallbacks
    def test_extraBuildArgs_archives_primary(self):
        # The build uses the release, security, and updates pockets from the
        # primary archive.
        job = self.makeJob()
        expected_archives = [
            "deb %s %s main universe" % (
                job.archive.archive_url, job.build.distro_series.name),
            "deb %s %s-security main universe" % (
                job.archive.archive_url, job.build.distro_series.name),
            "deb %s %s-updates main universe" % (
                job.archive.archive_url, job.build.distro_series.name),
            ]
        with dbuser(config.builddmaster.dbuser):
            extra_args = yield job.extraBuildArgs()
        self.assertEqual(expected_archives, extra_args["archives"])

    @defer.inlineCallbacks
    def test_extraBuildArgs_private(self):
        # If the repository is private, extraBuildArgs sends the appropriate
        # arguments.
        repository = self.factory.makeGitRepository(
            information_type=InformationType.USERDATA)
        job = self.makeJob(git_repository=repository)
        with dbuser(config.builddmaster.dbuser):
            args = yield job.extraBuildArgs()
        self.assertTrue(args["private"])

    @defer.inlineCallbacks
    def test_composeBuildRequest_proxy_url_set(self):
        job = self.makeJob()
        build_request = yield job.composeBuildRequest(None)
        self.assertThat(
            build_request[4]["proxy_url"], ProxyURLMatcher(job, self.now))

    @defer.inlineCallbacks
    def test_composeBuildRequest_unparseable(self):
        # If the job's configuration file fails to parse,
        # composeBuildRequest raises CannotBuild.
        job = self.makeJob(configuration=b"")
        expected_exception_msg = (
            r"Cannot parse \.launchpad\.yaml from .*: "
            r"Empty configuration file")
        with ExpectedException(CannotBuild, expected_exception_msg):
            yield job.composeBuildRequest(None)

    @defer.inlineCallbacks
    def test_composeBuildRequest_no_jobs_defined(self):
        # If the job's configuration does not define any jobs,
        # composeBuildRequest raises CannotBuild.
        job = self.makeJob(configuration=b"pipeline: []\njobs: {}\n")
        expected_exception_msg = re.escape(
            "No jobs defined for %s:%s" % (
                job.build.git_repository.unique_name, job.build.commit_sha1))
        with ExpectedException(CannotBuild, expected_exception_msg):
            yield job.composeBuildRequest(None)

    @defer.inlineCallbacks
    def test_composeBuildRequest_undefined_job(self):
        # If the job's configuration has a pipeline that defines a job not
        # in the jobs matrix, composeBuildRequest raises CannotBuild.
        job = self.makeJob(configuration=b"pipeline: [test]\njobs: {}\n")
        expected_exception_msg = re.escape(
            "Job 'test' in pipeline for %s:%s but not in jobs" % (
                job.build.git_repository.unique_name, job.build.commit_sha1))
        with ExpectedException(CannotBuild, expected_exception_msg):
            yield job.composeBuildRequest(None)

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_prefers_lxd(self):
        self.pushConfig("builddmaster", builder_proxy_host=None)
        job = self.makeJob()
        builder = MockBuilder()
        builder.processor = job.build.processor
        worker = OkWorker()
        job.setBuilder(builder, worker)
        chroot_lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(
            chroot_lfa, image_type=BuildBaseImageType.CHROOT)
        lxd_lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(
            lxd_lfa, image_type=BuildBaseImageType.LXD)
        yield job.dispatchBuildToWorker(DevNullLogger())
        self.assertEqual(
            ("ensurepresent", lxd_lfa.http_url, "", ""), worker.call_log[0])
        self.assertEqual(1, self.stats_client.incr.call_count)
        self.assertEqual(
            self.stats_client.incr.call_args_list[0][0],
            ("build.count,builder_name={},env=test,"
             "job_type=CIBUILD".format(builder.name),))

    @defer.inlineCallbacks
    def test_dispatchBuildToWorker_falls_back_to_chroot(self):
        self.pushConfig("builddmaster", builder_proxy_host=None)
        job = self.makeJob()
        builder = MockBuilder()
        builder.processor = job.build.processor
        worker = OkWorker()
        job.setBuilder(builder, worker)
        chroot_lfa = self.factory.makeLibraryFileAlias(db_only=True)
        job.build.distro_arch_series.addOrUpdateChroot(
            chroot_lfa, image_type=BuildBaseImageType.CHROOT)
        yield job.dispatchBuildToWorker(DevNullLogger())
        self.assertEqual(
            ("ensurepresent", chroot_lfa.http_url, "", ""), worker.call_log[0])


class MakeCIBuildMixin:
    """Provide the common makeBuild method returning a queued build."""

    def makeBuild(self):
        build = self.factory.makeCIBuild(status=BuildStatus.BUILDING)
        das = build.distro_arch_series
        self.useFixture(GitHostingFixture(blob=dedent("""\
            pipeline:
                - [test]
            jobs:
                test:
                    series: {}
                    architectures: [{}]
            """.format(das.distroseries.name, das.architecturetag)).encode()))
        build.queueBuild()
        return build

    def makeUnmodifiableBuild(self):
        self.skipTest("Not relevant for CI builds.")


class TestGetUploadMethodsForCIBuild(
        MakeCIBuildMixin, TestGetUploadMethodsMixin, TestCaseWithFactory):
    """IPackageBuild.getUpload* methods work with CI builds."""


class TestVerifySuccessfulBuildForCIBuild(
        MakeCIBuildMixin, TestVerifySuccessfulBuildMixin, TestCaseWithFactory):
    """IBuildFarmJobBehaviour.verifySuccessfulBuild works with CI builds."""


class TestHandleStatusForCIBuild(
        MakeCIBuildMixin, TestHandleStatusMixin, TestCaseWithFactory):
    """IPackageBuild.handleStatus works with CI builds."""

    @defer.inlineCallbacks
    def test_handleStatus_WAITING_OK_with_jobs(self):
        # If the worker status includes a "jobs" item, then we additionally
        # dump that to jobs.json.
        with dbuser(config.builddmaster.dbuser):
            yield self.behaviour.handleStatus(
                self.build.buildqueue_record,
                {"builder_status": "BuilderStatus.WAITING",
                 "build_status": "BuildStatus.OK",
                 "filemap": {"build:0.log": "test_file_hash"},
                 "jobs": {"build:0": {"log": "test_file_hash"}}})
        jobs_path = os.path.join(
            self.upload_root, "incoming",
            self.behaviour.getUploadDirLeaf(self.build.build_cookie),
            str(self.build.archive.id), self.build.distribution.name,
            "jobs.json")
        with open(jobs_path) as jobs_file:
            self.assertEqual(
                {"build:0": {"log": "test_file_hash"}}, json.load(jobs_file))
