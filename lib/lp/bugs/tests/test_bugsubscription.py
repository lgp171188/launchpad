# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for BugSubscriptions."""

import json

from testtools.matchers import LessThan
from zope.security.interfaces import Unauthorized

from lp.bugs.enums import BugNotificationLevel
from lp.registry.interfaces.teammembership import TeamMembershipStatus
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    RequestTimelineCollector,
    TestCaseWithFactory,
    api_url,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person


class TestBugSubscription(TestCaseWithFactory):
    """Tests for the `BugSubscription` class."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.bug = self.factory.makeBug()
        self.subscriber = self.factory.makePerson()

    def updateBugNotificationLevelWithWebService(
        self, bug, subscriber, update_as
    ):
        """Helper method to update a subscription's bug_notification_level."""
        bug_url = api_url(bug)
        subscriber_url = api_url(subscriber)
        webservice = webservice_for_person(
            update_as,
            permission=OAuthPermission.WRITE_PUBLIC,
            default_api_version="devel",
        )
        ws_bug = self.getWebserviceJSON(webservice, bug_url)
        ws_subscriptions = self.getWebserviceJSON(
            webservice, ws_bug["subscriptions_collection_link"]
        )
        absolute_subscriber_url = webservice.getAbsoluteUrl(subscriber_url)
        [ws_subscription] = [
            subscription
            for subscription in ws_subscriptions["entries"]
            if subscription["person_link"] == absolute_subscriber_url
        ]
        response = webservice.patch(
            ws_subscription["self_link"],
            "application/json",
            json.dumps({"bug_notification_level": "Lifecycle"}),
        )
        self.assertEqual(209, response.status)

    def test_subscribers_can_change_bug_notification_level(self):
        # The bug_notification_level of a subscription can be changed by
        # the subscription's owner.
        with person_logged_in(self.subscriber):
            subscription = self.bug.subscribe(self.subscriber, self.subscriber)
            for level in BugNotificationLevel.items:
                subscription.bug_notification_level = level
                self.assertEqual(level, subscription.bug_notification_level)

    def test_only_subscribers_can_change_bug_notification_level(self):
        # Only the owner of the subscription can change its
        # bug_notification_level.
        other_person = self.factory.makePerson()
        with person_logged_in(self.subscriber):
            subscription = self.bug.subscribe(self.subscriber, self.subscriber)

        def set_bug_notification_level(level):
            subscription.bug_notification_level = level

        with person_logged_in(other_person):
            for level in BugNotificationLevel.items:
                self.assertRaises(
                    Unauthorized, set_bug_notification_level, level
                )

    def test_team_owner_can_change_bug_notification_level(self):
        # A team owner can change the bug_notification_level of the
        # team's subscriptions.
        team = self.factory.makeTeam()
        with person_logged_in(team.teamowner):
            subscription = self.bug.subscribe(team, team.teamowner)
            for level in BugNotificationLevel.items:
                subscription.bug_notification_level = level
                self.assertEqual(level, subscription.bug_notification_level)

    def test_team_admin_can_change_bug_notification_level(self):
        # A team's administrators can change the bug_notification_level
        # of its subscriptions.
        team = self.factory.makeTeam()
        with person_logged_in(team.teamowner):
            team.addMember(
                self.subscriber,
                team.teamowner,
                status=TeamMembershipStatus.ADMIN,
            )
        with person_logged_in(self.subscriber):
            subscription = self.bug.subscribe(team, team.teamowner)
            for level in BugNotificationLevel.items:
                subscription.bug_notification_level = level
                self.assertEqual(level, subscription.bug_notification_level)

    def test_permission_check_query_count_for_admin_members(self):
        # The number of administrators a team has doesn't affect the
        # number of queries carried out when checking that one of those
        # administrators can update that team's subscriptions.
        team = self.factory.makeTeam()
        team_2 = self.factory.makeTeam()
        # For this test we'll create two teams, one with one
        # administrator and the other with several.
        with person_logged_in(team.teamowner):
            team.addMember(
                self.subscriber,
                team.teamowner,
                status=TeamMembershipStatus.ADMIN,
            )
            self.bug.subscribe(team, team.teamowner)
        with person_logged_in(team_2.teamowner):
            for _ in range(25):
                person = self.factory.makePerson()
                team_2.addMember(
                    person, team_2.teamowner, status=TeamMembershipStatus.ADMIN
                )
            team_2.addMember(
                self.subscriber,
                team_2.teamowner,
                status=TeamMembershipStatus.ADMIN,
            )
            self.bug.subscribe(team_2, team_2.teamowner)

        collector = RequestTimelineCollector()
        collector.register()
        self.addCleanup(collector.unregister)
        with person_logged_in(self.subscriber):
            self.updateBugNotificationLevelWithWebService(
                self.bug, team, self.subscriber
            )
        # 25 is an entirely arbitrary limit for the number of queries
        # this requires, based on the number run when the code was
        # written; it should give us a nice early warning if the number
        # of queries starts to grow.
        self.assertThat(collector, HasQueryCount(LessThan(25)))
        # It might seem odd that we don't do this all as one with block,
        # but using the collector and the webservice means our
        # interaction goes away, so we have to set up a new one.
        with person_logged_in(self.subscriber):
            self.updateBugNotificationLevelWithWebService(
                self.bug, team_2, self.subscriber
            )
        self.assertThat(collector, HasQueryCount(LessThan(25)))
