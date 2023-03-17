# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test charm package build features."""

import base64
from datetime import datetime, timedelta, timezone
from urllib.request import urlopen

from fixtures import FakeLogger
from nacl.public import PrivateKey
from pymacaroons import Macaroon
from testtools.matchers import (
    ContainsDict,
    Equals,
    Is,
    MatchesDict,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.enums import InformationType
from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.charms.interfaces.charmrecipe import (
    CHARM_RECIPE_ALLOW_CREATE,
    CHARM_RECIPE_PRIVATE_FEATURE_FLAG,
    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG,
)
from lp.charms.interfaces.charmrecipebuild import (
    CannotScheduleStoreUpload,
    CharmRecipeBuildStoreUploadStatus,
    ICharmRecipeBuild,
    ICharmRecipeBuildSet,
)
from lp.charms.interfaces.charmrecipebuildjob import ICharmhubUploadJobSource
from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.services.crypto.interfaces import IEncryptedContainer
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.propertycache import clear_property_cache
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.testing import (
    ANONYMOUS,
    StormStatementRecorder,
    TestCaseWithFactory,
    api_url,
    login,
    logout,
    person_logged_in,
)
from lp.testing.dbuser import dbuser
from lp.testing.layers import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person

expected_body = """\
 * Charm Recipe: charm-1
 * Project: charm-project
 * Distroseries: distro unstable
 * Architecture: i386
 * State: Failed to build
 * Duration: 10 minutes
 * Build Log: %s
 * Upload Log: %s
 * Builder: http://launchpad.test/builders/bob
"""


class TestCharmRecipeBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))
        self.build = self.factory.makeCharmRecipeBuild()

    def test_implements_interfaces(self):
        # CharmRecipeBuild implements IPackageBuild and ICharmRecipeBuild.
        self.assertProvides(self.build, IPackageBuild)
        self.assertProvides(self.build, ICharmRecipeBuild)

    def test___repr__(self):
        # CharmRecipeBuild has an informative __repr__.
        self.assertEqual(
            "<CharmRecipeBuild ~%s/%s/+charm/%s/+build/%s>"
            % (
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
                self.build.id,
            ),
            repr(self.build),
        )

    def test_title(self):
        # CharmRecipeBuild has an informative title.
        das = self.build.distro_arch_series
        self.assertEqual(
            "%s build of /~%s/%s/+charm/%s"
            % (
                das.architecturetag,
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
            ),
            self.build.title,
        )

    def test_queueBuild(self):
        # CharmRecipeBuild can create the queue entry for itself.
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
        # A CharmRecipeBuild is private iff its recipe or owner are.
        self.assertFalse(self.build.is_private)
        self.useFixture(
            FeatureFixture(
                {
                    CHARM_RECIPE_ALLOW_CREATE: "on",
                    CHARM_RECIPE_PRIVATE_FEATURE_FLAG: "on",
                }
            )
        )
        private_team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED,
            visibility=PersonVisibility.PRIVATE,
        )
        with person_logged_in(private_team.teamowner):
            build = self.factory.makeCharmRecipeBuild(
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
            build = self.factory.makeCharmRecipeBuild(status=status)
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
        build = self.factory.makeCharmRecipeBuild(distro_arch_series=das)
        self.assertFalse(build.can_be_retried)

    def test_can_be_cancelled(self):
        # For all states that can be cancelled, can_be_cancelled returns True.
        ok_cases = [
            BuildStatus.BUILDING,
            BuildStatus.NEEDSBUILD,
        ]
        for status in BuildStatus.items:
            build = self.factory.makeCharmRecipeBuild()
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
        build = self.factory.makeCharmRecipeBuild()
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
        self.factory.makeCharmRecipeBuild(
            requester=self.build.requester,
            recipe=self.build.recipe,
            distro_arch_series=self.build.distro_arch_series,
            status=BuildStatus.FULLYBUILT,
            duration=timedelta(seconds=335),
        )
        for i in range(3):
            self.factory.makeCharmRecipeBuild(
                requester=self.build.requester,
                recipe=self.build.recipe,
                distro_arch_series=self.build.distro_arch_series,
                status=BuildStatus.FAILEDTOBUILD,
                duration=timedelta(seconds=20),
            )
        self.assertEqual(335, self.build.estimateDuration().seconds)

    def test_build_cookie(self):
        build = self.factory.makeCharmRecipeBuild()
        self.assertEqual("CHARMRECIPEBUILD-%d" % build.id, build.build_cookie)

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
        filenames = ("ubuntu.squashfs", "ubuntu.manifest", "foo_log.txt")
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
        self.factory.makeCharmFile(build=self.build)
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

    def test_updateStatus_triggers_webhooks(self):
        # Updating the status of a CharmRecipeBuild triggers webhooks on the
        # corresponding CharmRecipe.
        self.useFixture(
            FeatureFixture(
                {
                    CHARM_RECIPE_ALLOW_CREATE: "on",
                    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                }
            )
        )
        logger = self.useFixture(FakeLogger())
        hook = self.factory.makeWebhook(
            target=self.build.recipe, event_types=["charm-recipe:build:0.1"]
        )
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        expected_payload = {
            "recipe_build": Equals(
                canonical_url(self.build, force_local_path=True)
            ),
            "action": Equals("status-changed"),
            "recipe": Equals(
                canonical_url(self.build.recipe, force_local_path=True)
            ),
            "build_request": Equals(
                canonical_url(self.build.build_request, force_local_path=True)
            ),
            "status": Equals("Successfully built"),
            "store_upload_status": Equals("Unscheduled"),
        }
        delivery = hook.deliveries.one()
        self.assertThat(
            delivery,
            MatchesStructure(
                event_type=Equals("charm-recipe:build:0.1"),
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
                    [
                        (
                            hook,
                            "charm-recipe:build:0.1",
                            MatchesDict(expected_payload),
                        )
                    ]
                ),
            )

    def test_updateStatus_no_change_does_not_trigger_webhooks(self):
        # An updateStatus call that changes details such as the revision_id
        # but that doesn't change the build's status attribute does not
        # trigger webhooks.
        self.useFixture(
            FeatureFixture(
                {
                    CHARM_RECIPE_ALLOW_CREATE: "on",
                    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                }
            )
        )
        logger = self.useFixture(FakeLogger())
        hook = self.factory.makeWebhook(
            target=self.build.recipe, event_types=["charm-recipe:build:0.1"]
        )
        builder = self.factory.makeBuilder()
        self.build.updateStatus(BuildStatus.BUILDING)
        expected_logs = [
            (
                hook,
                "charm-recipe:build:0.1",
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
        self.build.updateStatus(
            BuildStatus.BUILDING,
            builder=builder,
            worker_status={"revision_id": "1"},
        )
        self.assertEqual(1, hook.deliveries.count())
        self.assertThat(logger.output, LogsScheduledWebhooks(expected_logs))
        self.build.updateStatus(BuildStatus.UPLOADING)
        expected_logs.append(
            (
                hook,
                "charm-recipe:build:0.1",
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

    def test_updateStatus_failure_does_not_trigger_store_uploads(self):
        # A failed build does not trigger store uploads.
        self.pushConfig("charms", charmhub_url="http://charmhub.example/")
        self.build.recipe.store_name = self.factory.getUniqueUnicode()
        self.build.recipe.store_upload = True
        # CharmRecipe.can_upload_to_store only checks whether
        # "exchanged_encrypted" is present, so don't bother setting up
        # encryption keys here.
        self.build.recipe.store_secrets = {
            "exchanged_encrypted": Macaroon().serialize()
        }
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.FAILEDTOBUILD)
        self.assertContentEqual([], self.build.store_upload_jobs)

    def test_updateStatus_fullybuilt_not_configured(self):
        # A completed build does not trigger store uploads if the recipe is
        # not properly configured for that.
        logger = self.useFixture(FakeLogger())
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.assertEqual(0, len(list(self.build.store_upload_jobs)))
        self.assertIn(
            "<CharmRecipe ~%s/%s/+charm/%s> is not configured for upload to "
            "the store."
            % (
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
            ),
            logger.output.splitlines(),
        )

    def test_updateStatus_fullybuilt_triggers_store_uploads(self):
        # A completed build triggers store uploads.
        self.pushConfig("charms", charmhub_url="http://charmhub.example/")
        logger = self.useFixture(FakeLogger())
        self.build.recipe.store_name = self.factory.getUniqueUnicode()
        self.build.recipe.store_upload = True
        # CharmRecipe.can_upload_to_store only checks whether
        # "exchanged_encrypted" is present, so don't bother setting up
        # encryption keys here.
        self.build.recipe.store_secrets = {
            "exchanged_encrypted": Macaroon().serialize()
        }
        with dbuser(config.builddmaster.dbuser):
            self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.assertEqual(1, len(list(self.build.store_upload_jobs)))
        self.assertIn(
            "Scheduling upload of <CharmRecipeBuild "
            "~%s/%s/+charm/%s/+build/%d> to the store."
            % (
                self.build.recipe.owner.name,
                self.build.recipe.project.name,
                self.build.recipe.name,
                self.build.id,
            ),
            logger.output.splitlines(),
        )

    def test_notify_fullybuilt(self):
        # notify does not send mail when a recipe build completes normally.
        build = self.factory.makeCharmRecipeBuild(
            status=BuildStatus.FULLYBUILT
        )
        build.notify()
        self.assertEqual(0, len(pop_notifications()))

    def test_notify_packagefail(self):
        # notify sends mail when a recipe build fails.
        person = self.factory.makePerson(name="person")
        project = self.factory.makeProduct(name="charm-project")
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
        build = self.factory.makeCharmRecipeBuild(
            name="charm-1",
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
            "[Charm recipe build #%d] i386 build of "
            "/~person/charm-project/+charm/charm-1" % build.id,
            subject,
        )
        self.assertEqual(
            "Requester", notification["X-Launchpad-Message-Rationale"]
        )
        self.assertEqual(person.name, notification["X-Launchpad-Message-For"])
        self.assertEqual(
            "charm-recipe-build-status",
            notification["X-Launchpad-Notification-Type"],
        )
        self.assertEqual(
            "FAILEDTOBUILD", notification["X-Launchpad-Build-State"]
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertEqual(expected_body % (build.log_url, ""), body)
        self.assertEqual(
            "http://launchpad.test/~person/charm-project/+charm/charm-1/"
            "+build/%d\n"
            "You are the requester of the build.\n" % build.id,
            footer,
        )

    def addFakeBuildLog(self, build):
        build.setLog(self.factory.makeLibraryFileAlias("mybuildlog.txt"))

    def test_log_url(self):
        # The log URL for a charm recipe build will use the recipe context.
        self.addFakeBuildLog(self.build)
        self.assertEqual(
            "http://launchpad.test/~%s/%s/+charm/%s/+build/%d/+files/"
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
        # CharmRecipeBuild.eta returns a non-None value when it should, or
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
        # CharmRecipeBuild.estimate returns True until the job is completed.
        self.build.queueBuild()
        self.factory.makeBuilder(processors=[self.build.processor])
        self.build.updateStatus(BuildStatus.BUILDING)
        self.assertTrue(self.build.estimate)
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        clear_property_cache(self.build)
        self.assertFalse(self.build.estimate)

    def setUpStoreUpload(self):
        self.private_key = PrivateKey.generate()
        self.pushConfig(
            "charms",
            charmhub_url="http://charmhub.example/",
            charmhub_secrets_public_key=base64.b64encode(
                bytes(self.private_key.public_key)
            ).decode(),
        )
        self.build.recipe.store_name = self.factory.getUniqueUnicode()
        container = getUtility(IEncryptedContainer, "charmhub-secrets")
        self.build.recipe.store_secrets = {
            "exchanged_encrypted": removeSecurityProxy(
                container.encrypt(Macaroon().serialize().encode())
            ),
        }

    def test_store_upload_status_unscheduled(self):
        build = self.factory.makeCharmRecipeBuild(
            status=BuildStatus.FULLYBUILT
        )
        self.assertEqual(
            CharmRecipeBuildStoreUploadStatus.UNSCHEDULED,
            build.store_upload_status,
        )

    def test_store_upload_status_pending(self):
        build = self.factory.makeCharmRecipeBuild(
            status=BuildStatus.FULLYBUILT
        )
        getUtility(ICharmhubUploadJobSource).create(build)
        self.assertEqual(
            CharmRecipeBuildStoreUploadStatus.PENDING,
            build.store_upload_status,
        )

    def test_store_upload_status_uploaded(self):
        build = self.factory.makeCharmRecipeBuild(
            status=BuildStatus.FULLYBUILT
        )
        job = getUtility(ICharmhubUploadJobSource).create(build)
        naked_job = removeSecurityProxy(job)
        naked_job.job._status = JobStatus.COMPLETED
        self.assertEqual(
            CharmRecipeBuildStoreUploadStatus.UPLOADED,
            build.store_upload_status,
        )

    def test_store_upload_status_failed_to_upload(self):
        build = self.factory.makeCharmRecipeBuild(
            status=BuildStatus.FULLYBUILT
        )
        job = getUtility(ICharmhubUploadJobSource).create(build)
        naked_job = removeSecurityProxy(job)
        naked_job.job._status = JobStatus.FAILED
        self.assertEqual(
            CharmRecipeBuildStoreUploadStatus.FAILEDTOUPLOAD,
            build.store_upload_status,
        )

    def test_store_upload_status_failed_to_release(self):
        build = self.factory.makeCharmRecipeBuild(
            status=BuildStatus.FULLYBUILT
        )
        job = getUtility(ICharmhubUploadJobSource).create(build)
        naked_job = removeSecurityProxy(job)
        naked_job.job._status = JobStatus.FAILED
        naked_job.store_revision = 1
        self.assertEqual(
            CharmRecipeBuildStoreUploadStatus.FAILEDTORELEASE,
            build.store_upload_status,
        )

    def test_scheduleStoreUpload(self):
        # A build not previously uploaded to the store can be uploaded
        # manually.
        self.setUpStoreUpload()
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.factory.makeCharmFile(
            build=self.build,
            library_file=self.factory.makeLibraryFileAlias(db_only=True),
        )
        self.build.scheduleStoreUpload()
        [job] = getUtility(ICharmhubUploadJobSource).iterReady()
        self.assertEqual(JobStatus.WAITING, job.job.status)
        self.assertEqual(self.build, job.build)

    def test_scheduleStoreUpload_not_configured(self):
        # A build that is not properly configured cannot be uploaded to the
        # store.
        self.setUpStoreUpload()
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.build.recipe.store_name = None
        self.assertRaisesWithContent(
            CannotScheduleStoreUpload,
            "Cannot upload this charm to Charmhub because it is not properly "
            "configured.",
            self.build.scheduleStoreUpload,
        )
        self.assertEqual(
            [], list(getUtility(ICharmhubUploadJobSource).iterReady())
        )

    def test_scheduleStoreUpload_no_files(self):
        # A build with no files cannot be uploaded to the store.
        self.setUpStoreUpload()
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.assertRaisesWithContent(
            CannotScheduleStoreUpload,
            "Cannot upload this charm because it has no files.",
            self.build.scheduleStoreUpload,
        )
        self.assertEqual(
            [], list(getUtility(ICharmhubUploadJobSource).iterReady())
        )

    def test_scheduleStoreUpload_already_in_progress(self):
        # A build with an upload already in progress will not have another
        # one created.
        self.setUpStoreUpload()
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.factory.makeCharmFile(
            build=self.build,
            library_file=self.factory.makeLibraryFileAlias(db_only=True),
        )
        old_job = getUtility(ICharmhubUploadJobSource).create(self.build)
        self.assertRaisesWithContent(
            CannotScheduleStoreUpload,
            "An upload of this charm is already in progress.",
            self.build.scheduleStoreUpload,
        )
        self.assertEqual(
            [old_job], list(getUtility(ICharmhubUploadJobSource).iterReady())
        )

    def test_scheduleStoreUpload_already_uploaded(self):
        # A build with an upload that has already completed will not have
        # another one created.
        self.setUpStoreUpload()
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.factory.makeCharmFile(
            build=self.build,
            library_file=self.factory.makeLibraryFileAlias(db_only=True),
        )
        old_job = getUtility(ICharmhubUploadJobSource).create(self.build)
        removeSecurityProxy(old_job).job._status = JobStatus.COMPLETED
        self.assertRaisesWithContent(
            CannotScheduleStoreUpload,
            "Cannot upload this charm because it has already been uploaded.",
            self.build.scheduleStoreUpload,
        )
        self.assertEqual(
            [], list(getUtility(ICharmhubUploadJobSource).iterReady())
        )

    def test_scheduleStoreUpload_triggers_webhooks(self):
        # Scheduling a store upload triggers webhooks on the corresponding
        # recipe.
        self.useFixture(
            FeatureFixture(
                {
                    CHARM_RECIPE_ALLOW_CREATE: "on",
                    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                }
            )
        )
        logger = self.useFixture(FakeLogger())
        self.setUpStoreUpload()
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        self.factory.makeCharmFile(
            build=self.build,
            library_file=self.factory.makeLibraryFileAlias(db_only=True),
        )
        hook = self.factory.makeWebhook(
            target=self.build.recipe, event_types=["charm-recipe:build:0.1"]
        )
        self.build.scheduleStoreUpload()
        expected_payload = {
            "recipe_build": Equals(
                canonical_url(self.build, force_local_path=True)
            ),
            "action": Equals("status-changed"),
            "recipe": Equals(
                canonical_url(self.build.recipe, force_local_path=True)
            ),
            "build_request": Equals(
                canonical_url(self.build.build_request, force_local_path=True)
            ),
            "status": Equals("Successfully built"),
            "store_upload_status": Equals("Pending"),
        }
        delivery = hook.deliveries.one()
        self.assertThat(
            delivery,
            MatchesStructure(
                event_type=Equals("charm-recipe:build:0.1"),
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
                    [
                        (
                            hook,
                            "charm-recipe:build:0.1",
                            MatchesDict(expected_payload),
                        )
                    ]
                ),
            )


class TestCharmRecipeBuildSet(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_getByBuildFarmJob_works(self):
        build = self.factory.makeCharmRecipeBuild()
        self.assertEqual(
            build,
            getUtility(ICharmRecipeBuildSet).getByBuildFarmJob(
                build.build_farm_job
            ),
        )

    def test_getByBuildFarmJob_returns_None_when_missing(self):
        bpb = self.factory.makeBinaryPackageBuild()
        self.assertIsNone(
            getUtility(ICharmRecipeBuildSet).getByBuildFarmJob(
                bpb.build_farm_job
            )
        )

    def test_getByBuildFarmJobs_works(self):
        builds = [self.factory.makeCharmRecipeBuild() for i in range(10)]
        self.assertContentEqual(
            builds,
            getUtility(ICharmRecipeBuildSet).getByBuildFarmJobs(
                [build.build_farm_job for build in builds]
            ),
        )

    def test_getByBuildFarmJobs_works_empty(self):
        self.assertContentEqual(
            [], getUtility(ICharmRecipeBuildSet).getByBuildFarmJobs([])
        )

    def test_virtualized_recipe_requires(self):
        recipe = self.factory.makeCharmRecipe(require_virtualized=True)
        target = self.factory.makeCharmRecipeBuild(recipe=recipe)
        self.assertTrue(target.virtualized)

    def test_virtualized_processor_requires(self):
        recipe = self.factory.makeCharmRecipe(require_virtualized=False)
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = False
        target = self.factory.makeCharmRecipeBuild(
            distro_arch_series=distro_arch_series, recipe=recipe
        )
        self.assertTrue(target.virtualized)

    def test_virtualized_no_support(self):
        recipe = self.factory.makeCharmRecipe(require_virtualized=False)
        distro_arch_series = self.factory.makeDistroArchSeries()
        distro_arch_series.processor.supports_nonvirtualized = True
        target = self.factory.makeCharmRecipeBuild(
            recipe=recipe, distro_arch_series=distro_arch_series
        )
        self.assertFalse(target.virtualized)


class TestCharmRecipeBuildWebservice(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(
            FeatureFixture(
                {
                    CHARM_RECIPE_ALLOW_CREATE: "on",
                    CHARM_RECIPE_PRIVATE_FEATURE_FLAG: "on",
                }
            )
        )
        self.person = self.factory.makePerson()
        self.webservice = webservice_for_person(
            self.person, permission=OAuthPermission.WRITE_PRIVATE
        )
        self.webservice.default_api_version = "devel"
        login(ANONYMOUS)

    def getURL(self, obj):
        return self.webservice.getAbsoluteUrl(api_url(obj))

    def test_properties(self):
        # The basic properties of a charm recipe build are sensible.
        db_build = self.factory.makeCharmRecipeBuild(
            requester=self.person,
            date_created=datetime(2021, 9, 15, 16, 21, 0, tzinfo=timezone.utc),
        )
        build_url = api_url(db_build)
        logout()
        build = self.webservice.get(build_url).jsonBody()
        with person_logged_in(self.person):
            self.assertThat(
                build,
                ContainsDict(
                    {
                        "requester_link": Equals(self.getURL(self.person)),
                        "recipe_link": Equals(self.getURL(db_build.recipe)),
                        "distro_arch_series_link": Equals(
                            self.getURL(db_build.distro_arch_series)
                        ),
                        "arch_tag": Equals(
                            db_build.distro_arch_series.architecturetag
                        ),
                        "channels": Is(None),
                        "score": Is(None),
                        "can_be_rescored": Is(False),
                        "can_be_retried": Is(False),
                        "can_be_cancelled": Is(False),
                    }
                ),
            )

    def test_public(self):
        # A charm recipe build with a public recipe is itself public.
        db_build = self.factory.makeCharmRecipeBuild()
        build_url = api_url(db_build)
        unpriv_webservice = webservice_for_person(
            self.factory.makePerson(), permission=OAuthPermission.WRITE_PUBLIC
        )
        unpriv_webservice.default_api_version = "devel"
        logout()
        self.assertEqual(200, self.webservice.get(build_url).status)
        self.assertEqual(200, unpriv_webservice.get(build_url).status)

    def test_cancel(self):
        # The owner of a build can cancel it.
        db_build = self.factory.makeCharmRecipeBuild(requester=self.person)
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
        db_build = self.factory.makeCharmRecipeBuild(requester=self.person)
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
        self.assertEqual(2510, build["score"])
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
        db_build = self.factory.makeCharmRecipeBuild(requester=self.person)
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
