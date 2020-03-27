# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

from __future__ import absolute_import, print_function, unicode_literals

from datetime import timedelta

from fixtures import FakeLogger
import six
from testtools.matchers import (
    ContainsDict,
    Equals,
    MatchesDict,
    MatchesStructure,
    )
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.buildqueue import IBuildQueue
from lp.buildmaster.interfaces.packagebuild import IPackageBuild
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.interfaces.ocirecipe import OCI_RECIPE_WEBHOOKS_FEATURE_FLAG
from lp.oci.interfaces.ocirecipebuild import (
    IOCIRecipeBuild,
    IOCIRecipeBuildSet,
    )
from lp.oci.model.ocirecipebuild import OCIRecipeBuildSet
from lp.registry.interfaces.series import SeriesStatus
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.propertycache import clear_property_cache
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.testing import LogsScheduledWebhooks
from lp.testing import (
    admin_logged_in,
    StormStatementRecorder,
    TestCaseWithFactory,
    )
from lp.testing.dbuser import dbuser
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.testing.matchers import HasQueryCount


class TestOCIRecipeBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(TestOCIRecipeBuild, self).setUp()
        self.build = self.factory.makeOCIRecipeBuild()

    def test_implements_interface(self):
        with admin_logged_in():
            self.assertProvides(self.build, IOCIRecipeBuild)
            self.assertProvides(self.build, IPackageBuild)

    def test_addFile(self):
        lfa = self.factory.makeLibraryFileAlias()
        self.build.addFile(lfa)
        _, result_lfa, _ = self.build.getByFileName(lfa.filename)
        self.assertEqual(result_lfa, lfa)

    def test_getByFileName(self):
        files = [self.factory.makeOCIFile(build=self.build) for x in range(3)]
        result, _, _ = self.build.getByFileName(
            files[0].library_file.filename)
        self.assertEqual(result, files[0])

    def test_getByFileName_missing(self):
        self.assertRaises(
            NotFoundError,
            self.build.getByFileName,
            "missing")

    def test_getLayerFileByDigest(self):
        files = [self.factory.makeOCIFile(
                    build=self.build, layer_file_digest=six.text_type(x))
                 for x in range(3)]
        result, _, _ = self.build.getLayerFileByDigest(
            files[0].layer_file_digest)
        self.assertEqual(result, files[0])

    def test_getLayerFileByDigest_missing(self):
        [self.factory.makeOCIFile(
            build=self.build, layer_file_digest=six.text_type(x))
         for x in range(3)]
        self.assertRaises(
            NotFoundError,
            self.build.getLayerFileByDigest,
            'missing')

    def test_estimateDuration(self):
        # Without previous builds, the default time estimate is 30m.
        self.assertEqual(1800, self.build.estimateDuration().seconds)

    def test_estimateDuration_with_history(self):
        # Previous successful builds of the same OCI recipe are used for
        # estimates.
        oci_build = self.factory.makeOCIRecipeBuild(
            status=BuildStatus.FULLYBUILT, duration=timedelta(seconds=335))
        for i in range(3):
            self.factory.makeOCIRecipeBuild(
                requester=oci_build.requester, recipe=oci_build.recipe,
                status=BuildStatus.FAILEDTOBUILD,
                duration=timedelta(seconds=20))
        self.assertEqual(335, oci_build.estimateDuration().seconds)

    def test_queueBuild(self):
        # OCIRecipeBuild can create the queue entry for itself.
        bq = self.build.queueBuild()
        self.assertProvides(bq, IBuildQueue)
        self.assertEqual(
            self.build.build_farm_job, removeSecurityProxy(bq)._build_farm_job)
        self.assertEqual(self.build, bq.specific_build)
        self.assertEqual(self.build.virtualized, bq.virtualized)
        self.assertIsNotNone(bq.processor)
        self.assertEqual(bq, self.build.buildqueue_record)

    def test_updateStatus_triggers_webhooks(self):
        # Updating the status of an OCIRecipeBuild triggers webhooks on the
        # corresponding OCIRecipe.
        logger = self.useFixture(FakeLogger())
        hook = self.factory.makeWebhook(
            target=self.build.recipe, event_types=["oci-recipe:build:0.1"])
        with FeatureFixture({OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: "on"}):
            self.build.updateStatus(BuildStatus.FULLYBUILT)
        expected_payload = {
            "recipe_build": Equals(
                canonical_url(self.build, force_local_path=True)),
            "action": Equals("status-changed"),
            "recipe": Equals(
                 canonical_url(self.build.recipe, force_local_path=True)),
            "status": Equals("Successfully built"),
            }
        self.assertThat(
            logger.output, LogsScheduledWebhooks([
                (hook, "oci-recipe:build:0.1",
                 MatchesDict(expected_payload))]))

        delivery = hook.deliveries.one()
        self.assertThat(
            delivery, MatchesStructure(
                event_type=Equals("oci-recipe:build:0.1"),
                payload=MatchesDict(expected_payload)))
        with dbuser(config.IWebhookDeliveryJobSource.dbuser):
            self.assertEqual(
                "<WebhookDeliveryJob for webhook %d on %r>" % (
                    hook.id, hook.target),
                repr(delivery))

    def test_updateStatus_no_change_does_not_trigger_webhooks(self):
        # An updateStatus call that doesn't change the build's status
        # attribute does not trigger webhooks.
        logger = self.useFixture(FakeLogger())
        hook = self.factory.makeWebhook(
            target=self.build.recipe, event_types=["oci-recipe:build:0.1"])
        with FeatureFixture({OCI_RECIPE_WEBHOOKS_FEATURE_FLAG: "on"}):
            self.build.updateStatus(BuildStatus.BUILDING)
        expected_logs = [
            (hook, "oci-recipe:build:0.1", ContainsDict({
                "action": Equals("status-changed"),
                "status": Equals("Currently building"),
                }))]
        self.assertEqual(1, hook.deliveries.count())
        self.assertThat(logger.output, LogsScheduledWebhooks(expected_logs))

        self.build.updateStatus(BuildStatus.BUILDING)
        expected_logs = [
            (hook, "oci-recipe:build:0.1", ContainsDict({
                "action": Equals("status-changed"),
                "status": Equals("Currently building"),
                }))]
        self.assertEqual(1, hook.deliveries.count())
        self.assertThat(logger.output, LogsScheduledWebhooks(expected_logs))

    def test_eta(self):
        # OCIRecipeBuild.eta returns a non-None value when it should, or
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
        # OCIRecipeBuild.estimate returns True until the job is completed.
        self.build.queueBuild()
        self.factory.makeBuilder(processors=[self.build.processor])
        self.build.updateStatus(BuildStatus.BUILDING)
        self.assertTrue(self.build.estimate)
        self.build.updateStatus(BuildStatus.FULLYBUILT)
        clear_property_cache(self.build)
        self.assertFalse(self.build.estimate)


class TestOCIRecipeBuildSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target = OCIRecipeBuildSet()
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipeBuildSet)

    def test_new(self):
        requester = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.CURRENT)
        processor = getUtility(IProcessorSet).getByName("386")
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=distroseries, architecturetag="i386",
            processor=processor)
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        target = getUtility(IOCIRecipeBuildSet).new(
            requester, recipe, distro_arch_series)
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipeBuild)
            self.assertEqual(distro_arch_series, target.distro_arch_series)

    def test_new_oci_feature_flag_enabled(self):
        requester = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        distroseries = self.factory.makeDistroSeries(
            distribution=distribution, status=SeriesStatus.CURRENT)
        processor = getUtility(IProcessorSet).getByName("386")
        self.useFixture(FeatureFixture({
            "oci.build_series.%s" % distribution.name: distroseries.name}))
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=distroseries, architecturetag="i386",
            processor=processor)
        oci_project = self.factory.makeOCIProject(pillar=distribution)
        recipe = self.factory.makeOCIRecipe(oci_project=oci_project)
        target = getUtility(IOCIRecipeBuildSet).new(
            requester, recipe, distro_arch_series)
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipeBuild)
            self.assertEqual(distro_arch_series, target.distro_arch_series)

    def test_getByID(self):
        builds = [self.factory.makeOCIRecipeBuild() for x in range(3)]
        result = getUtility(IOCIRecipeBuildSet).getByID(builds[1].id)
        self.assertEqual(result, builds[1])

    def test_getByBuildFarmJob(self):
        builds = [self.factory.makeOCIRecipeBuild() for x in range(3)]
        result = getUtility(IOCIRecipeBuildSet).getByBuildFarmJob(
            builds[1].build_farm_job)
        self.assertEqual(result, builds[1])

    def test_getByBuildFarmJobs(self):
        builds = [self.factory.makeOCIRecipeBuild() for x in range(3)]
        self.assertContentEqual(
            builds,
            getUtility(IOCIRecipeBuildSet).getByBuildFarmJobs(
                [build.build_farm_job for build in builds]))

    def test_getByBuildFarmJobs_empty(self):
        self.assertContentEqual(
            [], getUtility(IOCIRecipeBuildSet).getByBuildFarmJobs([]))

    def test_virtualized_recipe_requires(self):
        recipe = self.factory.makeOCIRecipe(require_virtualized=True)
        target = self.factory.makeOCIRecipeBuild(recipe=recipe)
        self.assertTrue(target.virtualized)

    def test_virtualized_processor_requires(self):
        recipe = self.factory.makeOCIRecipe(require_virtualized=False)
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=self.factory.makeDistroSeries(
                distribution=recipe.oci_project.distribution))
        distro_arch_series.processor.supports_nonvirtualized = False
        target = self.factory.makeOCIRecipeBuild(
            distro_arch_series=distro_arch_series, recipe=recipe)
        self.assertTrue(target.virtualized)

    def test_virtualized_no_support(self):
        recipe = self.factory.makeOCIRecipe(require_virtualized=False)
        distro_arch_series = self.factory.makeDistroArchSeries(
            distroseries=self.factory.makeDistroSeries(
                distribution=recipe.oci_project.distribution))
        distro_arch_series.processor.supports_nonvirtualized = True
        target = self.factory.makeOCIRecipeBuild(
            recipe=recipe, distro_arch_series=distro_arch_series)
        self.assertFalse(target.virtualized)
