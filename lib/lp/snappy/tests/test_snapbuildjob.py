# Copyright 2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for snap build jobs."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from zope.interface import implementer

from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.job.runner import JobRunner
from lp.snappy.interfaces.snap import SNAP_TESTING_FLAGS
from lp.snappy.interfaces.snapbuildjob import (
    ISnapBuildJob,
    ISnapStoreUploadJob,
    )
from lp.snappy.interfaces.snapstoreclient import (
    ISnapStoreClient,
    UnauthorizedUploadResponse,
    )
from lp.snappy.model.snapbuildjob import (
    SnapBuildJob,
    SnapBuildJobType,
    SnapStoreUploadJob,
    )
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.testing.mail_helpers import pop_notifications


@implementer(ISnapStoreClient)
class FakeSnapStoreClient:

    def __init__(self):
        self.upload = FakeMethod()


class TestSnapBuildJob(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestSnapBuildJob, self).setUp()
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))

    def test_provides_interface(self):
        # `SnapBuildJob` objects provide `ISnapBuildJob`.
        snapbuild = self.factory.makeSnapBuild()
        self.assertProvides(
            SnapBuildJob(snapbuild, SnapBuildJobType.STORE_UPLOAD, {}),
            ISnapBuildJob)


class TestSnapStoreUploadJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestSnapStoreUploadJob, self).setUp()
        self.useFixture(FeatureFixture(SNAP_TESTING_FLAGS))

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
            "<SnapStoreUploadJob for %s>" % snapbuild.title, repr(job))

    def test_run(self):
        # The job uploads the build to the store.
        snapbuild = self.factory.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            JobRunner([job]).runAll()
        self.assertEqual([((snapbuild,), {})], client.upload.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())

    def test_run_failed(self):
        # A failed run sets the store upload status to FAILED.
        snapbuild = self.factory.makeSnapBuild()
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.upload.failure = ValueError("An upload failure")
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            JobRunner([job]).runAll()
        self.assertEqual([((snapbuild,), {})], client.upload.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual("An upload failure", job.error_message)
        self.assertEqual([], pop_notifications())

    def test_run_unauthorized_notifies(self):
        # A run that gets 401 from the store sends mail.
        requester = self.factory.makePerson(name="requester")
        snapbuild = self.factory.makeSnapBuild(
            requester=requester, name="test-snap", owner=requester)
        self.assertContentEqual([], snapbuild.store_upload_jobs)
        job = SnapStoreUploadJob.create(snapbuild)
        client = FakeSnapStoreClient()
        client.upload.failure = UnauthorizedUploadResponse(
            "Authorization failed.")
        self.useFixture(ZopeUtilityFixture(client, ISnapStoreClient))
        with dbuser(config.ISnapStoreUploadJobSource.dbuser):
            JobRunner([job]).runAll()
        self.assertEqual([((snapbuild,), {})], client.upload.calls)
        self.assertContentEqual([job], snapbuild.store_upload_jobs)
        self.assertEqual("Authorization failed.", job.error_message)
        [notification] = pop_notifications()
        self.assertEqual(
            config.canonical.noreply_from_address, notification["From"])
        self.assertEqual(
            "Requester <%s>" % requester.preferredemail.email,
            notification["To"])
        subject = notification["Subject"].replace("\n ", " ")
        self.assertEqual("Store authorization failed for test-snap", subject)
        self.assertEqual(
            "Requester", notification["X-Launchpad-Message-Rationale"])
        self.assertEqual(
            requester.name, notification["X-Launchpad-Message-For"])
        self.assertEqual(
            "snap-build-upload-unauthorized",
            notification["X-Launchpad-Notification-Type"])
        body, footer = notification.get_payload(decode=True).split("\n-- \n")
        self.assertIn(
            "http://launchpad.dev/~requester/+snap/test-snap/+authorize", body)
        self.assertEqual(
            "http://launchpad.dev/~requester/+snap/test-snap/+build/%d\n"
            "You are the requester of the build.\n" % snapbuild.id, footer)