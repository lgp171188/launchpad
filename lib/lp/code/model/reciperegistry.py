# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementation of recipe registry."""

__all__ = [
    "RecipeRegistry",
    "recipe_registry",
]

from zope.component import getGlobalSiteManager, provideUtility
from zope.interface import implementer

from lp.code.interfaces.reciperegistry import IRecipeRegistry


@implementer(IRecipeRegistry)
class RecipeRegistry:
    def __init__(self):
        self.recipe_types = []
        getGlobalSiteManager().registerUtility(self, IRecipeRegistry)

    def register_recipe_type(self, utility, message):
        def decorator(cls):
            self.recipe_types.append((utility, message, cls))
            provideUtility(cls(), utility)
            return cls

        return decorator

    def get_recipe_types(self):
        return self.recipe_types


recipe_registry = RecipeRegistry()
