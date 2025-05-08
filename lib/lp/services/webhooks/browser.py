# Copyright 2015-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webhook browser and API classes."""

__all__ = [
    "WebhookNavigation",
    "WebhookTargetNavigationMixin",
]

from lazr.restful.interface import use_template
from lazr.restful.interfaces import IJSONRequestCache
from zope.component import getUtility
from zope.interface import Interface

from lp.app.browser.launchpadform import (
    LaunchpadEditFormView,
    LaunchpadFormView,
    action,
)
from lp.app.widgets.itemswidgets import WebhookCheckboxWidget
from lp.code.interfaces.gitrepository import IGitRepository
from lp.services.propertycache import cachedproperty
from lp.services.webapp import (
    LaunchpadView,
    Navigation,
    canonical_url,
    stepthrough,
)
from lp.services.webapp.batching import (
    BatchNavigator,
    StormRangeFactory,
    get_batch_properties_for_json_cache,
)
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webhooks.interfaces import IWebhook, IWebhookSet


class WebhookNavigation(Navigation):
    usedfor = IWebhook

    @stepthrough("+delivery")
    def traverse_delivery(self, id):
        try:
            id = int(id)
        except ValueError:
            return None
        return self.context.getDelivery(id)


class WebhookTargetNavigationMixin:
    @stepthrough("+webhook")
    def traverse_webhook(self, id):
        try:
            id = int(id)
        except ValueError:
            return None
        webhook = getUtility(IWebhookSet).getByID(id)
        if webhook is None or webhook.target != self.context:
            return None
        return webhook


class WebhooksView(LaunchpadView):
    @property
    def page_title(self):
        return "Webhooks"

    @property
    def label(self):
        return "Webhooks for %s" % self.context.display_name

    @cachedproperty
    def batchnav(self):
        return BatchNavigator(
            getUtility(IWebhookSet).findByTarget(self.context), self.request
        )


class WebhooksBreadcrumb(Breadcrumb):
    text = "Webhooks"

    @property
    def url(self):
        return canonical_url(self.context, view_name="+webhooks")

    @property
    def inside(self):
        return self.context


class WebhookBreadcrumb(Breadcrumb):
    @property
    def text(self):
        return self.context.delivery_url

    @property
    def inside(self):
        return WebhooksBreadcrumb(self.context.target)


class WebhookEditSchema(Interface):
    use_template(
        IWebhook,
        include=[
            "delivery_url",
            "active",
            "event_types",
            "secret",
            "git_ref_pattern",
        ],
    )


class WebhookAddView(LaunchpadFormView):
    page_title = label = "Add webhook"

    schema = WebhookEditSchema
    custom_widget_event_types = WebhookCheckboxWidget
    next_url = None

    @property
    def field_names(self):
        field_names = ["delivery_url", "event_types", "active", "secret"]

        # Only show `git_ref_pattern` in webhooks targeted at Git Repositories
        if IGitRepository.providedBy(self.context):
            field_names.append("git_ref_pattern")

        return field_names

    @property
    def inside_breadcrumb(self):
        return WebhooksBreadcrumb(self.context)

    @property
    def initial_values(self):
        return {
            "active": True,
            "event_types": self.context.default_webhook_event_types,
        }

    @property
    def cancel_url(self):
        return canonical_url(self.context, view_name="+webhooks")

    @action("Add webhook", name="new")
    def new_action(self, action, data):
        webhook = self.context.newWebhook(
            registrant=self.user,
            delivery_url=data["delivery_url"],
            event_types=data["event_types"],
            active=data["active"],
            secret=data["secret"],
            git_ref_pattern=data.get("git_ref_pattern"),
        )
        self.next_url = canonical_url(webhook)


class WebhookView(LaunchpadEditFormView):
    label = "Manage webhook"

    schema = WebhookEditSchema
    custom_widget_event_types = WebhookCheckboxWidget

    @property
    def field_names(self):
        # XXX wgrant 2015-08-04: Need custom widget for secret.
        field_names = ["delivery_url", "event_types", "active"]

        # Only show `git_ref_pattern` in webhooks targeted at Git Repositories
        if IGitRepository.providedBy(self.context.target):
            field_names.append("git_ref_pattern")

        return field_names

    def initialize(self):
        super().initialize()
        cache = IJSONRequestCache(self.request)
        cache.objects["deliveries"] = list(self.deliveries.batch)
        cache.objects.update(
            get_batch_properties_for_json_cache(self, self.deliveries)
        )

    @cachedproperty
    def deliveries(self):
        return BatchNavigator(
            self.context.deliveries,
            self.request,
            hide_counts=True,
            range_factory=StormRangeFactory(self.context.deliveries),
        )

    @property
    def next_url(self):
        # The edit form is the default view, so the URL doesn't need the
        # normal view name suffix.
        return canonical_url(self.context)

    @property
    def adapters(self):
        return {self.schema: self.context}

    @action("Save webhook", name="save")
    def save_action(self, action, data):
        self.updateContextFromData(data)


class WebhookDeleteView(LaunchpadFormView):
    schema = Interface
    next_url = None

    page_title = label = "Delete webhook"

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @action("Delete webhook", name="delete")
    def delete_action(self, action, data):
        target = self.context.target
        self.context.destroySelf()
        self.request.response.addNotification(
            "Webhook for %s deleted." % self.context.delivery_url
        )
        self.next_url = canonical_url(target, view_name="+webhooks")
