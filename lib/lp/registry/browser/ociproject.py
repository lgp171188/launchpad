# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views, menus, and traversal related to `OCIProject`s."""

__all__ = [
    "OCIProjectBreadcrumb",
    "OCIProjectContextMenu",
    "OCIProjectFacets",
    "OCIProjectNavigation",
    "OCIProjectNavigationMenu",
    "OCIProjectURL",
]

from urllib.parse import urlsplit, urlunsplit

from breezy import urlutils
from zope.component import getUtility
from zope.interface import implementer

from lp.app.browser.launchpadform import (
    LaunchpadEditFormView,
    LaunchpadFormView,
    action,
)
from lp.app.browser.tales import CustomizableFormatter
from lp.app.errors import NotFoundError
from lp.app.interfaces.headings import IHeadingBreadcrumb
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from lp.code.browser.vcslisting import TargetDefaultVCSNavigationMixin
from lp.code.interfaces.gitrepository import IGitRepositorySet
from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.registry.enums import DistributionDefaultTraversalPolicy
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.ociproject import (
    OCI_PROJECT_ALLOW_CREATE,
    IOCIProject,
    IOCIProjectSet,
    OCIProjectCreateFeatureDisabled,
)
from lp.registry.interfaces.ociprojectname import (
    IOCIProjectName,
    IOCIProjectNameSet,
)
from lp.registry.interfaces.product import IProduct
from lp.services.config import config
from lp.services.features import getFeatureFlag
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    ContextMenu,
    LaunchpadView,
    Link,
    Navigation,
    NavigationMenu,
    StandardLaunchpadFacets,
    canonical_url,
    enabled_with_permission,
    stepthrough,
)
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.batching import BatchNavigator
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import (
    ICanonicalUrlData,
    IMultiFacetedBreadcrumb,
)


@implementer(ICanonicalUrlData)
class OCIProjectURL:
    """OCI project URL creation rules.

    The canonical URL for an OCI project in a distribution depends on the
    values of `default_traversal_policy` and `redirect_default_traversal` on
    the context distribution.
    """

    rootsite = None

    def __init__(self, context):
        self.context = context

    @property
    def inside(self):
        return self.context.pillar

    @property
    def path(self):
        if self.context.distribution is not None:
            policy = self.context.distribution.default_traversal_policy
            if (
                policy == DistributionDefaultTraversalPolicy.OCI_PROJECT
                and not self.context.distribution.redirect_default_traversal
            ):
                return self.context.name
        return "+oci/%s" % self.context.name


def getPillarFieldName(pillar):
    if IDistribution.providedBy(pillar):
        return "distribution"
    elif IProduct.providedBy(pillar):
        return "project"
    raise NotImplementedError(
        "This view only supports distribution or "
        "project as pillars for OCIProject."
    )


class OCIProjectAddView(LaunchpadFormView):
    schema = IOCIProjectName
    field_names = ["name"]
    next_url = None

    def initialize(self):
        if not getFeatureFlag(
            OCI_PROJECT_ALLOW_CREATE
        ) and not self.context.canAdministerOCIProjects(self.user):
            raise OCIProjectCreateFeatureDisabled
        super().initialize()

    @action("Create OCI Project", name="create")
    def create_action(self, action, data):
        """Create a new OCI Project."""
        name = data.get("name")
        oci_project_name = getUtility(IOCIProjectNameSet).getOrCreateByName(
            name
        )
        oci_project = getUtility(IOCIProjectSet).new(
            registrant=self.user, pillar=self.context, name=oci_project_name
        )
        self.next_url = canonical_url(oci_project)

    def validate(self, data):
        super().validate(data)
        name = data.get("name", None)
        oci_project_name = getUtility(IOCIProjectNameSet).getOrCreateByName(
            name
        )

        oci_project = getUtility(IOCIProjectSet).getByPillarAndName(
            self.context, oci_project_name.name
        )
        if oci_project:
            pillar_type = getPillarFieldName(self.context)
            msg = (
                "There is already an OCI project in %s %s with this name."
                % (pillar_type, self.context.display_name)
            )
            self.setFieldError("name", msg)


class OCIProjectFormatterAPI(CustomizableFormatter):
    """Adapt `IOCIProject` objects to a formatted string."""

    _link_summary_template = "%(displayname)s"

    def _link_summary_values(self):
        displayname = self._context.display_name
        return {"displayname": displayname}


class OCIProjectNavigation(
    TargetDefaultVCSNavigationMixin, BugTargetTraversalMixin, Navigation
):
    usedfor = IOCIProject

    @stepthrough("+series")
    def traverse_series(self, name):
        series = self.context.getSeriesByName(name)
        if series is None:
            raise NotFoundError("%s is not a valid series name" % name)
        return series


@implementer(IMultiFacetedBreadcrumb, IHeadingBreadcrumb)
class OCIProjectBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IOCIProject`."""

    @property
    def text(self):
        return "%s OCI project" % self.context.name


class OCIProjectFacets(StandardLaunchpadFacets):
    usedfor = IOCIProject
    enable_only = [
        "overview",
        "branches",
        "bugs",
    ]

    def makeLink(self, text, context, view_name, site):
        site = "mainsite" if self.mainsite_only else site
        target = canonical_url(context, view_name=view_name, rootsite=site)
        return Link(target, text, site=site)

    def branches(self):
        return self.makeLink("Code", self.context, "+code", "code")

    def bugs(self):
        """Override bugs link to show the OCIProject's bug page, instead of
        the pillar's bug page.
        """
        return self.makeLink("Bugs", self.context, "+bugs", "bugs")


class OCIProjectNavigationMenu(NavigationMenu):
    """Navigation menu for OCI projects."""

    usedfor = IOCIProject

    facet = "overview"

    links = ("edit", "create_recipe", "view_recipes")

    @enabled_with_permission("launchpad.Edit")
    def edit(self):
        return Link("+edit", "Edit OCI project", icon="edit")

    @enabled_with_permission("launchpad.AnyLegitimatePerson")
    def create_recipe(self):
        return Link("+new-recipe", "Create OCI recipe", icon="add")

    def view_recipes(self):
        enabled = (
            not getUtility(IOCIRecipeSet)
            .findByOCIProject(self.context, visible_by_user=self.user)
            .is_empty()
        )
        return Link(
            "+recipes", "View all recipes", icon="info", enabled=enabled
        )


class OCIProjectContextMenu(ContextMenu):
    """Context menu for OCI projects."""

    usedfor = IOCIProject

    facet = "overview"

    links = ("create_recipe", "view_recipes")

    @enabled_with_permission("launchpad.AnyLegitimatePerson")
    def create_recipe(self):
        return Link("+new-recipe", "Create OCI recipe", icon="add")

    def view_recipes(self):
        enabled = (
            not getUtility(IOCIRecipeSet)
            .findByOCIProject(self.context, visible_by_user=self.user)
            .is_empty()
        )
        return Link(
            "+recipes", "View all recipes", icon="info", enabled=enabled
        )


class OCIProjectIndexView(LaunchpadView):
    @property
    def git_repository(self):
        return getUtility(IGitRepositorySet).getDefaultRepository(self.context)

    @property
    def git_ssh_url(self):
        base_url = urlsplit(
            urlutils.join(
                config.codehosting.git_ssh_root,
                canonical_url(self.context, force_local_path=True)[1:],
            )
        )
        url = list(base_url)
        url[1] = f"{self.user.name}@{base_url.hostname}"
        return urlunsplit(url)

    @property
    def user_can_push_default(self):
        return check_permission("launchpad.Edit", self.context)

    @property
    def official_recipes(self):
        return self.context.getOfficialRecipes(visible_by_user=self.user)

    @cachedproperty
    def official_recipe_count(self):
        return self.context.getOfficialRecipes(
            visible_by_user=self.user
        ).count()

    @cachedproperty
    def other_recipe_count(self):
        return self.context.getUnofficialRecipes(
            visible_by_user=self.user
        ).count()


class OCIProjectEditView(LaunchpadEditFormView):
    """Edit an OCI project."""

    schema = IOCIProject
    field_names = [
        "name",
    ]

    def setUpFields(self):
        pillar_key = getPillarFieldName(self.context.pillar)
        self.field_names = [pillar_key] + self.field_names

        super().setUpFields()

        # Set the correct pillar field as mandatory
        pillar_field = self.form_fields.get(pillar_key).field
        pillar_field.required = True

    @property
    def label(self):
        return "Edit %s OCI project" % self.context.name

    page_title = "Edit"

    def validate(self, data):
        super().validate(data)
        pillar_type_field = getPillarFieldName(self.context.pillar)
        pillar = data.get(pillar_type_field)
        name = data.get("name")
        if pillar and name:
            oci_project = getUtility(IOCIProjectSet).getByPillarAndName(
                pillar, name
            )
            if oci_project is not None and oci_project != self.context:
                self.setFieldError(
                    "name",
                    "There is already an OCI project in %s %s with this name."
                    % (pillar_type_field, pillar.display_name),
                )

    @action("Update OCI project", name="update")
    def update_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url


class OCIProjectSearchView(LaunchpadView):
    """Page to search for OCI projects of a given pillar."""

    page_title = ""

    @property
    def label(self):
        return "Search OCI projects in %s" % self.context.title

    @property
    def text(self):
        text = self.request.get("text", None)
        if isinstance(text, list):
            # The user may have URL hacked a query string with more than one
            # "text" parameter. We'll take the last one.
            text = text[-1]
        return text

    @property
    def search_requested(self):
        return self.text is not None

    @property
    def title(self):
        return self.context.name

    @cachedproperty
    def count(self):
        """Return the number of matched search results."""
        return self.batchnav.batch.total()

    @cachedproperty
    def batchnav(self):
        """Return the batch navigator for the search results."""
        return BatchNavigator(self.search_results, self.request)

    @cachedproperty
    def preloaded_batch(self):
        projects = self.batchnav.batch
        getUtility(IOCIProjectSet).preloadDataForOCIProjects(projects)
        return projects

    @property
    def search_results(self):
        return getUtility(IOCIProjectSet).findByPillarAndName(
            self.context, self.text or ""
        )
