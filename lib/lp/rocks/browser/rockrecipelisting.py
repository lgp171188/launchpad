# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base class view for rock recipe listings."""

__all__ = [
    "GitRockRecipeListingView",
    "PersonRockRecipeListingView",
    "ProjectRockRecipeListingView",
]

from zope.component import getUtility

from lp.rocks.interfaces.rockrecipe import IRockRecipeSet
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.feeds.browser import FeedsMixin
from lp.services.propertycache import cachedproperty
from lp.services.webapp import LaunchpadView
from lp.services.webapp.batching import BatchNavigator


class RockRecipeListingView(LaunchpadView, FeedsMixin):

    feed_types = ()

    source_enabled = True
    owner_enabled = True

    @property
    def page_title(self):
        return "Rock recipes"

    @property
    def label(self):
        return "Rock recipes for %(displayname)s" % {
            "displayname": self.context.displayname
        }

    def initialize(self):
        super().initialize()
        recipes = getUtility(IRockRecipeSet).findByContext(
            self.context, visible_by_user=self.user
        )
        # XXX jugmac00 2024-10-06: we need to skip preloading until the
        # function is able to handle rock recipes with external git
        # repositories, see https://warthogs.atlassian.net/browse/LP-1972
        #
        # loader = partial(
        #     getUtility(IRockRecipeSet).preloadDataForRecipes, user=self.user
        # )
        # self.recipes = DecoratedResultSet(recipes, pre_iter_hook=loader)
        self.recipes = DecoratedResultSet(recipes)

    @cachedproperty
    def batchnav(self):
        return BatchNavigator(self.recipes, self.request)


class GitRockRecipeListingView(RockRecipeListingView):
    source_enabled = False

    @property
    def label(self):
        return "Rock recipes for %(display_name)s" % {
            "display_name": self.context.display_name
        }


class PersonRockRecipeListingView(RockRecipeListingView):
    owner_enabled = False


class ProjectRockRecipeListingView(RockRecipeListingView):
    pass
