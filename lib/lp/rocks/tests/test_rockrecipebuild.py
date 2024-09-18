# Copyright 2015-2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test rock package build features."""
from datetime import datetime, timedelta, timezone

import six
from testtools.matchers import Equals
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.errors import NotFoundError
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
from lp.registry.interfaces.series import SeriesStatus
from lp.rocks.interfaces.rockrecipe import (
    ROCK_RECIPE_ALLOW_CREATE,
    ROCK_RECIPE_PRIVATE_FEATURE_FLAG,
)
from lp.rocks.interfaces.rockrecipebuild import (
    IRockRecipeBuild,
    IRockRecipeBuildSet,
)
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.propertycache import clear_property_cache
from lp.testing import (
    StormStatementRecorder,
    TestCaseWithFactory,
    person_logged_in,
)
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications
from lp.testing.matchers import HasQueryCount

expected_body = """\
 * Rock Recipe: rock-1
 * Project: rock-project
 * Distroseries: distro unstable
 * Architecture: i386
 * State: Failed to build
 * Duration: 10 minutes
 * Build Log: %s
 * Upload Log: %s
 * Builder: http://launchpad.test/builders/bob
"""


class TestRockRecipeBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))
        self.build = self.factory.makeRockRecipeBuild()

    def test_implements_interfaces(self):
        # RockRecipeBuild implements IPackageBuild and IRockRecipeBuild.
        self.assertProvides(self.build, IPackageBuild)
        self.assertProvides(self.build, IRockRecipeBuild)

    def test___repr__(self):
        # RockRecipeBuild has an informative __repr__.
        self.assertEqual(
            "<RockRecipeBuild ~%s/%s/+rock/%s/+build/%s>"
            % (
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
                self.build.id,
            ),
            repr(self.build),
        )

    def test_title(self):
        # RockRecipeBuild has an informative title.
        das = self.build.distro_arch_series
        self.assertEqual(
            "%s build of /~%s/%s/+rock/%s"
            % (
                das.architecturetag,
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
            ),
            self.build.title,
        )

    def test_queueBuild(self):
        # RockRecipeBuild can create the queue entry for itself.
        bq = self.build.queueBuild()
        self.assertProvides(bq, IBuildQueue)
        self.assertEqual(
            self.build.build_farm_job, removeSecurityProxy(bq)._build_farm_job
        )
        self.assertEqual(self.build, bq.specific_build)
        self.assertEqual(self.build.virtualized, bq.virtualized)
        self.assertIsNotNone(bq.processor)
        self.assertEqual(bq, self.build.buildqueue_record)

    def test_is_private(self):
        # A RockRecipeBuild is private iff its recipe or owner are.
        self.assertFalse(self.build.is_private)
        self.useFixture(
            FeatureFixture(
                {
                    ROCK_RECIPE_ALLOW_CREATE: "on",
                    ROCK_RECIPE_PRIVATE_FEATURE_FLAG: "on",
                }
            )
        )
        private_team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED,
            visibility=PersonVisibility.PRIVATE,
        )
        with person_logged_in(private_team.teamowner):
            build = self.factory.makeRockRecipeBuild(
                requester=private_team.teamowner,
                owner=private_team,
                information_type=InformationType.PROPRIETARY,
            )
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
            build = self.factory.makeRockRecipeBuild(status=status)
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
        build = self.factory.makeRockRecipeBuild(distro_arch_series=das)
        self.assertFalse(build.can_be_retried)

    def test_can_be_cancelled(self):
        # For all states that can be cancelled, can_be_cancelled returns True.
        ok_cases = [
            BuildStatus.BUILDING,
            BuildStatus.NEEDSBUILD,
        ]
        for status in BuildStatus.items:
            build = self.factory.makeRockRecipeBuild()
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
        build = self.factory.makeRockRecipeBuild()
        build.updateStatus(BuildStatus.BUILDING, date_started=now)
        build.updateStatus(BuildStatus.FAILEDTOBUILD)
        build.gotFailure()
        with person_logged_in(build.recipe.owner):
            build.retry()
        self.assertEqual(BuildStatus.NEEDSBUILD, build.status)
        self.assertEqual(now, build.date_first_dispatched)
        self.assertIsNone(build.log)
        self.assertIsNone(build.upload_log)
        self.assertEqual(0, build.failure_count)

    def test_cancel_not_in_progress(self):
        # The cancel() method for a pending build leaves it in the CANCELLED
        # state.
        self.build.queueBuild()
        self.build.cancel()
        self.assertEqual(BuildStatus.CANCELLED, self.build.status)
        self.assertIsNone(self.build.buildqueue_record)

    def test_cancel_in_progress(self):
        # The cancel() method for a building build leaves it in the
        # CANCELLING state.
        bq = self.build.queueBuild()
        bq.markAsBuilding(self.factory.makeBuilder())
        self.build.cancel()
        self.assertEqual(BuildStatus.CANCELLING, self.build.status)
        self.assertEqual(bq, self.build.buildqueue_record)

    def test_estimateDuration(self):
        # Without previous builds, the default time estimate is 10m.
        self.assertEqual(600, self.build.estimateDuration().seconds)

    def test_estimateDuration_with_history(self):
        # Previous successful builds of the same recipe are used for
        # estimates.
        self.factory.makeRockRecipeBuild(
            requester=self.build.requester,
            recipe=self.build.recipe,
            distro_arch_series=self.build.distro_arch_series,
            status=BuildStatus.FULLYBUILT,
            duration=timedelta(seconds=335),
        )
        for _ in range(3):
            self.factory.makeRockRecipeBuild(
                requester=self.build.requester,
                recipe=self.build.recipe,
                distro_arch_series=self.build.distro_arch_series,
                status=BuildStatus.FAILEDTOBUILD,
                duration=timedelta(seconds=20),
            )
        self.assertEqual(335, self.build.estimateDuration().seconds)

    def test_build_cookie(self):
        build = self.factory.makeRockRecipeBuild()
        self.assertEqual("ROCKRECIPEBUILD-%d" % build.id, build.build_cookie)

    def test_getFileByName_logs(self):
        # getFileByName returns the logs when requested by name.
        self.build.setLog(
            self.factory.makeLibraryFileAlias(filename="buildlog.txt.gz")
        )
        self.assertEqual(
            self.build.log, self.build.getFileByName("buildlog.txt.gz")
        )
        self.assertRaises(NotFoundError, self.build.getFileByName, "foo")
        self.build.storeUploadLog("uploaded")
        self.assertEqual(
            self.build.upload_log,
            self.build.getFileByName(self.build.upload_log.filename),
        )

    def test_getFileByName_uploaded_files(self):
        # getFileByName returns uploaded files when requested by name.
        filenames = ("ubuntu.squashfs", "ubuntu.manifest")
        lfas = []
        for filename in filenames:
            lfa = self.factory.makeLibraryFileAlias(filename=filename)
            lfas.append(lfa)
            self.build.addFile(lfa)
        self.assertContentEqual(
            lfas, [row[1] for row in self.build.getFiles()]
        )
        for filename, lfa in zip(filenames, lfas):
            self.assertEqual(lfa, self.build.getFileByName(filename))
        self.assertRaises(NotFoundError, self.build.getFileByName, "missing")

    def test_verifySuccessfulUpload(self):
        self.assertFalse(self.build.verifySuccessfulUpload())
        self.factory.makeRockFile(build=self.build)
        self.assertTrue(self.build.verifySuccessfulUpload())

    def test_updateStatus_stores_revision_id(self):
        # If the builder reports a revision_id, updateStatus saves it.
        self.assertIsNone(self.build.revision_id)
        self.build.updateStatus(BuildStatus.BUILDING, worker_status={})
        self.assertIsNone(self.build.revision_id)
        self.build.updateStatus(
            BuildStatus.BUILDING, worker_status={"revision_id": "dummy"}
        )
        self.assertEqual("dummy", self.build.revision_id)

    def test_notify_fullybuilt(self):
        # notify does not send mail when a recipe build completes normally.
        build = self.factory.makeRockRecipeBuild(status=BuildStatus.FULLYBUILT)
        build.notify()
        self.assertEqual(0, len(pop_notifications()))

    def test_notify_packagefail(self):
        # notify sends mail when a recipe build fails.
        person = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="rock-project")
        distribution = self.factory.makeDistribution(name="distro")
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, name="unstable"
        )
        processor = getUtility(IProcessorSet).getByName("386")
        das = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag="i386",
            processor=processor,
        )
        build = self.factory.makeRockRecipeBuild(
            name="rock-1",
            requester=person,
            owner=person,
            project=project,
            distro_arch_series=das,
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
        self.assertEqual(
            "[Rock recipe build #%d] i386 build of "
            "/~person/rock-project/+rock/rock-1" % build.id,
            subject,
        )
        self.assertEqual(
            "Requester", notification["X-Launchpad-Message-Rationale"]
        )
        self.assertEqual(person.name, notification["X-Launchpad-Message-For"])
        self.assertEqual(
            "rock-recipe-build-status",
            notification["X-Launchpad-Notification-Type"],
        )
        self.assertEqual(
            "FAILEDTOBUILD", notification["X-Launchpad-Build-State"]
        )
        body, footer = six.ensure_text(
            notification.get_payload(decode=True)
        ).split("\n-- \n")
        self.assertEqual(expected_body % (build.log_url, ""), body)
        self.assertEqual(
            "http://launchpad.test/~person/rock-project/+rock/rock-1/"
            "+build/%d\n"
            "You are the requester of the build.\n" % build.id,
            footer,
        )

    def addFakeBuildLog(self, build):
        build.setLog(self.factory.makeLibraryFileAlias("mybuildlog.txt"))

    def test_log_url_123(self):
        # The log URL for a rock recipe build will use the recipe context.
        self.addFakeBuildLog(self.build)
        self.build.log_url
        self.assertEqual(
            "http://launchpad.test/~%s/%s/+rock/%s/+build/%d/+files/"
            "mybuildlog.txt"
            % (
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
                self.build.id,
            ),
            self.build.log_url,
        )

    def test_eta(self):
        # RockRecipeBuild.eta returns a non-None value when it should, or
        # None when there's no start time.
        self.build.queueBuild()
        self.assertIsNone(self.build.eta)
        self.factory.makeBuilder(processors=[self.build.processor])
        clear_property_cache(self.build)
        self.assertIsNotNone(self.build.eta)

    def test_eta_cached(self):
        # The expensive completion time estimate is cached.
        self.build.queueBuild()
        self.build.eta
        with StormStatementRecorder() as recorder:
            self.build.eta
        self.assertThat(recorder, HasQueryCount(Equals(0)))

    def test_estimate(self):
        # RockRecipeBuild.estimate returns True until the job is completed.
        self.build.queueBuild()
        self.factory.makeBuilder(processors=[self.build.processor])
        self.build.updateStatus(BuildStatus.BUILDING)
        self.assertTrue(self.build.estimate)
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        clear_property_cache(self.build)
        self.assertFalse(self.build.estimate)


class TestRockRecipeBuildSet(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({ROCK_RECIPE_ALLOW_CREATE: "on"}))

    def test_getByBuildFarmJob_works(self):
        build = self.factory.makeRockRecipeBuild()
        self.assertEqual(
            build,
            getUtility(IRockRecipeBuildSet).getByBuildFarmJob(
                build.build_farm_job
            ),
        )

    def test_getByBuildFarmJob_returns_None_when_missing(self):
        bpb = self.factory.makeBinaryPackageBuild()
        self.assertIsNone(
            getUtility(IRockRecipeBuildSet).getByBuildFarmJob(
                bpb.build_farm_job
            )
        )

    def test_getByBuildFarmJobs_works(self):
        builds = [self.factory.makeRockRecipeBuild() for i in range(10)]
        self.assertContentEqual(
            builds,
            getUtility(IRockRecipeBuildSet).getByBuildFarmJobs(
                [build.build_farm_job for build in builds]
            ),
        )

    def test_getByBuildFarmJobs_works_empty(self):
        self.assertContentEqual(
            [], getUtility(IRockRecipeBuildSet).getByBuildFarmJobs([])
        )

    def test_virtualized_recipe_requires(self):
        recipe = self.factory.makeRockRecipe(require_virtualized=True)
        target = self.factory.makeRockRecipeBuild(recipe=recipe)
        self.assertTrue(target.virtualized)

    def test_virtualized_processor_requires(self):
        recipe = self.factory.makeRockRecipe(require_virtualized=False)
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = False
        target = self.factory.makeRockRecipeBuild(
            distro_arch_series=distro_arch_series, recipe=recipe
        )
        self.assertTrue(target.virtualized)

    def test_virtualized_no_support(self):
        recipe = self.factory.makeRockRecipe(require_virtualized=False)
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = True
        target = self.factory.makeRockRecipeBuild(
            recipe=recipe, distro_arch_series=distro_arch_series
        )
        self.assertFalse(target.virtualized)
