# Copyright 2011-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for +announcement views."""

from datetime import datetime, timezone

from lxml import html
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.enums import TeamMembershipPolicy
from lp.registry.interfaces.announcement import IAnnouncementSet
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.registry.model.announcement import Announcement
from lp.services.database.interfaces import IStore
from lp.testing import (
    BrowserTestCase,
    TestCaseWithFactory,
    normalize_whitespace,
)
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.views import create_initialized_view


class TestAnnouncement(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_announcement_info(self):
        product = self.factory.makeProduct(displayname="Foo")
        announcer = self.factory.makePerson(displayname="Bar Baz")
        announcement = product.announce(announcer, "Hello World")
        view = create_initialized_view(announcement, "+index")
        root = html.fromstring(view())
        [reg_para] = root.cssselect("p.registered")
        self.assertEqual(
            "Written for Foo by Bar Baz",
            normalize_whitespace(reg_para.text_content()),
        )

    def test_announcement_info_with_publication_date(self):
        product = self.factory.makeProduct(displayname="Foo")
        announcer = self.factory.makePerson(displayname="Bar Baz")
        announced = datetime(2007, 1, 12, tzinfo=timezone.utc)
        announcement = product.announce(
            announcer, "Hello World", publication_date=announced
        )
        view = create_initialized_view(announcement, "+index")
        root = html.fromstring(view())
        [reg_para] = root.cssselect("p.registered")
        self.assertEqual(
            "Written for Foo by Bar Baz on 2007-01-12",
            normalize_whitespace(reg_para.text_content()),
        )


class TestAnnouncementPage(BrowserTestCase):
    layer = LaunchpadFunctionalLayer

    def assertHidesUnwantedAnnouncements(
        self, context, view_name=None, user=None
    ):
        """
        Makes sure that unwanted announcements are not shown for the given
        context.

        This test method creates a set of possible announcements that
        should be specifically shown or hidden for the given context (
        IProjectGroup instance or IAnnouncementSet, for example).

        :param context: HasAnnouncements subclass, that routes to an
                        announcements page.
        :param view_name: View name of the announcements.
        :param user: Login with this user when showing the announcements page.
        """
        # cleanup announcements from test data to make sure we are not
        # hiding new announcements because of pagination.
        store = IStore(Announcement)
        for i in store.find(Announcement):
            store.remove(i)
        store.flush()

        real_user = self.factory.makePerson(karma=500)
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )

        if IProjectGroup.providedBy(context):
            project_group = context
        else:
            project_group = None
        first_product = self.factory.makeProduct(
            owner=real_user, projectgroup=project_group
        )
        first_announcement = first_product.announce(
            real_user,
            "Some real announcement",
            "Yep, announced here",
            publication_date=datetime.now(timezone.utc),
        )

        second_product = self.factory.makeProduct(
            owner=team, projectgroup=project_group
        )
        second_announcement = second_product.announce(
            team,
            "Other real announcement",
            "Yep too, announced here",
            publication_date=datetime.now(timezone.utc),
        )

        inactive_product = self.factory.makeProduct(
            owner=real_user, projectgroup=project_group
        )
        inactive_announcement = inactive_product.announce(
            real_user,
            "Do not show inactive, please",
            "Nope, not here",
            publication_date=datetime.now(timezone.utc),
        )
        removeSecurityProxy(inactive_product).active = False

        browser = self.getViewBrowser(context, view_name, user=user)
        contents = browser.contents

        self.assertIn(first_announcement.title, contents)
        self.assertIn(first_announcement.summary, contents)

        self.assertIn(second_announcement.title, contents)
        self.assertIn(second_announcement.summary, contents)

        self.assertNotIn(inactive_announcement.title, contents)
        self.assertNotIn(inactive_announcement.summary, contents)

    def test_announcement_page_filter_out_inactive_projects(self):
        user = self.factory.makePerson()
        context = getUtility(IAnnouncementSet)
        self.assertHidesUnwantedAnnouncements(context, None, user)

    def test_project_group_announcement_filter_out_inactive_projects(self):
        user = self.factory.makePerson()
        context = self.factory.makeProject()  # actually, a IProjectGroup
        self.assertHidesUnwantedAnnouncements(context, None, user)
