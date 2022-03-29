# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test CI builds."""

from datetime import (
    datetime,
    timedelta,
    )
import hashlib
from textwrap import dedent
from unittest.mock import Mock

from fixtures import MockPatchObject
import pytz
from storm.locals import Store
from testtools.matchers import (
    Equals,
    MatchesSetwise,
    MatchesStructure,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import (
    BuildQueueStatus,
    BuildStatus,
    )
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.code.errors import (
    GitRepositoryBlobNotFound,
    GitRepositoryScanFault,
    )
from lp.code.interfaces.cibuild import (
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
from lp.code.model.lpcraft import load_configuration
from lp.code.tests.helpers import GitHostingFixture
from lp.registry.interfaces.series import SeriesStatus
from lp.services.log.logger import BufferLogger
from lp.services.propertycache import clear_property_cache
from lp.testing import (
    person_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.matchers import HasQueryCount


class TestGetAllCommitsForPaths(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_no_refs(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']

        rv = get_all_commits_for_paths(repository, ref_paths)

        self.assertEqual([], rv)

    def test_one_ref_one_path(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
        [ref] = self.factory.makeGitRefs(repository, ref_paths)

        rv = get_all_commits_for_paths(repository, ref_paths)

        self.assertEqual(1, len(rv))
        self.assertEqual(ref.commit_sha1, rv[0])

    def test_multiple_refs_and_paths(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master', "refs/heads/dev"]
        refs = self.factory.makeGitRefs(repository, ref_paths)

        rv = get_all_commits_for_paths(repository, ref_paths)

        self.assertEqual(2, len(rv))
        self.assertEqual({ref.commit_sha1 for ref in refs}, set(rv))


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

    def test_getFileByName_logs(self):
        # getFileByName returns the logs when requested by name.
        build = self.factory.makeCIBuild()
        build.setLog(
            self.factory.makeLibraryFileAlias(filename="buildlog.txt.gz"))
        self.assertEqual(build.log, build.getFileByName("buildlog.txt.gz"))
        self.assertRaises(NotFoundError, build.getFileByName, "foo")
        build.storeUploadLog("uploaded")
        self.assertEqual(
            build.upload_log, build.getFileByName(build.upload_log.filename))

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

    def test_requestCIBuild(self):
        # requestBuild creates a new CIBuild.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        das = self.factory.makeBuildableDistroArchSeries()

        build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, das)

        self.assertTrue(ICIBuild.providedBy(build))
        self.assertThat(build, MatchesStructure.byEquality(
            git_repository=repository,
            commit_sha1=commit_sha1,
            distro_arch_series=das,
            status=BuildStatus.NEEDSBUILD,
            ))
        store = Store.of(build)
        store.flush()
        build_queue = store.find(
            BuildQueue,
            BuildQueue._build_farm_job_id ==
                removeSecurityProxy(build).build_farm_job_id).one()
        self.assertProvides(build_queue, IBuildQueue)
        self.assertTrue(build_queue.virtualized)
        self.assertEqual(BuildQueueStatus.WAITING, build_queue.status)

    def test_requestBuild_score(self):
        # CI builds have an initial queue score of 2600.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        das = self.factory.makeBuildableDistroArchSeries()
        build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, das)
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
                distroseries=distro_series)
            for _ in range(2)]
        old_build = getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, arches[0])
        self.assertRaises(
            CIBuildAlreadyRequested, getUtility(ICIBuildSet).requestBuild,
            repository, commit_sha1, arches[0])
        # We can build for a different distroarchseries.
        getUtility(ICIBuildSet).requestBuild(
            repository, commit_sha1, arches[1])
        # Changing the status of the old build does not allow a new build.
        old_build.updateStatus(BuildStatus.BUILDING)
        old_build.updateStatus(BuildStatus.FULLYBUILT)
        self.assertRaises(
            CIBuildAlreadyRequested, getUtility(ICIBuildSet).requestBuild,
            repository, commit_sha1, arches[0])

    def test_requestBuild_virtualization(self):
        # New builds are virtualized.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        distro_series = self.factory.makeDistroSeries()
        for proc_nonvirt in True, False:
            das = self.factory.makeBuildableDistroArchSeries(
                distroseries=distro_series, supports_virtualized=True,
                supports_nonvirtualized=proc_nonvirt)
            build = getUtility(ICIBuildSet).requestBuild(
                repository, commit_sha1, das)
            self.assertTrue(build.virtualized)

    def test_requestBuild_nonvirtualized(self):
        # A non-virtualized processor cannot run a CI build.
        repository = self.factory.makeGitRepository()
        commit_sha1 = hashlib.sha1(self.factory.getUniqueBytes()).hexdigest()
        distro_series = self.factory.makeDistroSeries()
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series, supports_virtualized=False,
            supports_nonvirtualized=True)
        self.assertRaises(
            CIBuildDisallowedArchitecture,
            getUtility(ICIBuildSet).requestBuild, repository, commit_sha1, das)

    def test_requestBuildsForRefs_triggers_builds(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series,
            architecturetag="amd64"
        )
        configuration = dedent("""\
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
            """).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
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
            [((repository.getInternalPath(), [ref.commit_sha1]),
              {"filter_paths": [".launchpad.yaml"], "logger": None})],
            hosting_fixture.getCommits.calls
        )

        build = getUtility(ICIBuildSet).findByGitRepository(repository).one()
        reports = list(
            getUtility(IRevisionStatusReportSet).findByRepository(repository))

        # check that a build and some reports were created
        self.assertEqual(ref.commit_sha1, build.commit_sha1)
        self.assertEqual("focal", build.distro_arch_series.distroseries.name)
        self.assertEqual("amd64", build.distro_arch_series.architecturetag)
        self.assertThat(reports, MatchesSetwise(*(
            MatchesStructure.byEquality(
                creator=repository.owner,
                title=title,
                git_repository=repository,
                commit_sha1=ref.commit_sha1,
                ci_build=build)
            for title in ("build:0", "build:1", "test:0"))))

    def test_requestBuildsForRefs_no_commits_at_all(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
        hosting_fixture = self.useFixture(GitHostingFixture(commits=[]))

        getUtility(ICIBuildSet).requestBuildsForRefs(repository, ref_paths)

        self.assertEqual(
            [((repository.getInternalPath(), []),
              {"filter_paths": [".launchpad.yaml"], "logger": None})],
            hosting_fixture.getCommits.calls
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet).findByRepository(
                repository).is_empty()
        )

    def test_requestBuildsForRefs_no_matching_commits(self):
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
        [ref] = self.factory.makeGitRefs(repository, ref_paths)
        hosting_fixture = self.useFixture(
            GitHostingFixture(commits=[])
        )

        getUtility(ICIBuildSet).requestBuildsForRefs(repository, ref_paths)

        self.assertEqual(
            [((repository.getInternalPath(), [ref.commit_sha1]),
              {"filter_paths": [".launchpad.yaml"], "logger": None})],
            hosting_fixture.getCommits.calls
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet).findByRepository(
                repository).is_empty()
        )

    def test_requestBuildsForRefs_configuration_parse_error(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series,
            architecturetag="amd64"
        )
        configuration = dedent("""\
            no - valid - configuration - file
            """).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
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
            repository, ref_paths, logger)

        self.assertEqual(
            [((repository.getInternalPath(), [ref.commit_sha1]),
              {"filter_paths": [".launchpad.yaml"], "logger": logger})],
            hosting_fixture.getCommits.calls
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet).findByRepository(
                repository).is_empty()
        )

        self.assertEqual(
            "ERROR Cannot parse .launchpad.yaml from %s: "
            "Configuration file does not declare 'pipeline'\n" % (
                repository.unique_name,),
            logger.getLogBuffer()
        )

    def test_requestBuildsForRefs_build_already_scheduled(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series,
            architecturetag="amd64"
        )
        configuration = dedent("""\
            pipeline:
            - test

            jobs:
                test:
                    series: focal
                    architectures: amd64
                    run: echo hello world >output
            """).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
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
            [((repository.getInternalPath(), [ref.commit_sha1]),
              {"filter_paths": [".launchpad.yaml"], "logger": logger})],
            hosting_fixture.getCommits.calls
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet).findByRepository(
                repository).is_empty()
        )
        self.assertEqual(
            "INFO Requesting CI build "
            "for %s on focal/amd64\n" % ref.commit_sha1,
            logger.getLogBuffer()
        )

    def test_requestBuildsForRefs_unexpected_exception(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        series = self.factory.makeDistroSeries(
            distribution=ubuntu,
            name="focal",
        )
        self.factory.makeBuildableDistroArchSeries(
            distroseries=series,
            architecturetag="amd64"
        )
        configuration = dedent("""\
            pipeline:
            - test

            jobs:
                test:
                    series: focal
                    architectures: amd64
                    run: echo hello world >output
            """).encode()
        repository = self.factory.makeGitRepository()
        ref_paths = ['refs/heads/master']
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
            [((repository.getInternalPath(), [ref.commit_sha1]),
              {"filter_paths": [".launchpad.yaml"], "logger": logger})],
            hosting_fixture.getCommits.calls
        )

        self.assertTrue(
            getUtility(ICIBuildSet).findByGitRepository(repository).is_empty()
        )
        self.assertTrue(
            getUtility(IRevisionStatusReportSet).findByRepository(
                repository).is_empty()
        )

        log_line1, log_line2 = logger.getLogBuffer().splitlines()
        self.assertEqual(
            "INFO Requesting CI build for %s on focal/amd64" % ref.commit_sha1,
            log_line1)
        self.assertEqual(
            "ERROR Failed to request CI build for %s on focal/amd64: "
            "some unexpected error" % (ref.commit_sha1,),
            log_line2
        )

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


class TestDetermineDASesToBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_returns_expected_DASes(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_serieses = [
            self.factory.makeDistroSeries(ubuntu) for _ in range(2)]
        dases = []
        for distro_series in distro_serieses:
            for _ in range(2):
                dases.append(self.factory.makeBuildableDistroArchSeries(
                    distroseries=distro_series))
        configuration = load_configuration(dedent("""\
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
            """.format(distro_serieses=distro_serieses, dases=dases)))
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger))

        self.assertContentEqual(dases[2:], dases_to_build)
        self.assertEqual("", logger.getLogBuffer())


    def test_logs_missing_job_definition(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_series = self.factory.makeDistroSeries(ubuntu)
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series)
        configuration = load_configuration(dedent("""\
            pipeline:
                - [test]
            jobs:
                build:
                    series: {distro_series.name}
                    architectures:
                        - {das.architecturetag}
            """.format(distro_series=distro_series, das=das)))
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger))

        self.assertEqual(0, len(dases_to_build))
        self.assertEqual(
            "ERROR No job definition for 'test'\n", logger.getLogBuffer()
        )


    def test_logs_missing_series(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_series = self.factory.makeDistroSeries(ubuntu)
        das = self.factory.makeBuildableDistroArchSeries(
            distroseries=distro_series)
        configuration = load_configuration(dedent("""\
            pipeline:
                - [build]
            jobs:
                build:
                    series: unknown-series
                    architectures:
                        - {das.architecturetag}
            """.format(das=das)))
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger))

        self.assertEqual(0, len(dases_to_build))
        self.assertEqual(
            "ERROR Unknown Ubuntu series name unknown-series\n",
            logger.getLogBuffer()
        )


    def test_logs_non_buildable_architecture(self):
        ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        distro_series = self.factory.makeDistroSeries(ubuntu)
        configuration = load_configuration(dedent("""\
            pipeline:
                - [build]
            jobs:
                build:
                    series: {distro_series.name}
                    architectures:
                        - non-buildable-architecture
            """.format(distro_series=distro_series)))
        logger = BufferLogger()

        dases_to_build = list(
            determine_DASes_to_build(configuration, logger=logger))

        self.assertEqual(0, len(dases_to_build))
        self.assertEqual(
            "ERROR non-buildable-architecture is not a buildable architecture "
            "name in Ubuntu %s\n" % distro_series.name,
            logger.getLogBuffer()
        )
