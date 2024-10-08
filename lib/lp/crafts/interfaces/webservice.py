# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice.

There is a declaration in ZCML somewhere that looks like:
  <webservice:register module="lp.crafts.interfaces.webservice" />

which tells `lazr.restful` that it should look for webservice exports here.
"""

__all__ = [
    "ICraftRecipe",
    "ICraftRecipeBuild",
    "ICraftRecipeBuildRequest",
    "ICraftRecipeSet",
]

from lp.crafts.interfaces.craftrecipe import (
    ICraftRecipe,
    ICraftRecipeBuildRequest,
    ICraftRecipeSet,
    ICraftRecipeView,
)
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_reference_property,
)

# ICraftRecipeBuildRequest
patch_reference_property(ICraftRecipeBuildRequest, "recipe", ICraftRecipe)
patch_collection_property(
    ICraftRecipeBuildRequest, "builds", ICraftRecipeBuild
)

# ICraftRecipeView
patch_collection_property(ICraftRecipeView, "builds", ICraftRecipeBuild)
patch_collection_property(
    ICraftRecipeView, "completed_builds", ICraftRecipeBuild
)
patch_collection_property(
    ICraftRecipeView, "pending_builds", ICraftRecipeBuild
)
