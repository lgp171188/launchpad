# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import unittest

import transaction
from zope.component import getUtility

from canonical.launchpad.ftests import ANONYMOUS, login
from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.registry.interfaces.karma import IKarmaCacheManager
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing import (
    DatabaseFunctionalLayer, LaunchpadFunctionalLayer, LaunchpadZopelessLayer)
from lp.registry.browser.person import PersonEditView, PersonView
from lp.registry.interfaces.person import PersonVisibility
from lp.registry.interfaces.teammembership import TeamMembershipStatus
from lp.registry.model.karma import KarmaCategory
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.soyuz.interfaces.archive import ArchiveStatus
from lp.testing import TestCaseWithFactory, login_person
from lp.testing.views import create_view


class TestPersonViewKarma(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        transaction.commit()
        self.view = PersonView(
            person, LaunchpadTestRequest())
        self._makeKarmaCache(
            person, product, KarmaCategory.byName('bugs'))
        self._makeKarmaCache(
            person, product, KarmaCategory.byName('answers'))
        self._makeKarmaCache(
            person, product, KarmaCategory.byName('code'))

    def test_karma_category_sort(self):
        categories = self.view.contributed_categories
        category_names = []
        for category in categories:
            category_names.append(category.name)

        self.assertEqual(category_names, [u'code', u'bugs', u'answers'],
                         'Categories are not sorted correctly')

    def _makeKarmaCache(self, person, product, category, value=10):
        """ Create and return a KarmaCache entry with the given arguments.

        In order to create the KarmaCache record we must switch to the DB
        user 'karma', so tests that need a different user after calling
        this method should do run switchDbUser() themselves.
        """

        LaunchpadZopelessLayer.switchDbUser('karma')

        cache_manager = getUtility(IKarmaCacheManager)
        karmacache = cache_manager.new(
            value, person.id, category.id, product_id=product.id)

        try:
            cache_manager.updateKarmaValue(
                value, person.id, category_id=None, product_id=product.id)
        except NotFoundError:
            cache_manager.new(
                value, person.id, category_id=None, product_id=product.id)

        # We must commit here so that the change is seen in other transactions
        # (e.g. when the callsite issues a switchDbUser() after we return).
        transaction.commit()
        return karmacache


class TestShouldShowPpaSection(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.owner = self.factory.makePerson(name='mowgli')
        self.person_ppa = self.factory.makeArchive(owner=self.owner)
        self.team = self.factory.makeTeam(name='jbook', owner=self.owner)

        # The team is the owner of the PPA.
        self.team_ppa = self.factory.makeArchive(owner=self.team)
        self.team_view = PersonView(self.team, LaunchpadTestRequest())

    def make_ppa_private(self, ppa):
        """Helper method to privatise a ppa."""
        login('foo.bar@canonical.com')
        ppa.private = True
        ppa.buildd_secret = "secret"
        login(ANONYMOUS)

    def test_viewing_person_with_public_ppa(self):
        # Show PPA section only if context has at least one PPA the user is
        # authorised to view the PPA.
        login(ANONYMOUS)
        person_view = PersonView(self.owner, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)

    def test_viewing_person_without_ppa(self):
        # If the context person does not have a ppa then the section
        # should not display.
        login(ANONYMOUS)
        person_without_ppa = self.factory.makePerson()
        person_view = PersonView(person_without_ppa, LaunchpadTestRequest())
        self.failIf(person_view.should_show_ppa_section)

    def test_viewing_self(self):
        # If the current user has edit access to the context person then
        # the section should always display.
        login_person(self.owner)
        person_view = PersonView(self.owner, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)

        # If the ppa is private, the section is still displayed to
        # a user with edit access to the person.
        self.make_ppa_private(self.person_ppa)
        login_person(self.owner)
        person_view = PersonView(self.owner, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)

        # Even a person without a PPA will see the section when viewing
        # themselves.
        person_without_ppa = self.factory.makePerson()
        login_person(person_without_ppa)
        person_view = PersonView(person_without_ppa, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)

    def test_anon_viewing_person_with_private_ppa(self):
        # If the ppa is private, the ppa section will not be displayed
        # to users without view access to the ppa.
        self.make_ppa_private(self.person_ppa)
        login(ANONYMOUS)
        person_view = PersonView(self.owner, LaunchpadTestRequest())
        self.failIf(person_view.should_show_ppa_section)

        # But if the context person has a second ppa that is public,
        # then anon users will see the section.
        second_ppa = self.factory.makeArchive(owner=self.owner)
        person_view = PersonView(self.owner, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)

    def test_viewing_team_with_private_ppa(self):
        # If a team PPA is private, the ppa section will be displayed
        # to team members.
        self.make_ppa_private(self.team_ppa)
        member = self.factory.makePerson()
        login_person(self.owner)
        self.team.addMember(member, self.owner)
        login_person(member)

        # So the member will see the section.
        person_view = PersonView(self.team, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)

        # But other users who are not members will not.
        non_member = self.factory.makePerson()
        login_person(non_member)
        person_view = PersonView(self.team, LaunchpadTestRequest())
        self.failIf(person_view.should_show_ppa_section)

        # Unless the team also has another ppa which is public.
        second_ppa = self.factory.makeArchive(owner=self.team)
        person_view = PersonView(self.team, LaunchpadTestRequest())
        self.failUnless(person_view.should_show_ppa_section)


class TestPersonEditView(TestCaseWithFactory):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self)
        self.person = self.factory.makePerson()
        login_person(self.person)
        self.ppa = self.factory.makeArchive(owner=self.person)
        self.view = PersonEditView(
            self.person, LaunchpadTestRequest())

    def test_can_rename_with_empty_PPA(self):
        # If a PPA exists but has no packages, we can rename the
        # person.
        self.view.initialize()
        self.assertFalse(self.view.form_fields['name'].for_display)

    def _publishPPAPackage(self):
        stp = SoyuzTestPublisher()
        stp.setUpDefaultDistroSeries()
        stp.getPubSource(archive=self.ppa)

    def test_cannot_rename_with_non_empty_PPA(self):
        # Publish some packages in the PPA and test that we can't rename
        # the person.
        self._publishPPAPackage()
        self.view.initialize()
        self.assertTrue(self.view.form_fields['name'].for_display)
        self.assertEqual(
            self.view.widgets['name'].hint,
            "This user has an active PPA with packages published and "
            "may not be renamed.")

    def test_cannot_rename_with_deleting_PPA(self):
        # When a PPA is in the DELETING state we should not allow
        # renaming just yet.
        self._publishPPAPackage()
        self.view.initialize()
        self.ppa.delete(self.person)
        self.assertEqual(self.ppa.status, ArchiveStatus.DELETING)
        self.assertTrue(self.view.form_fields['name'].for_display)

    def test_can_rename_with_deleted_PPA(self):
        # Delete a PPA and test that the person can be renamed.
        self._publishPPAPackage()
        # Deleting the PPA will remove the publications, which is
        # necessary for the renaming check.
        self.ppa.delete(self.person)
        # Simulate the external script running and finalising the
        # DELETED status.
        self.ppa.status = ArchiveStatus.DELETED
        self.view.initialize()
        self.assertFalse(self.view.form_fields['name'].for_display)


class TestPersonParticipationView(TestCaseWithFactory):

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super(TestPersonParticipationView, self).setUp()
        self.user = self.factory.makePerson()
        self.view = create_view(self.user, name='+participation')

    def test__asParticpation_owner(self):
        # Team owners have the role of 'Owner'.
        self.factory.makeTeam(owner=self.user)
        [participation] = self.view.active_participations
        self.assertEqual('Owner', participation['role'])

    def test__asParticpation_admin(self):
        # Team admins have the role of 'Admin'.
        team = self.factory.makeTeam()
        login_person(team.teamowner)
        team.addMember(self.user, team.teamowner)
        for membership in self.user.myactivememberships:
            membership.setStatus(
                TeamMembershipStatus.ADMIN, team.teamowner)
        [participation] = self.view.active_participations
        self.assertEqual('Admin', participation['role'])

    def test__asParticpation_member(self):
        # The default team role is 'Member'.
        team = self.factory.makeTeam()
        login_person(team.teamowner)
        team.addMember(self.user, team.teamowner)
        [participation] = self.view.active_participations
        self.assertEqual('Member', participation['role'])

    def test_active_participations_with_private_team(self):
        # Users cannot see private teams that they are not members of.
        team = self.factory.makeTeam(visibility=PersonVisibility.PRIVATE)
        login_person(team.teamowner)
        team.addMember(self.user, team.teamowner)
        # The team is included in active_participations.
        login_person(self.user)
        view = create_view(
            self.user, name='+participation', principal=self.user)
        self.assertEqual(1, len(view.active_participations))
        # The team is not included in active_participations.
        observer = self.factory.makePerson()
        login_person(observer)
        view = create_view(
            self.user, name='+participation', principal=observer)
        self.assertEqual(0, len(view.active_participations))

    def test_active_participations_indirect_membership(self):
        # Verify the path of indirect membership.
        a_team = self.factory.makeTeam(name='a')
        b_team = self.factory.makeTeam(name='b', owner=a_team)
        c_team = self.factory.makeTeam(name='c', owner=b_team)
        login_person(a_team.teamowner)
        a_team.addMember(self.user, a_team.teamowner)
        transaction.commit()
        participations = self.view.active_participations
        self.assertEqual(3, len(participations))
        display_names = [
            participation['displayname'] for participation in participations]
        self.assertEqual(['A', 'B', 'C'], display_names)
        self.assertEqual('', participations[0]['via'])
        self.assertEqual('A', participations[1]['via'])
        self.assertEqual('A, B', participations[2]['via'])


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
