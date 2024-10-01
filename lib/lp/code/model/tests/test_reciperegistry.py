# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the RecipeRegistry."""

from zope.component import getGlobalSiteManager, getUtility
from zope.interface import Interface

from lp.code.interfaces.reciperegistry import IRecipeRegistry
from lp.code.model.reciperegistry import RecipeRegistry
from lp.testing import TestCase


class TestRecipeRegistry(TestCase):

    def setUp(self):
        super().setUp()
        self.registry = RecipeRegistry()

    def tearDown(self):
        getGlobalSiteManager().unregisterUtility(
            self.registry, IRecipeRegistry
        )
        super().tearDown()

    def test_register_recipe_type(self):
        class IDummyRecipe(Interface):
            pass

        @self.registry.register_recipe_type(IDummyRecipe, "Dummy Recipe")
        class DummyRecipe:
            pass

        self.assertEqual(1, len(self.registry.recipe_types))
        self.assertEqual(
            (IDummyRecipe, "Dummy Recipe", DummyRecipe),
            self.registry.recipe_types[0],
        )
        self.assertIsInstance(getUtility(IDummyRecipe), DummyRecipe)

    def test_get_recipe_types(self):
        class IDummyRecipe1(Interface):
            pass

        class IDummyRecipe2(Interface):
            pass

        @self.registry.register_recipe_type(IDummyRecipe1, "Dummy Recipe 1")
        class DummyRecipe1:
            pass

        @self.registry.register_recipe_type(IDummyRecipe2, "Dummy Recipe 2")
        class DummyRecipe2:
            pass

        recipe_types = self.registry.get_recipe_types()
        self.assertEqual(2, len(recipe_types))
        self.assertEqual(
            [
                (IDummyRecipe1, "Dummy Recipe 1", DummyRecipe1),
                (IDummyRecipe2, "Dummy Recipe 2", DummyRecipe2),
            ],
            recipe_types,
        )

    def test_global_recipe_registry(self):
        from lp.code.model.reciperegistry import recipe_registry

        self.assertIsInstance(recipe_registry, RecipeRegistry)
        self.assertIsInstance(getUtility(IRecipeRegistry), RecipeRegistry)
