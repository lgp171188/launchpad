# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""All the interfaces that are exposed through the webservice.

There is a declaration in ZCML somewhere that looks like:
  <webservice:register module="lp.rocks.interfaces.webservice" />

which tells `lazr.restful` that it should look for webservice exports here.
"""

__all__ = [
    "IRockBase",
    "IRockBaseSet",
    "IRockRecipe",
    "IRockRecipeBuild",
    "IRockRecipeBuildRequest",
    "IRockRecipeSet",
]

from lp.rocks.interfaces.rockbase import IRockBase, IRockBaseSet
from lp.rocks.interfaces.rockrecipe import (
    IRockRecipe,
    IRockRecipeBuildRequest,
    IRockRecipeSet,
    IRockRecipeView,
)
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuild
from lp.services.webservice.apihelpers import (
    patch_collection_property,
    patch_reference_property,
)

# IRockRecipeBuildRequest
patch_reference_property(IRockRecipeBuildRequest, "recipe", IRockRecipe)
patch_collection_property(IRockRecipeBuildRequest, "builds", IRockRecipeBuild)

# IRockRecipeView
patch_collection_property(IRockRecipeView, "builds", IRockRecipeBuild)
patch_collection_property(
    IRockRecipeView, "completed_builds", IRockRecipeBuild
)
patch_collection_property(IRockRecipeView, "pending_builds", IRockRecipeBuild)
