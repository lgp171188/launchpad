# Copyright 2012-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Unit tests for ArchiveSubscribersView."""

from soupmatchers import HTMLContains, Tag
from zope.component import getUtility

from lp.registry.enums import PersonVisibility
from lp.registry.interfaces.person import IPersonSet
from lp.services.webapp import canonical_url
from lp.testing import (
    TestCaseWithFactory,
    login_person,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.views import create_initialized_view


class TestArchiveSubscribersView(TestCaseWithFactory):
    """Tests for ArchiveSubscribersView."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.p3a_owner = self.factory.makePerson()
        admin = getUtility(IPersonSet).getByEmail("admin@canonical.com")
        with person_logged_in(admin):
            self.private_ppa = self.factory.makeArchive(
                owner=self.p3a_owner, private=True, name="p3a"
            )
        with person_logged_in(self.p3a_owner):
            for _ in range(3):
                subscriber = self.factory.makePerson()
                self.private_ppa.newSubscription(subscriber, self.p3a_owner)

    def test_has_batch_navigation(self):
        # The page has the usual batch navigation links.
        with person_logged_in(self.p3a_owner):
            view = create_initialized_view(
                self.private_ppa, "+subscriptions", principal=self.p3a_owner
            )
            html = view.render()
        has_batch_navigation = HTMLContains(
            Tag(
                "batch navigation links",
                "td",
                attrs={"class": "batch-navigation-links"},
                count=2,
            )
        )
        self.assertThat(html, has_batch_navigation)

    def test_constant_query_count(self):
        def create_subscribers():
            self.private_ppa.newSubscription(
                self.factory.makePerson(), self.p3a_owner
            )
            self.private_ppa.newSubscription(
                self.factory.makeTeam(
                    visibility=PersonVisibility.PRIVATE,
                    members=[self.p3a_owner],
                ),
                self.p3a_owner,
            )

        self.pushConfig("launchpad", default_batch_size=75)
        url = canonical_url(self.private_ppa, view_name="+subscriptions")
        recorder1, recorder2 = record_two_runs(
            lambda: self.getUserBrowser(url, user=self.p3a_owner),
            create_subscribers,
            2,
            login_method=lambda: login_person(self.p3a_owner),
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))
