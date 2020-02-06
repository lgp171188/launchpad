# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for OCI image building recipe functionality."""

from __future__ import absolute_import, print_function, unicode_literals

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeSet,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeNotOwner,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.services.database.interfaces import IMasterStore
from lp.testing import (
    admin_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import DatabaseFunctionalLayer


class TestOCIRecipe(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target = self.factory.makeOCIRecipe()
        with admin_logged_in():
            self.assertProvides(target, IOCIRecipe)

    def test_checkRequestBuild(self):
        ocirecipe = removeSecurityProxy(self.factory.makeOCIRecipe())
        unrelated_person = self.factory.makePerson()
        self.assertRaises(
            OCIRecipeNotOwner,
            ocirecipe._checkRequestBuild,
            unrelated_person)

    def test_requestBuild(self):
        ocirecipe = self.factory.makeOCIRecipe()
        oci_arch = self.factory.makeOCIRecipeArch(recipe=ocirecipe)
        build = ocirecipe.requestBuild(ocirecipe.owner, oci_arch)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    def test_requestBuild_already_exists(self):
        ocirecipe = self.factory.makeOCIRecipe()
        oci_arch = self.factory.makeOCIRecipeArch(recipe=ocirecipe)
        ocirecipe.requestBuild(ocirecipe.owner, oci_arch)

        self.assertRaises(
            OCIRecipeBuildAlreadyPending,
            ocirecipe.requestBuild,
            ocirecipe.owner, oci_arch)

    def test_destroySelf(self):
        oci_recipe = self.factory.makeOCIRecipe()
        build_ids = []
        for x in range(3):
            build_ids.append(
                self.factory.makeOCIRecipeBuild(recipe=oci_recipe).id)

        oci_recipe.destroySelf()

        for build_id in build_ids:
            self.assertIsNone(getUtility(IOCIRecipeBuildSet).getByID(build_id))

    def test_getBuilds(self):
        # Test the various getBuilds methods.
        oci_recipe = self.factory.makeOCIRecipe()
        builds = [self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
                  for x in range(3)]
        # We want the latest builds first.
        builds.reverse()

        self.assertEqual(builds, list(oci_recipe.builds))
        self.assertEqual([], list(oci_recipe.completed_builds))
        self.assertEqual(builds, list(oci_recipe.pending_builds))

        # Change the status of one of the builds and retest.
        builds[0].updateStatus(BuildStatus.BUILDING)
        builds[0].updateStatus(BuildStatus.FULLYBUILT)
        self.assertEqual(builds, list(oci_recipe.builds))
        self.assertEqual(builds[:1], list(oci_recipe.completed_builds))
        self.assertEqual(builds[1:], list(oci_recipe.pending_builds))

    def test_getBuilds_cancelled_never_started_last(self):
        # A cancelled build that was never even started sorts to the end.
        oci_recipe = self.factory.makeOCIRecipe()
        fullybuilt = self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
        instacancelled = self.factory.makeOCIRecipeBuild(recipe=oci_recipe)
        fullybuilt.updateStatus(BuildStatus.BUILDING)
        fullybuilt.updateStatus(BuildStatus.FULLYBUILT)
        instacancelled.updateStatus(BuildStatus.CANCELLED)
        self.assertEqual([fullybuilt, instacancelled], list(oci_recipe.builds))
        self.assertEqual(
            [fullybuilt, instacancelled], list(oci_recipe.completed_builds))
        self.assertEqual([], list(oci_recipe.pending_builds))


class TestOCIRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target_set = getUtility(IOCIRecipeSet)
        with admin_logged_in():
            self.assertProvides(target_set, IOCIRecipeSet)

    def test_new(self):
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(members=[registrant])
        oci_project = self.factory.makeOCIProject()
        git_repo = self.factory.makeGitRepository()
        target = getUtility(IOCIRecipeSet).new(
            name='a name',
            registrant=registrant,
            owner=owner,
            oci_project=oci_project,
            description='a description',
            official=False,
            require_virtualized=False,
            git_repository=git_repo,
            git_path='git path',
            build_file='build file')
        self.assertEqual(target.registrant, registrant)
        self.assertEqual(target.owner, owner)
        self.assertEqual(target.oci_project, oci_project)
        self.assertEqual(target.official, False)
        self.assertEqual(target.require_virtualized, False)
        self.assertEqual(target.git_repository, git_repo)
