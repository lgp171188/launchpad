# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe views."""

__all__ = [
    "CraftRecipeURL",
]

from zope.component import getUtility
from zope.interface import implementer

from lp.crafts.interfaces.craftrecipe import ICraftRecipe
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuildSet
from lp.registry.interfaces.personproduct import IPersonProductFactory
from lp.services.webapp import Navigation, stepthrough
from lp.services.webapp.interfaces import ICanonicalUrlData
from lp.soyuz.browser.build import get_build_by_id_str


@implementer(ICanonicalUrlData)
class CraftRecipeURL:
    """Craft recipe URL creation rules."""

    rootsite = "mainsite"

    def __init__(self, recipe):
        self.recipe = recipe

    @property
    def inside(self):
        owner = self.recipe.owner
        project = self.recipe.project
        return getUtility(IPersonProductFactory).create(owner, project)

    @property
    def path(self):
        return "+craft/%s" % self.recipe.name


class CraftRecipeNavigation(Navigation):
    usedfor = ICraftRecipe

    @stepthrough("+build-request")
    def traverse_build_request(self, name):
        try:
            job_id = int(name)
        except ValueError:
            return None
        return self.context.getBuildRequest(job_id)

    @stepthrough("+build")
    def traverse_build(self, name):
        build = get_build_by_id_str(ICraftRecipeBuildSet, name)
        if build is None or build.recipe != self.context:
            return None
        return build
