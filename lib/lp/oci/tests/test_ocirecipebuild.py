# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

from __future__ import absolute_import, print_function, unicode_literals

from zope.component import getUtility

from lp.app.errors import NotFoundError
from lp.oci.interfaces.ocirecipebuild import (
    IOCIRecipeBuild,
    IOCIRecipeBuildSet,
    )
from lp.oci.model.ocirecipebuild import (
    OCIFile,
    OCIRecipeBuildSet,
    )
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadZopelessLayer,
    )


class TestOCIRecipeBuild(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_implements_interface(self):
        target = self.factory.makeOCIRecipeBuild()
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipeBuild)

    def test_addFile(self):
        target = self.factory.makeOCIRecipeBuild()
        lfa = self.factory.makeLibraryFileAlias()
        target.addFile(lfa)

        _, result_lfa, _ = target.getFileByFileName(lfa.filename)
        self.assertEqual(result_lfa, lfa)

    def test_getFileByFileName(self):
        oci_build = self.factory.makeOCIRecipeBuild()
        files = [self.factory.makeOCIFile(build=oci_build) for x in range(3)]

        result, _, _ = oci_build.getFileByFileName(
            files[0].library_file.filename)

        self.assertEqual(result, files[0])

    def test_getLayerFileByDigest(self):
        oci_build = self.factory.makeOCIRecipeBuild()
        files = [self.factory.makeOCILayerFile(build=oci_build)
                 for x in range(3)]

        result, _, _ = oci_build.getLayerFileByDigest(
            files[0].layer_file_digest)

        self.assertEqual(result, files[0])

    def test_getLayerFileByDigest_missing(self):
        oci_build = self.factory.makeOCIRecipeBuild()
        files = [self.factory.makeOCILayerFile(build=oci_build)
                 for x in range(3)]

        self.assertRaises(
            NotFoundError,
            oci_build.getLayerFileByDigest,
            'missing')


class TestOCIRecipeBuildSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target = OCIRecipeBuildSet()
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipeBuildSet)

    def test_new(self):
        requester = self.factory.makePerson()
        recipe = self.factory.makeOCIRecipe()
        channel_name = 'test'
        processor = self.factory.makeProcessor()
        virtualized = False
        target = getUtility(IOCIRecipeBuildSet).new(
            requester, recipe, channel_name, processor, virtualized)
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipeBuild)

    def test_getById(self):
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
