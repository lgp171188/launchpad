# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipeBuildJob tests"""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type


from lp.oci.interfaces.ocirecipebuildjob import IOCIRecipeBuildJob
from lp.oci.model.ocirecipebuildjob import (
    OCIRecipeBuildJob,
    OCIRecipeBuildJobDerived,
    OCIRecipeBuildJobType,
    )
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


class FakeOCIBuildJob(OCIRecipeBuildJobDerived):
    """For testing OCIRecipeBuildJobDerived without a child class."""


class TestOCIRecipeBuildJob(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

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
