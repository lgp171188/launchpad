# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI recipe views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeAddView',
    'OCIRecipeAdminView',
    'OCIRecipeContextMenu',
    'OCIRecipeDeleteView',
    'OCIRecipeEditView',
    'OCIRecipeNavigation',
    'OCIRecipeNavigationMenu',
    'OCIRecipeRequestBuildsView',
    'OCIRecipeView',
    ]

from lazr.restful.interface import (
    copy_field,
    use_template,
    )
from zope.component import getUtility
from zope.interface import Interface
from zope.schema import (
    Choice,
    List,
    )

from lp.app.browser.launchpadform import (
    action,
    LaunchpadEditFormView,
    LaunchpadFormView,
    )
from lp.app.browser.lazrjs import InlinePersonEditPickerWidget
from lp.app.browser.tales import format_link
from lp.app.widgets.itemswidgets import LabeledMultiCheckBoxWidget
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.code.browser.widgets.gitref import GitRefWidget
from lp.oci.interfaces.ocipushrule import IOCIPushRuleSet
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeSet,
    NoSuchOCIRecipe,
    OCI_RECIPE_ALLOW_CREATE,
    OCI_RECIPE_WEBHOOKS_FEATURE_FLAG,
    OCIRecipeBuildAlreadyPending,
    OCIRecipeFeatureDisabled,
    )
from lp.oci.interfaces.ocirecipebuild import IOCIRecipeBuildSet
from lp.services.features import getFeatureFlag
from lp.services.helpers import english_list
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    canonical_url,
    ContextMenu,
    enabled_with_permission,
    LaunchpadView,
    Link,
    Navigation,
    NavigationMenu,
    stepthrough,
    structured,
    )
from lp.services.webapp.batching import BatchNavigator
from lp.services.webapp.breadcrumb import NameBreadcrumb
from lp.services.webhooks.browser import WebhookTargetNavigationMixin
from lp.soyuz.browser.archive import EnableProcessorsMixin
from lp.soyuz.browser.build import get_build_by_id_str


class OCIRecipeNavigation(WebhookTargetNavigationMixin, Navigation):

    usedfor = IOCIRecipe

    @stepthrough('+build-request')
    def traverse_build_request(self, name):
        try:
            job_id = int(name)
        except ValueError:
            return None
        return self.context.getBuildRequest(job_id)

    @stepthrough('+build')
    def traverse_build(self, name):
        build = get_build_by_id_str(IOCIRecipeBuildSet, name)
        if build is None or build.recipe != self.context:
            return None
        return build

    @stepthrough('+push-rule')
    def traverse_pushrule(self, id):
        id = int(id)
        return getUtility(IOCIPushRuleSet).getByID(id)


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


class OCIRecipeContextMenu(ContextMenu):
    """Context menu for OCI recipes."""

    usedfor = IOCIRecipe

    facet = 'overview'

    links = ('request_builds',)

    @enabled_with_permission('launchpad.Edit')
    def request_builds(self):
        return Link('+request-builds', 'Request builds', icon='add')


class OCIRecipeSetView(LaunchpadView):
    """Default view for the list of OCI recipes of an OCI project."""
    page_title = 'Recipes'
    description = 'These are the recipes created for this OCI project.'

    @property
    def title(self):
        return self.context.name

    @cachedproperty
    def recipes(self):
        recipes = getUtility(IOCIRecipeSet).findByOCIProject(self.context)
        return recipes.order_by('name')

    @property
    def recipes_navigator(self):
        return BatchNavigator(self.recipes, self.request)

    @cachedproperty
    def count(self):
        return self.recipes_navigator.batch.total()

    @property
    def preloaded_recipes_batch(self):
        recipes = self.recipes_navigator.batch
        getUtility(IOCIRecipeSet).preloadDataForOCIRecipes(recipes)
        return recipes


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


def new_builds_notification_text(builds, already_pending=None):
    nr_builds = len(builds)
    if not nr_builds:
        builds_text = "All requested builds are already queued."
    elif nr_builds == 1:
        builds_text = "1 new build has been queued."
    else:
        builds_text = "%d new builds have been queued." % nr_builds
    if nr_builds and already_pending:
        return structured("<p>%s</p><p>%s</p>", builds_text, already_pending)
    else:
        return builds_text


class OCIRecipeRequestBuildsView(LaunchpadFormView):
    """A view for requesting builds of an OCI recipe."""

    @property
    def label(self):
        return 'Request builds for %s' % self.context.name

    page_title = 'Request builds'

    class schema(Interface):
        """Schema for requesting a build."""

        distro_arch_series = List(
            Choice(vocabulary='OCIRecipeDistroArchSeries'),
            title='Architectures', required=True)

    custom_widget_distro_arch_series = LabeledMultiCheckBoxWidget

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def initial_values(self):
        """See `LaunchpadFormView`."""
        return {'distro_arch_series': self.context.getAllowedArchitectures()}

    def validate(self, data):
        """See `LaunchpadFormView`."""
        arches = data.get('distro_arch_series', [])
        if not arches:
            self.setFieldError(
                'distro_arch_series',
                'You need to select at least one architecture.')

    def requestBuilds(self, data):
        """User action for requesting a number of builds.

        We raise exceptions for most errors, but if there's already a
        pending build for a particular architecture, we simply record that
        so that other builds can be queued and a message displayed to the
        caller.
        """
        informational = {}
        builds = []
        already_pending = []
        for arch in data['distro_arch_series']:
            try:
                build = self.context.requestBuild(self.user, arch)
                builds.append(build)
            except OCIRecipeBuildAlreadyPending:
                already_pending.append(arch)
        if already_pending:
            informational['already_pending'] = (
                "An identical build is already pending for %s." %
                english_list(arch.architecturetag for arch in already_pending))
        return builds, informational

    @action('Request builds', name='request')
    def request_action(self, action, data):
        builds, informational = self.requestBuilds(data)
        already_pending = informational.get('already_pending')
        notification_text = new_builds_notification_text(
            builds, already_pending)
        self.request.response.addNotification(notification_text)
        self.next_url = self.cancel_url


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


class OCIRecipeAddView(LaunchpadFormView, EnableProcessorsMixin):
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

    def initialize(self):
        super(OCIRecipeAddView, self).initialize()
        if not getFeatureFlag(OCI_RECIPE_ALLOW_CREATE):
            raise OCIRecipeFeatureDisabled()

    def setUpFields(self):
        """See `LaunchpadFormView`."""
        super(OCIRecipeAddView, self).setUpFields()
        self.form_fields += self.createEnabledProcessors(
            getUtility(IProcessorSet).getAll(),
            "The architectures that this OCI recipe builds for. Some "
            "architectures are restricted and may only be enabled or "
            "disabled by administrators.")

    def setUpWidgets(self):
        """See `LaunchpadFormView`."""
        super(OCIRecipeAddView, self).setUpWidgets()
        self.widgets["processors"].widget_class = "processors"

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
            "processors": [
                p for p in getUtility(IProcessorSet).getAll()
                if p.build_by_default],
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
            build_file=data["build_file"], description=data["description"],
            build_daily=data["build_daily"], processors=data["processors"])
        self.next_url = canonical_url(recipe)


class BaseOCIRecipeEditView(LaunchpadEditFormView):

    schema = IOCIRecipeEditSchema

    @property
    def cancel_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @action("Update OCI recipe", name="update")
    def request_action(self, action, data):
        new_processors = data.get("processors")
        if new_processors is not None:
            if set(self.context.processors) != set(new_processors):
                self.context.setProcessors(
                    new_processors, check_permissions=True, user=self.user)
            del data["processors"]
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


class OCIRecipeEditView(BaseOCIRecipeEditView, EnableProcessorsMixin):
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

    def setUpFields(self):
        """See `LaunchpadFormView`."""
        super(OCIRecipeEditView, self).setUpFields()
        self.form_fields += self.createEnabledProcessors(
            self.context.available_processors,
            "The architectures that this OCI recipe builds for. Some "
            "architectures are restricted and may only be enabled or "
            "disabled by administrators.")

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
        if "processors" in data:
            available_processors = set(self.context.available_processors)
            widget = self.widgets["processors"]
            for processor in self.context.processors:
                if processor not in data["processors"]:
                    if processor not in available_processors:
                        # This processor is not currently available for
                        # selection, but is enabled.  Leave it untouched.
                        data["processors"].append(processor)
                    elif processor.name in widget.disabled_items:
                        # This processor is restricted and currently
                        # enabled. Leave it untouched.
                        data["processors"].append(processor)


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
