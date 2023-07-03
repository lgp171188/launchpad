# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap subscription views."""

__all__ = ["SnapPortletSubscribersContent"]

from zope.component import getUtility
from zope.formlib.form import action
from zope.security.interfaces import ForbiddenAttribute

from lp.app.browser.launchpadform import (
    LaunchpadEditFormView,
    LaunchpadFormView,
)
from lp.registry.interfaces.person import IPersonSet
from lp.services.webapp import LaunchpadView, canonical_url
from lp.services.webapp.authorization import (
    check_permission,
    precache_permission_for_objects,
)
from lp.snappy.interfaces.snapsubscription import ISnapSubscription


class SnapPortletSubscribersContent(LaunchpadView):
    """View for the contents for the subscribers portlet."""

    def subscriptions(self):
        """Return a decorated list of Snap recipe subscriptions."""

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


class RedirectToSnapMixin:
    @property
    def next_url(self):
        if self.snap.visibleByUser(self.user):
            return canonical_url(self.snap)
        # If the subscriber can no longer see the Snap recipe, tries to
        # redirect to the project page.
        try:
            project = self.snap.project
            if project is not None and project.userCanLimitedView(self.user):
                return canonical_url(self.snap.project)
        except ForbiddenAttribute:
            pass
        # If not possible, redirect user back to its own page.
        return canonical_url(self.user)

    cancel_url = next_url


class SnapSubscriptionEditView(RedirectToSnapMixin, LaunchpadEditFormView):
    """The view for editing Snap recipe subscriptions."""

    schema = ISnapSubscription
    field_names = []

    @property
    def page_title(self):
        return "Edit subscription to snap recipe %s" % self.snap.displayname

    @property
    def label(self):
        return (
            "Edit subscription to snap recipe for %s" % self.person.displayname
        )

    def initialize(self):
        self.snap = self.context.snap
        self.person = self.context.person
        super().initialize()

    @action("Unsubscribe", name="unsubscribe")
    def unsubscribe_action(self, action, data):
        """Unsubscribe the team from the Snap recipe."""
        self.snap.unsubscribe(self.person, self.user)
        self.request.response.addNotification(
            "%s has been unsubscribed from this snap recipe."
            % self.person.displayname
        )


class _SnapSubscriptionCreationView(RedirectToSnapMixin, LaunchpadFormView):
    """Contains the common functionality of the Add and Edit views."""

    schema = ISnapSubscription
    field_names = []

    def initialize(self):
        self.snap = self.context
        super().initialize()


class SnapSubscriptionAddView(_SnapSubscriptionCreationView):
    page_title = label = "Subscribe to snap recipe"

    @action("Subscribe")
    def subscribe(self, action, data):
        # To catch the stale post problem, check that the user is not
        # subscribed before continuing.
        if self.context.hasSubscription(self.user):
            self.request.response.addNotification(
                "You are already subscribed to this snap recipe."
            )
        else:
            self.context.subscribe(self.user, self.user)

            self.request.response.addNotification(
                "You have subscribed to this snap recipe."
            )


class SnapSubscriptionAddOtherView(_SnapSubscriptionCreationView):
    """View used to subscribe someone other than the current user."""

    field_names = ["person"]
    for_input = True

    # Since we are subscribing other people, the current user
    # is never considered subscribed.
    user_is_subscribed = False

    page_title = label = "Subscribe to snap recipe"

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
                    "private snap recipes.",
                )

    @action("Subscribe", name="subscribe_action")
    def subscribe_action(self, action, data):
        """Subscribe the specified user to the Snap recipe."""
        person = data["person"]
        subscription = self.context.getSubscription(person)
        if subscription is None:
            self.context.subscribe(person, self.user)
            self.request.response.addNotification(
                "%s has been subscribed to this snap recipe."
                % person.displayname
            )
        else:
            self.request.response.addNotification(
                "%s was already subscribed to this snap recipe."
                % person.displayname
            )
