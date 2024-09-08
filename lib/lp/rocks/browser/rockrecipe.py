# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Rock recipe views."""

__all__ = [
    "RockRecipeNavigation",
    "RockRecipeURL",
]

from zope.component import getUtility
from zope.interface import implementer

from lp.registry.interfaces.personproduct import IPersonProductFactory
from lp.rocks.interfaces.rockrecipe import IRockRecipe
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuildSet
from lp.services.webapp import Navigation, stepthrough
from lp.services.webapp.interfaces import ICanonicalUrlData
from lp.soyuz.browser.build import get_build_by_id_str


@implementer(ICanonicalUrlData)
class RockRecipeURL:
    """Rock recipe URL creation rules."""

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
        return "+rock/%s" % self.recipe.name


class RockRecipeNavigation(Navigation):
    usedfor = IRockRecipe

    @stepthrough("+build-request")
    def traverse_build_request(self, name):
        try:
            job_id = int(name)
        except ValueError:
            return None
        return self.context.getBuildRequest(job_id)

    @stepthrough("+build")
    def traverse_build(self, name):
        build = get_build_by_id_str(IRockRecipeBuildSet, name)
        if build is None or build.recipe != self.context:
            return None
        return build
