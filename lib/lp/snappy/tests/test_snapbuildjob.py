# Copyright 2016-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for snap build jobs."""

from datetime import timedelta

import transaction
from fixtures import FakeLogger
from testtools.matchers import (
    Equals,
    Is,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
)
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.code.tests.helpers import BranchHostingFixture
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.snappy.interfaces.snapbuildjob import (
    ISnapBuildJob,
    ISnapStoreUploadJob,
)
from lp.snappy.interfaces.snapstoreclient import (
    BadRefreshResponse,
    ISnapStoreClient,
    ScanFailedResponse,
    UnauthorizedUploadResponse,
    UploadFailedResponse,
    UploadNotScannedYetResponse,
)
from lp.snappy.model.snapbuild import SnapBuild
from lp.snappy.model.snapbuildjob import (
    SnapBuildJob,
    SnapBuildJobType,
    SnapStoreUploadJob,
)
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


class FakeMethodWithMaxCalls(FakeMethod):
    """Method that throws error after a given number of calls"""

    def __init__(self, max_calls=-1):
        self.max_calls = max_calls
        super().__init__(result=1, failure=None)

    def __call__(self, *args, **kwargs):
        if self.call_count == self.max_calls:
            self.failure = UploadFailedResponse("Proxy error", can_retry=True)
            self.result = None
        else:
            self.result = 1
            self.failure = None
        return super().__call__(*args, **kwargs)


@implementer(ISnapStoreClient)
class FakeSnapStoreClient:
    def __init__(self, max_calls=-1):
        if max_calls >= 0:
            self.uploadFile = FakeMethodWithMaxCalls(max_calls)
        else:
            self.uploadFile = FakeMethod()
        self.push = FakeMethod()
        self.checkStatus = FakeMethod()


class FileUploaded(MatchesListwise):
    def __init__(self, filename):
        super().__init__(
            [
                MatchesListwise(
                    [
                        MatchesListwise(
                            [
                                MatchesStructure.byEquality(filename=filename),
                            ]
                        ),
                        MatchesDict({}),
                    ]
                ),
            ]
        )


class TestSnapBuildJob(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_provides_interface(self):
        # `SnapBuildJob` objects provide `ISnapBuildJob`.
        snapbuild = self.factory.makeSnapBuild()
        self.assertProvides(
            SnapBuildJob(snapbuild, SnapBuildJobType.STORE_UPLOAD, {}),
            ISnapBuildJob,
        )


class TestSnapStoreUploadJob(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.status_url = "http://sca.example/dev/api/snaps/1/builds/1/status"
        self.store_url = "http://sca.example/dev/click-apps/1/rev/1/"

    def test_provides_interface(self):
        # `SnapStoreUploadJob` objects provide `ISnapStoreUploadJob`.
        snapbuild = self.factory.makeSnapBuild()
        job = SnapStoreUploadJob.create(snapbuild)
        self.assertProvides(job, ISnapStoreUploadJob)

    def test___repr__(self):
        # `SnapStoreUploadJob` objects have an informative __repr__.
        snapbuild = self.factory.makeSnapBuild()
        job = SnapStoreUploadJob.create(snapbuild)
        self.assertEqual(
            "<SnapStoreUploadJob for ~%s/+snap/%s/+build/%d>"
            % (snapbuild.snap.owner.name, snapbuild.snap.name, snapbuild.id),
            repr(job),
        )

    def makeSnapBuild(self, **kwargs):
        # Make a build with a builder, a file, and a webhook.
        snapbuild = self.factory.makeSnapBuild(
            builder=self.factory.makeBuilder(), **kwargs
        )
        snapbuild.updateStatus(BuildStatus.FULLYBUILT)
        irrelevant_lfa = self.factory.makeLibraryFileAlias(
            filename="000-irrelevant.txt", content=b"irrelevant file"
        )
        self.factory.makeSnapFile(
            snapbuild=snapbuild, libraryfile=irrelevant_lfa
        )
        snap_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap.snap", content=b"dummy snap content"
        )
        self.factory.makeSnapFile(snapbuild=snapbuild, libraryfile=snap_lfa)
        self.factory.makeWebhook(
            target=snapbuild.snap, event_types=["snap:build:0.1"]
        )
        return snapbuild

    def makeSnapBuildWithComponents(self, num_components):
        # Make a build with a builder, components, and a webhook.
        snapcraft_yaml = """
        name : test-snap,
        components:
        """
        branch = self.factory.makeBranch()
        snap = self.factory.makeSnap(store_name="test-snap", branch=branch)
        snapbuild = self.factory.makeSnapBuild(
            snap=snap, builder=self.factory.makeBuilder()
        )
        snapbuild.updateStatus(BuildStatus.FULLYBUILT)
        snap_lfa = self.factory.makeLibraryFileAlias(
            filename="test-snap_0_all.snap", content=b"dummy snap content"
        )
        for i in range(num_components):
            self.factory.makeSnapFile(
                snapbuild=snapbuild, libraryfile=snap_lfa
            )
            component_lfa = self.factory.makeLibraryFileAlias(
                filename="test-snap+somecomponent%s_0.comp" % i,
                content=b"component",
            )
            self.factory.makeSnapFile(
                snapbuild=snapbuild, libraryfile=component_lfa
            )
            snapcraft_yaml += (
                """
                somecomponent%s:
                    description: test
            """
                % i
            )
        self.useFixture(
            BranchHostingFixture(
                blob=bytes(snapcraft_yaml, "utf-8"),
            )
        )
        self.factory.makeWebhook(
            target=snapbuild.snap, event_types=["snap:build:0.1"]
        )
        return snapbuild

    def assertWebhookDeliveries(
        self, snapbuild, expected_store_upload_statuses, logger
    ):
        hook = snapbuild.snap.webhooks.one()
        deliveries = list(hook.deliveries)
        deliveries.reverse()
        expected_payloads = [
            {
                "snap_build": Equals(
                    canonical_url(snapbuild, force_local_path=True)
                ),
                "action": Equals("status-changed"),
                "snap": Equals(
                    canonical_url(snapbuild.snap, force_local_path=True)
                ),
                "build_request": Is(None),
                "status": Equals("Successfully built"),
                "store_upload_status": Equals(expected),
            }
            for expected in expected_store_upload_statuses
        ]
        matchers = [
            MatchesStructure(
                event_type=Equals("snap:build:0.1"),
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
                        (hook, "snap:build:0.1", MatchesDict(expected_payload))
                        for expected_payload in expected_payloads
                    ]
                ),
            )

    def test_run(self):
        # The job uploads the build to the store and records the store URL
        # and revision.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 1, {}), {})], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_with_component(self):
        # The job uploads the build to the storage with its component
        # and then pushes it to the store and records the store URL
        # and revision.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuildWithComponents(1)
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # Check if uploadFile is called for snap and its component.
        self.assertThat(
            [client.uploadFile.calls[0]], FileUploaded("test-snap_0_all.snap")
        )
        self.assertThat(
            [client.uploadFile.calls[1]],
            FileUploaded("test-snap+somecomponent0_0.comp"),
        )
        self.assertEqual(
            [((snapbuild, 1, {"somecomponent0": 1}), {})],
            client.push.calls,
        )
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_with_multiple_components(self):
        # The job uploads the build to the storage with its components
        # and then pushes it to the store and records the store URL
        # and revision.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuildWithComponents(2)
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # Check if uploadFile is called for snap and its components.
        self.assertThat(
            [client.uploadFile.calls[0]], FileUploaded("test-snap_0_all.snap")
        )
        self.assertThat(
            [client.uploadFile.calls[1]],
            FileUploaded("test-snap+somecomponent0_0.comp"),
        )
        self.assertThat(
            [client.uploadFile.calls[2]],
            FileUploaded("test-snap+somecomponent1_0.comp"),
        )
        self.assertEqual(
            [
                (
                    (
                        snapbuild,
                        1,
                        {
                            "somecomponent0": 1,
                            "somecomponent1": 1,
                        },
                    ),
                    {},
                )
            ],
            client.push.calls,
        )
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertIn(
            "[SnapStoreUploadJob] Pushing build snap-name-100030 with id 1.",
            logger.output,
        )
        self.assertIn(
            "[SnapStoreUploadJob] "
            "Components: {'somecomponent0': 1, 'somecomponent1': 1}",
            logger.output,
        )

        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_failed(self):
        # A failed run sets the store upload status to FAILED.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.failure = ValueError("An upload failure")
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertEqual("An upload failure", job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Failed to upload"], logger
        )

    def test_run_unauthorized_notifies(self):
        # A run that gets 401 from the store sends mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        snapbuild = self.makeSnapBuild(
            requester=requester_team, name="test-snap", owner=requester_team
        )
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.failure = UnauthorizedUploadResponse(
            "Authorization failed."
        )
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 1, {}), {})], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
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
        self.assertEqual("Store authorization failed for test-snap", subject)
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "snap-build-upload-unauthorized",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn(
            "http://launchpad.test/~requester-team/+snap/test-snap/+authorize",
            body,
        )
        self.assertEqual(
            "http://launchpad.test/~requester-team/+snap/test-snap/+build/%d\n"
            "Your team Requester Team is the requester of the build.\n"
            % snapbuild.id,
            footer,
        )
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Failed to upload"], logger
        )

    def test_run_502_retries_with_components(self):
        # A run that gets a 502 error from the store schedules itself to be
        # retried.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuildWithComponents(2)
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)

        # The error raises on the third uploadFile call.
        client = FakeSnapStoreClient(2)
        client.uploadFile.result = 1
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            [client.uploadFile.calls[0]], FileUploaded("test-snap_0_all.snap")
        )
        self.assertThat(
            [client.uploadFile.calls[1]],
            FileUploaded("test-snap+somecomponent0_0.comp"),
        )
        self.assertThat(
            [client.uploadFile.calls[2]],
            FileUploaded("test-snap+somecomponent1_0.comp"),
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)

        # Component upload is incomplete.
        self.assertEqual(
            {
                "somecomponent0": 1,
                "somecomponent1": None,
            },
            job.components_ids,
        )
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.WAITING, job.job.status)
        self.assertWebhookDeliveries(snapbuild, ["Pending"], logger)

        # Try again.  The upload part of the job is retried, and this time
        # it succeeds.
        job.scheduled_start = None
        client.uploadFile.max_calls = -1
        client.uploadFile.failure = None
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # The last call should contains just the component that failed.
        self.assertEqual(len(client.uploadFile.calls), 4)
        self.assertThat(
            [client.uploadFile.calls[3]],
            FileUploaded("test-snap+somecomponent1_0.comp"),
        )

        self.assertEqual(
            {
                "somecomponent0": 1,
                "somecomponent1": 1,
            },
            job.components_ids,
        )

        # After that the snap is uploaded to the store.
        self.assertEqual(
            [
                (
                    (
                        snapbuild,
                        1,
                        {
                            "somecomponent0": 1,
                            "somecomponent1": 1,
                        },
                    ),
                    {},
                )
            ],
            client.push.calls,
        )
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_502_retries(self):
        # A run that gets a 502 error from the store schedules itself to be
        # retried.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.WAITING, job.job.status)
        self.assertWebhookDeliveries(snapbuild, ["Pending"], logger)
        # Try again.  The upload part of the job is retried, and this time
        # it succeeds.
        job.scheduled_start = None
        client.uploadFile.calls = []
        client.uploadFile.failure = None
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 1, {}), {})], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_refresh_failure_notifies(self):
        # A run that gets a failure when trying to refresh macaroons sends
        # mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        snapbuild = self.makeSnapBuild(
            requester=requester_team, name="test-snap", owner=requester_team
        )
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.failure = BadRefreshResponse("SSO melted.")
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 1, {}), {})], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertEqual("SSO melted.", job.error_message)
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
            "Refreshing store authorization failed for test-snap", subject
        )
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "snap-build-upload-refresh-failed",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn(
            "http://launchpad.test/~requester-team/+snap/test-snap/+authorize",
            body,
        )
        self.assertEqual(
            "http://launchpad.test/~requester-team/+snap/test-snap/+build/%d\n"
            "Your team Requester Team is the requester of the build.\n"
            % snapbuild.id,
            footer,
        )
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Failed to upload"], logger
        )

    def test_run_upload_failure_notifies(self):
        # A run that gets some other upload failure from the store sends
        # mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        snapbuild = self.makeSnapBuild(
            requester=requester_team, name="test-snap", owner=requester_team
        )
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.failure = UploadFailedResponse(
            "Failed to upload", detail="The proxy exploded.\n"
        )
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([], client.push.calls)
        self.assertEqual([], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
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
        self.assertEqual("Store upload failed for test-snap", subject)
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "snap-build-upload-failed",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn("Failed to upload", body)
        build_url = (
            "http://launchpad.test/~requester-team/+snap/test-snap/+build/%d"
            % snapbuild.id
        )
        self.assertIn(build_url, body)
        self.assertEqual(
            "%s\nYour team Requester Team is the requester of the build.\n"
            % build_url,
            footer,
        )
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Failed to upload"], logger
        )
        self.assertIn(
            ("error_detail", "The proxy exploded.\n"), job.getOopsVars()
        )

    def test_run_scan_pending_retries(self):
        # A run that finds that the store has not yet finished scanning the
        # package schedules itself to be retried.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 2
        client.push.result = self.status_url
        client.checkStatus.failure = UploadNotScannedYetResponse()
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 2, {}), {})], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.WAITING, job.job.status)
        self.assertWebhookDeliveries(snapbuild, ["Pending"], logger)
        # Try again.  The upload and push parts of the job are not retried,
        # and this time the scan completes.
        job.scheduled_start = None
        client.uploadFile.calls = []
        client.push.calls = []
        client.checkStatus.calls = []
        client.checkStatus.failure = None
        client.checkStatus.result = (self.store_url, 1)
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertEqual([], client.uploadFile.calls)
        self.assertEqual([], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_scan_failure_notifies(self):
        # A run that gets a scan failure from the store sends mail.
        logger = self.useFixture(FakeLogger())
        requester = self.factory.makePerson(name="requester")
        requester_team = self.factory.makeTeam(
            owner=requester, name="requester-team", members=[requester]
        )
        snapbuild = self.makeSnapBuild(
            requester=requester_team, name="test-snap", owner=requester_team
        )
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 2
        client.push.result = self.status_url
        client.checkStatus.failure = ScanFailedResponse(
            "Scan failed.\nConfinement not allowed.",
            messages=[
                {"message": "Scan failed.", "link": "link1"},
                {"message": "Confinement not allowed.", "link": "link2"},
            ],
        )
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 2, {}), {})], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertEqual(
            "Scan failed.\nConfinement not allowed.", job.error_message
        )
        self.assertEqual(
            [
                {"message": "Scan failed.", "link": "link1"},
                {"message": "Confinement not allowed.", "link": "link2"},
            ],
            job.error_messages,
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
        self.assertEqual("Store upload scan failed for test-snap", subject)
        self.assertEqual(
            "Requester @requester-team",
            notification["X-Launchpad-Message-Rationale"],
        )
        self.assertEqual(
            requester_team.name, notification["X-Launchpad-Message-For"]
        )
        self.assertEqual(
            "snap-build-upload-scan-failed",
            notification["X-Launchpad-Notification-Type"],
        )
        body, footer = (
            notification.get_payload(decode=True).decode().split("\n-- \n")
        )
        self.assertIn("Scan failed.", body)
        self.assertEqual(
            "http://launchpad.test/~requester-team/+snap/test-snap/+build/%d\n"
            "Your team Requester Team is the requester of the build.\n"
            % snapbuild.id,
            footer,
        )
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Failed to upload"], logger
        )

    def test_run_scan_review_queued(self):
        # A run that finds that the store has queued the package behind
        # others for manual review completes, but without recording a store
        # URL or revision.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (None, None)
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 1, {}), {})], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_run_release(self):
        # A run configured to automatically release the package to certain
        # channels does so.
        logger = self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild(store_channels=["stable", "edge"])
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertThat(
            client.uploadFile.calls, FileUploaded("test-snap.snap")
        )
        self.assertEqual([((snapbuild, 1, {}), {})], client.push.calls)
        self.assertEqual([((self.status_url,), {})], client.checkStatus.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual(1, snapbuild.store_upload_revision)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            snapbuild, ["Pending", "Uploaded"], logger
        )

    def test_retry_delay(self):
        # The job is retried every minute, unless it just made one of its
        # first four attempts to poll the status endpoint, in which case the
        # delays are 15/15/30/30 seconds.
        self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild()
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertNotIn("upload_id", job.store_metadata)
        self.assertEqual(timedelta(seconds=60), job.retry_delay)
        job.scheduled_start = None
        client.uploadFile.failure = None
        client.uploadFile.result = 1
        client.push.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertIn("upload_id", job.snapbuild.store_upload_metadata)
        self.assertNotIn("status_url", job.store_metadata)
        self.assertEqual(timedelta(seconds=60), job.retry_delay)
        job.scheduled_start = None
        client.push.failure = None
        client.push.result = self.status_url
        client.checkStatus.failure = UploadNotScannedYetResponse()
        for expected_delay in (15, 15, 30, 30, 60):
            with dbuser(config.ISnapStoreUploadJobSource.dbuser):
                run_isolated_jobs([job])
            self.assertIn("status_url", job.snapbuild.store_upload_metadata)
            self.assertIsNone(job.store_url)
            self.assertEqual(
                timedelta(seconds=expected_delay), job.retry_delay
            )
            job.scheduled_start = None
        client.checkStatus.failure = None
        client.checkStatus.result = (self.store_url, 1)
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertEqual(self.store_url, job.store_url)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertEqual(JobStatus.COMPLETED, job.job.status)

    def test_retry_after_upload_does_not_upload(self):
        # If the job has uploaded but failed to push, it should not attempt
        # to upload again on the next run.
        self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild(store_channels=["stable", "edge"])
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.failure = UploadFailedResponse(
            "Proxy error", can_retry=True
        )
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # We performed the upload as expected, but the push failed.
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertEqual(timedelta(seconds=60), job.retry_delay)
        self.assertEqual(1, len(client.uploadFile.calls))
        self.assertIsNone(job.error_message)

        # Run the job again.
        client.uploadFile.calls = []
        client.push.calls = []
        client.push.failure = None
        client.push.result = self.status_url
        client.checkStatus.result = (self.store_url, 1)
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # The push has now succeeded.  Make sure that we didn't try to
        # upload the file again first.
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual([], client.uploadFile.calls)
        self.assertEqual(1, len(client.push.calls))
        self.assertIsNone(job.error_message)

    def test_retry_after_push_does_not_upload_or_push(self):
        # If the job has uploaded and pushed but has not yet been scanned,
        # it should not attempt to upload or push again on the next run.
        self.useFixture(FakeLogger())
        snapbuild = self.makeSnapBuild(store_channels=["stable", "edge"])
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.uploadFile.result = 1
        client.push.result = self.status_url
        client.checkStatus.failure = UploadNotScannedYetResponse()
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # We performed the upload and push as expected, but the store is
        # still scanning it.
        self.assertIsNone(job.store_url)
        self.assertIsNone(job.store_revision)
        self.assertIsNone(snapbuild.store_upload_revision)
        self.assertEqual(timedelta(seconds=15), job.retry_delay)
        self.assertEqual(1, len(client.uploadFile.calls))
        self.assertEqual(1, len(client.push.calls))
        self.assertIsNone(job.error_message)

        # Run the job again.
        client.uploadFile.calls = []
        client.push.calls = []
        client.checkStatus.calls = []
        client.checkStatus.failure = None
        client.checkStatus.result = (self.store_url, 1)
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            run_isolated_jobs([job])

        # The store has now scanned the upload.  Make sure that we didn't
        # try to upload or push it again first.
        self.assertEqual(self.store_url, job.store_url)
        self.assertEqual(1, job.store_revision)
        self.assertEqual([], client.uploadFile.calls)
        self.assertEqual([], client.push.calls)
        self.assertEqual(1, len(client.checkStatus.calls))
        self.assertIsNone(job.error_message)

    def test_with_snapbuild_metadata_as_none(self):
        db_build = self.factory.makeSnapBuild()
        unsecure_db_build = removeSecurityProxy(db_build)
        unsecure_db_build.store_upload_metadata = None
        store = IStore(SnapBuild)
        store.flush()
        loaded_build = store.find(SnapBuild, id=unsecure_db_build.id).one()

        job = SnapStoreUploadJob.create(loaded_build)
        self.assertEqual({}, job.store_metadata)

    def test_with_snapbuild_metadata_as_none_set_status(self):
        db_build = self.factory.makeSnapBuild()
        unsecure_db_build = removeSecurityProxy(db_build)
        unsecure_db_build.store_upload_metadata = None
        store = IStore(SnapBuild)
        store.flush()
        loaded_build = store.find(SnapBuild, id=unsecure_db_build.id).one()

        job = SnapStoreUploadJob.create(loaded_build)
        job.status_url = "http://example.org"
        store.flush()

        loaded_build = store.find(SnapBuild, id=unsecure_db_build.id).one()
        self.assertEqual(
            "http://example.org",
            loaded_build.store_upload_metadata["status_url"],
        )
