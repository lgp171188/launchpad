# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for recipe registry."""

__all__ = [
    "IRecipeSet",
    "IRecipeRegistry",
]

from zope.interface import Attribute, Interface


class IRecipeSet(Interface):
    """Base interface for recipe sets."""

    def findByGitRepository(repository):
        """Find recipes that use the given repository."""

    def detachFromGitRepository(repository):
        """Detach recipes from the given repository."""


class IRecipeRegistry(Interface):
    """A registry for recipe types."""

    recipe_types = Attribute("List of registered recipe types")

    def register_recipe_type(utility_name, message):
        """Register a new recipe type."""

    def get_recipe_types():
        """Get all registered recipe types."""
