from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeSet,
    OCIBuildAlreadyPending,
    OCIRecipeNotOwner,
    )
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
            OCIBuildAlreadyPending,
            ocirecipe.requestBuild,
            ocirecipe.owner, ocirecipechannel, oci_arch)


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
        target = getUtility(IOCIRecipeSet).new(
            registrant=registrant,
            owner=owner,
            ociproject=ociproject,
            ociproject_default=False,
            require_virtualized=False)
        self.assertEqual(target.registrant, registrant)
        self.assertEqual(target.owner, owner)
        self.assertEqual(target.ociproject, ociproject)
        self.assertEqual(target.ociproject_default, False)
        self.assertEqual(target.require_virtualized, False)
