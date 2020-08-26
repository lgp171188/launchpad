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
    'OCIRecipeEditPushRulesView',
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
from zope.formlib.form import FormFields
from zope.formlib.widget import (
    DisplayWidget,
    renderElement,
    )
from zope.interface import Interface
from zope.schema import (
    Bool,
    Choice,
    List,
    Password,
    TextLine,
    ValidationError,
    )

from lp.app.browser.launchpadform import (
    action,
    LaunchpadEditFormView,
    LaunchpadFormView,
    )
from lp.app.browser.lazrjs import InlinePersonEditPickerWidget
from lp.app.browser.tales import format_link
from lp.app.errors import UnexpectedFormData
from lp.app.widgets.itemswidgets import LabeledMultiCheckBoxWidget
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.code.browser.widgets.gitref import GitRefWidget
from lp.oci.interfaces.ocipushrule import (
    IOCIPushRuleSet,
    OCIPushRuleAlreadyExists,
    )
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
from lp.oci.interfaces.ociregistrycredentials import (
    IOCIRegistryCredentialsSet,
    OCIRegistryCredentialsAlreadyExist,
    user_can_edit_credentials_for_owner,
    )
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
from lp.services.webapp.authorization import check_permission
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

    links = ('request_builds', 'edit_push_rules')

    @enabled_with_permission('launchpad.Edit')
    def request_builds(self):
        return Link('+request-builds', 'Request builds', icon='add')

    @enabled_with_permission('launchpad.Edit')
    def edit_push_rules(self):
        return Link(
            '+edit-push-rules', 'Edit push rules', icon='edit')


class OCIProjectRecipesView(LaunchpadView):
    """Default view for the list of OCI recipes of an OCI project."""
    page_title = 'Recipes'

    @property
    def label(self):
        return 'OCI recipes for %s' % self.context.name

    @property
    def title(self):
        return self.context.name

    @property
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

    @cachedproperty
    def push_rules(self):
        # XXX: We need to think about rearranging the permissions on
        # OCIRegistryCredentials so that only the actual secrets are
        # secret; the registry URL and probably the username could
        # arguably be public and displayed in the table with the push rules
        # on lib/lp/oci/templates/ocirecipe-index.pt.
        # We're still not sure how this plays into
        # plans for internal registry announcements and such, so we
        # land redaction first and think about this later.
        return list(
            getUtility(IOCIPushRuleSet).findByRecipe(self.context))

    @property
    def has_push_rules(self):
        return len(self.push_rules) > 0

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


class InvisibleCredentialsWidget(DisplayWidget):
    """A widget that just displays a private icon.

    This indicates invisible credentials.
    """

    def __call__(self):
        return renderElement("span", id=self.name, cssClass="sprite private")


class OCIRecipeEditPushRulesView(LaunchpadFormView):
    """View for +ocirecipe-edit-push-rules.pt."""

    class schema(Interface):
        """Schema for editing push rules."""

    @cachedproperty
    def push_rules(self):
        return list(
            getUtility(IOCIPushRuleSet).findByRecipe(self.context))

    @property
    def has_push_rules(self):
        return len(self.push_rules) > 0

    @cachedproperty
    def can_edit_credentials(self):
        return user_can_edit_credentials_for_owner(
            self.context.owner, self.user)

    def _getFieldName(self, name, rule_id):
        """Get the combined field name for an `OCIPushRule` ID.

        In order to be able to render a table, we encode the rule ID
        in the form field name.
        """
        return "%s.%d" % (name, rule_id)

    def _parseFieldName(self, field_name):
        """Parse a combined field name as described in `_getFieldName`.

        :raises UnexpectedFormData: if the field name cannot be parsed or
            the `OCIPushRule` cannot be found.
        """
        field_bits = field_name.split(".")
        if len(field_bits) != 2:
            raise UnexpectedFormData(
                "Cannot parse field name: %s" % field_name)
        field_type = field_bits[0]
        try:
            rule_id = int(field_bits[1])
        except ValueError:
            raise UnexpectedFormData(
                "Cannot parse field name: %s" % field_name)
        return field_type, rule_id

    def setUpFields(self):
        super(OCIRecipeEditPushRulesView, self).setUpFields()
        image_name_fields = []
        url_fields = []
        private_url_fields = []
        username_fields = []
        private_username_fields = []
        password_fields = []
        delete_fields = []
        for elem in list(self.context.push_rules):
            image_name_fields.append(
                TextLine(
                    __name__=self._getFieldName('image_name', elem.id),
                    default=elem.image_name,
                    required=True, readonly=False))
            if check_permission('launchpad.View', elem.registry_credentials):
                url_fields.append(
                    TextLine(
                        __name__=self._getFieldName('url', elem.id),
                        default=elem.registry_credentials.url,
                        required=True, readonly=True))
                username_fields.append(
                    TextLine(
                        __name__=self._getFieldName('username', elem.id),
                        default=elem.registry_credentials.username,
                        required=True, readonly=True))
            else:
                private_url_fields.append(
                    TextLine(
                        __name__=self._getFieldName('url', elem.id),
                        default='', required=True, readonly=True))
                private_username_fields.append(
                    TextLine(
                        __name__=self._getFieldName('username', elem.id),
                        default='', required=True, readonly=True))
            delete_fields.append(
                Bool(
                    __name__=self._getFieldName('delete', elem.id),
                    default=False,
                    required=True, readonly=False))
        image_name_fields.append(
            TextLine(
                __name__=u'add_image_name',
                required=False, readonly=False))
        add_credentials = Choice(
            __name__='add_credentials',
            default='existing', values=('existing', 'new'),
            required=False, readonly=False)
        existing_credentials = Choice(
            vocabulary='OCIRegistryCredentials',
            required=False,
            __name__=u'existing_credentials')
        url_fields.append(
            TextLine(
                __name__=u'add_url',
                required=False, readonly=False))
        username_fields.append(
            TextLine(
                __name__=u'add_username',
                required=False, readonly=False))
        password_fields.append(
            Password(
                __name__=u'add_password',
                required=False, readonly=False))
        password_fields.append(
            Password(
                __name__=u'add_confirm_password',
                required=False, readonly=False))

        self.form_fields = (
            FormFields(*image_name_fields) +
            FormFields(*url_fields) +
            FormFields(
                *private_url_fields,
                custom_widget=InvisibleCredentialsWidget) +
            FormFields(*username_fields) +
            FormFields(
                *private_username_fields,
                custom_widget=InvisibleCredentialsWidget) +
            FormFields(*password_fields) +
            FormFields(*delete_fields) +
            FormFields(add_credentials, existing_credentials))

    def setUpWidgets(self, context=None):
        """See `LaunchpadFormView`."""
        super(OCIRecipeEditPushRulesView, self).setUpWidgets(context=context)
        for widget in self.widgets:
            widget.display_label = False
            widget.hint = None

    @property
    def label(self):
        return 'Edit OCI push rules for %s' % self.context.name

    page_title = 'Edit OCI push rules'

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    def getRuleWidgets(self, rule):
        widgets_by_name = {widget.name: widget for widget in self.widgets}
        url_field_name = (
                "field." + self._getFieldName("url", rule.id))
        image_field_name = (
                "field." + self._getFieldName("image_name", rule.id))
        username_field_name = (
                "field." + self._getFieldName("username", rule.id))
        delete_field_name = (
                "field." + self._getFieldName("delete", rule.id))
        return {
            "url": widgets_by_name[url_field_name],
            "image_name": widgets_by_name[image_field_name],
            "username": widgets_by_name[username_field_name],
            "delete": widgets_by_name[delete_field_name],
        }

    def getNewRuleWidgets(self):
        widgets_by_name = {widget.name: widget for widget in self.widgets}
        return {
            "image_name": widgets_by_name["field.add_image_name"],
            "existing_credentials":
                widgets_by_name["field.existing_credentials"],
            "url": widgets_by_name["field.add_url"],
            "username": widgets_by_name["field.add_username"],
            "password": widgets_by_name["field.add_password"],
            "confirm_password": widgets_by_name["field.add_confirm_password"],
            }

    def parseData(self, data):
        """Rearrange form data to make it easier to process."""
        parsed_data = {}
        add_image_name = data.get("add_image_name")
        add_url = data.get("add_url")
        add_username = data.get("add_username")
        add_password = data.get("add_password")
        add_confirm_password = data.get("add_confirm_password")
        add_existing_credentials = data.get("existing_credentials")

        # parse data from the Add new rule section of the form
        if (add_url or add_username or add_password or
                add_confirm_password or add_image_name or
                add_existing_credentials):
            parsed_data.setdefault(None, {
                "image_name": add_image_name,
                "url": add_url,
                "username": add_username,
                "password": add_password,
                "confirm_password": add_confirm_password,
                "existing_credentials": data["existing_credentials"],
                "add_credentials": data["add_credentials"],
                "action": "add",
            })
        # parse data from the Edit existing rule section of the form
        for field_name in sorted(
                name for name in data if name.split(".")[0] == "image_name"):
            _, rule_id = self._parseFieldName(field_name)
            image_field_name = self._getFieldName("image_name", rule_id)
            delete_field_name = self._getFieldName("delete", rule_id)
            if data.get(delete_field_name):
                action = "delete"
            else:
                action = "change"
            parsed_data.setdefault(rule_id, {
                "image_name": data.get(image_field_name),
                "action": action,
            })

        return parsed_data

    def addNewRule(self, parsed_data):
        add_data = parsed_data[None]
        image_name = add_data.get("image_name")
        url = add_data.get("url")
        password = add_data.get("password")
        confirm_password = add_data.get("confirm_password")
        username = add_data.get("username")
        existing_credentials = add_data.get("existing_credentials")
        add_credentials = add_data.get("add_credentials")

        if not image_name:
            self.setFieldError(
                "add_image_name",
                "Image name must be set.")
        else:
            if add_credentials == "existing":
                if not existing_credentials:
                    return
                try:
                    getUtility(IOCIPushRuleSet).new(
                        self.context,
                        existing_credentials,
                        image_name)
                except OCIPushRuleAlreadyExists:
                    self.setFieldError("add_image_name",
                                       "A push rule already exists"
                                       " with the same URL, image"
                                       " name and credentials.")
            elif add_credentials == "new":
                if not url:
                    self.setFieldError(
                        "add_url",
                        "Registry URL must be set.")
                else:
                    if password != confirm_password:
                        self.setFieldError(
                            "password",
                            "Please make sure the new password matches"
                            " the confirm password field.")
                        return
                    try:
                        credentials = getUtility(
                            IOCIRegistryCredentialsSet).getOrCreate(
                            owner=self.context.owner,
                            url=url,
                            credentials={
                                'username': username,
                                'password': password})
                        try:
                            getUtility(IOCIPushRuleSet).new(
                                self.context, credentials, image_name)
                        except OCIPushRuleAlreadyExists:
                            self.setFieldError(
                                "add_image_name",
                                "A push rule already exists with the "
                                "same URL, image name, and "
                                "credentials.")
                    except OCIRegistryCredentialsAlreadyExist:
                        self.setFieldError(
                            "add_url",
                            "Credentials already exist with"
                            " the same URL and username.")

                    except ValidationError:
                        self.setFieldError(
                            "add_url", "Not a valid URL.")

    def updatePushRulesFromData(self, parsed_data):
        rules_map = {
            rule.id: rule
            for rule in self.context.push_rules}
        for rule_id, parsed_rules in parsed_data.items():
            rule = rules_map.get(rule_id)
            action = parsed_rules["action"]

            if action == "change":
                image_name = parsed_rules["image_name"]
                if not image_name:
                    self.setFieldError(
                        self._getFieldName(
                            "image_name", rule_id),
                        "Image name must be set.")
                else:
                    if rule.image_name != image_name:
                        rule.setNewImageName(image_name)
            elif action == "delete":
                rule.destroySelf()
            elif action == "add":
                self.addNewRule(parsed_data)
            else:
                raise AssertionError("unknown action: %s" % action)

    @action("Save")
    def save(self, action, data):
        parsed_data = self.parseData(data)
        self.updatePushRulesFromData(parsed_data)

        if not self.errors:
            self.request.response.addNotification("Saved push rules")
            self.next_url = canonical_url(self.context)


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
        "allow_internet",
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

    field_names = ("require_virtualized", "allow_internet")


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
