# Copyright 2019 Canonical Ltd.  This software is licensed under the
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
    )
from lp.app.browser.tales import CustomizableFormatter
from lp.code.browser.vcslisting import TargetDefaultVCSNavigationMixin
from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.registry.interfaces.ociproject import (
    IOCIProject,
    IOCIProjectSet,
    )
from lp.services.webapp import (
    canonical_url,
    ContextMenu,
    enabled_with_permission,
    Link,
    Navigation,
    NavigationMenu,
    StandardLaunchpadFacets,
    )
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import IMultiFacetedBreadcrumb


class OCIProjectFormatterAPI(CustomizableFormatter):
    """Adapt `IOCIProject` objects to a formatted string."""

    _link_summary_template = '%(displayname)s'

    def _link_summary_values(self):
        displayname = self._context.display_name
        return {'displayname': displayname}


class OCIProjectNavigation(TargetDefaultVCSNavigationMixin, Navigation):

    usedfor = IOCIProject


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
