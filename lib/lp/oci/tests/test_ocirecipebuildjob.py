# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipeBuildJob tests"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from fixtures import FakeLogger
from testtools.matchers import (
    Equals,
    MatchesDict,
    MatchesListwise,
    MatchesStructure,
    )
import transaction
from zope.interface import implementer

from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipe import (
    OCI_RECIPE_ALLOW_CREATE,
    OCI_RECIPE_WEBHOOKS_FEATURE_FLAG,
    )
from lp.oci.interfaces.ocirecipebuildjob import (
    IOCIRecipeBuildJob,
    IOCIRegistryUploadJob,
    IOCIRegistryUploadJobSource,
    )
from lp.oci.interfaces.ociregistryclient import IOCIRegistryClient
from lp.oci.model.ocirecipebuildjob import (
    OCIRecipeBuildJob,
    OCIRecipeBuildJobDerived,
    OCIRecipeBuildJobType,
    OCIRegistryUploadJob,
    )
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.job.runner import JobRunner
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.testing.mail_helpers import pop_notifications
from lp.services.webapp import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks


def run_isolated_jobs(jobs):
    """Run a sequence of jobs, ensuring transaction isolation.

    We abort the transaction after each job to make sure that there is no
    relevant uncommitted work.
    """
    for job in jobs:
        JobRunner([job]).runAll()
        transaction.abort()


@implementer(IOCIRegistryClient)
class FakeRegistryClient:

    def __init__(self):
        self.upload = FakeMethod()


class FakeOCIBuildJob(OCIRecipeBuildJobDerived):
    """For testing OCIRecipeBuildJobDerived without a child class."""


class TestOCIRecipeBuildJob(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeBuildJob, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

    def test_provides_interface(self):
        oci_build = self.factory.makeOCIRecipeBuild()
        self.assertProvides(
            OCIRecipeBuildJob(
                oci_build, OCIRecipeBuildJobType.REGISTRY_UPLOAD, {}),
            IOCIRecipeBuildJob)

    def test_getOopsVars(self):
        oci_build = self.factory.makeOCIRecipeBuild()
        build_job = OCIRecipeBuildJob(
                oci_build, OCIRecipeBuildJobType.REGISTRY_UPLOAD, {})
        derived = FakeOCIBuildJob(build_job)
        oops = derived.getOopsVars()
        expected = [
            ('job_id', build_job.job.id),
            ('job_type', build_job.job_type.title),
            ('build_id', oci_build.id),
            ('recipe_owner_id', oci_build.recipe.owner.id),
            ('oci_project_name', oci_build.recipe.oci_project.name),
            ]
        self.assertEqual(expected, oops)


class TestOCIRegistryUploadJob(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRegistryUploadJob, self).setUp()
        self.useFixture(FeatureFixture({
            'webhooks.new.enabled': 'true',
            OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: 'on',
            OCI_RECIPE_ALLOW_CREATE: 'on'
            }))

    def makeOCIRecipeBuild(self, **kwargs):
        ocibuild = self.factory.makeOCIRecipeBuild(
            builder=self.factory.makeBuilder(), **kwargs)
        ocibuild.updateStatus(BuildStatus.FULLYBUILT)
        self.factory.makeWebhook(
            target=ocibuild.recipe, event_types=["oci-recipe:build:0.1"])
        return ocibuild

    def assertWebhookDeliveries(self, ocibuild,
                                expected_registry_upload_statuses, logger):
        hook = ocibuild.recipe.webhooks.one()
        deliveries = list(hook.deliveries)
        deliveries.reverse()
        expected_payloads = [{
            "recipe_build": Equals(
                canonical_url(ocibuild, force_local_path=True)),
            "action": Equals("created"),
            "recipe": Equals(
                canonical_url(ocibuild.recipe, force_local_path=True)),
            "status": Equals("Successfully built"),
            "registry_upload_status": Equals("Pending")}]
        expected_payloads += [{
            "recipe_build": Equals(
                canonical_url(ocibuild, force_local_path=True)),
            "action": Equals("status-changed"),
            "recipe": Equals(
                canonical_url(ocibuild.recipe, force_local_path=True)),
            "status": Equals("Successfully built"),
            "registry_upload_status": Equals(expected),
            } for expected in expected_registry_upload_statuses]
        matchers = [
            MatchesStructure(
                event_type=Equals("oci-recipe:build:0.1"),
                payload=MatchesDict(expected_payload))
            for expected_payload in expected_payloads]
        self.assertThat(deliveries, MatchesListwise(matchers))
        with dbuser(config.IWebhookDeliveryJobSource.dbuser):
            for delivery in deliveries:
                self.assertEqual(
                    "<WebhookDeliveryJob for webhook %d on %r>" % (
                        hook.id, hook.target),
                    repr(delivery))
            self.assertThat(
                logger.output, LogsScheduledWebhooks([
                    (hook, "oci-recipe:build:0.1", MatchesDict(
                        expected_payload))
                    for expected_payload in expected_payloads]))

    def test_provides_interface(self):
        # `OCIRegistryUploadJob` objects provide `IOCIRegistryUploadJob`.
        ocibuild = self.factory.makeOCIRecipeBuild()
        job = OCIRegistryUploadJob.create(ocibuild)
        self.assertProvides(job, IOCIRegistryUploadJob)

    def test_run(self):
        logger = self.useFixture(FakeLogger())
        ocibuild = self.makeOCIRecipeBuild()
        self.assertContentEqual([], ocibuild.registry_upload_jobs)
        job = OCIRegistryUploadJob.create(ocibuild)
        client = FakeRegistryClient()
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))
        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertEqual([((ocibuild,), {})], client.upload.calls)
        self.assertContentEqual([job], ocibuild.registry_upload_jobs)
        self.assertIsNone(job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            ocibuild, ["Uploaded"], logger)

    def test_run_failed(self):
        # A failed run sets the registry upload status to FAILED.
        logger = self.useFixture(FakeLogger())
        ocibuild = self.makeOCIRecipeBuild()
        self.assertContentEqual([], ocibuild.registry_upload_jobs)
        job = OCIRegistryUploadJob.create(ocibuild)
        client = FakeRegistryClient()
        client.upload.failure = ValueError("An upload failure")
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))
        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertEqual([((ocibuild,), {})], client.upload.calls)
        self.assertContentEqual([job], ocibuild.registry_upload_jobs)
        self.assertEqual("An upload failure", job.error_message)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            ocibuild, ["Failed to upload"], logger)
