# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap subscription views."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'SnapPortletSubscribersContent'
]

from lp.app.browser.launchpadform import LaunchpadEditFormView
from lp.app.interfaces.services import IService
from lp.registry.interfaces.person import IPersonSet
from lp.services.webapp import LaunchpadView, canonical_url
from lp.services.webapp.authorization import precache_permission_for_objects, \
    check_permission
from lp.snappy.interfaces.snapsubscription import ISnapSubscription
from zope.component._api import getUtility
from zope.formlib.form import action


class SnapPortletSubscribersContent(LaunchpadView):
    """View for the contents for the subscribers portlet."""

    def subscriptions(self):
        """Return a decorated list of Snap recipe subscriptions."""

        # Cache permissions so private subscribers can be rendered.
        # The security adaptor will do the job also but we don't want or
        # need the expense of running several complex SQL queries.
        subscriptions = list(self.context.subscriptions)
        person_ids = [sub.person.id for sub in subscriptions]
        list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(
            person_ids, need_validity=True))
        if self.user is not None:
            subscribers = [
                subscription.person for subscription in subscriptions]
            precache_permission_for_objects(
                self.request, "launchpad.LimitedView", subscribers)

        visible_subscriptions = [
            subscription for subscription in subscriptions
            if check_permission("launchpad.LimitedView", subscription.person)]
        return sorted(
            visible_subscriptions,
            key=lambda subscription: subscription.person.displayname)


class SnapSubscriptionEditView(LaunchpadEditFormView):
    """The view for editing Snap recipe subscriptions."""
    schema = ISnapSubscription
    field_names = []

    @property
    def page_title(self):
        return (
            "Edit subscription to Snap recipe %s" %
            self.snap.displayname)

    @property
    def label(self):
        return (
            "Edit subscription to Snap recipe for %s" %
            self.person.displayname)

    def initialize(self):
        self.snap = self.context.snap
        self.person = self.context.person
        super(SnapSubscriptionEditView, self).initialize()

    @action("Unsubscribe", name="unsubscribe")
    def unsubscribe_action(self, action, data):
        """Unsubscribe the team from the repository."""
        self.snap.unsubscribe(self.person, self.user)
        self.request.response.addNotification(
            "%s has been unsubscribed from this Snap recipe."
            % self.person.displayname)

    @property
    def next_url(self):
        url = canonical_url(self.snap)
        # If the subscriber can no longer see the repository, redirect them
        # away.
        if not self.snap.visibleByUser(self.person):
            url = canonical_url(self.snap.pillar)
        return url

    cancel_url = next_url
