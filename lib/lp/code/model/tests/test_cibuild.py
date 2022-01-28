# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test CI builds."""

from datetime import (
    datetime,
    timedelta,
    )
from textwrap import dedent

import pytz
from testtools.matchers import (
    Equals,
    MatchesStructure,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.code.errors import (
    GitRepositoryBlobNotFound,
    GitRepositoryScanFault,
    )
from lp.code.interfaces.cibuild import (
    CannotFetchConfiguration,
    CannotParseConfiguration,
    ICIBuild,
    ICIBuildSet,
    MissingConfiguration,
    )
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.interfaces.series import SeriesStatus
from lp.services.propertycache import clear_property_cache
from lp.testing import (
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.matchers import HasQueryCount


class TestCIBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_implements_interfaces(self):
        # CIBuild implements IPackageBuild and ICIBuild.
        build = self.factory.makeCIBuild()
        self.assertProvides(build, IPackageBuild)
        self.assertProvides(build, ICIBuild)

    def test___repr__(self):
        # CIBuild has an informative __repr__.
        build = self.factory.makeCIBuild()
        self.assertEqual(
            "<CIBuild %s/+build/%s>" % (
                build.git_repository.unique_name, build.id),
            repr(build))

    def test_title(self):
        # CIBuild has an informative title.
        build = self.factory.makeCIBuild()
        self.assertEqual(
            "%s CI build of %s:%s" % (
                build.distro_arch_series.architecturetag,
                build.git_repository.unique_name, build.commit_sha1),
            build.title)

    def test_queueBuild(self):
        # CIBuild can create the queue entry for itself.
        build = self.factory.makeCIBuild()
        bq = build.queueBuild()
        self.assertProvides(bq, IBuildQueue)
        self.assertEqual(
            build.build_farm_job, removeSecurityProxy(bq)._build_farm_job)
        self.assertEqual(build, bq.specific_build)
        self.assertEqual(build.virtualized, bq.virtualized)
        self.assertIsNotNone(bq.processor)
        self.assertEqual(bq, build.buildqueue_record)

    def test_is_private(self):
        # A CIBuild is private iff its repository is.
        build = self.factory.makeCIBuild()
        self.assertFalse(build.is_private)
        with person_logged_in(self.factory.makePerson()) as owner:
            build = self.factory.makeCIBuild(
                git_repository=self.factory.makeGitRepository(
                    owner=owner, information_type=InformationType.USERDATA))
            self.assertTrue(build.is_private)

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
            status=SeriesStatus.OBSOLETE)
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
        now = datetime.now(pytz.UTC)
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
            status=BuildStatus.FULLYBUILT, duration=timedelta(seconds=335))
        for i in range(3):
            self.factory.makeCIBuild(
                git_repository=build.git_repository,
                distro_arch_series=build.distro_arch_series,
                status=BuildStatus.FAILEDTOBUILD,
                duration=timedelta(seconds=20))
        self.assertEqual(335, build.estimateDuration().seconds)

    def test_build_cookie(self):
        build = self.factory.makeCIBuild()
        self.assertEqual('CIBUILD-%d' % build.id, build.build_cookie)

    def addFakeBuildLog(self, build):
        build.setLog(self.factory.makeLibraryFileAlias("mybuildlog.txt"))

    def test_log_url(self):
        # The log URL for a CI build will use the repository context.
        build = self.factory.makeCIBuild()
        self.addFakeBuildLog(build)
        self.assertEqual(
            "http://launchpad.test/%s/+build/%d/+files/mybuildlog.txt" % (
                build.git_repository.unique_name, build.id),
            build.log_url)

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
        self.useFixture(GitHostingFixture(blob=dedent("""\
            pipeline: [test]
            jobs:
                test:
                    series: {}
                    architectures: [{}]
            """.format(das.distroseries.name, das.architecturetag)).encode()))
        self.assertThat(
            build.getConfiguration(),
            MatchesStructure.byEquality(
                pipeline=[["test"]],
                jobs={
                    "test": [{
                        "series": das.distroseries.name,
                        "architectures": [das.architecturetag],
                        }]}))

    def test_getConfiguration_not_found(self):
        build = self.factory.makeCIBuild()
        self.useFixture(GitHostingFixture()).getBlob.failure = (
            GitRepositoryBlobNotFound(
                build.git_repository.getInternalPath(), ".launchpad.yaml",
                rev=build.commit_sha1))
        self.assertRaisesWithContent(
            MissingConfiguration,
            "Cannot find .launchpad.yaml in %s" % (
                build.git_repository.unique_name),
            build.getConfiguration)

    def test_getConfiguration_fetch_error(self):
        build = self.factory.makeCIBuild()
        self.useFixture(GitHostingFixture()).getBlob.failure = (
            GitRepositoryScanFault("Boom"))
        self.assertRaisesWithContent(
            CannotFetchConfiguration,
            "Failed to get .launchpad.yaml from %s: Boom" % (
                build.git_repository.unique_name),
            build.getConfiguration)

    def test_getConfiguration_invalid_data(self):
        build = self.factory.makeCIBuild()
        hosting_fixture = self.useFixture(GitHostingFixture())
        for invalid_result in (None, 123, b"", b"[][]", b"#name:test", b"]"):
            hosting_fixture.getBlob.result = invalid_result
            self.assertRaises(CannotParseConfiguration, build.getConfiguration)


class TestCIBuildSet(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_getByBuildFarmJob_works(self):
        build = self.factory.makeCIBuild()
        self.assertEqual(
            build,
            getUtility(ICIBuildSet).getByBuildFarmJob(build.build_farm_job))

    def test_getByBuildFarmJob_returns_None_when_missing(self):
        bpb = self.factory.makeBinaryPackageBuild()
        self.assertIsNone(
            getUtility(ICIBuildSet).getByBuildFarmJob(bpb.build_farm_job))

    def test_getByBuildFarmJobs_works(self):
        builds = [self.factory.makeCIBuild() for i in range(10)]
        self.assertContentEqual(
            builds,
            getUtility(ICIBuildSet).getByBuildFarmJobs(
                [build.build_farm_job for build in builds]))

    def test_getByBuildFarmJobs_works_empty(self):
        self.assertContentEqual(
            [], getUtility(ICIBuildSet).getByBuildFarmJobs([]))

    def test_virtualized_processor_requires(self):
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = False
        target = self.factory.makeCIBuild(
            distro_arch_series=distro_arch_series)
        self.assertTrue(target.virtualized)

    def test_virtualized_processor_does_not_require(self):
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = True
        target = self.factory.makeCIBuild(
            distro_arch_series=distro_arch_series)
        self.assertTrue(target.virtualized)

    def test_findByGitRepository(self):
        repositories = [self.factory.makeGitRepository() for _ in range(2)]
        builds = []
        for repository in repositories:
            builds.extend(
                [self.factory.makeCIBuild(repository) for _ in range(2)])
        ci_build_set = getUtility(ICIBuildSet)
        self.assertContentEqual(
            builds[:2], ci_build_set.findByGitRepository(repositories[0]))
        self.assertContentEqual(
            builds[2:], ci_build_set.findByGitRepository(repositories[1]))

    def test_deleteByGitRepository(self):
        repositories = [self.factory.makeGitRepository() for _ in range(2)]
        builds = []
        for repository in repositories:
            builds.extend(
                [self.factory.makeCIBuild(repository) for _ in range(2)])
        ci_build_set = getUtility(ICIBuildSet)

        ci_build_set.deleteByGitRepository(repositories[0])

        self.assertContentEqual(
            [], ci_build_set.findByGitRepository(repositories[0]))
        self.assertContentEqual(
            builds[2:], ci_build_set.findByGitRepository(repositories[1]))
