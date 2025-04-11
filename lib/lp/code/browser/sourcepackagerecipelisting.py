# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base class view for sourcepackagerecipe listings."""

__all__ = [
    "BranchRecipeListingView",
    "HasRecipesMenuMixin",
    "PersonRecipeListingView",
    "ProductRecipeListingView",
]


from lp.code.browser.decorations import DecoratedBranch
from lp.code.interfaces.branch import IBranch
from lp.services.feeds.browser import FeedsMixin
from lp.services.webapp import LaunchpadView, Link


class HasRecipesMenuMixin:
    """A mixin for context menus for objects that implement IHasRecipes."""

    def view_recipes(self):
        text = "View source package recipes"

        # The dynamic link enablement uses a query too complex to be useful
        # So we disable it for now, for all recipe types:
        # snap, charm, source, rock and oci
        enabled = True

        # if self.context.recipes.count():
        #    enabled = True
        return Link(
            "+recipes", text, icon="info", enabled=enabled, site="code"
        )


class RecipeListingView(LaunchpadView, FeedsMixin):
    feed_types = ()

    branch_enabled = True
    owner_enabled = True

    @property
    def page_title(self):
        return "Source Package Recipes for %(display_name)s" % {
            "display_name": self.context.display_name
        }


class BranchRecipeListingView(RecipeListingView):
    branch_enabled = False

    def initialize(self):
        super().initialize()
        # Replace our context with a decorated branch, if it is not already
        # decorated.
        if IBranch.providedBy(self.context) and not isinstance(
            self.context, DecoratedBranch
        ):
            self.context = DecoratedBranch(self.context)


class PersonRecipeListingView(RecipeListingView):
    owner_enabled = False


class ProductRecipeListingView(RecipeListingView):
    pass
