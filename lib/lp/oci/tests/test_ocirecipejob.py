# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for classes in OCIRecipeJob."""

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.oci.interfaces.ocirecipe import OCI_RECIPE_ALLOW_CREATE
from lp.oci.interfaces.ocirecipebuild import (
    OCIRecipeBuildSetRegistryUploadStatus,
)
from lp.oci.interfaces.ocirecipebuildjob import IOCIRegistryUploadJobSource
from lp.oci.interfaces.ocirecipejob import IOCIRecipeRequestBuildsJobSource
from lp.registry.interfaces.series import SeriesStatus
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIRecipeRequestBuildsJob(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({OCI_RECIPE_ALLOW_CREATE: "on"}))

    def getDistroArchSeries(
        self, distroseries, proc_name="386", arch_tag="i386"
    ):
        processor = getUtility(IProcessorSet).getByName(proc_name)

        das = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag=arch_tag,
            processor=processor,
        )
        fake_chroot = self.factory.makeLibraryFileAlias(
            filename="fake_chroot.tar.gz", db_only=True
        )
        das.addOrUpdateChroot(fake_chroot)
        return das

    def test_partial_on_failure(self):
        ocirecipe = removeSecurityProxy(
            self.factory.makeOCIRecipe(require_virtualized=False)
        )
        owner = ocirecipe.owner
        distro = ocirecipe.oci_project.distribution
        series = self.factory.makeDistroSeries(
            distribution=distro, status=SeriesStatus.CURRENT
        )
        self.getDistroArchSeries(series, "386", "386")
        self.getDistroArchSeries(series, "hppa", "hppa")
        job = getUtility(IOCIRecipeRequestBuildsJobSource).create(
            ocirecipe, owner
        )

        with person_logged_in(job.requester):
            builds = ocirecipe.requestBuildsFromJob(
                job.requester, build_request=job.build_request
            )
            removeSecurityProxy(job).builds = builds

        builds[0].updateStatus(BuildStatus.FAILEDTOBUILD)
        builds[1].updateStatus(BuildStatus.FULLYBUILT)
        upload_job = getUtility(IOCIRegistryUploadJobSource).create(builds[1])
        removeSecurityProxy(upload_job).job._status = JobStatus.COMPLETED

        status = job.build_status

        self.assertTrue(status["upload_requested"])
        self.assertEqual(
            OCIRecipeBuildSetRegistryUploadStatus.PARTIAL, status["upload"]
        )
