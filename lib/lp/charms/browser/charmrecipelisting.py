# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base class view for charm recipe listings."""

__all__ = [
    "GitCharmRecipeListingView",
    "PersonCharmRecipeListingView",
    "ProjectCharmRecipeListingView",
]

from functools import partial

from zope.component import getUtility

from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.feeds.browser import FeedsMixin
from lp.services.propertycache import cachedproperty
from lp.services.webapp import LaunchpadView
from lp.services.webapp.batching import BatchNavigator


class CharmRecipeListingView(LaunchpadView, FeedsMixin):
    feed_types = ()

    source_enabled = True
    owner_enabled = True

    @property
    def page_title(self):
        return "Charm recipes"

    @property
    def label(self):
        return "Charm recipes for %(displayname)s" % {
            "displayname": self.context.displayname
        }

    def initialize(self):
        super().initialize()
        recipes = getUtility(ICharmRecipeSet).findByContext(
            self.context, visible_by_user=self.user
        )
        loader = partial(
            getUtility(ICharmRecipeSet).preloadDataForRecipes, user=self.user
        )
        self.recipes = DecoratedResultSet(recipes, pre_iter_hook=loader)

    @cachedproperty
    def batchnav(self):
        return BatchNavigator(self.recipes, self.request)


class GitCharmRecipeListingView(CharmRecipeListingView):
    source_enabled = False

    @property
    def label(self):
        return "Charm recipes for %(display_name)s" % {
            "display_name": self.context.display_name
        }


class PersonCharmRecipeListingView(CharmRecipeListingView):
    owner_enabled = False


class ProjectCharmRecipeListingView(CharmRecipeListingView):
    pass
