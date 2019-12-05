# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

from __future__ import absolute_import, print_function, unicode_literals

from lp.app.errors import NotFoundError
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuild
from lp.oci.model.ocirecipebuild import OCIFile
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadZopelessLayer


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
