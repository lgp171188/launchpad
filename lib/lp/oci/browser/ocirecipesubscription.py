# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI recipe subscription views."""

__all__ = ["OCIRecipePortletSubscribersContent"]

from zope.component import getUtility
from zope.formlib.form import action
from zope.security.interfaces import ForbiddenAttribute

from lp.app.browser.launchpadform import (
    LaunchpadEditFormView,
    LaunchpadFormView,
)
from lp.oci.interfaces.ocirecipesubscription import IOCIRecipeSubscription
from lp.registry.interfaces.person import IPersonSet
from lp.services.webapp import LaunchpadView, canonical_url
from lp.services.webapp.authorization import (
    check_permission,
    precache_permission_for_objects,
)


class OCIRecipePortletSubscribersContent(LaunchpadView):
    """View for the contents for the subscribers portlet."""

    def subscriptions(self):
        """Return a decorated list of OCI recipe subscriptions."""

        # Cache permissions so private subscribers can be rendered.
        # The security adaptor will do the job also but we don't want or
        # need the expense of running several complex SQL queries.
        subscriptions = list(self.context.subscriptions)
        person_ids = [sub.person.id for sub in subscriptions]
        list(
            getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                person_ids, need_validity=True
            )
        )
        if self.user is not None:
            subscribers = [
                subscription.person for subscription in subscriptions
            ]
            precache_permission_for_objects(
                self.request, "launchpad.LimitedView", subscribers
            )

        visible_subscriptions = [
            subscription
            for subscription in subscriptions
            if check_permission("launchpad.LimitedView", subscription.person)
        ]
        return sorted(
            visible_subscriptions,
            key=lambda subscription: subscription.person.displayname,
        )


class RedirectToOCIRecipeMixin:
    @property
    def next_url(self):
        if self.ocirecipe.visibleByUser(self.user):
            return canonical_url(self.ocirecipe)
        # If the subscriber can no longer see the OCI recipe, tries to
        # redirect to the pillar page.
        try:
            pillar = self.ocirecipe.pillar
            if pillar is not None and pillar.userCanLimitedView(self.user):
                return canonical_url(pillar)
        except ForbiddenAttribute:
            pass
        # If not possible, redirect user back to its own page.
        return canonical_url(self.user)

    cancel_url = next_url


class OCIRecipeSubscriptionEditView(
    RedirectToOCIRecipeMixin, LaunchpadEditFormView
):
    """The view for editing OCI recipe subscriptions."""

    schema = IOCIRecipeSubscription
    field_names = []

    @property
    def page_title(self):
        return (
            "Edit subscription to OCI recipe %s" % self.ocirecipe.displayname
        )

    @property
    def label(self):
        return (
            "Edit subscription to OCI recipe for %s" % self.person.displayname
        )

    def initialize(self):
        self.ocirecipe = self.context.recipe
        self.person = self.context.person
        super().initialize()

    @action("Unsubscribe", name="unsubscribe")
    def unsubscribe_action(self, action, data):
        """Unsubscribe the team from the OCI recipe."""
        self.ocirecipe.unsubscribe(self.person, self.user)
        self.request.response.addNotification(
            "%s has been unsubscribed from this OCI recipe."
            % self.person.displayname
        )


class _OCIRecipeSubscriptionCreationView(
    RedirectToOCIRecipeMixin, LaunchpadFormView
):
    """Contains the common functionality of the Add and Edit views."""

    schema = IOCIRecipeSubscription
    field_names = []

    def initialize(self):
        self.ocirecipe = self.context
        super().initialize()


class OCIRecipeSubscriptionAddView(_OCIRecipeSubscriptionCreationView):
    page_title = label = "Subscribe to OCI recipe"

    @action("Subscribe")
    def subscribe(self, action, data):
        # To catch the stale post problem, check that the user is not
        # subscribed before continuing.
        if self.context.getSubscription(self.user) is not None:
            self.request.response.addNotification(
                "You are already subscribed to this OCI recipe."
            )
        else:
            self.context.subscribe(self.user, self.user)
            self.request.response.addNotification(
                "You have subscribed to this OCI recipe."
            )


class OCIRecipeSubscriptionAddOtherView(_OCIRecipeSubscriptionCreationView):
    """View used to subscribe someone other than the current user."""

    field_names = ["person"]
    for_input = True

    # Since we are subscribing other people, the current user
    # is never considered subscribed.
    user_is_subscribed = False

    page_title = label = "Subscribe to OCI recipe"

    def validate(self, data):
        if "person" in data:
            person = data["person"]
            subscription = self.context.getSubscription(person)
            if subscription is None and not self.context.userCanBeSubscribed(
                person
            ):
                self.setFieldError(
                    "person",
                    "Open and delegated teams cannot be subscribed to "
                    "private OCI recipes.",
                )

    @action("Subscribe", name="subscribe_action")
    def subscribe_action(self, action, data):
        """Subscribe the specified user to the OCI recipe."""
        person = data["person"]
        subscription = self.context.getSubscription(person)
        if subscription is None:
            self.context.subscribe(person, self.user)
            self.request.response.addNotification(
                "%s has been subscribed to this OCI recipe."
                % person.displayname
            )
        else:
            self.request.response.addNotification(
                "%s was already subscribed to this OCI recipe."
                % person.displayname
            )
