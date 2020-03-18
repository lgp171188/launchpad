# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI recipe views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeAddView',
    'OCIRecipeAdminView',
    'OCIRecipeDeleteView',
    'OCIRecipeEditView',
    'OCIRecipeNavigation',
    'OCIRecipeNavigationMenu',
    'OCIRecipeView',
    ]

from lazr.restful.interface import (
    copy_field,
    use_template,
    )
from zope.component import getUtility
from zope.interface import Interface

from lp.app.browser.launchpadform import (
    action,
    LaunchpadEditFormView,
    LaunchpadFormView,
    )
from lp.app.browser.lazrjs import InlinePersonEditPickerWidget
from lp.app.browser.tales import format_link
from lp.code.browser.widgets.gitref import GitRefWidget
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeSet,
    NoSuchOCIRecipe,
    OCI_RECIPE_WEBHOOKS_FEATURE_FLAG,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.services.features import getFeatureFlag
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    canonical_url,
    enabled_with_permission,
    LaunchpadView,
    Link,
    Navigation,
    NavigationMenu,
    stepthrough,
    )
from lp.services.webapp.breadcrumb import NameBreadcrumb
from lp.services.webhooks.browser import WebhookTargetNavigationMixin
from lp.soyuz.browser.build import get_build_by_id_str


class OCIRecipeNavigation(WebhookTargetNavigationMixin, Navigation):

    usedfor = IOCIRecipe

    @stepthrough('+build')
    def traverse_build(self, name):
        build = get_build_by_id_str(IOCIRecipeBuildSet, name)
        if build is None or build.recipe != self.context:
            return None
        return build


class OCIRecipeBreadcrumb(NameBreadcrumb):

    @property
    def inside(self):
        return self.context.oci_project


class OCIRecipeNavigationMenu(NavigationMenu):
    """Navigation menu for OCI recipes."""

    usedfor = IOCIRecipe

    facet = "overview"

    links = ("admin", "edit", "webhooks", "delete")

    @enabled_with_permission("launchpad.Admin")
    def admin(self):
        return Link("+admin", "Administer OCI recipe", icon="edit")

    @enabled_with_permission("launchpad.Edit")
    def edit(self):
        return Link("+edit", "Edit OCI recipe", icon="edit")

    @enabled_with_permission('launchpad.Edit')
    def webhooks(self):
        return Link(
            '+webhooks', 'Manage webhooks', icon='edit',
            enabled=bool(getFeatureFlag(OCI_RECIPE_WEBHOOKS_FEATURE_FLAG)))

    @enabled_with_permission("launchpad.Edit")
    def delete(self):
        return Link("+delete", "Delete OCI recipe", icon="trash-icon")


class OCIRecipeView(LaunchpadView):
    """Default view of an OCI recipe."""

    @cachedproperty
    def builds(self):
        return builds_for_recipe(self.context)

    @property
    def person_picker(self):
        field = copy_field(
            IOCIRecipe["owner"],
            vocabularyName="AllUserTeamsParticipationPlusSelfSimpleDisplay")
        return InlinePersonEditPickerWidget(
            self.context, field, format_link(self.context.owner),
            header="Change owner", step_title="Select a new owner")

    @property
    def build_frequency(self):
        if self.context.build_daily:
            return "Built daily"
        else:
            return "Built on request"


def builds_for_recipe(recipe):
    """A list of interesting builds.

    All pending builds are shown, as well as 1-10 recent builds.  Recent
    builds are ordered by date finished (if completed) or date_started (if
    date finished is not set due to an error building or other circumstance
    which resulted in the build not being completed).  This allows started
    but unfinished builds to show up in the view but be discarded as more
    recent builds become available.

    Builds that the user does not have permission to see are excluded (by
    the model code).
    """
    builds = list(recipe.pending_builds)
    if len(builds) < 10:
        builds.extend(recipe.completed_builds[:10 - len(builds)])
    return builds


class IOCIRecipeEditSchema(Interface):
    """Schema for adding or editing an OCI recipe."""

    use_template(IOCIRecipe, include=[
        "name",
        "owner",
        "description",
        "git_ref",
        "build_file",
        "build_daily",
        "require_virtualized",
        ])


class OCIRecipeAddView(LaunchpadFormView):
    """View for creating OCI recipes."""

    page_title = label = "Create a new OCI recipe"

    schema = IOCIRecipeEditSchema
    field_names = (
        "name",
        "owner",
        "description",
        "git_ref",
        "build_file",
        "build_daily",
        )
    custom_widget_git_ref = GitRefWidget

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @property
    def initial_values(self):
        """See `LaunchpadFormView`."""
        return {
            "owner": self.user,
            "build_file": "Dockerfile",
            }

    def validate(self, data):
        """See `LaunchpadFormView`."""
        super(OCIRecipeAddView, self).validate(data)
        owner = data.get("owner", None)
        name = data.get("name", None)
        if owner and name:
            if getUtility(IOCIRecipeSet).exists(owner, self.context, name):
                self.setFieldError(
                    "name",
                    "There is already an OCI recipe owned by %s in %s with "
                    "this name." % (
                        owner.display_name, self.context.display_name))

    @action("Create OCI recipe", name="create")
    def create_action(self, action, data):
        recipe = getUtility(IOCIRecipeSet).new(
            name=data["name"], registrant=self.user, owner=data["owner"],
            oci_project=self.context, git_ref=data["git_ref"],
            build_file=data["build_file"], description=data["description"])
        self.next_url = canonical_url(recipe)


class BaseOCIRecipeEditView(LaunchpadEditFormView):

    schema = IOCIRecipeEditSchema

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @action("Update OCI recipe", name="update")
    def request_action(self, action, data):
        self.updateContextFromData(data)
        self.next_url = canonical_url(self.context)

    @property
    def adapters(self):
        """See `LaunchpadFormView`."""
        return {IOCIRecipeEditSchema: self.context}


class OCIRecipeAdminView(BaseOCIRecipeEditView):
    """View for administering OCI recipes."""

    @property
    def label(self):
        return "Administer %s OCI recipe" % self.context.name

    page_title = "Administer"

    field_names = ("require_virtualized",)


class OCIRecipeEditView(BaseOCIRecipeEditView):
    """View for editing OCI recipes."""

    @property
    def label(self):
        return "Edit %s OCI recipe" % self.context.name

    page_title = "Edit"

    field_names = (
        "owner",
        "name",
        "description",
        "git_ref",
        "build_file",
        "build_daily",
        )
    custom_widget_git_ref = GitRefWidget

    def validate(self, data):
        """See `LaunchpadFormView`."""
        super(OCIRecipeEditView, self).validate(data)
        # XXX cjwatson 2020-02-18: We should permit and check moving recipes
        # between OCI projects too.
        owner = data.get("owner", None)
        name = data.get("name", None)
        if owner and name:
            try:
                recipe = getUtility(IOCIRecipeSet).getByName(
                    owner, self.context.oci_project, name)
                if recipe != self.context:
                    self.setFieldError(
                        "name",
                        "There is already an OCI recipe owned by %s in %s "
                        "with this name." % (
                            owner.display_name,
                            self.context.oci_project.display_name))
            except NoSuchOCIRecipe:
                pass


class OCIRecipeDeleteView(BaseOCIRecipeEditView):
    """View for deleting OCI recipes."""

    @property
    def label(self):
        return "Delete %s OCI recipe" % self.context.name

    page_title = "Delete"

    field_names = ()

    @action("Delete OCI recipe", name="delete")
    def delete_action(self, action, data):
        oci_project = self.context.oci_project
        self.context.destroySelf()
        self.next_url = canonical_url(oci_project)
