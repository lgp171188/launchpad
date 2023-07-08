# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for charm recipe build jobs."""

from datetime import timedelta

import transaction
from fixtures import FakeLogger
from testtools.matchers import (
    Equals,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
)
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.charms.interfaces.charmhubclient import (
    ICharmhubClient,
    ReleaseFailedResponse,
    ReviewFailedResponse,
    UnauthorizedUploadResponse,
    UploadFailedResponse,
    UploadNotReviewedYetResponse,
)
from lp.charms.interfaces.charmrecipe import (
    CHARM_RECIPE_ALLOW_CREATE,
    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG,
)
from lp.charms.interfaces.charmrecipebuildjob import (
    ICharmhubUploadJob,
    ICharmRecipeBuildJob,
)
from lp.charms.model.charmrecipebuild import CharmRecipeBuild
from lp.charms.model.charmrecipebuildjob import (
    CharmhubUploadJob,
    CharmRecipeBuildJob,
    CharmRecipeBuildJobType,
)
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications


def run_isolated_jobs(jobs):
    """Run a sequence of jobs, ensuring transaction isolation.

    We abort the transaction after each job to make sure that there is no
    relevant uncommitted work.
    """
    for job in jobs:
        JobRunner([job]).runAll()
        transaction.abort()


# XXX cjwatson 2021-09-06: This approach makes it too easy to commit
# type-safety errors.  Perhaps we should fake the HTTP responses instead, or
# otherwise ensure that the signatures of the faked methods match the real
# ones?
@implementer(ICharmhubClient)
class FakeCharmhubClient:
    def __init__(self):
        self.uploadFile = FakeMethod()
        self.push = FakeMethod()
        self.checkStatus = FakeMethod()
        self.release = FakeMethod()


class FileUploaded(MatchesListwise):
    def __init__(self, filename):
        super().__init__(
            [
                MatchesListwise(
                    [
                        MatchesListwise(
                            [MatchesStructure.byEquality(filename=filename)]
                        ),
                        MatchesDict({}),
                    ]
                ),
            ]
        )


class TestCharmRecipeBuildJob(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CHARM_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CharmRecipeBuildJob` objects provide `ICharmRecipeBuildJob`.
        build = self.factory.makeCharmRecipeBuild()
        self.assertProvides(
            CharmRecipeBuildJob(
                build, CharmRecipeBuildJobType.CHARMHUB_UPLOAD, {}
            ),
            ICharmRecipeBuildJob,
        )


class TestCharmhubUploadJob(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.useFixture(
            FeatureFixture(
                {
                    CHARM_RECIPE_ALLOW_CREATE: "on",
                    CHARM_RECIPE_WEBHOOKS_FEATURE_FLAG: "on",
                }
            )
        )
        self.status_url = "/v1/charm/test-charm/revisions/review?upload-id=123"

    def test_provides_interface(self):
        # `CharmhubUploadJob` objects provide `ICharmhubUploadJob`.
        build = self.factory.makeCharmRecipeBuild()
        job = CharmhubUploadJob.create(build)
        self.assertProvides(job, ICharmhubUploadJob)

    def test___repr__(self):
        # `CharmhubUploadJob` objects have an informative __repr__.
        build = self.factory.makeCharmRecipeBuild()
        job = CharmhubUploadJob.create(build)
        self.assertEqual(
            "<CharmhubUploadJob for ~%s/%s/+charm/%s/+build/%d>"
            % (
                build.recipe.owner.name,
                build.recipe.project.name,
                build.recipe.name,
                build.id,
            ),
            repr(job),
        )

    def makeCharmRecipeBuild(self, **kwargs):
        # Make a build with a builder, some files, and a webhook.
        build = self.factory.makeCharmRecipeBuild(
            builder=self.factory.makeBuilder(), **kwargs
        )
        build.updateStatus(BuildStatus.FULLYBUILT)
        irrelevant_lfa = self.factory.makeLibraryFileAlias(
            filename="000-irrelevant.txt", content=b"irrelevant file"
        )
        self.factory.makeCharmFile(build=build, library_file=irrelevant_lfa)
        charm_lfa = self.factory.makeLibraryFileAlias(
            filename="test-charm.charm", content=b"dummy charm content"
        )
        self.factory.makeCharmFile(build=build, library_file=charm_lfa)
        self.factory.makeWebhook(
            target=build.recipe, event_types=["charm-recipe:build:0.1"]
        )
        return build

    def assertWebhookDeliveries(
        self, build, expected_store_upload_statuses, logger
    ):
        hook = build.recipe.webhooks.one()
        deliveries = list(hook.deliveries)
        deliveries.reverse()
        expected_payloads = [
            {
                "recipe_build": Equals(
                    canonical_url(build, force_local_path=True)
                ),
                "action": Equals("status-changed"),
                "recipe": Equals(
                    canonical_url(build.recipe, force_local_path=True)
                ),
                "build_request": Equals(
                    canonical_url(build.build_request, force_local_path=True)
                ),
                "status": Equals("Successfully built"),
                "store_upload_status": Equals(expected),
            }
            for expected in expected_store_upload_statuses
        ]
        matchers = [
            MatchesStructure(
                event_type=Equals("charm-recipe:build:0.1"),
                payload=MatchesDict(expected_payload),
            )
            for expected_payload in expected_payloads
        ]
        self.assertThat(deliveries, MatchesListwise(matchers))
        with dbuser(config.IWebhookDeliveryJobSource.dbuser):
            for delivery in deliveries:
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
                        for expected_payload in expected_payloads
                    ]
                ),
            )

    def test_run(self):
        # The job uploads the build to Charmhub and records the Charmhub
        # revision.
        logger = self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild()
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = 1
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([((build, 1), {})], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertEqual(1, job.store_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(build, ["Pending", "Uploaded"], logger)

    def test_run_failed(self):
        # A failed run sets the store upload status to FAILED.
        logger = self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild()
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.failure = ValueError("An upload failure")
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertIsNone(job.store_revision)
        self.assertEqual("An upload failure", job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            build, ["Pending", "Failed to upload"], logger
        )

    def test_run_unauthorized_notifies(self):
        # A run that gets 401 from Charmhub sends mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        project = self.factory.makeProduct(name="test-project")
        build = self.makeCharmRecipeBuild(
            requester=requester_team,
            name="test-charm",
            owner=requester_team,
            project=project,
        )
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 1
        client.uploadFile.failure = UnauthorizedUploadResponse(
            "Authorization failed."
        )
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertIsNone(job.store_revision)
        self.assertEqual("Authorization failed.", job.error_message)
        [notification] = pop_notifications()
        self.assertEqual(
            config.canonical.noreply_from_address, notification["From"]
        )
        self.assertEqual(
            "Requester <%s>" % requester.preferredemail.email,
            notification["To"],
        )
        subject = notification["Subject"].replace("\n ", " ")
        self.assertEqual(
            "Charmhub authorization failed for test-charm", subject
        )
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "charm-recipe-build-upload-unauthorized",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn(
            "http://launchpad.test/~requester-team/test-project/+charm/"
            "test-charm/+authorize",
            body,
        )
        self.assertEqual(
            "http://launchpad.test/~requester-team/test-project/+charm/"
            "test-charm/+build/%d\n"
            "Your team Requester Team is the requester of the build.\n"
            % build.id,
            footer,
        )
        self.assertWebhookDeliveries(
            build, ["Pending", "Failed to upload"], logger
        )

    def test_run_502_retries(self):
        # A run that gets a 502 error from Charmhub schedules itself to be
        # retried.
        logger = self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild()
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.WAITING, job.job.status)
        self.assertWebhookDeliveries(build, ["Pending"], logger)
        # Try again.  The upload part of the job is retried, and this time
        # it succeeds.
        job.scheduled_start = None
        client.uploadFile.calls = []
        client.uploadFile.failure = None
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = 1
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([((build, 1), {})], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertEqual(1, job.store_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)
        self.assertWebhookDeliveries(build, ["Pending", "Uploaded"], logger)

    def test_run_upload_failure_notifies(self):
        # A run that gets some other upload failure from Charmhub sends
        # mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        project = self.factory.makeProduct(name="test-project")
        build = self.makeCharmRecipeBuild(
            requester=requester_team,
            name="test-charm",
            owner=requester_team,
            project=project,
        )
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.failure = UploadFailedResponse(
            "Failed to upload", detail="The proxy exploded.\n"
        )
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertIsNone(job.store_revision)
        self.assertEqual("Failed to upload", job.error_message)
        [notification] = pop_notifications()
        self.assertEqual(
            config.canonical.noreply_from_address, notification["From"]
        )
        self.assertEqual(
            "Requester <%s>" % requester.preferredemail.email,
            notification["To"],
        )
        subject = notification["Subject"].replace("\n ", " ")
        self.assertEqual("Charmhub upload failed for test-charm", subject)
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "charm-recipe-build-upload-failed",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn("Failed to upload", body)
        build_url = (
            "http://launchpad.test/~requester-team/test-project/+charm/"
            "test-charm/+build/%d" % build.id
        )
        self.assertIn(build_url, body)
        self.assertEqual(
            "%s\nYour team Requester Team is the requester of the build.\n"
            % build_url,
            footer,
        )
        self.assertWebhookDeliveries(
            build, ["Pending", "Failed to upload"], logger
        )
        self.assertIn(
            ("error_detail", "The proxy exploded.\n"), job.getOopsVars()
        )

    def test_run_review_pending_retries(self):
        # A run that finds that Charmhub has not yet finished reviewing the
        # charm schedules itself to be retried.
        logger = self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild()
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 2
        client.push.result = self.status_url
        client.checkStatus.failure = UploadNotReviewedYetResponse()
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([((build, 2), {})], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.WAITING, job.job.status)
        self.assertWebhookDeliveries(build, ["Pending"], logger)
        # Try again.  The upload and push parts of the job are not retried,
        # and this time the review completes.
        job.scheduled_start = None
        client.uploadFile.calls = []
        client.push.calls = []
        client.checkStatus.calls = []
        client.checkStatus.failure = None
        client.checkStatus.result = 1
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertEqual([], client.uploadFile.calls)
        self.assertEqual([], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertEqual(1, job.store_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)
        self.assertWebhookDeliveries(build, ["Pending", "Uploaded"], logger)

    def test_run_review_failure_notifies(self):
        # A run that gets a review failure from Charmhub sends mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        project = self.factory.makeProduct(name="test-project")
        build = self.makeCharmRecipeBuild(
            requester=requester_team,
            name="test-charm",
            owner=requester_team,
            project=project,
        )
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 2
        client.push.result = self.status_url
        client.checkStatus.failure = ReviewFailedResponse(
            "Review failed.\nCharm is terrible."
        )
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([((build, 2), {})], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertIsNone(job.store_revision)
        self.assertEqual(
            "Review failed.\nCharm is terrible.", job.error_message
        )
        [notification] = pop_notifications()
        self.assertEqual(
            config.canonical.noreply_from_address, notification["From"]
        )
        self.assertEqual(
            "Requester <%s>" % requester.preferredemail.email,
            notification["To"],
        )
        subject = notification["Subject"].replace("\n ", " ")
        self.assertEqual(
            "Charmhub upload review failed for test-charm", subject
        )
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "charm-recipe-build-upload-review-failed",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn("Review failed.", body)
        self.assertEqual(
            "http://launchpad.test/~requester-team/test-project/+charm/"
            "test-charm/+build/%d\n"
            "Your team Requester Team is the requester of the build.\n"
            % build.id,
            footer,
        )
        self.assertWebhookDeliveries(
            build, ["Pending", "Failed to upload"], logger
        )

    def test_run_release(self):
        # A run configured to automatically release the charm to certain
        # channels does so.
        logger = self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild(store_channels=["stable", "edge"])
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = 1
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([((build, 1), {})], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([((build, 1), {})], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertEqual(1, job.store_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(build, ["Pending", "Uploaded"], logger)

    def test_run_release_failure_notifies(self):
        # A run configured to automatically release the charm to certain
        # channels but that fails to do so sends mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        project = self.factory.makeProduct(name="test-project")
        build = self.makeCharmRecipeBuild(
            requester=requester_team,
            name="test-charm",
            owner=requester_team,
            project=project,
            store_channels=["stable", "edge"],
        )
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = 1
        client.release.failure = ReleaseFailedResponse("Failed to release")
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            JobRunner([job]).runAll()
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-charm.charm")
        )
        self.assertEqual([((build, 1), {})], client.push.calls)
        self.assertEqual(
            [((build, self.status_url), {})], client.checkStatus.calls
        )
        self.assertEqual([((build, 1), {})], client.release.calls)
        self.assertContentEqual([job], build.store_upload_jobs)
        self.assertEqual(1, job.store_revision)
        self.assertEqual("Failed to release", job.error_message)
        [notification] = pop_notifications()
        self.assertEqual(
            config.canonical.noreply_from_address, notification["From"]
        )
        self.assertEqual(
            "Requester <%s>" % requester.preferredemail.email,
            notification["To"],
        )
        subject = notification["Subject"].replace("\n", " ")
        self.assertEqual("Charmhub release failed for test-charm", subject)
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "charm-recipe-build-release-failed",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn("Failed to release", body)
        self.assertEqual(
            "http://launchpad.test/~requester-team/test-project/+charm/"
            "test-charm/+build/%d\n"
            "Your team Requester Team is the requester of the build.\n"
            % build.id,
            footer,
        )
        self.assertWebhookDeliveries(
            build, ["Pending", "Failed to release to channels"], logger
        )

    def test_retry_delay(self):
        # The job is retried every minute, unless it just made one of its
        # first four attempts to poll the status endpoint, in which case the
        # delays are 15/15/30/30 seconds.
        self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild()
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertNotIn("upload_id", job.store_metadata)
        self.assertEqual(timedelta(seconds=60), job.retry_delay)
        job.scheduled_start = None
        client.uploadFile.failure = None
        client.uploadFile.result = 1
        client.push.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertIn("upload_id", job.build.store_upload_metadata)
        self.assertNotIn("status_url", job.store_metadata)
        self.assertEqual(timedelta(seconds=60), job.retry_delay)
        job.scheduled_start = None
        client.push.failure = None
        client.push.result = self.status_url
        client.checkStatus.failure = UploadNotReviewedYetResponse()
        for expected_delay in (15, 15, 30, 30, 60):
            with dbuser(config.ICharmhubUploadJobSource.dbuser):
                run_isolated_jobs([job])
            self.assertIn("status_url", job.build.store_upload_metadata)
            self.assertEqual(
                timedelta(seconds=expected_delay), job.retry_delay
            )
            job.scheduled_start = None
        client.checkStatus.failure = None
        client.checkStatus.result = 1
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)

    def test_retry_after_upload_does_not_upload(self):
        # If the job has uploaded but failed to push, it should not attempt
        # to upload again on the next run.
        self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild(store_channels=["stable", "edge"])
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 1
        client.push.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # We performed the upload as expected, but the store failed to release
        # it.
        self.assertIsNone(job.store_revision)
        self.assertEqual(timedelta(seconds=60), job.retry_delay)
        self.assertEqual(1, len(client.uploadFile.calls))
        self.assertIsNone(job.error_message)

        # Run the job again.
        client.uploadFile.calls = []
        client.push.calls = []
        client.push.failure = None
        client.push.result = self.status_url
        client.checkStatus.result = 1
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # The push has now succeeded.  Make sure that we didn't try to
        # upload the file again first.
        self.assertEqual(1, job.store_revision)
        self.assertEqual([], client.uploadFile.calls)
        self.assertEqual(1, len(client.push.calls))
        self.assertIsNone(job.error_message)

    def test_retry_after_push_does_not_upload_or_push(self):
        # If the job has uploaded and pushed but has not yet been reviewed,
        # it should not attempt to upload or push again on the next run.
        self.useFixture(FakeLogger())
        build = self.makeCharmRecipeBuild(store_channels=["stable", "edge"])
        self.assertContentEqual([], build.store_upload_jobs)
        job = CharmhubUploadJob.create(build)
        client = FakeCharmhubClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.failure = UploadNotReviewedYetResponse()
        self.useFixture(ZopeUtilityFixture(client, ICharmhubClient))
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # We performed the upload as expected, but the store is still
        # reviewing it.
        self.assertIsNone(job.store_revision)
        self.assertEqual(timedelta(seconds=15), job.retry_delay)
        self.assertEqual(1, len(client.uploadFile.calls))
        self.assertIsNone(job.error_message)

        # Run the job again.
        client.uploadFile.calls = []
        client.push.calls = []
        client.checkStatus.calls = []
        client.checkStatus.failure = None
        client.checkStatus.result = 1
        with dbuser(config.ICharmhubUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # The store has now reviewed the upload.  Make sure that we didn't
        # try to upload or push it again first.
        self.assertEqual(1, job.store_revision)
        self.assertEqual([], client.uploadFile.calls)
        self.assertEqual([], client.push.calls)
        self.assertEqual(1, len(client.checkStatus.calls))
        self.assertIsNone(job.error_message)

    def test_with_build_metadata_as_none(self):
        db_build = self.factory.makeCharmRecipeBuild()
        removeSecurityProxy(db_build).store_upload_metadata = None
        store = IStore(CharmRecipeBuild)
        store.flush()
        loaded_build = store.find(CharmRecipeBuild, id=db_build.id).one()

        job = CharmhubUploadJob.create(loaded_build)
        self.assertEqual({}, job.store_metadata)

    def test_with_build_metadata_as_none_set_status(self):
        db_build = self.factory.makeCharmRecipeBuild()
        removeSecurityProxy(db_build).store_upload_metadata = None
        store = IStore(CharmRecipeBuild)
        store.flush()
        loaded_build = store.find(CharmRecipeBuild, id=db_build.id).one()

        job = CharmhubUploadJob.create(loaded_build)
        job.status_url = "http://example.org"
        store.flush()

        loaded_build = store.find(CharmRecipeBuild, id=db_build.id).one()
        self.assertEqual(
            "http://example.org",
            loaded_build.store_upload_metadata["status_url"],
        )
