# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice.

There is a declaration in ZCML somewhere that looks like:
  <webservice:register module="lp.charms.interfaces.webservice" />

which tells `lazr.restful` that it should look for webservice exports here.
"""

__all__ = [
    "ICharmBase",
    "ICharmBaseSet",
    "ICharmRecipe",
    "ICharmRecipeBuild",
    "ICharmRecipeBuildRequest",
    "ICharmRecipeSet",
    ]

from lp.charms.interfaces.charmbase import (
    ICharmBase,
    ICharmBaseSet,
    )
from lp.charms.interfaces.charmrecipe import (
    ICharmRecipe,
    ICharmRecipeBuildRequest,
    ICharmRecipeSet,
    ICharmRecipeView,
    )
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuild
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_reference_property,
    )


# ICharmRecipeBuildRequest
patch_reference_property(ICharmRecipeBuildRequest, "recipe", ICharmRecipe)
patch_collection_property(
    ICharmRecipeBuildRequest, "builds", ICharmRecipeBuild)

# ICharmRecipeView
patch_collection_property(ICharmRecipeView, "builds", ICharmRecipeBuild)
patch_collection_property(
    ICharmRecipeView, "completed_builds", ICharmRecipeBuild)
patch_collection_property(
    ICharmRecipeView, "pending_builds", ICharmRecipeBuild)
