# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mixins for browser classes for objects that have charm recipes."""

__all__ = [
    "HasCharmRecipesMenuMixin",
    "HasCharmRecipesViewMixin",
]

from zope.component import getUtility

from lp.charms.interfaces.charmrecipe import (
    CHARM_RECIPE_ALLOW_CREATE,
    CHARM_RECIPE_PRIVATE_FEATURE_FLAG,
    ICharmRecipeSet,
)
from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.features import getFeatureFlag
from lp.services.webapp import Link, canonical_url
from lp.services.webapp.escaping import structured


class HasCharmRecipesMenuMixin:
    """A mixin for context menus for objects that have charm recipes."""

    def view_charm_recipes(self):
        text = "View charm recipes"

        # The dynamic link enablement uses a query too complex to be useful
        # So we disable it for now, for all recipe types:
        # snap, charm, source, rock and oci
        enabled = True

        # enabled = (
        #   not getUtility(ICharmRecipeSet)
        #   .findByContext(self.context, visible_by_user=self.user)
        #   .is_empty()
        # )

        return Link("+charm-recipes", text, icon="info", enabled=enabled)

    def create_charm_recipe(self):
        # Only enabled for private contexts if the
        # charm.recipe.allow_private flag is enabled.
        enabled = bool(getFeatureFlag(CHARM_RECIPE_ALLOW_CREATE)) and (
            not self.context.private
            or bool(getFeatureFlag(CHARM_RECIPE_PRIVATE_FEATURE_FLAG))
        )

        text = "Create charm recipe"
        return Link("+new-charm-recipe", text, enabled=enabled, icon="add")


class HasCharmRecipesViewMixin:
    """A view mixin for objects that have charm recipes."""

    @property
    def charm_recipes(self):
        return getUtility(ICharmRecipeSet).findByContext(
            self.context, visible_by_user=self.user
        )

    @property
    def charm_recipes_link(self):
        """A link to charm recipes for this object."""
        count = self.charm_recipes.count()
        if IGitRepository.providedBy(self.context):
            context_type = "repository"
        else:
            context_type = "branch"
        if count == 0:
            # Nothing to link to.
            return "No charm recipes using this %s." % context_type
        elif count == 1:
            # Link to the single charm recipe.
            return structured(
                '<a href="%s">1 charm recipe</a> using this %s.',
                canonical_url(self.charm_recipes.one()),
                context_type,
            ).escapedtext
        else:
            # Link to a charm recipe listing.
            return structured(
                '<a href="+charm-recipes">%s charm recipes</a> using this %s.',
                count,
                context_type,
            ).escapedtext
