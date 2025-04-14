# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mixins for browser classes for objects that have rock recipes."""

__all__ = [
    "HasRockRecipesMenuMixin",
    "HasRockRecipesViewMixin",
]

from zope.component import getUtility

from lp.code.interfaces.gitrepository import IGitRepository
from lp.rocks.interfaces.rockrecipe import IRockRecipeSet
from lp.services.webapp import Link, canonical_url
from lp.services.webapp.escaping import structured


class HasRockRecipesMenuMixin:
    """A mixin for context menus for objects that have rock recipes."""

    def view_rock_recipes(self):
        text = "View rock recipes"

        # The dynamic link enablement uses a query too complex to be useful
        # So we disable it for now, for all recipe types:
        # snap, charm, source, rock and oci
        enabled = True

        # enabled = (
        #    not getUtility(IRockRecipeSet)
        #    .findByContext(self.context, visible_by_user=self.user)
        #    .is_empty()
        # )
        return Link("+rock-recipes", text, icon="info", enabled=enabled)


class HasRockRecipesViewMixin:
    """A view mixin for objects that have rock recipes."""

    @property
    def rock_recipes(self):
        return getUtility(IRockRecipeSet).findByContext(
            self.context, visible_by_user=self.user
        )

    @property
    def rock_recipes_link(self):
        """A link to rock recipes for this object."""
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
