# Copyright 2022-2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test CI builds."""

import hashlib
from datetime import datetime, timedelta, timezone
from textwrap import dedent
from unittest.mock import Mock
from urllib.request import urlopen

from fixtures import FakeLogger, MockPatchObject
from pymacaroons import Macaroon
from storm.locals import Store
from testtools.matchers import (
    ContainsDict,
    Equals,
    Is,
    MatchesDict,
    MatchesListwise,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility
from zope.publisher.xmlrpc import TestRequest
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import ILaunchpadCelebrities, IPrivacy
from lp.buildmaster.enums import BuildQueueStatus, BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildfarmjob import BuildFarmJob
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.errors import GitRepositoryBlobNotFound, GitRepositoryScanFault
from lp.code.interfaces.cibuild import (
    CI_WEBHOOKS_FEATURE_FLAG,
    CannotFetchConfiguration,
    CannotParseConfiguration,
    CIBuildAlreadyRequested,
    CIBuildDisallowedArchitecture,
    ICIBuild,
    ICIBuildSet,
    MissingConfiguration,
)
from lp.code.interfaces.revisionstatus import IRevisionStatusReportSet
from lp.code.model.cibuild import (
    determine_DASes_to_build,
    get_all_commits_for_paths,
)
from lp.code.model.lpci import load_configuration
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackage import SourcePackageType
from lp.services.authserver.xmlrpc import AuthServerAPIView
from lp.services.config import config
from lp.services.database.sqlbase import flush_database_caches
from lp.services.features.testing import FeatureFixture
from lp.services.librarian.browser import ProxiedLibraryFileAlias
from lp.services.log.logger import BufferLogger
from lp.services.macaroons.interfaces import IMacaroonIssuer
from lp.services.macaroons.testing import MacaroonTestMixin
from lp.services.propertycache import clear_property_cache
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.soyuz.enums import BinaryPackageFormat
from lp.testing import (
    ANONYMOUS,
    StormStatementRecorder,
    TestCaseWithFactory,
    api_url,
    celebrity_logged_in,
    login,
    logout,
    person_logged_in,
    pop_notifications,
)
from lp.testing.dbuser import dbuser
from lp.testing.layers import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person
from lp.xmlrpc.interfaces import IPrivateApplication


class TestGetAllCommitsForPaths(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_no_refs(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]

        rv = get_all_commits_for_paths(repository, ref_paths)

        self.assertEqual([], rv)

    def test_one_ref_one_path(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        [ref] = self.factory.makeGitRefs(repository, ref_paths)

        rv = get_all_commits_for_paths(repository, ref_paths)

        self.assertEqual(1, len(rv))
        self.assertEqual(ref.commit_sha1, rv[0])

    def test_multiple_refs_and_paths(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master", "refs/heads/dev"]
        refs = self.factory.makeGitRefs(repository, ref_paths)

        rv = get_all_commits_for_paths(repository, ref_paths)

        self.assertEqual(2, len(rv))
        self.assertEqual({ref.commit_sha1 for ref in refs}, set(rv))


class TestCIBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_implements_interfaces(self):
        # CIBuild implements IPackageBuild, ICIBuild, and IPrivacy.
        build = self.factory.makeCIBuild()
        self.assertProvides(build, IPackageBuild)
        self.assertProvides(build, ICIBuild)
        self.assertProvides(build, IPrivacy)

    def test___repr__(self):
        # CIBuild has an informative __repr__.
        build = self.factory.makeCIBuild()
        self.assertEqual(
            "<CIBuild %s/+build/%s>"
            % (build.git_repository.unique_name, build.id),
            repr(build),
        )

    def test_title(self):
        # CIBuild has an informative title.
        build = self.factory.makeCIBuild()
        self.assertEqual(
            "%s CI build of %s:%s"
            % (
                build.distro_arch_series.architecturetag,
                build.git_repository.unique_name,
                build.commit_sha1,
            ),
            build.title,
        )

    def test_queueBuild(self):
        # CIBuild can create the queue entry for itself.
        build = self.factory.makeCIBuild()
        bq = build.queueBuild()
        self.assertProvides(bq, IBuildQueue)
        self.assertEqual(
            build.build_farm_job, removeSecurityProxy(bq)._build_farm_job
        )
        self.assertEqual(build, bq.specific_build)
        self.assertEqual(build.virtualized, bq.virtualized)
        self.assertIsNone(bq.builder_constraints)
        self.assertIsNotNone(bq.processor)
        self.assertEqual(bq, build.buildqueue_record)

    def test_queueBuild_builder_constraints(self):
        # Builds inherit any builder constraints from their repository.
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                builder_constraints=["gpu"]
            )
        )
        bq = build.queueBuild()
        self.assertProvides(bq, IBuildQueue)
        self.assertEqual(("gpu",), bq.builder_constraints)

    def test_is_private(self):
        # A CIBuild is private iff its repository is.
        build = self.factory.makeCIBuild()
        self.assertFalse(build.is_private)
        self.assertFalse(build.private)
        with person_logged_in(self.factory.makePerson()) as owner:
            build = self.factory.makeCIBuild(
                git_repository=self.factory.makeGitRepository(
                    owner=owner, information_type=InformationType.USERDATA
                )
            )
            self.assertTrue(build.is_private)
            self.assertTrue(build.private)

    def test_can_be_retried(self):
        ok_cases = [
            BuildStatus.FAILEDTOBUILD,
            BuildStatus.MANUALDEPWAIT,
            BuildStatus.CHROOTWAIT,
            BuildStatus.FAILEDTOUPLOAD,
            BuildStatus.CANCELLED,
            BuildStatus.SUPERSEDED,
        ]
        for status in BuildStatus.items:
            build = self.factory.makeCIBuild(status=status)
            if status in ok_cases:
                self.assertTrue(build.can_be_retried)
            else:
                self.assertFalse(build.can_be_retried)

    def test_can_be_retried_obsolete_series(self):
        # Builds for obsolete series cannot be retried.
        distroseries = self.factory.makeDistroSeries(
            status=SeriesStatus.OBSOLETE
        )
        das = self.factory.makeDistroArchSeries(distroseries=distroseries)
        build = self.factory.makeCIBuild(distro_arch_series=das)
        self.assertFalse(build.can_be_retried)

    def test_can_be_cancelled(self):
        # For all states that can be cancelled, can_be_cancelled returns True.
        ok_cases = [
            BuildStatus.BUILDING,
            BuildStatus.NEEDSBUILD,
        ]
        for status in BuildStatus.items:
            build = self.factory.makeCIBuild()
            build.queueBuild()
            build.updateStatus(status)
            if status in ok_cases:
                self.assertTrue(build.can_be_cancelled)
            else:
                self.assertFalse(build.can_be_cancelled)

    def test_retry_resets_state(self):
        # Retrying a build resets most of the state attributes, but does
        # not modify the first dispatch time.
        now = datetime.now(timezone.utc)
        build = self.factory.makeCIBuild()
        build.updateStatus(BuildStatus.BUILDING, date_started=now)
        build.updateStatus(BuildStatus.FAILEDTOBUILD)
        build.gotFailure()
        with person_logged_in(build.git_repository.owner):
            build.retry()
        self.assertEqual(BuildStatus.NEEDSBUILD, build.status)
        self.assertEqual(now, build.date_first_dispatched)
        self.assertIsNone(build.log)
        self.assertIsNone(build.upload_log)
        self.assertEqual(0, build.failure_count)

    def test_retry_resets_builder_constraints(self):
        # Retrying a build recalculates its builder constraints.
        build = self.factory.makeCIBuild()
        self.assertIsNone(build.builder_constraints)
        build.updateStatus(BuildStatus.BUILDING)
        build.updateStatus(BuildStatus.FAILEDTOBUILD)
        build.gotFailure()
        with celebrity_logged_in("commercial_admin"):
            build.git_repository.builder_constraints = ["gpu"]
        with person_logged_in(build.git_repository.owner):
            build.retry()
        self.assertEqual(("gpu",), build.builder_constraints)

    def test_cancel_not_in_progress(self):
        # The cancel() method for a pending build leaves it in the CANCELLED
        # state.
        build = self.factory.makeCIBuild()
        build.queueBuild()
        build.cancel()
        self.assertEqual(BuildStatus.CANCELLED, build.status)
        self.assertIsNone(build.buildqueue_record)

    def test_cancel_in_progress(self):
        # The cancel() method for a building build leaves it in the
        # CANCELLING state.
        build = self.factory.makeCIBuild()
        bq = build.queueBuild()
        bq.markAsBuilding(self.factory.makeBuilder())
        build.cancel()
        self.assertEqual(BuildStatus.CANCELLING, build.status)
        self.assertEqual(bq, build.buildqueue_record)

    def test_estimateDuration(self):
        # Without previous builds, the default time estimate is 10m.
        build = self.factory.makeCIBuild()
        self.assertEqual(600, build.estimateDuration().seconds)

    def test_estimateDuration_with_history(self):
        # Previous successful builds of the same repository are used for
        # estimates.
        build = self.factory.makeCIBuild()
        self.factory.makeCIBuild(
            git_repository=build.git_repository,
            distro_arch_series=build.distro_arch_series,
            status=BuildStatus.FULLYBUILT,
            duration=timedelta(seconds=335),
        )
        for i in range(3):
            self.factory.makeCIBuild(
                git_repository=build.git_repository,
                distro_arch_series=build.distro_arch_series,
                status=BuildStatus.FAILEDTOBUILD,
                duration=timedelta(seconds=20),
            )
        self.assertEqual(335, build.estimateDuration().seconds)

    def test_build_cookie(self):
        build = self.factory.makeCIBuild()
        self.assertEqual("CIBUILD-%d" % build.id, build.build_cookie)

    def test_getFileByName_logs(self):
        # getFileByName returns the logs when requested by name.
        build = self.factory.makeCIBuild()
        build.setLog(
            self.factory.makeLibraryFileAlias(filename="buildlog.txt.gz")
        )
        self.assertEqual(build.log, build.getFileByName("buildlog.txt.gz"))
        self.assertRaises(NotFoundError, build.getFileByName, "foo")
        build.storeUploadLog("uploaded")
        self.assertEqual(
            build.upload_log, build.getFileByName(build.upload_log.filename)
        )

    def test_verifySuccessfulUpload(self):
        # verifySuccessfulUpload always returns True; the upload processor
        # requires us to implement this, but we don't have any interesting
        # checks to perform here.
        build = self.factory.makeCIBuild()
        self.assertTrue(build.verifySuccessfulUpload())

    def test_updateStatus_triggers_webhooks(self):
        # Updating the status of a CIBuild triggers webhooks on the
        # corresponding GitRepository.
        self.useFixture(FeatureFixture({CI_WEBHOOKS_FEATURE_FLAG: "on"}))
        logger = self.useFixture(FakeLogger())
        build = self.factory.makeCIBuild()
        hook = self.factory.makeWebhook(
            target=build.git_repository, event_types=["ci:build:0.1"]
        )
        build.updateStatus(BuildStatus.FULLYBUILT)
        expected_payload = {
            "build": Equals(canonical_url(build, force_local_path=True)),
            "action": Equals("status-changed"),
            "git_repository": Equals(
                canonical_url(build.git_repository, force_local_path=True)
            ),
            "commit_sha1": Equals(build.commit_sha1),
            "status": Equals("Successfully built"),
        }
        delivery = hook.deliveries.one()
        self.assertThat(
            delivery,
            MatchesStructure(
                event_type=Equals("ci:build:0.1"),
                payload=MatchesDict(expected_payload),
            ),
        )
        with dbuser(config.IWebhookDeliveryJobSource.dbuser):
            self.assertEqual(
                "<WebhookDeliveryJob for webhook %d on %r>"
                % (hook.id, hook.target),
                repr(delivery),
            )
            self.assertThat(
                logger.output,
                LogsScheduledWebhooks(
                    [(hook, "ci:build:0.1", MatchesDict(expected_payload))]
                ),
            )

    def test_updateStatus_no_change_does_not_trigger_webhooks(self):
        # An updateStatus call that changes details of the worker status but
        # that doesn't change the build's status attribute does not trigger
        # webhooks.
        self.useFixture(FeatureFixture({CI_WEBHOOKS_FEATURE_FLAG: "on"}))
        logger = self.useFixture(FakeLogger())
        build = self.factory.makeCIBuild()
        hook = self.factory.makeWebhook(
            target=build.git_repository, event_types=["ci:build:0.1"]
        )
        builder = self.factory.makeBuilder()
        build.updateStatus(BuildStatus.BUILDING)
        expected_logs = [
            (
                hook,
                "ci:build:0.1",
                ContainsDict(
                    {
                        "action": Equals("status-changed"),
                        "status": Equals("Currently building"),
                    }
                ),
            )
        ]
        self.assertEqual(1, hook.deliveries.count())
        self.assertThat(logger.output, LogsScheduledWebhooks(expected_logs))
        build.updateStatus(
            BuildStatus.BUILDING,
            builder=builder,
            worker_status={"revision_id": build.commit_sha1},
        )
        self.assertEqual(1, hook.deliveries.count())
        self.assertThat(logger.output, LogsScheduledWebhooks(expected_logs))
        build.updateStatus(BuildStatus.UPLOADING)
        expected_logs.append(
            (
                hook,
                "ci:build:0.1",
                ContainsDict(
                    {
                        "action": Equals("status-changed"),
                        "status": Equals("Uploading build"),
                    }
                ),
            )
        )
        self.assertEqual(2, hook.deliveries.count())
        self.assertThat(logger.output, LogsScheduledWebhooks(expected_logs))

    def addFakeBuildLog(self, build):
        build.setLog(self.factory.makeLibraryFileAlias("mybuildlog.txt"))

    def test_log_url(self):
        # The log URL for a CI build will use the repository context.
        build = self.factory.makeCIBuild()
        self.addFakeBuildLog(build)
        self.assertEqual(
            "http://launchpad.test/%s/+build/%d/+files/mybuildlog.txt"
            % (build.git_repository.unique_name, build.id),
            build.log_url,
        )

    def test_eta(self):
        # CIBuild.eta returns a non-None value when it should, or None when
        # there's no start time.
        build = self.factory.makeCIBuild()
        build.queueBuild()
        self.assertIsNone(build.eta)
        self.factory.makeBuilder(processors=[build.processor])
        clear_property_cache(build)
        self.assertIsNotNone(build.eta)

    def test_eta_cached(self):
        # The expensive completion time estimate is cached.
        build = self.factory.makeCIBuild()
        build.queueBuild()
        build.eta
        with StormStatementRecorder() as recorder:
            build.eta
        self.assertThat(recorder, HasQueryCount(Equals(0)))

    def test_estimate(self):
        # CIBuild.estimate returns True until the job is completed.
        build = self.factory.makeCIBuild()
        build.queueBuild()
        self.factory.makeBuilder(processors=[build.processor])
        build.updateStatus(BuildStatus.BUILDING)
        self.assertTrue(build.estimate)
        build.updateStatus(BuildStatus.FULLYBUILT)
        clear_property_cache(build)
        self.assertFalse(build.estimate)

    def test_getConfiguration(self):
        build = self.factory.makeCIBuild()
        das = build.distro_arch_series
        self.useFixture(
            GitHostingFixture(
                blob=dedent(
                    """\
            pipeline: [test]
            jobs:
                test:
                    series: {}
                    architectures: [{}]
            """.format(
                        das.distroseries.name, das.architecturetag
                    )
                ).encode()
            )
        )
        self.assertThat(
            build.getConfiguration(),
            MatchesStructure.byEquality(
                pipeline=[["test"]],
                jobs={
                    "test": [
                        {
                            "series": das.distroseries.name,
                            "architectures": [das.architecturetag],
                        }
                    ]
                },
            ),
        )

    def test_getConfiguration_not_found(self):
        build = self.factory.makeCIBuild()
        self.useFixture(
            GitHostingFixture()
        ).getBlob.failure = GitRepositoryBlobNotFound(
            build.git_repository.getInternalPath(),
            ".launchpad.yaml",
            rev=build.commit_sha1,
        )
        self.assertRaisesWithContent(
            MissingConfiguration,
            "Cannot find .launchpad.yaml in %s"
            % (build.git_repository.unique_name),
            build.getConfiguration,
        )

    def test_getConfiguration_fetch_error(self):
        build = self.factory.makeCIBuild()
        self.useFixture(
            GitHostingFixture()
        ).getBlob.failure = GitRepositoryScanFault("Boom")
        self.assertRaisesWithContent(
            CannotFetchConfiguration,
            "Failed to get .launchpad.yaml from %s: Boom"
            % (build.git_repository.unique_name),
            build.getConfiguration,
        )

    def test_getConfiguration_invalid_data(self):
        build = self.factory.makeCIBuild()
        hosting_fixture = self.useFixture(GitHostingFixture())
        for invalid_result in (None, 123, b"", b"[][]", b"#name:test", b"]"):
            hosting_fixture.getBlob.result = invalid_result
            self.assertRaises(CannotParseConfiguration, build.getConfiguration)

    def test_getOrCreateRevisionStatusReport_present(self):
        build = self.factory.makeCIBuild()
        report = self.factory.makeRevisionStatusReport(
            title="build:0", ci_build=build
        )
        self.assertEqual(
            report, build.getOrCreateRevisionStatusReport("build:0")
        )

    def test_getOrCreateRevisionStatusReport_absent(self):
        build = self.factory.makeCIBuild()
        self.assertThat(
            build.getOrCreateRevisionStatusReport("build:0"),
            MatchesStructure.byEquality(
                creator=build.git_repository.owner,
                title="build:0",
                git_repository=build.git_repository,
                commit_sha1=build.commit_sha1,
                ci_build=build,
            ),
        )

    def test_createSourcePackageRelease(self):
        distroseries = self.factory.makeDistroSeries()
        archive = self.factory.makeArchive(
            distribution=distroseries.distribution
        )
        build = self.factory.makeCIBuild()
        spn = self.factory.makeSourcePackageName()
        spr = build.createSourcePackageRelease(
            distroseries,
            spn,
            "1.0",
            creator=build.git_repository.owner,
            archive=archive,
        )
        self.assertThat(
            spr,
            MatchesStructure(
                upload_distroseries=Equals(distroseries),
                sourcepackagename=Equals(spn),
                version=Equals("1.0"),
                format=Equals(SourcePackageType.CI_BUILD),
                architecturehintlist=Equals(""),
                creator=Equals(build.git_repository.owner),
                upload_archive=Equals(archive),
                ci_build=Equals(build),
            ),
        )
        self.assertContentEqual([spr], build.sourcepackages)

    def test_createBinaryPackageRelease(self):
        build = self.factory.makeCIBuild()
        bpn = self.factory.makeBinaryPackageName()
        bpr = build.createBinaryPackageRelease(
            bpn,
            "1.0",
            "test summary",
            "test description",
            BinaryPackageFormat.WHL,
            False,
            installedsize=1024,
            homepage="https://example.com/",
        )
        self.assertThat(
            bpr,
            MatchesStructure(
                binarypackagename=Equals(bpn),
                version=Equals("1.0"),
                summary=Equals("test summary"),
                description=Equals("test description"),
                binpackageformat=Equals(BinaryPackageFormat.WHL),
                architecturespecific=Is(False),
                installedsize=Equals(1024),
                homepage=Equals("https://example.com/"),
            ),
        )
        self.assertContentEqual([bpr], build.binarypackages)

    def test_notify_fullybuilt(self):
        # notify does not send mail when a CIBuild completes normally.
        build = self.factory.makeCIBuild(status=BuildStatus.FULLYBUILT)
        build.notify()
        self.assertEqual(0, len(pop_notifications()))

    def test_notify_packagefail(self):
        # notify sends mail when a CIBuild fails.
        person = self.factory.makePerson(name="person")
        product = self.factory.makeProduct(name="product", owner=person)
        git_repository = self.factory.makeGitRepository(
            owner=person, target=product, name="repo"
        )
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
        build = self.factory.makeCIBuild(
            git_repository=git_repository,
            commit_sha1="a39b604dcf9124d61cf94a1f9fffab638ee9a0cd",
            distro_arch_series=distroarchseries,
            date_created=datetime(2014, 4, 25, 10, 38, 0, tzinfo=timezone.utc),
            status=BuildStatus.FAILEDTOBUILD,
            builder=self.factory.makeBuilder(name="bob"),
            duration=timedelta(minutes=10),
        )
        build.setLog(self.factory.makeLibraryFileAlias())
        build.notify()
        [notification] = pop_notifications()
        self.assertEqual(
            config.canonical.noreply_from_address, notification["From"]
        )
        self.assertEqual(
            "Person <%s>" % person.preferredemail.email, notification["To"]
        )
        subject = notification["Subject"].replace("\n ", " ")
        expected_subject = (
            "[CI build #{:d}] i386 CI build of "
            "~person/product/+git/repo:"
            "a39b604dcf9124d61cf94a1f9fffab638ee9a0cd"
        ).format(build.id)
        self.assertEqual(expected_subject, subject)
        self.assertEqual(
            "Owner", notification["X-Launchpad-Message-Rationale"]
        )
        self.assertEqual(person.name, notification["X-Launchpad-Message-For"])
        self.assertEqual(
            "ci-build-status", notification["X-Launchpad-Notification-Type"]
        )
        self.assertEqual(
            "FAILEDTOBUILD", notification["X-Launchpad-Build-State"]
        )

        message = notification.get_payload(decode=True).decode()
        body, footer = message.split("\n-- \n")

        expected_body = (
            " * Git Repository: ~person/product/+git/repo\n"
            " * Commit: a39b604dcf9124d61cf94a1f9fffab638ee9a0cd\n"
            " * Distroseries: distro unstable\n"
            " * Architecture: i386\n"
            " * State: Failed to build\n"
            " * Duration: 10 minutes\n"
            " * Build Log: {}\n"
            " * Upload Log: \n"
            " * Builder: http://launchpad.test/builders/bob\n"
        ).format(build.log_url)

        self.assertEqual(expected_body, body)
        self.assertEqual(
            "http://launchpad.test/~person/product/+git/repo/+build/{:d}\n"
            "You are receiving this email because you are the owner "
            "of this repository.\n".format(build.id),
            footer,
        )


class TestCIBuildSet(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_getByBuildFarmJob_works(self):
        build = self.factory.makeCIBuild()
        self.assertEqual(
            build,
            getUtility(ICIBuildSet).getByBuildFarmJob(build.build_farm_job),
        )

    def test_getByBuildFarmJob_returns_None_when_missing(self):
        bpb = self.factory.makeBinaryPackageBuild()
        self.assertIsNone(
            getUtility(ICIBuildSet).getByBuildFarmJob(bpb.build_farm_job)
        )

    def test_getByBuildFarmJobs_works(self):
        builds = [self.factory.makeCIBuild() for i in range(10)]
        self.assertContentEqual(
            builds,
            getUtility(ICIBuildSet).getByBuildFarmJobs(
                [build.build_farm_job for build in builds]
            ),
        )

    def test_getByBuildFarmJobs_works_empty(self):
        self.assertContentEqual(
            [], getUtility(ICIBuildSet).getByBuildFarmJobs([])
        )

    def test_virtualized_processor_requires(self):
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = False
        target = self.factory.makeCIBuild(
            distro_arch_series=distro_arch_series
        )
        self.assertTrue(target.virtualized)

    def test_virtualized_processor_does_not_require(self):
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = True
        target = self.factory.makeCIBuild(
            distro_arch_series=distro_arch_series
        )
        self.assertTrue(target.virtualized)

    def test_findByGitRepository(self):
        repositories = [self.factory.makeGitRepository() for _ in range(2)]
        builds = []
        for repository in repositories:
            builds.extend(
                [self.factory.makeCIBuild(repository) for _ in range(2)]
            )
        ci_build_set = getUtility(ICIBuildSet)
        self.assertContentEqual(
            builds[:2], ci_build_set.findByGitRepository(repositories[0])
        )
        self.assertContentEqual(
            builds[2:], ci_build_set.findByGitRepository(repositories[1])
        )

    def test_requestCIBuild(self):
        # requestBuild creates a new CIBuild.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        das = self.factory.makeBuildableDistroArchSeries()
        stages = [[("build", 0)]]

        build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, das, stages
        )

        self.assertTrue(ICIBuild.providedBy(build))
        self.assertThat(
            build,
            MatchesStructure.byEquality(
                git_repository=repository,
                commit_sha1=commit_sha1,
                distro_arch_series=das,
                stages=stages,
                status=BuildStatus.NEEDSBUILD,
            ),
        )
        store = Store.of(build)
        store.flush()
        build_queue = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id
            == removeSecurityProxy(build).build_farm_job_id,
        ).one()
        self.assertProvides(build_queue, IBuildQueue)
        self.assertTrue(build_queue.virtualized)
        self.assertIsNone(build_queue.builder_constraints)
        self.assertEqual(BuildQueueStatus.WAITING, build_queue.status)

    def test_requestBuild_score(self):
        # CI builds have an initial queue score of 2600.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        das = self.factory.makeBuildableDistroArchSeries()
        build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, das, [[("test", 0)]]
        )
        queue_record = build.buildqueue_record
        queue_record.score()
        self.assertEqual(2600, queue_record.lastscore)

    def test_requestBuild_rejects_repeats(self):
        # requestBuild refuses if an identical build was already requested.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        distro_series = self.factory.makeDistroSeries()
        arches = [
            self.factory.makeBuildableDistroArchSeries(
                distroseries=distro_series
            )
            for _ in range(2)
        ]
        old_build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, arches[0], [[("test", 0)]]
        )
        self.assertRaises(
            CIBuildAlreadyRequested,
            getUtility(ICIBuildSet).requestBuild,
            repository,
            commit_sha1,
            arches[0],
            [[("test", 0)]],
        )
        # We can build for a different distroarchseries.
        getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, arches[1], [[("test", 0)]]
        )
        # Changing the status of the old build does not allow a new build.
        old_build.updateStatus(BuildStatus.BUILDING)
        old_build.updateStatus(BuildStatus.FULLYBUILT)
        self.assertRaises(
            CIBuildAlreadyRequested,
            getUtility(ICIBuildSet).requestBuild,
            repository,
            commit_sha1,
            arches[0],
            [[("test", 0)]],
        )

    def test_requestBuild_virtualization(self):
        # New builds are virtualized.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        distro_series = self.factory.makeDistroSeries()
        for proc_nonvirt in True, False:
            das = self.factory.makeBuildableDistroArchSeries(
                distroseries=distro_series,
                supports_virtualized=True,
                supports_nonvirtualized=proc_nonvirt,
            )
            build = getUtility(ICIBuildSet).requestBuild(
                repository, commit_sha1, das, [[("test", 0)]]
            )
            self.assertTrue(build.virtualized)
            self.assertIsNone(build.builder_constraints)

    def test_requestBuild_nonvirtualized(self):
        # A non-virtualized processor cannot run a CI build.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        distro_series = self.factory.makeDistroSeries()
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series,
            supports_virtualized=False,
            supports_nonvirtualized=True,
        )
        self.assertRaises(
            CIBuildDisallowedArchitecture,
            getUtility(ICIBuildSet).requestBuild,
            repository,
            commit_sha1,
            das,
            [[("test", 0)]],
        )

    def test_requestBuild_builder_constraints(self):
        # New builds inherit any builder constraints from their repository.
        repository = self.factory.makeGitRepository(
            builder_constraints=["gpu"]
        )
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        distro_series = self.factory.makeDistroSeries()
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series,
            supports_virtualized=True,
            supports_nonvirtualized=False,
        )
        build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, das, [[("test", 0)]]
        )
        self.assertEqual(("gpu",), build.builder_constraints)

    def test_requestBuildsForRefs_triggers_builds(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series, architecturetag="amd64"
        )
        configuration = dedent(
            """\
            pipeline:
                - build
                - test

            jobs:
                build:
                    matrix:
                        - series: bionic
                          architectures: amd64
                        - series: focal
                          architectures: amd64
                    run: pyproject-build
                test:
                    series: focal
                    architectures: amd64
                    run: echo hello world >output
            """
        ).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        [ref] = self.factory.makeGitRefs(repository, ref_paths)
        encoded_commit_json = {
            "sha1": ref.commit_sha1,
            "blobs": {".launchpad.yaml": configuration},
        }
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[encoded_commit_json])
        )

        getUtility(ICIBuildSet).requestBuildsForRefs(repository, ref_paths)

        self.assertEqual(
            [
                (
                    (repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": None},
                )
            ],
            hosting_fixture.getCommits.calls,
        )

        build = getUtility(ICIBuildSet).findByGitRepository(repository).one()
        reports = list(
            getUtility(IRevisionStatusReportSet).findByRepository(repository)
        )

        # check that a build and some reports were created
        self.assertEqual(ref.commit_sha1, build.commit_sha1)
        self.assertEqual("focal", build.distro_arch_series.distroseries.name)
        self.assertEqual("amd64", build.distro_arch_series.architecturetag)
        self.assertEqual(
            [[("build", 0), ("build", 1)], [("test", 0)]], build.stages
        )
        self.assertThat(
            reports,
            MatchesSetwise(
                *(
                    MatchesStructure.byEquality(
                        creator=repository.owner,
                        title=title,
                        git_repository=repository,
                        commit_sha1=ref.commit_sha1,
                        ci_build=build,
                    )
                    for title in ("build:0", "build:1", "test:0")
                )
            ),
        )

    def test_requestBuildsForRefs_no_commits_at_all(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        hosting_fixture = self.useFixture(GitHostingFixture(commits=[]))

        getUtility(ICIBuildSet).requestBuildsForRefs(repository, ref_paths)

        self.assertEqual(
            [
                (
                    (repository.getInternalPath(), []),
                    {"filter_paths": [".launchpad.yaml"], "logger": None},
                )
            ],
            hosting_fixture.getCommits.calls,
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(repository)
            .is_empty()
        )

    def test_requestBuildsForRefs_no_matching_commits(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        [ref] = self.factory.makeGitRefs(repository, ref_paths)
        hosting_fixture = self.useFixture(GitHostingFixture(commits=[]))

        getUtility(ICIBuildSet).requestBuildsForRefs(repository, ref_paths)

        self.assertEqual(
            [
                (
                    (repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": None},
                )
            ],
            hosting_fixture.getCommits.calls,
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(repository)
            .is_empty()
        )

    def test_requestBuildsForRefs_configuration_parse_error(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series, architecturetag="amd64"
        )
        configuration = dedent(
            """\
            no - valid - configuration - file
            """
        ).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        [ref] = self.factory.makeGitRefs(repository, ref_paths)
        encoded_commit_json = {
            "sha1": ref.commit_sha1,
            "blobs": {".launchpad.yaml": configuration},
        }
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[encoded_commit_json])
        )
        logger = BufferLogger()

        getUtility(ICIBuildSet).requestBuildsForRefs(
            repository, ref_paths, logger
        )

        self.assertEqual(
            [
                (
                    (repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": logger},
                )
            ],
            hosting_fixture.getCommits.calls,
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(repository)
            .is_empty()
        )

        self.assertEqual(
            "ERROR Cannot parse .launchpad.yaml from %s: "
            "Configuration file does not declare 'pipeline'\n"
            % (repository.unique_name,),
            logger.getLogBuffer(),
        )

    def test_requestBuildsForRefs_no_pipeline_defined(self):
        # If the job's configuration does not define any pipeline stages,
        # requestBuildsForRefs logs an error.
        configuration = b"pipeline: []\njobs: {}\n"
        [ref] = self.factory.makeGitRefs()
        encoded_commit_json = {
            "sha1": ref.commit_sha1,
            "blobs": {".launchpad.yaml": configuration},
        }
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[encoded_commit_json])
        )
        logger = BufferLogger()

        getUtility(ICIBuildSet).requestBuildsForRefs(
            ref.repository, [ref.path], logger
        )

        self.assertEqual(
            [
                (
                    (ref.repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": logger},
                )
            ],
            hosting_fixture.getCommits.calls,
        )
        self.assertTrue(
            getUtility(ICIBuildSet)
            .findByGitRepository(ref.repository)
            .is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(ref.repository)
            .is_empty()
        )
        self.assertEqual(
            "ERROR Failed to request CI builds for %s: "
            "No pipeline stages defined\n" % ref.commit_sha1,
            logger.getLogBuffer(),
        )

    def test_requestBuildsForRefs_undefined_job(self):
        # If the job's configuration has a pipeline that defines a job not
        # in the jobs matrix, requestBuildsForRefs logs an error.
        configuration = b"pipeline: [test]\njobs: {}\n"
        [ref] = self.factory.makeGitRefs()
        encoded_commit_json = {
            "sha1": ref.commit_sha1,
            "blobs": {".launchpad.yaml": configuration},
        }
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[encoded_commit_json])
        )
        logger = BufferLogger()

        getUtility(ICIBuildSet).requestBuildsForRefs(
            ref.repository, [ref.path], logger
        )

        self.assertEqual(
            [
                (
                    (ref.repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": logger},
                )
            ],
            hosting_fixture.getCommits.calls,
        )
        self.assertTrue(
            getUtility(ICIBuildSet)
            .findByGitRepository(ref.repository)
            .is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(ref.repository)
            .is_empty()
        )
        self.assertEqual(
            "ERROR Failed to request CI builds for %s: "
            "No job definition for 'test'\n" % ref.commit_sha1,
            logger.getLogBuffer(),
        )

    def test_requestBuildsForRefs_build_already_scheduled(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series, architecturetag="amd64"
        )
        configuration = dedent(
            """\
            pipeline:
            - test

            jobs:
                test:
                    series: focal
                    architectures: amd64
                    run: echo hello world >output
            """
        ).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        [ref] = self.factory.makeGitRefs(repository, ref_paths)
        encoded_commit_json = {
            "sha1": ref.commit_sha1,
            "blobs": {".launchpad.yaml": configuration},
        }
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[encoded_commit_json])
        )
        build_set = removeSecurityProxy(getUtility(ICIBuildSet))
        mock = Mock(side_effect=CIBuildAlreadyRequested)
        self.useFixture(MockPatchObject(build_set, "requestBuild", mock))
        logger = BufferLogger()

        build_set.requestBuildsForRefs(repository, ref_paths, logger)

        self.assertEqual(
            [
                (
                    (repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": logger},
                )
            ],
            hosting_fixture.getCommits.calls,
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(repository)
            .is_empty()
        )
        self.assertEqual(
            "INFO Requesting CI build "
            "for %s on focal/amd64\n" % ref.commit_sha1,
            logger.getLogBuffer(),
        )

    def test_requestBuildsForRefs_unexpected_exception(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series, architecturetag="amd64"
        )
        configuration = dedent(
            """\
            pipeline:
            - test

            jobs:
                test:
                    series: focal
                    architectures: amd64
                    run: echo hello world >output
            """
        ).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ["refs/heads/master"]
        [ref] = self.factory.makeGitRefs(repository, ref_paths)
        encoded_commit_json = {
            "sha1": ref.commit_sha1,
            "blobs": {".launchpad.yaml": configuration},
        }
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[encoded_commit_json])
        )
        build_set = removeSecurityProxy(getUtility(ICIBuildSet))
        mock = Mock(side_effect=Exception("some unexpected error"))
        self.useFixture(MockPatchObject(build_set, "requestBuild", mock))
        logger = BufferLogger()

        build_set.requestBuildsForRefs(repository, ref_paths, logger)

        self.assertEqual(
            [
                (
                    (repository.getInternalPath(), [ref.commit_sha1]),
                    {"filter_paths": [".launchpad.yaml"], "logger": logger},
                )
            ],
            hosting_fixture.getCommits.calls,
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet)
            .findByRepository(repository)
            .is_empty()
        )

        log_line1, log_line2 = logger.getLogBuffer().splitlines()
        self.assertEqual(
            "INFO Requesting CI build for %s on focal/amd64" % ref.commit_sha1,
            log_line1,
        )
        self.assertEqual(
            "ERROR Failed to request CI build for %s on focal/amd64: "
            "some unexpected error" % (ref.commit_sha1,),
            log_line2,
        )

    def test_deleteByGitRepository(self):
        repositories = [self.factory.makeGitRepository() for _ in range(2)]
        builds = []
        for repository in repositories:
            builds.extend(
                [self.factory.makeCIBuild(repository) for _ in range(2)]
            )
        build_queue = builds[0].queueBuild()
        other_build = self.factory.makeCIBuild()
        other_build.queueBuild()
        store = Store.of(builds[0])
        store.flush()
        build_queue_id = build_queue.id
        build_farm_job_id = removeSecurityProxy(builds[0]).build_farm_job_id
        ci_build_set = getUtility(ICIBuildSet)

        ci_build_set.deleteByGitRepository(repositories[0])

        flush_database_caches()
        # The deleted CI builds are gone.
        self.assertContentEqual(
            [], ci_build_set.findByGitRepository(repositories[0])
        )
        self.assertContentEqual(
            builds[2:], ci_build_set.findByGitRepository(repositories[1])
        )
        self.assertIsNone(store.get(BuildQueue, build_queue_id))
        self.assertIsNone(store.get(BuildFarmJob, build_farm_job_id))
        # Unrelated CI builds are still present.
        clear_property_cache(other_build)
        self.assertEqual(other_build, ci_build_set.getByID(other_build.id))
        self.assertIsNotNone(other_build.buildqueue_record)


class TestDetermineDASesToBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_returns_expected_DASes(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_serieses = [
            self.factory.makeDistroSeries(ubuntu) for _ in range(2)
        ]
        dases = []
        for distro_series in distro_serieses:
            for _ in range(2):
                dases.append(
                    self.factory.makeBuildableDistroArchSeries(
                        distroseries=distro_series
                    )
                )
        configuration = load_configuration(
            dedent(
                """\
            pipeline:
                - [build]
                - [test]
            jobs:
                build:
                    series: {distro_serieses[1].name}
                    architectures:
                        - {dases[2].architecturetag}
                        - {dases[3].architecturetag}
                test:
                    series: {distro_serieses[1].name}
                    architectures:
                        - {dases[2].architecturetag}
            """.format(
                    distro_serieses=distro_serieses, dases=dases
                )
            )
        )
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger)
        )

        self.assertContentEqual(dases[2:], dases_to_build)
        self.assertEqual("", logger.getLogBuffer())

    def test_logs_missing_job_definition(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_series = self.factory.makeDistroSeries(ubuntu)
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series
        )
        configuration = load_configuration(
            dedent(
                """\
            pipeline:
                - [test]
            jobs:
                build:
                    series: {distro_series.name}
                    architectures:
                        - {das.architecturetag}
            """.format(
                    distro_series=distro_series, das=das
                )
            )
        )
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger)
        )

        self.assertEqual(0, len(dases_to_build))
        self.assertEqual(
            "ERROR No job definition for 'test'\n", logger.getLogBuffer()
        )

    def test_logs_missing_series(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_series = self.factory.makeDistroSeries(ubuntu)
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series
        )
        configuration = load_configuration(
            dedent(
                """\
            pipeline:
                - [build]
            jobs:
                build:
                    series: unknown-series
                    architectures:
                        - {das.architecturetag}
            """.format(
                    das=das
                )
            )
        )
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger)
        )

        self.assertEqual(0, len(dases_to_build))
        self.assertEqual(
            "ERROR Unknown Ubuntu series name unknown-series\n",
            logger.getLogBuffer(),
        )

    def test_logs_non_buildable_architecture(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_series = self.factory.makeDistroSeries(ubuntu)
        configuration = load_configuration(
            dedent(
                """\
            pipeline:
                - [build]
            jobs:
                build:
                    series: {distro_series.name}
                    architectures:
                        - non-buildable-architecture
            """.format(
                    distro_series=distro_series
                )
            )
        )
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger)
        )

        self.assertEqual(0, len(dases_to_build))
        self.assertEqual(
            "ERROR non-buildable-architecture is not a buildable architecture "
            "name in Ubuntu %s\n" % distro_series.name,
            logger.getLogBuffer(),
        )


class TestCIBuildWebservice(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PRIVATE
        )
        self.webservice.default_api_version = "devel"
        login(ANONYMOUS)

    def getURL(self, obj):
        return self.webservice.getAbsoluteUrl(api_url(obj))

    def test_properties(self):
        # The basic properties of a CI build are sensible.
        db_build = self.factory.makeCIBuild()
        build_url = api_url(db_build)
        logout()
        build = self.webservice.get(build_url).jsonBody()
        with person_logged_in(self.person):
            self.assertThat(
                build,
                ContainsDict(
                    {
                        "git_repository_link": Equals(
                            self.getURL(db_build.git_repository)
                        ),
                        "commit_sha1": Equals(db_build.commit_sha1),
                        "distro_arch_series_link": Equals(
                            self.getURL(db_build.distro_arch_series)
                        ),
                        "arch_tag": Equals(
                            db_build.distro_arch_series.architecturetag
                        ),
                        "score": Is(None),
                        "stages": Equals([[["test", 0]]]),
                        "results": Equals({}),
                        "can_be_rescored": Is(False),
                        "can_be_retried": Is(False),
                        "can_be_cancelled": Is(False),
                    }
                ),
            )

    def test_public(self):
        # A CI build with a public repository is itself public.
        db_build = self.factory.makeCIBuild()
        build_url = api_url(db_build)
        unpriv_webservice = webservice_for_person(
            self.factory.makePerson(), permission=OAuthPermission.WRITE_PUBLIC
        )
        unpriv_webservice.default_api_version = "devel"
        logout()
        self.assertEqual(200, self.webservice.get(build_url).status)
        self.assertEqual(200, unpriv_webservice.get(build_url).status)

    def test_private(self):
        # A CI build with a private repository is private.
        db_repository = self.factory.makeGitRepository(
            owner=self.person, information_type=InformationType.USERDATA
        )
        with person_logged_in(self.person):
            db_build = self.factory.makeCIBuild(git_repository=db_repository)
            build_url = api_url(db_build)
        unpriv_webservice = webservice_for_person(
            self.factory.makePerson(), permission=OAuthPermission.WRITE_PUBLIC
        )
        unpriv_webservice.default_api_version = "devel"
        logout()
        self.assertEqual(200, self.webservice.get(build_url).status)
        self.assertEqual(401, unpriv_webservice.get(build_url).status)

    def test_cancel(self):
        # The owner of a build's repository can cancel the build.
        db_repository = self.factory.makeGitRepository(owner=self.person)
        db_build = self.factory.makeCIBuild(git_repository=db_repository)
        db_build.queueBuild()
        build_url = api_url(db_build)
        unpriv_webservice = webservice_for_person(
            self.factory.makePerson(), permission=OAuthPermission.WRITE_PUBLIC
        )
        unpriv_webservice.default_api_version = "devel"
        logout()
        build = self.webservice.get(build_url).jsonBody()
        self.assertTrue(build["can_be_cancelled"])
        response = unpriv_webservice.named_post(build["self_link"], "cancel")
        self.assertEqual(401, response.status)
        response = self.webservice.named_post(build["self_link"], "cancel")
        self.assertEqual(200, response.status)
        build = self.webservice.get(build_url).jsonBody()
        self.assertFalse(build["can_be_cancelled"])
        with person_logged_in(self.person):
            self.assertEqual(BuildStatus.CANCELLED, db_build.status)

    def test_rescore(self):
        # Buildd administrators can rescore builds.
        db_build = self.factory.makeCIBuild()
        db_build.queueBuild()
        build_url = api_url(db_build)
        buildd_admin = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).buildd_admin]
        )
        buildd_admin_webservice = webservice_for_person(
            buildd_admin, permission=OAuthPermission.WRITE_PUBLIC
        )
        buildd_admin_webservice.default_api_version = "devel"
        logout()
        build = self.webservice.get(build_url).jsonBody()
        self.assertEqual(2600, build["score"])
        self.assertTrue(build["can_be_rescored"])
        response = self.webservice.named_post(
            build["self_link"], "rescore", score=5000
        )
        self.assertEqual(401, response.status)
        response = buildd_admin_webservice.named_post(
            build["self_link"], "rescore", score=5000
        )
        self.assertEqual(200, response.status)
        build = self.webservice.get(build_url).jsonBody()
        self.assertEqual(5000, build["score"])

    def assertCanOpenRedirectedUrl(self, browser, url):
        browser.open(url)
        self.assertEqual(303, browser.responseStatusCode)
        urlopen(browser.headers["Location"]).close()

    def test_logs(self):
        # API clients can fetch the build and upload logs.
        db_build = self.factory.makeCIBuild()
        db_build.setLog(self.factory.makeLibraryFileAlias("buildlog.txt.gz"))
        db_build.storeUploadLog("uploaded")
        build_url = api_url(db_build)
        logout()
        build = self.webservice.get(build_url).jsonBody()
        browser = self.getNonRedirectingBrowser(user=self.person)
        browser.raiseHttpErrors = False
        self.assertIsNotNone(build["build_log_url"])
        self.assertCanOpenRedirectedUrl(browser, build["build_log_url"])
        self.assertIsNotNone(build["upload_log_url"])
        self.assertCanOpenRedirectedUrl(browser, build["upload_log_url"])

    def test_getFileUrls(self):
        # API clients can fetch files attached to builds.
        db_build = self.factory.makeCIBuild()
        db_reports = [
            self.factory.makeRevisionStatusReport(ci_build=db_build)
            for _ in range(2)
        ]
        db_artifacts = []
        for db_report in db_reports:
            for _ in range(2):
                db_artifacts.append(
                    self.factory.makeRevisionStatusArtifact(
                        lfa=self.factory.makeLibraryFileAlias(),
                        report=db_report,
                    )
                )
        build_url = api_url(db_build)
        file_urls = [
            ProxiedLibraryFileAlias(
                db_artifact.library_file, db_artifact
            ).http_url
            for db_artifact in db_artifacts
        ]
        logout()
        response = self.webservice.named_get(build_url, "getFileUrls")
        self.assertEqual(200, response.status)
        self.assertContentEqual(file_urls, response.jsonBody())
        browser = self.getNonRedirectingBrowser(user=self.person)
        browser.raiseHttpErrors = False
        for file_url in file_urls:
            self.assertCanOpenRedirectedUrl(browser, file_url)


class TestCIBuildMacaroonIssuer(MacaroonTestMixin, TestCaseWithFactory):
    """Test CIBuild macaroon issuing and verification."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )

    def test_issueMacaroon_good(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        issuer = getUtility(IMacaroonIssuer, "ci-build")
        macaroon = removeSecurityProxy(issuer).issueMacaroon(build)
        self.assertThat(
            macaroon,
            MatchesStructure(
                location=Equals("launchpad.test"),
                identifier=Equals("ci-build"),
                caveats=MatchesListwise(
                    [
                        MatchesStructure.byEquality(
                            caveat_id="lp.ci-build %s" % build.id
                        ),
                    ]
                ),
            ),
        )

    def test_issueMacaroon_via_authserver(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        private_root = getUtility(IPrivateApplication)
        authserver = AuthServerAPIView(private_root.authserver, TestRequest())
        macaroon = Macaroon.deserialize(
            authserver.issueMacaroon("ci-build", "CIBuild", build.id)
        )
        self.assertThat(
            macaroon,
            MatchesStructure(
                location=Equals("launchpad.test"),
                identifier=Equals("ci-build"),
                caveats=MatchesListwise(
                    [
                        MatchesStructure.byEquality(
                            caveat_id="lp.ci-build %s" % build.id
                        ),
                    ]
                ),
            ),
        )

    def test_verifyMacaroon_good_repository(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertMacaroonVerifies(issuer, macaroon, build.git_repository)

    def test_verifyMacaroon_good_no_context(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertMacaroonVerifies(
            issuer, macaroon, None, require_context=False
        )
        self.assertMacaroonVerifies(
            issuer, macaroon, build.git_repository, require_context=False
        )

    def test_verifyMacaroon_no_context_but_require_context(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertMacaroonDoesNotVerify(
            ["Expected macaroon verification context but got None."],
            issuer,
            macaroon,
            None,
        )

    def test_verifyMacaroon_wrong_location(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = Macaroon(
            location="another-location", key=issuer._root_secret
        )
        self.assertMacaroonDoesNotVerify(
            ["Macaroon has unknown location 'another-location'."],
            issuer,
            macaroon,
            build.git_repository,
        )
        self.assertMacaroonDoesNotVerify(
            ["Macaroon has unknown location 'another-location'."],
            issuer,
            macaroon,
            build.git_repository,
            require_context=False,
        )

    def test_verifyMacaroon_wrong_key(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = Macaroon(
            location=config.vhost.mainsite.hostname, key="another-secret"
        )
        self.assertMacaroonDoesNotVerify(
            ["Signatures do not match"], issuer, macaroon, build.git_repository
        )
        self.assertMacaroonDoesNotVerify(
            ["Signatures do not match"],
            issuer,
            macaroon,
            build.git_repository,
            require_context=False,
        )

    def test_verifyMacaroon_not_building(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertMacaroonDoesNotVerify(
            ["Caveat check for 'lp.ci-build %s' failed." % build.id],
            issuer,
            macaroon,
            build.git_repository,
        )

    def test_verifyMacaroon_wrong_build(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        build.updateStatus(BuildStatus.BUILDING)
        other_build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        other_build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = issuer.issueMacaroon(other_build)
        self.assertMacaroonDoesNotVerify(
            ["Caveat check for 'lp.ci-build %s' failed." % other_build.id],
            issuer,
            macaroon,
            build.git_repository,
        )

    def test_verifyMacaroon_wrong_repository(self):
        build = self.factory.makeCIBuild(
            git_repository=self.factory.makeGitRepository(
                information_type=InformationType.USERDATA
            )
        )
        other_repository = self.factory.makeGitRepository()
        build.updateStatus(BuildStatus.BUILDING)
        issuer = removeSecurityProxy(getUtility(IMacaroonIssuer, "ci-build"))
        macaroon = issuer.issueMacaroon(build)
        self.assertMacaroonDoesNotVerify(
            ["Caveat check for 'lp.ci-build %s' failed." % build.id],
            issuer,
            macaroon,
            other_repository,
        )
