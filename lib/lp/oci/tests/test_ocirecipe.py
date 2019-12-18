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
    OCIRecipeChannelAlreadyExists,
    OCIRecipeNotOwner,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.oci.model.ocirecipechannel import OCIRecipeChannel
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
        ocirecipechannel = self.factory.makeOCIRecipeChannel(recipe=ocirecipe)
        oci_arch = self.factory.makeOCIRecipeArch(recipe=ocirecipe)
        build = ocirecipe.requestBuild(
            ocirecipe.owner, ocirecipechannel, oci_arch)
        self.assertEqual(build.status, BuildStatus.NEEDSBUILD)

    def test_requestBuild_already_exists(self):
        ocirecipe = self.factory.makeOCIRecipe()
        ocirecipechannel = self.factory.makeOCIRecipeChannel(recipe=ocirecipe)
        oci_arch = self.factory.makeOCIRecipeArch(recipe=ocirecipe)
        ocirecipe.requestBuild(
            ocirecipe.owner, ocirecipechannel, oci_arch)

        self.assertRaises(
            OCIRecipeBuildAlreadyPending,
            ocirecipe.requestBuild,
            ocirecipe.owner, ocirecipechannel, oci_arch)

    def test_destroySelf(self):
        oci_recipe = self.factory.makeOCIRecipe()
        build_ids = []
        for x in range(3):
            build_ids.append(
                self.factory.makeOCIRecipeBuild(recipe=oci_recipe).id)
            self.factory.makeOCIRecipeChannel(recipe=oci_recipe)

        oci_recipe.destroySelf()

        for build_id in build_ids:
            self.assertIsNone(getUtility(IOCIRecipeBuildSet).getByID(build_id))

        channels_store = IMasterStore(OCIRecipeChannel).find(OCIRecipeChannel)
        self.assertEqual(channels_store.count(), 0)

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

    def test_channels(self):
        oci_recipe = self.factory.makeOCIRecipe()
        channels = [self.factory.makeOCIRecipeChannel(recipe=oci_recipe)
                    for x in range(3)]
        channels.reverse()

        self.assertEqual(channels, list(oci_recipe.channels))

    def test_addChannel(self):
        oci_recipe = self.factory.makeOCIRecipe()
        oci_recipe.addChannel('test-channel', '/a/path', 'afile.file')
        self.assertEqual(oci_recipe.channels.count(), 1)

    def test_addChannel_existing(self):
        oci_recipe = self.factory.makeOCIRecipe()
        oci_recipe.addChannel('test-channel', '/a/path', 'afile.file')
        self.assertRaises(
            OCIRecipeChannelAlreadyExists,
            oci_recipe.addChannel,
            'test-channel',
            '/a/path',
            'afile.file')

    def test_removeChannel(self):
        oci_recipe = self.factory.makeOCIRecipe()
        channels = [self.factory.makeOCIRecipeChannel(recipe=oci_recipe)
                    for x in range(3)]
        removed_name = channels[0].name
        oci_recipe.removeChannel(removed_name)
        for channel in oci_recipe.channels:
            self.assertNotEqual(channel.name, removed_name)


class TestOCIRecipeSet(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def test_implements_interface(self):
        target_set = getUtility(IOCIRecipeSet)
        with admin_logged_in():
            self.assertProvides(target_set, IOCIRecipeSet)

    def test_new(self):
        registrant = self.factory.makePerson()
        owner = self.factory.makeTeam(members=[registrant])
        ociproject = self.factory.makeOCIProject()
        git_repo = self.factory.makeGitRepository()
        target = getUtility(IOCIRecipeSet).new(
            registrant=registrant,
            owner=owner,
            ociproject=ociproject,
            ociproject_default=False,
            require_virtualized=False,
            git_repository=git_repo)
        self.assertEqual(target.registrant, registrant)
        self.assertEqual(target.owner, owner)
        self.assertEqual(target.ociproject, ociproject)
        self.assertEqual(target.ociproject_default, False)
        self.assertEqual(target.require_virtualized, False)
        self.assertEqual(target.git_repository, git_repo)
