# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the registry security adapters."""

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.enums import PersonVisibility
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.interfaces.teammembership import (
    ITeamMembershipSet,
    TeamMembershipStatus,
)
from lp.registry.security import PublicOrPrivateTeamsExistence
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    person_logged_in,
    record_two_runs,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount


class TestPublicOrPrivateTeamsExistence(TestCaseWithFactory):
    """Tests for the PublicOrPrivateTeamsExistence security adapter."""

    layer = DatabaseFunctionalLayer

    def test_members_of_parent_teams_get_limited_view(self):
        team_owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=team_owner, visibility=PersonVisibility.PRIVATE
        )
        public_team = self.factory.makeTeam(owner=team_owner)
        team_user = self.factory.makePerson()
        other_user = self.factory.makePerson()
        with person_logged_in(team_owner):
            public_team.addMember(team_user, team_owner)
            public_team.addMember(private_team, team_owner)
        checker = PublicOrPrivateTeamsExistence(
            removeSecurityProxy(private_team)
        )
        self.assertTrue(checker.checkAuthenticated(IPersonRoles(team_user)))
        self.assertFalse(checker.checkAuthenticated(IPersonRoles(other_user)))

    def test_members_of_pending_parent_teams_get_limited_view(self):
        team_owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=team_owner, visibility=PersonVisibility.PRIVATE
        )
        public_team = self.factory.makeTeam(owner=team_owner)
        team_user = self.factory.makePerson()
        other_user = self.factory.makePerson()
        with person_logged_in(team_owner):
            public_team.addMember(team_user, team_owner)
            getUtility(ITeamMembershipSet).new(
                private_team,
                public_team,
                TeamMembershipStatus.INVITED,
                team_owner,
            )
        checker = PublicOrPrivateTeamsExistence(
            removeSecurityProxy(private_team)
        )
        self.assertTrue(checker.checkAuthenticated(IPersonRoles(team_user)))
        self.assertFalse(checker.checkAuthenticated(IPersonRoles(other_user)))

    def assertTeamOwnerCanListPrivateTeamWithTeamStatus(self, team_status):
        main_team_owner = self.factory.makePerson()
        main_team = self.factory.makeTeam(
            owner=main_team_owner, visibility=PersonVisibility.PRIVATE
        )
        private_team_owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=private_team_owner, visibility=PersonVisibility.PRIVATE
        )
        with admin_logged_in():
            # Cannot add a team with a non-APPROVED / PENDING status, so add
            # it as approved and then edit the membership.
            main_team.addMember(
                private_team,
                main_team_owner,
                status=TeamMembershipStatus.APPROVED,
                force_team_add=True,
            )
            main_team.setMembershipData(
                private_team, team_status, main_team_owner
            )

        checker = PublicOrPrivateTeamsExistence(
            removeSecurityProxy(private_team)
        )
        self.assertTrue(
            checker.checkAuthenticated(IPersonRoles(main_team_owner))
        )

    def test_can_list_team_with_deactivated_private_team(self):
        self.assertTeamOwnerCanListPrivateTeamWithTeamStatus(
            TeamMembershipStatus.DEACTIVATED
        )

    def test_can_list_team_with_expired_private_team(self):
        self.assertTeamOwnerCanListPrivateTeamWithTeamStatus(
            TeamMembershipStatus.EXPIRED
        )

    def test_private_team_query_count(self):
        # Testing visibility of a private team involves checking for
        # subscriptions to any private PPAs owned by that team.  Make sure
        # that this doesn't involve a query for every archive subscription
        # the user has.
        person = self.factory.makePerson()
        team_owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=team_owner, visibility=PersonVisibility.PRIVATE
        )
        checker = PublicOrPrivateTeamsExistence(
            removeSecurityProxy(private_team)
        )

        def create_subscribed_archive():
            with person_logged_in(team_owner):
                archive = self.factory.makeArchive(
                    owner=private_team, private=True
                )
                archive.newSubscription(person, team_owner)

        def check_team_limited_view():
            person.clearInTeamCache()
            with person_logged_in(person):
                self.assertTrue(
                    checker.checkAuthenticated(IPersonRoles(person))
                )

        recorder1, recorder2 = record_two_runs(
            check_team_limited_view, create_subscribed_archive, 5
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))
