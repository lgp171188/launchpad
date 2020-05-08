# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views, menus, and traversal related to `OCIProject`s."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIProjectBreadcrumb',
    'OCIProjectContextMenu',
    'OCIProjectFacets',
    'OCIProjectNavigation',
    'OCIProjectNavigationMenu',
    ]

from zope.component import getUtility
from zope.interface import implementer

from lp.app.browser.launchpadform import (
    action,
    LaunchpadEditFormView,
    LaunchpadFormView,
    )
from lp.app.browser.tales import CustomizableFormatter
from lp.app.errors import NotFoundError
from lp.code.browser.vcslisting import TargetDefaultVCSNavigationMixin
from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.registry.interfaces.ociproject import (
    IOCIProject,
    IOCIProjectSet,
    OCI_PROJECT_ALLOW_CREATE,
    OCIProjectCreateFeatureDisabled,
    )
from lp.registry.interfaces.ociprojectname import (
    IOCIProjectName,
    IOCIProjectNameSet,
    )
from lp.services.features import getFeatureFlag
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    canonical_url,
    ContextMenu,
    enabled_with_permission,
    LaunchpadView,
    Link,
    Navigation,
    NavigationMenu,
    StandardLaunchpadFacets,
    stepthrough,
    )
from lp.services.webapp.batching import BatchNavigator
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import IMultiFacetedBreadcrumb


class OCIProjectAddView(LaunchpadFormView):

    schema = IOCIProjectName
    field_names = ['name']

    def initialize(self):
        if (not getFeatureFlag(OCI_PROJECT_ALLOW_CREATE) and not
                self.context.canAdministerOCIProjects(self.user)):
            raise OCIProjectCreateFeatureDisabled
        super(OCIProjectAddView, self).initialize()

    @action("Create OCI Project", name="create")
    def create_action(self, action, data):
        """Create a new OCI Project."""
        name = data.get('name')
        oci_project_name = getUtility(
            IOCIProjectNameSet).getOrCreateByName(name)
        oci_project = getUtility(IOCIProjectSet).new(
            registrant=self.user,
            pillar=self.context,
            name=oci_project_name)
        self.next_url = canonical_url(oci_project)

    def validate(self, data):
        super(OCIProjectAddView, self).validate(data)
        name = data.get('name', None)
        oci_project_name = getUtility(
            IOCIProjectNameSet).getOrCreateByName(name)

        oci_project = getUtility(IOCIProjectSet).getByDistributionAndName(
            self.context, oci_project_name.name)
        if oci_project:
            self.setFieldError(
                    'name',
                    'There is already an OCI project in %s with this name.' % (
                        self.context.display_name))


class OCIProjectFormatterAPI(CustomizableFormatter):
    """Adapt `IOCIProject` objects to a formatted string."""

    _link_summary_template = '%(displayname)s'

    def _link_summary_values(self):
        displayname = self._context.display_name
        return {'displayname': displayname}


class OCIProjectNavigation(TargetDefaultVCSNavigationMixin, Navigation):

    usedfor = IOCIProject

    @stepthrough('+series')
    def traverse_series(self, name):
        series = self.context.getSeriesByName(name)
        if series is None:
            raise NotFoundError('%s is not a valid series name' % name)
        return series


@implementer(IMultiFacetedBreadcrumb)
class OCIProjectBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IOCIProject`."""

    @property
    def text(self):
        return '%s OCI project' % self.context.name


class OCIProjectFacets(StandardLaunchpadFacets):

    usedfor = IOCIProject
    enable_only = [
        'overview',
        'branches',
        ]


class OCIProjectNavigationMenu(NavigationMenu):
    """Navigation menu for OCI projects."""

    usedfor = IOCIProject

    facet = 'overview'

    links = ('edit',)

    @enabled_with_permission('launchpad.Edit')
    def edit(self):
        return Link('+edit', 'Edit OCI project', icon='edit')


class OCIProjectContextMenu(ContextMenu):
    """Context menu for OCI projects."""

    usedfor = IOCIProject

    facet = 'overview'

    links = ('create_recipe', 'view_recipes')

    @enabled_with_permission('launchpad.AnyLegitimatePerson')
    def create_recipe(self):
        return Link('+new-recipe', 'Create OCI recipe', icon='add')

    def view_recipes(self):
        enabled = not getUtility(IOCIRecipeSet).findByOCIProject(
            self.context).is_empty()
        return Link(
            '+recipes', 'View OCI recipes', icon='info', enabled=enabled)


class OCIProjectEditView(LaunchpadEditFormView):
    """Edit an OCI project."""

    schema = IOCIProject
    field_names = [
        'distribution',
        'name',
        ]

    @property
    def label(self):
        return 'Edit %s OCI project' % self.context.name

    page_title = 'Edit'

    def validate(self, data):
        super(OCIProjectEditView, self).validate(data)
        distribution = data.get('distribution')
        name = data.get('name')
        if distribution and name:
            oci_project = getUtility(IOCIProjectSet).getByDistributionAndName(
                distribution, name)
            if oci_project is not None and oci_project != self.context:
                self.setFieldError(
                    'name',
                    'There is already an OCI project in %s with this name.' % (
                        distribution.display_name))

    @action('Update OCI project', name='update')
    def update_action(self, action, data):
        self.updateContextFromData(data)

    @property
    def next_url(self):
        return canonical_url(self.context)

    cancel_url = next_url


class OCIProjectSearchView(LaunchpadView):
    """Page to search for OCI projects of a given distribution."""
    page_title = ''

    @property
    def text(self):
        text = self.request.get("text", None)
        if isinstance(text, list):
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
        return getUtility(IOCIProjectSet).findByDistributionAndName(
            self.context, self.text or '')
