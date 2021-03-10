# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipeBuildJob tests"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import (
    datetime,
    timedelta,
    )
import threading
import time

from fixtures import FakeLogger
from testtools.matchers import (
    Equals,
    MatchesDict,
    MatchesListwise,
    MatchesSetwise,
    MatchesStructure,
    )
import transaction
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.interfaces.ocirecipe import (
    OCI_RECIPE_ALLOW_CREATE,
    OCI_RECIPE_WEBHOOKS_FEATURE_FLAG,
    )
from lp.oci.interfaces.ocirecipebuildjob import (
    IOCIRecipeBuildJob,
    IOCIRegistryUploadJob,
    )
from lp.oci.interfaces.ocirecipejob import IOCIRecipeRequestBuildsJobSource
from lp.oci.interfaces.ociregistryclient import (
    BlobUploadFailed,
    IOCIRegistryClient,
    )
from lp.oci.model.ocirecipebuildjob import (
    OCIRecipeBuildJob,
    OCIRecipeBuildJobDerived,
    OCIRecipeBuildJobType,
    OCIRegistryUploadJob,
    )
from lp.services.compat import mock
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.job.tests import (
    block_on_job,
    pop_remote_notifications,
    )
from lp.services.statsd.tests import StatsMixin
from lp.services.webapp import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.dbuser import dbuser
from lp.testing.fakemethod import FakeMethod
from lp.testing.fixture import ZopeUtilityFixture
from lp.testing.layers import (
    CeleryJobLayer,
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.testing.mail_helpers import pop_notifications


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
        self.uploadManifestList = FakeMethod()


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


class TestOCIRecipeBuildJobDerived(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestOCIRecipeBuildJobDerived, self).setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: 'on'}))

    def test_repr(self):
        build = self.factory.makeOCIRecipeBuild()
        job = OCIRecipeBuildJob(
            build, OCIRecipeBuildJobType.REGISTRY_UPLOAD, {})
        derived_job = OCIRecipeBuildJobDerived(job)
        expected_repr = (
            "<OCIRecipeBuildJobDerived for "
            "~%s/%s/+oci/%s/+recipe/%s/+build/%d>" % (
                build.recipe.owner.name,
                build.recipe.oci_project.pillar.name,
                build.recipe.oci_project.name, build.recipe.name, build.id))
        self.assertEqual(expected_repr, repr(derived_job))

    def test_repr_fails_to_get_an_attribute(self):
        class ErrorOCIRecipeBuildJobDerived(OCIRecipeBuildJobDerived):
            def __getattribute__(self, item):
                if item == 'build':
                    raise AttributeError("Somethng is wrong with build")
                return super(
                    ErrorOCIRecipeBuildJobDerived, self).__getattribute__(item)
        oci_build = self.factory.makeOCIRecipeBuild()
        job = OCIRecipeBuildJob(
            oci_build, OCIRecipeBuildJobType.REGISTRY_UPLOAD, {})
        derived_job = ErrorOCIRecipeBuildJobDerived(job)
        self.assertEqual(
            "<ErrorOCIRecipeBuildJobDerived ID#%s>" % derived_job.job_id,
            repr(derived_job))


class MultiArchRecipeMixin:
    def makeRecipe(self, include_i386=True, include_amd64=True,
                   include_hppa=False):
        processors = []
        if include_i386:
            processors.append("386")
        if include_amd64:
            processors.append("amd64")
        if include_hppa:
            processors.append("hppa")
        archs = []
        recipe = self.factory.makeOCIRecipe(require_virtualized=False)
        distroseries = self.factory.makeDistroSeries(
            distribution=recipe.oci_project.distribution)
        for processor_name in processors:
            proc = getUtility(IProcessorSet).getByName(processor_name)
            distro_arch = self.factory.makeDistroArchSeries(
                distroseries=distroseries, architecturetag=processor_name,
                processor=proc)
            distro_arch.addOrUpdateChroot(self.factory.makeLibraryFileAlias())
            archs.append(proc)
        recipe.setProcessors(archs)
        return recipe

    def makeBuildRequest(self, include_i386=True, include_amd64=True,
                         include_hppa=False):
        recipe = self.makeRecipe(include_i386, include_amd64, include_hppa)
        # Creates a build request with a build in it.
        build_request = recipe.requestBuilds(recipe.owner)
        with admin_logged_in():
            jobs = getUtility(IOCIRecipeRequestBuildsJobSource).iterReady()
            with dbuser(config.IOCIRecipeRequestBuildsJobSource.dbuser):
                JobRunner(jobs).runAll()
        return build_request


class TestOCIRegistryUploadJob(TestCaseWithFactory, MultiArchRecipeMixin,
                               StatsMixin):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRegistryUploadJob, self).setUp()
        self.useFixture(FeatureFixture({
            'webhooks.new.enabled': 'true',
            OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: 'on',
            OCI_RECIPE_ALLOW_CREATE: 'on'
            }))
        self.setUpStats()

    def makeOCIRecipeBuild(self, **kwargs):
        ocibuild = self.factory.makeOCIRecipeBuild(
            builder=self.factory.makeBuilder(), **kwargs)
        ocibuild.updateStatus(BuildStatus.FULLYBUILT)
        self.makeWebhook(ocibuild.recipe)
        return ocibuild

    def makeWebhook(self, recipe):
        self.factory.makeWebhook(
            target=recipe, event_types=["oci-recipe:build:0.1"])

    def assertWebhookDeliveries(self, ocibuild,
                                expected_registry_upload_statuses, logger):
        hook = ocibuild.recipe.webhooks.one()
        deliveries = list(hook.deliveries)
        deliveries.reverse()
        build_req_url = (
            None if ocibuild.build_request is None
            else canonical_url(ocibuild.build_request, force_local_path=True))
        expected_payloads = [{
            "recipe_build": Equals(
                canonical_url(ocibuild, force_local_path=True)),
            "action": Equals("status-changed"),
            "recipe": Equals(
                canonical_url(ocibuild.recipe, force_local_path=True)),
            "build_request": Equals(build_req_url),
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
        build_request = self.makeBuildRequest(include_i386=False)
        recipe = build_request.recipe

        self.assertEqual(1, build_request.builds.count())
        ocibuild = build_request.builds[0]
        ocibuild.updateStatus(BuildStatus.FULLYBUILT)
        self.makeWebhook(recipe)

        self.assertContentEqual([], ocibuild.registry_upload_jobs)
        job = OCIRegistryUploadJob.create(ocibuild)
        client = FakeRegistryClient()
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))
        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            run_isolated_jobs([job])

        self.assertEqual([((ocibuild,), {})], client.upload.calls)
        self.assertEqual([((build_request, {ocibuild}), {})],
                         client.uploadManifestList.calls)
        self.assertContentEqual([job], ocibuild.registry_upload_jobs)
        self.assertIsNone(job.error_summary)
        self.assertIsNone(job.errors)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(ocibuild, ["Pending", "Uploaded"], logger)
        self.assertEqual(4, self.stats_client.incr.call_count)
        calls = [x[0][0] for x in self.stats_client.incr.call_args_list]
        self.assertThat(calls, MatchesListwise([
            Equals('job.start_count,env=test,type=OCIRecipeRequestBuildsJob'),
            Equals(
                'job.complete_count,env=test,type=OCIRecipeRequestBuildsJob'),
            Equals('job.start_count,env=test,type=OCIRegistryUploadJob'),
            Equals('job.complete_count,env=test,type=OCIRegistryUploadJob')]))

    def test_run_multiple_architectures(self):
        build_request = self.makeBuildRequest()
        builds = list(build_request.builds)
        self.assertEqual(2, len(builds))
        self.assertEqual(builds[0].build_request, builds[1].build_request)

        upload_jobs = []
        for build in builds:
            self.assertContentEqual([], build.registry_upload_jobs)
            upload_jobs.append(OCIRegistryUploadJob.create(build))

        client = FakeRegistryClient()
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))

        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            JobRunner([upload_jobs[0]]).runAll()
        self.assertEqual([((builds[0],), {})], client.upload.calls)
        # Should have tried to upload the manifest list with only the first
        # build.
        self.assertEqual([((build_request, set(builds[:1])), {})],
                         client.uploadManifestList.calls)

        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            JobRunner([upload_jobs[1]]).runAll()
        self.assertEqual(
            [((builds[0],), {}), ((builds[1],), {})], client.upload.calls)
        # Should have tried to upload the manifest list with both builds.
        self.assertEqual(
            [((build_request, set(builds[:1])), {}),
             ((build_request, set(builds)), {})],
            client.uploadManifestList.calls)
        calls = [x[0][0] for x in self.stats_client.incr.call_args_list]
        self.assertThat(calls, MatchesListwise([
            Equals('job.start_count,env=test,type=OCIRecipeRequestBuildsJob'),
            Equals(
                'job.complete_count,env=test,type=OCIRecipeRequestBuildsJob'),
            Equals('job.start_count,env=test,type=OCIRegistryUploadJob'),
            Equals('job.complete_count,env=test,type=OCIRegistryUploadJob'),
            Equals('job.start_count,env=test,type=OCIRegistryUploadJob'),
            Equals('job.complete_count,env=test,type=OCIRegistryUploadJob')]))

    def test_failing_upload_does_not_retries_automatically(self):
        build_request = self.makeBuildRequest(include_i386=False)
        builds = build_request.builds
        self.assertEqual(1, builds.count())

        build = builds.one()
        self.assertContentEqual([], build.registry_upload_jobs)
        upload_job = OCIRegistryUploadJob.create(build)

        client = mock.Mock()
        client.upload.side_effect = Exception("Nope! Error.")
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))

        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            JobRunner([upload_job]).runAll()
        self.assertEqual(1, client.upload.call_count)
        self.assertEqual(0, client.uploadManifestList.call_count)
        self.assertEqual(JobStatus.FAILED, upload_job.status)
        self.assertFalse(upload_job.build_uploaded)

    def test_failing_upload_manifest_list_retries(self):
        build_request = self.makeBuildRequest(include_i386=False)
        builds = build_request.builds
        self.assertEqual(1, builds.count())

        build = builds.one()
        self.assertContentEqual([], build.registry_upload_jobs)
        upload_job = OCIRegistryUploadJob.create(build)

        client = mock.Mock()
        client.uploadManifestList.side_effect = (
            OCIRegistryUploadJob.ManifestListUploadError("Nope! Error."))
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))

        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            JobRunner([upload_job]).runAll()
        self.assertEqual(1, client.upload.call_count)
        self.assertEqual(1, client.uploadManifestList.call_count)
        self.assertEqual(JobStatus.WAITING, upload_job.status)
        self.assertTrue(upload_job.is_pending)
        self.assertTrue(upload_job.build_uploaded)

        # Retry should skip client.upload and only run
        # client.uploadManifestList:
        client.uploadManifestList.side_effect = None
        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            JobRunner([upload_job]).runAll()
        self.assertEqual(1, client.upload.call_count)
        self.assertEqual(2, client.uploadManifestList.call_count)
        self.assertEqual(JobStatus.COMPLETED, upload_job.status)
        self.assertTrue(upload_job.build_uploaded)

    def test_getUploadedBuilds_lock_between_two_jobs(self):
        """Simple test to ensure that getUploadedBuilds method locks
        rows in the database and make concurrent calls wait for that.

        This is not a 100% reliable way to check that concurrent calls to
        getUploadedBuilds will queue up since it relies on the
        execution time, but it's a "good enough" approach: this test might
        pass if the machine running it is *really, really* slow, but a failure
        here will indicate that something is for sure wrong.
        """

        class AllBuildsUploadedChecker(threading.Thread):
            """Thread to run upload_job.getUploadedBuilds tracking the time."""
            def __init__(self, build_request):
                super(AllBuildsUploadedChecker, self).__init__()
                self.build_request = build_request
                self.upload_job = None
                # Locks the measurement start until we finished running the
                # bootstrap code. Parent thread should call waitBootstrap
                # after self.start().
                self.bootstrap_lock = threading.Lock()
                self.bootstrap_lock.acquire()
                self.result = None
                self.error = None
                self.start_date = None
                self.end_date = None

            @property
            def lock_duration(self):
                return self.end_date - self.start_date

            def waitBootstrap(self):
                """Wait until self.bootstrap finishes running."""
                self.bootstrap_lock.acquire()
                # We don't actually need the lock... just wanted to wait
                # for it. let's release it then.
                self.bootstrap_lock.release()

            def bootstrap(self):
                try:
                    build = self.build_request.builds[1]
                    self.upload_job = OCIRegistryUploadJob.create(build)
                finally:
                    self.bootstrap_lock.release()

            def run(self):
                with admin_logged_in():
                    self.bootstrap()
                    self.start_date = datetime.now()
                    try:
                        self.result = self.upload_job.getUploadedBuilds(
                            self.build_request)
                    except Exception as e:
                        self.error = e
                    self.end_date = datetime.now()

        # Create a build request with 2 builds.
        build_request = self.makeBuildRequest(
            include_i386=True, include_amd64=True, include_hppa=True)
        builds = build_request.builds
        self.assertEqual(3, builds.count())

        # Fail one of the builds, to make sure we are ignoring it.
        removeSecurityProxy(builds[2]).status = BuildStatus.FAILEDTOBUILD

        # Create the upload job for the first build.
        upload_job1 = OCIRegistryUploadJob.create(builds[0])
        upload_job1 = removeSecurityProxy(upload_job1)

        # How long the lock will be held by the first job, in seconds.
        # Adjust to minimize false positives: a number too small here might
        # make the test pass even if the lock is not correctly implemented.
        # A number too big will slow down the test execution...
        waiting_time = 2
        # Start a clean transaction and lock the rows at database level.
        transaction.commit()
        self.assertEqual(
            {builds[0]}, upload_job1.getUploadedBuilds(build_request))

        # Start, in parallel, another upload job to run `getUploadedBuilds`.
        concurrent_checker = AllBuildsUploadedChecker(build_request)
        concurrent_checker.start()
        # Wait until concurrent_checker is ready to measure the time waiting
        # for the database lock.
        concurrent_checker.waitBootstrap()

        # Wait a bit and release the database lock by committing current
        # transaction.
        time.sleep(waiting_time)
        # Let's force the first job to be finished, just to make sure the
        # second job will realise it's the last one running.
        upload_job1.start()
        upload_job1.complete()
        transaction.commit()

        # Now, the concurrent checker should have already finished running,
        # without any error and it should have taken at least the
        # waiting_time to finish running (since it was waiting).
        concurrent_checker.join()
        self.assertIsNone(concurrent_checker.error)
        self.assertGreaterEqual(
            concurrent_checker.lock_duration, timedelta(seconds=waiting_time))
        # Should have noticed that both builds are ready to upload.
        self.assertEqual(2, len(concurrent_checker.result))
        thread_build1, thread_build2 = concurrent_checker.result
        self.assertThat(set(builds[:2]), MatchesSetwise(
            MatchesStructure(id=Equals(thread_build1.id)),
            MatchesStructure(id=Equals(thread_build2.id))))

    def test_run_failed_registry_error(self):
        # A run that fails with a registry error sets the registry upload
        # status to FAILED, and stores the detailed errors.
        logger = self.useFixture(FakeLogger())
        ocibuild = self.makeOCIRecipeBuild()
        self.assertContentEqual([], ocibuild.registry_upload_jobs)
        job = OCIRegistryUploadJob.create(ocibuild)
        client = FakeRegistryClient()
        error_summary = "Upload of some-digest for some-image failed"
        errors = [
            {
                "code": "UNAUTHORIZED",
                "message": "authentication required",
                "detail": [
                    {
                        "Type": "repository",
                        "Class": "",
                        "Name": "some-image",
                        "Action": "pull",
                        },
                    {
                        "Type": "repository",
                        "Class": "",
                        "Name": "some-image",
                        "Action": "push",
                        },
                    ],
                },
            ]
        client.upload.failure = BlobUploadFailed(error_summary, errors)
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))
        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            run_isolated_jobs([job])
        self.assertEqual([((ocibuild,), {})], client.upload.calls)
        self.assertContentEqual([job], ocibuild.registry_upload_jobs)
        self.assertEqual(error_summary, job.error_summary)
        self.assertEqual(errors, job.errors)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            ocibuild, ["Pending", "Failed to upload"], logger)

    def test_run_failed_other_error(self):
        # A run that fails for some reason other than a registry error sets
        # the registry upload status to FAILED.
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
        self.assertEqual("An upload failure", job.error_summary)
        self.assertIsNone(job.errors)
        self.assertEqual([], pop_notifications())
        self.assertWebhookDeliveries(
            ocibuild, ["Pending", "Failed to upload"], logger)

    def test_run_does_not_oops(self):
        # The job can OOPS, but it is hidden by our exception handling
        # Check that it's actually empty
        build_request = self.makeBuildRequest(include_i386=False)
        recipe = build_request.recipe

        self.assertEqual(1, build_request.builds.count())
        ocibuild = build_request.builds[0]
        ocibuild.updateStatus(BuildStatus.FULLYBUILT)
        self.makeWebhook(recipe)

        self.assertContentEqual([], ocibuild.registry_upload_jobs)
        job = OCIRegistryUploadJob.create(ocibuild)
        client = FakeRegistryClient()
        self.useFixture(ZopeUtilityFixture(client, IOCIRegistryClient))
        with dbuser(config.IOCIRegistryUploadJobSource.dbuser):
            run_isolated_jobs([job])

        self.assertEqual(0, len(self.oopses))


class TestOCIRegistryUploadJobViaCelery(TestCaseWithFactory,
                                        MultiArchRecipeMixin):
    """Runs OCIRegistryUploadJob via Celery, to make sure the machinery
    around it works.

    It's important to have this test specially because this job does some
    dodgy things with its own status and the database transaction,
    so we should make sure we are not breaking anything in the interaction
    with the job lifecycle via celery.
    """
    layer = CeleryJobLayer

    def setUp(self):
        super(TestOCIRegistryUploadJobViaCelery, self).setUp()
        self.useFixture(FeatureFixture({
            'webhooks.new.enabled': 'true',
            OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: 'on',
            OCI_RECIPE_ALLOW_CREATE: 'on',
            'jobs.celery.enabled_classes': 'OCIRegistryUploadJob',
            }))

    def test_run_upload(self):
        build_request = self.makeBuildRequest()
        builds = build_request.builds
        self.assertEqual(2, builds.count())

        with block_on_job():
            for build in builds:
                OCIRegistryUploadJob.create(build)
            transaction.commit()
        self.assertEqual(0, len(pop_remote_notifications()))
