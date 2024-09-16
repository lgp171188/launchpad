# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Rock recipe views."""

__all__ = [
    "RockRecipeNavigation",
    "RockRecipeURL",
    "RockRecipeView",
]

from zope.component import getUtility
from zope.interface import implementer
from zope.security.interfaces import Unauthorized

from lp.registry.interfaces.personproduct import IPersonProductFactory
from lp.rocks.interfaces.rockrecipe import IRockRecipe
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuildSet
from lp.services.propertycache import cachedproperty
from lp.services.utils import seconds_since_epoch
from lp.services.webapp import LaunchpadView, Navigation, stepthrough
from lp.services.webapp.breadcrumb import Breadcrumb, NameBreadcrumb
from lp.services.webapp.interfaces import ICanonicalUrlData
from lp.soyuz.browser.build import get_build_by_id_str


@implementer(ICanonicalUrlData)
class RockRecipeURL:
    """Rock recipe URL creation rules."""

    rootsite = "mainsite"

    def __init__(self, recipe):
        self.recipe = recipe

    @property
    def inside(self):
        owner = self.recipe.owner
        project = self.recipe.project
        return getUtility(IPersonProductFactory).create(owner, project)

    @property
    def path(self):
        return "+rock/%s" % self.recipe.name


class RockRecipeNavigation(Navigation):
    usedfor = IRockRecipe

    @stepthrough("+build-request")
    def traverse_build_request(self, name):
        try:
            job_id = int(name)
        except ValueError:
            return None
        return self.context.getBuildRequest(job_id)

    @stepthrough("+build")
    def traverse_build(self, name):
        build = get_build_by_id_str(IRockRecipeBuildSet, name)
        if build is None or build.recipe != self.context:
            return None
        return build


class RockRecipeBreadcrumb(NameBreadcrumb):

    @property
    def inside(self):
        # XXX cjwatson 2021-06-04: This should probably link to an
        # appropriate listing view, but we don't have one of those yet.
        return Breadcrumb(
            self.context.project,
            text=self.context.project.display_name,
            inside=self.context.project,
        )


class RockRecipeView(LaunchpadView):
    """Default view of a rock recipe."""

    @cachedproperty
    def builds_and_requests(self):
        return builds_and_requests_for_recipe(self.context)

    @property
    def build_frequency(self):
        if self.context.auto_build:
            return "Built automatically"
        else:
            return "Built on request"

    @property
    def sorted_auto_build_channels_items(self):
        if self.context.auto_build_channels is None:
            return []
        return sorted(self.context.auto_build_channels.items())

    @property
    def store_channels(self):
        return ", ".join(self.context.store_channels)

    @property
    def user_can_see_source(self):
        try:
            return self.context.source.visibleByUser(self.user)
        except Unauthorized:
            return False


def builds_and_requests_for_recipe(recipe):
    """A list of interesting builds and build requests.

    All pending builds and pending build requests are shown, as well as up
    to 10 recent builds and recent failed build requests.  Pending items are
    ordered by the date they were created; recent items are ordered by the
    date they finished (if available) or the date they started (if the date
    they finished is not set due to an error).  This allows started but
    unfinished builds to show up in the view but be discarded as more recent
    builds become available.

    Builds that the user does not have permission to see are excluded (by
    the model code).
    """

    # We need to interleave items of different types, so SQL can't do all
    # the sorting for us.
    def make_sort_key(*date_attrs):
        def _sort_key(item):
            for date_attr in date_attrs:
                if getattr(item, date_attr, None) is not None:
                    return -seconds_since_epoch(getattr(item, date_attr))
            return 0

        return _sort_key

    items = sorted(
        list(recipe.pending_builds) + list(recipe.pending_build_requests),
        key=make_sort_key("date_created", "date_requested"),
    )
    if len(items) < 10:
        # We need to interleave two unbounded result sets, but we only need
        # enough items from them to make the total count up to 10.  It's
        # simplest to just fetch the upper bound from each set and do our
        # own sorting.
        recent_items = sorted(
            list(recipe.completed_builds[: 10 - len(items)])
            + list(recipe.failed_build_requests[: 10 - len(items)]),
            key=make_sort_key(
                "date_finished",
                "date_started",
                "date_created",
                "date_requested",
            ),
        )
        items.extend(recent_items[: 10 - len(items)])
    return items
