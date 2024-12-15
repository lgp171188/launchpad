# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import re
from datetime import datetime, timedelta, timezone

from lazr.lifecycle.snapshot import Snapshot
from lazr.restful.utils import smartquote
from storm.locals import Desc
from storm.store import Store
from testtools.matchers import Equals
from zope.component import getUtility
from zope.interface import providedBy
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.answers.model.answercontact import AnswerContact
from lp.app.enums import InformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.blueprints.enums import (
    NewSpecificationDefinitionStatus,
    SpecificationDefinitionStatus,
    SpecificationFilter,
    SpecificationImplementationStatus,
    SpecificationPriority,
    SpecificationSort,
)
from lp.blueprints.model.specification import Specification
from lp.bugs.interfaces.bugtasksearch import (
    IllegalRelatedBugTasksParams,
    get_person_bugtasks_search_params,
)
from lp.bugs.model.bug import Bug
from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
from lp.registry.errors import PrivatePersonLinkageError
from lp.registry.interfaces.accesspolicy import IAccessPolicySource
from lp.registry.interfaces.karma import IKarmaCacheManager
from lp.registry.interfaces.person import ImmutableVisibilityError, IPersonSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.product import IProductSet
from lp.registry.interfaces.teammembership import ITeamMembershipSet
from lp.registry.model.distribution import Distribution
from lp.registry.model.karma import KarmaCategory, KarmaTotalCache
from lp.registry.model.person import Person, get_recipients
from lp.registry.model.product import Product
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import (
    flush_database_caches,
    flush_database_updates,
)
from lp.services.identity.interfaces.account import AccountStatus
from lp.services.identity.interfaces.emailaddress import EmailAddressStatus
from lp.services.propertycache import clear_property_cache
from lp.services.webapp.publisher import canonical_url
from lp.soyuz.enums import ArchivePurpose
from lp.testing import (
    BrowserTestCase,
    StormStatementRecorder,
    TestCaseWithFactory,
    celebrity_logged_in,
    launchpadlib_for,
    login,
    login_admin,
    login_person,
    logout,
    person_logged_in,
    record_two_runs,
)
from lp.testing.dbuser import dbuser
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import LaunchpadWebServiceCaller
from lp.testing.sampledata import ADMIN_EMAIL
from lp.testing.views import create_initialized_view


class TestPersonTeams(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.user = self.factory.makePerson(name="test-member")
        self.a_team = self.factory.makeTeam(name="a")
        self.b_team = self.factory.makeTeam(name="b", owner=self.a_team)
        self.c_team = self.factory.makeTeam(name="c", owner=self.b_team)
        login_person(self.a_team.teamowner)
        self.a_team.addMember(self.user, self.a_team.teamowner)

    def test_teams_indirectly_participated_in(self):
        indirect_teams = self.user.teams_indirectly_participated_in
        expected_teams = [self.b_team, self.c_team]
        test_teams = sorted(indirect_teams, key=lambda team: team.displayname)
        self.assertEqual(expected_teams, test_teams)

    def test_team_memberships(self):
        memberships = self.user.team_memberships
        memberships = [(m.person, m.team) for m in memberships]
        self.assertEqual([(self.user, self.a_team)], memberships)

    def test_path_to_team(self):
        path_to_a = self.user.findPathToTeam(self.a_team)
        path_to_b = self.user.findPathToTeam(self.b_team)
        path_to_c = self.user.findPathToTeam(self.c_team)

        self.assertEqual([self.a_team], path_to_a)
        self.assertEqual([self.a_team, self.b_team], path_to_b)
        self.assertEqual([self.a_team, self.b_team, self.c_team], path_to_c)

    def test_teams_participated_in(self):
        teams = self.user.teams_participated_in
        teams = sorted(list(teams), key=lambda x: x.displayname)
        expected_teams = [self.a_team, self.b_team, self.c_team]
        self.assertEqual(expected_teams, teams)

    def test_getPathsToTeams(self):
        paths, memberships = self.user.getPathsToTeams()
        expected_paths = {
            self.a_team: [self.a_team, self.user],
            self.b_team: [self.b_team, self.a_team, self.user],
            self.c_team: [self.c_team, self.b_team, self.a_team, self.user],
        }
        self.assertEqual(expected_paths, paths)

        expected_memberships = [(self.a_team, self.user)]
        memberships = [
            (membership.team, membership.person) for membership in memberships
        ]
        self.assertEqual(expected_memberships, memberships)

    def test_getPathsToTeams_complicated(self):
        d_team = self.factory.makeTeam(name="d", owner=self.b_team)
        e_team = self.factory.makeTeam(name="e")
        f_team = self.factory.makeTeam(name="f", owner=e_team)
        self.factory.makeTeam(name="unrelated")
        login_person(self.a_team.teamowner)
        d_team.addMember(self.user, d_team.teamowner)
        login_person(e_team.teamowner)
        e_team.addMember(self.user, e_team.teamowner)

        paths, memberships = self.user.getPathsToTeams()
        expected_paths = {
            self.a_team: [self.a_team, self.user],
            self.b_team: [self.b_team, self.a_team, self.user],
            self.c_team: [self.c_team, self.b_team, self.a_team, self.user],
            d_team: [d_team, self.b_team, self.a_team, self.user],
            e_team: [e_team, self.user],
            f_team: [f_team, e_team, self.user],
        }
        self.assertEqual(expected_paths, paths)

        expected_memberships = [
            (e_team, self.user),
            (d_team, self.user),
            (self.a_team, self.user),
        ]
        memberships = [
            (membership.team, membership.person) for membership in memberships
        ]
        self.assertEqual(expected_memberships, memberships)

    def test_getPathsToTeams_multiple_paths(self):
        d_team = self.factory.makeTeam(name="d", owner=self.b_team)
        login_person(self.a_team.teamowner)
        self.c_team.addMember(d_team, self.c_team.teamowner)

        paths, memberships = self.user.getPathsToTeams()
        # getPathsToTeams should not randomly pick one path or another
        # when multiples exist; it sorts to use the oldest path, so
        # the expected paths below should be the returned result.
        expected_paths = {
            self.a_team: [self.a_team, self.user],
            self.b_team: [self.b_team, self.a_team, self.user],
            self.c_team: [self.c_team, self.b_team, self.a_team, self.user],
            d_team: [d_team, self.b_team, self.a_team, self.user],
        }
        self.assertEqual(expected_paths, paths)

        expected_memberships = [(self.a_team, self.user)]
        memberships = [
            (membership.team, membership.person) for membership in memberships
        ]
        self.assertEqual(expected_memberships, memberships)

    def test_inTeam_direct_team(self):
        # Verify direct membership is True and the cache is populated.
        self.assertTrue(self.user.inTeam(self.a_team))
        self.assertEqual(
            {self.a_team.id: True},
            removeSecurityProxy(self.user)._inTeam_cache,
        )

    def test_inTeam_indirect_team(self):
        # Verify indirect membeship is True and the cache is populated.
        self.assertTrue(self.user.inTeam(self.b_team))
        self.assertEqual(
            {self.b_team.id: True},
            removeSecurityProxy(self.user)._inTeam_cache,
        )

    def test_inTeam_cache_cleared_by_membership_change(self):
        # Verify a change in membership clears the team cache.
        self.user.inTeam(self.a_team)
        with person_logged_in(self.b_team.teamowner):
            self.b_team.addMember(self.user, self.b_team.teamowner)
        self.assertEqual({}, removeSecurityProxy(self.user)._inTeam_cache)

    def test_inTeam_person_is_false(self):
        # Verify a user cannot be a member of another user.
        other_user = self.factory.makePerson()
        self.assertFalse(self.user.inTeam(other_user))

    def test_inTeam_person_does_not_build_TeamParticipation_cache(self):
        # Verify when a user is the argument, a DB call to TeamParticipation
        # was not made to learn this.
        other_user = self.factory.makePerson()
        Store.of(self.user).invalidate()
        # Load the two person objects only by reading a non-id attribute
        # unrelated to team/person or teamparticipation.
        other_user.name
        self.user.name
        self.assertFalse(
            self.assertStatementCount(0, self.user.inTeam, other_user)
        )
        self.assertEqual({}, removeSecurityProxy(self.user)._inTeam_cache)

    def test_inTeam_person_string_missing_team(self):
        # If a check against a string is done, the team lookup is implicit:
        # treat a missing team as an empty team so that any pages that choose
        # to do this don't blow up unnecessarily. Similarly feature flags
        # team: scopes depend on this.
        self.assertFalse(self.user.inTeam("does-not-exist"))

    def test_inTeam_person_incorrect_archive(self):
        # If a person has an archive marked incorrectly that person should
        # still be retrieved by 'api_all_members'.  See bug #680461.
        self.factory.makeArchive(
            owner=self.user, purpose=ArchivePurpose.PARTNER
        )
        expected_members = [self.user, self.a_team.teamowner]
        retrieved_members = list(self.a_team.api_all_members)
        self.assertContentEqual(expected_members, retrieved_members)

    def test_inTeam_person_no_archive(self):
        # If a person has no archive that person should still be retrieved by
        # 'api_all_members'.
        expected_members = [self.user, self.a_team.teamowner]
        retrieved_members = list(self.a_team.api_all_members)
        self.assertContentEqual(expected_members, retrieved_members)

    def test_inTeam_person_ppa_archive(self):
        # If a person has a PPA that person should still be retrieved by
        # 'api_all_members'.
        self.factory.makeArchive(owner=self.user, purpose=ArchivePurpose.PPA)
        expected_members = [self.user, self.a_team.teamowner]
        retrieved_members = list(self.a_team.api_all_members)
        self.assertContentEqual(expected_members, retrieved_members)

    def test_inAnyTeam_no_teams_passed(self):
        # Verify that the inAnyTeam() method returns False when
        # it is passed an empty list of teams.
        self.assertFalse(self.user.inAnyTeam([]))

    def test_inAnyTeam_team_is_a_member_of_itself(self):
        # Verify that the inAnyTeam() method returns True when passed the same
        # team as the user being queried.
        d_team = self.factory.makeTeam(name="d")
        with StormStatementRecorder() as recorder:
            self.assertTrue(self.a_team.inAnyTeam([d_team, self.a_team]))
            self.assertEqual(0, recorder.count)

    def test_inAnyTeam_user_is_a_member_of_themselves(self):
        # Verify that the inAnyTeam() method returns True when passed the same
        # user as the user being queried. Also verify that the user is
        # not a member of any other non-team user.
        other_user = self.factory.makePerson()
        self.assertTrue(self.user.inAnyTeam([self.user]))
        self.assertFalse(self.user.inAnyTeam([other_user]))

    def test_inAnyTeam_no_cached_entries(self):
        # Verify that the inAnyTeam() method returns True when the user is a
        # member of the passed team and the cache is populated with
        # the positive and negative entries when it was initially empty.
        d_team = self.factory.makeTeam(name="d")
        self.assertEqual({}, removeSecurityProxy(self.user)._inTeam_cache)

        with StormStatementRecorder() as recorder:
            self.assertTrue(self.user.inAnyTeam([self.a_team, d_team]))
            self.assertEqual(1, len(recorder.queries))

        self.assertEqual(
            {self.a_team.id: True, d_team.id: False},
            removeSecurityProxy(self.user)._inTeam_cache,
        )

    def test_inAnyTeam_membership_already_cached(self):
        # Verify that the inAnyTeam() method returns True when the cache is
        # pre-populated with the data about that membership. Also verify that
        # no SQL queries are executed in this scenario.
        removeSecurityProxy(self.user)._inTeam_cache = {self.a_team.id: True}
        with StormStatementRecorder() as recorder:
            self.assertTrue(self.user.inAnyTeam([self.a_team, self.b_team]))
            self.assertEqual(0, recorder.count)

    def test_inAnyTeam_membership_not_cached_in_existing_cache(self):
        # Verify that the inAnyTeam() method returns True when the
        # existing cache does not contain an entry for the queried team. Also
        # verify that the positive and negative entries are added to the cache.
        d_team = self.factory.makeTeam(name="d")
        removeSecurityProxy(self.user)._inTeam_cache = {self.b_team.id: True}
        with StormStatementRecorder() as recorder:
            self.assertTrue(self.user.inAnyTeam([self.a_team, d_team]))
            self.assertEqual(1, recorder.count)
        self.assertEqual(
            {self.b_team.id: True, self.a_team.id: True, d_team.id: False},
            removeSecurityProxy(self.user)._inTeam_cache,
        )

    def test_inAnyTeam_negative_cached_results_not_queried_again(self):
        # Verify that when the cache has no positive matches and some of
        # the teams passed to the inAnyTeam() method
        # have a negative entry in the cache, they are not queried again
        d_team = self.factory.makeTeam(name="d")
        removeSecurityProxy(self.user)._inTeam_cache = {d_team.id: False}
        with StormStatementRecorder() as recorder:
            self.assertTrue(
                self.user.inAnyTeam([self.b_team, self.a_team, d_team])
            )
            self.assertEqual(1, recorder.count)
            queried_team_ids = re.search(
                r"TeamParticipation.team IN \((.+)\)", recorder.statements[0]
            )
            self.assertIsNotNone(queried_team_ids)
            team_ids = {
                int(team_id)
                for team_id in queried_team_ids.group(1).split(", ")
            }
            self.assertEqual({self.b_team.id, self.a_team.id}, team_ids)

    def test_getOwnedTeams(self):
        # The iterator contains the teams that person owns, regardless of
        # membership.
        owner = self.a_team.teamowner
        with person_logged_in(owner):
            owner.leave(self.a_team)
        results = list(owner.getOwnedTeams(self.user))
        self.assertEqual([self.a_team], results)

    def test_getOwnedTeams_visibility(self):
        # The iterator contains the teams that the user can see.
        owner = self.a_team.teamowner
        p_team = self.factory.makeTeam(
            name="p", owner=owner, visibility=PersonVisibility.PRIVATE
        )
        results = list(owner.getOwnedTeams(self.user))
        self.assertEqual([self.a_team], results)
        results = list(owner.getOwnedTeams(owner))
        self.assertEqual([self.a_team, p_team], results)

    def test_getOwnedTeams_webservice(self):
        # The user in the interaction is used as the user arg.
        owner = self.a_team.teamowner
        self.factory.makeTeam(
            name="p", owner=owner, visibility=PersonVisibility.PRIVATE
        )
        owner_name = owner.name
        lp = launchpadlib_for("test", person=self.user)
        lp_owner = lp.people[owner_name]
        results = lp_owner.getOwnedTeams()
        self.assertEqual(["a"], [t.name for t in results])

    def test_getOwnedTeams_webservice_anonymous(self):
        # The user in the interaction is used as the user arg.
        # Anonymous scripts also do not reveal private teams.
        owner = self.a_team.teamowner
        self.factory.makeTeam(
            name="p", owner=owner, visibility=PersonVisibility.PRIVATE
        )
        owner_name = owner.name
        logout()
        lp = launchpadlib_for("test", person=None)
        lp_owner = lp.people[owner_name]
        results = lp_owner.getOwnedTeams()
        self.assertEqual(["a"], [t.name for t in results])

    def test_administrated_teams(self):
        # The property Person.administrated_teams is a cached copy of
        # the result of Person.getAdministratedTeams().
        expected = [self.b_team, self.c_team]
        self.assertEqual(expected, list(self.user.getAdministratedTeams()))
        with StormStatementRecorder() as recorder:
            self.assertEqual(expected, self.user.administrated_teams)
            self.user.administrated_teams
        # The second access of administrated_teams did not require an
        # SQL query, hence the total number of SQL queries is 1.
        self.assertEqual(1, len(recorder.queries))


class TestPerson(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_title_user(self):
        user = self.factory.makePerson(name="snarf")
        self.assertEqual("Snarf", user.title)
        self.assertEqual(user.displayname, user.title)

    def test_title_team(self):
        team = self.factory.makeTeam(name="pting")
        title = smartquote('"%s" team') % team.displayname
        self.assertEqual(title, team.title)

    def test_description_not_exists(self):
        # When the person does not have a description, teamdescription or
        # homepage_content, the value is None.
        person = self.factory.makePerson()
        self.assertEqual(None, person.description)

    def test_description_fallback_for_person(self):
        # When the person does not have a description, but does have a
        # teamdescription or homepage_content, they are used.
        person = self.factory.makePerson()
        with person_logged_in(person):
            person.homepage_content = "babble"
            person.teamdescription = "fish"
        self.assertEqual("babble\nfish", person.description)

    def test_description_exists(self):
        # When the person has a description, it is returned.
        person = self.factory.makePerson()
        with person_logged_in(person):
            person.description = "babble"
        self.assertEqual("babble", person.description)

    def test_description_setting_reconciles_obsolete_sources(self):
        # When the description is set, the homepage_content and teamdescription
        # are set to None.
        person = self.factory.makePerson()
        with person_logged_in(person):
            person.homepage_content = "babble"
            person.teamdescription = "fish"
            person.description = "What's this fish doing?"
        self.assertEqual("What's this fish doing?", person.description)
        self.assertEqual(None, person.homepage_content)
        self.assertEqual(None, person.teamdescription)

    def test_getAffiliatedPillars_kinds(self):
        # Distributions, project groups, and projects are returned in this
        # same order.
        user = self.factory.makePerson()
        project = self.factory.makeProduct(owner=user)
        project_group = self.factory.makeProject(owner=user)
        distribution = self.factory.makeDistribution(owner=user)
        expected_pillars = [
            distribution.name,
            project_group.name,
            project.name,
        ]
        received_pillars = [
            pillar.name for pillar in user.getAffiliatedPillars(user)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_getAffiliatedPillars_roles(self):
        # owned, driven, and supervised pillars are returned ordered by
        # display name.
        user = self.factory.makePerson()
        owned_project = self.factory.makeProduct(owner=user, name="cat")
        driven_project = self.factory.makeProduct(name="bat")
        supervised_project = self.factory.makeProduct(name="nat")
        with celebrity_logged_in("admin"):
            driven_project.driver = user
            supervised_project.bug_supervisor = user
        expected_pillars = [
            driven_project.name,
            owned_project.name,
            supervised_project.name,
        ]
        received_pillars = [
            pillar.name for pillar in user.getAffiliatedPillars(user)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_getAffiliatedPillars_active_pillars(self):
        # Only active pillars are returned.
        user = self.factory.makePerson()
        active_project = self.factory.makeProject(owner=user)
        inactive_project = self.factory.makeProject(owner=user)
        with celebrity_logged_in("admin"):
            inactive_project.active = False
        expected_pillars = [active_project.name]
        received_pillars = [
            pillar.name for pillar in user.getAffiliatedPillars(user)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_getAffiliatedPillars_minus_proprietary(self):
        # Skip non public products if not allowed to see them.
        owner = self.factory.makePerson()
        user = self.factory.makePerson()
        self.factory.makeProduct(
            information_type=InformationType.PROPRIETARY, owner=owner
        )
        public = self.factory.makeProduct(
            information_type=InformationType.PUBLIC, owner=owner
        )

        expected_pillars = [public.name]
        received_pillars = [
            pillar.name for pillar in owner.getAffiliatedPillars(user)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_getAffiliatedPillars_visible_to_self(self):
        # Users can see their own non-public affiliated products.
        owner = self.factory.makePerson()
        self.factory.makeProduct(
            name="proprietary",
            information_type=InformationType.PROPRIETARY,
            owner=owner,
        )
        self.factory.makeProduct(
            name="public", information_type=InformationType.PUBLIC, owner=owner
        )

        expected_pillars = ["proprietary", "public"]
        received_pillars = [
            pillar.name for pillar in owner.getAffiliatedPillars(owner)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_getAffiliatedPillars_visible_to_admins(self):
        # Users can see their own non-public affiliated products.
        owner = self.factory.makePerson()
        admin = self.factory.makeAdministrator()
        self.factory.makeProduct(
            name="proprietary",
            information_type=InformationType.PROPRIETARY,
            owner=owner,
        )
        self.factory.makeProduct(
            name="public", information_type=InformationType.PUBLIC, owner=owner
        )

        expected_pillars = ["proprietary", "public"]
        received_pillars = [
            pillar.name for pillar in owner.getAffiliatedPillars(admin)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_getAffiliatedPillars_visible_to_commercial_admins(self):
        # Users can see their own non-public affiliated products.
        owner = self.factory.makePerson()
        admin = self.factory.makeCommercialAdmin()
        self.factory.makeProduct(
            name="proprietary",
            information_type=InformationType.PROPRIETARY,
            owner=owner,
        )
        self.factory.makeProduct(
            name="public", information_type=InformationType.PUBLIC, owner=owner
        )

        expected_pillars = ["proprietary", "public"]
        received_pillars = [
            pillar.name for pillar in owner.getAffiliatedPillars(admin)
        ]
        self.assertEqual(expected_pillars, received_pillars)

    def test_no_merge_pending(self):
        # isMergePending() returns False when this person is not the "from"
        # person of an active merge job.
        person = self.factory.makePerson()
        self.assertFalse(person.isMergePending())

    def test_isMergePending(self):
        # isMergePending() returns True when this person is being merged with
        # another person in an active merge job.
        from_person = self.factory.makePerson()
        to_person = self.factory.makePerson()
        requester = self.factory.makePerson()
        getUtility(IPersonSet).mergeAsync(from_person, to_person, requester)
        self.assertTrue(from_person.isMergePending())
        self.assertFalse(to_person.isMergePending())

    def test_mergeAsync_success(self):
        # mergeAsync returns a job with the from and to persons, and the
        # requester.
        from_person = self.factory.makePerson()
        to_person = self.factory.makePerson()
        requester = self.factory.makePerson()
        person_set = getUtility(IPersonSet)
        job = person_set.mergeAsync(from_person, to_person, requester)
        self.assertEqual(from_person, job.from_person)
        self.assertEqual(to_person, job.to_person)
        self.assertEqual(requester, job.requester)

    def test_selfgenerated_bugnotifications_false_by_default(self):
        # Default for new accounts is to not get any
        # self-generated bug notifications.
        user = self.factory.makePerson()
        self.assertFalse(user.selfgenerated_bugnotifications)

    def test_expanded_notification_footers_false_by_default(self):
        # Default for new accounts is to disable expanded notification footers.
        user = self.factory.makePerson()
        self.assertFalse(user.expanded_notification_footers)

    def test_require_strong_email_authentication_false_by_default(self):
        # Default for new accounts is to not require strong email
        # authentication.
        user = self.factory.makePerson()
        self.assertFalse(user.require_strong_email_authentication)

    def test_require_strong_email_authentication_permissions(self):
        # A person cannot set require_strong_email_authentication on their
        # own account, but a registry expert can.
        user = self.factory.makePerson()
        with person_logged_in(user):
            self.assertRaises(
                Unauthorized,
                setattr,
                user,
                "require_strong_email_authentication",
                True,
            )
        with celebrity_logged_in("registry_experts"):
            user.require_strong_email_authentication = True

    def test_canAccess__anonymous(self):
        # Anonymous users cannot call Person.canAccess()
        person = self.factory.makePerson()
        self.assertRaises(Unauthorized, getattr, person, "canAccess")

    def test_canAccess__checking_own_permissions(self):
        # Logged in users can call Person.canAccess() on their own
        # Person object.
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        with person_logged_in(person):
            self.assertTrue(person.canAccess(product, "licenses"))
            self.assertFalse(person.canAccess(product, "newSeries"))

    def test_canAccess__checking_permissions_of_others(self):
        # Logged in users cannot call Person.canAccess() on Person
        # object for other people.
        person = self.factory.makePerson()
        other = self.factory.makePerson()
        with person_logged_in(person):
            self.assertRaises(Unauthorized, getattr, other, "canAccess")

    def test_canWrite__anonymous(self):
        # Anonymous users cannot call Person.canWrite()
        person = self.factory.makePerson()
        self.assertRaises(Unauthorized, getattr, person, "canWrite")

    def test_canWrite__checking_own_permissions(self):
        # Logged in users can call Person.canWrite() on their own
        # Person object.
        person = self.factory.makePerson()
        product = self.factory.makeProduct()
        with person_logged_in(person):
            self.assertFalse(person.canWrite(product, "display_name"))
        with person_logged_in(product.owner):
            self.assertTrue(product.owner.canWrite(product, "display_name"))

    def test_canWrite__checking_permissions_of_others(self):
        # Logged in users cannot call Person.canWrite() on Person
        # object for other people.
        person = self.factory.makePerson()
        other = self.factory.makePerson()
        with person_logged_in(person):
            self.assertRaises(Unauthorized, getattr, other, "canWrite")

    def makeSubscribedDistroSourcePackages(self):
        # Create a person, a distribution and four
        # DistributionSourcePacakage. Subscribe the person to two
        # DSPs, and subscribe another person to another DSP.
        user = self.factory.makePerson()
        distribution = self.factory.makeDistribution()
        dsp1 = self.factory.makeDistributionSourcePackage(
            sourcepackagename="sp-b", distribution=distribution
        )
        distribution = self.factory.makeDistribution()
        dsp2 = self.factory.makeDistributionSourcePackage(
            sourcepackagename="sp-a", distribution=distribution
        )
        # We don't reference dsp3 so it gets no name:
        self.factory.makeDistributionSourcePackage(
            sourcepackagename="sp-c", distribution=distribution
        )
        with person_logged_in(user):
            dsp1.addSubscription(user, subscribed_by=user)
            dsp2.addSubscription(user, subscribed_by=user)
        dsp4 = self.factory.makeDistributionSourcePackage(
            sourcepackagename="sp-d", distribution=distribution
        )
        other_user = self.factory.makePerson()
        with person_logged_in(other_user):
            dsp4.addSubscription(other_user, subscribed_by=other_user)
        return user, dsp1, dsp2

    def test_getBugSubscriberPackages(self):
        # getBugSubscriberPackages() returns the DistributionSourcePackages
        # to which a user is subscribed.
        user, dsp1, dsp2 = self.makeSubscribedDistroSourcePackages()

        # We cannot directly compare the objects returned by
        # getBugSubscriberPackages() with the expected DSPs:
        # These are different objects and the class does not have
        # an __eq__ operator. So we compare the attributes distribution
        # and sourcepackagename.

        def get_distribution(dsp):
            return dsp.distribution

        def get_spn(dsp):
            return dsp.sourcepackagename

        result = user.getBugSubscriberPackages()
        self.assertEqual(
            [get_distribution(dsp) for dsp in (dsp2, dsp1)],
            [get_distribution(dsp) for dsp in result],
        )
        self.assertEqual(
            [get_spn(dsp) for dsp in (dsp2, dsp1)],
            [get_spn(dsp) for dsp in result],
        )

    def test_getBugSubscriberPackages__one_query(self):
        # getBugSubscriberPackages() retrieves all objects
        # needed to build the DistributionSourcePackages in
        # one SQL query.
        user, dsp1, dsp2 = self.makeSubscribedDistroSourcePackages()
        Store.of(user).invalidate()
        with StormStatementRecorder() as recorder:
            list(user.getBugSubscriberPackages())
        self.assertThat(recorder, HasQueryCount(Equals(1)))

    def createCopiedPackage(
        self, spph, copier, dest_distroseries=None, dest_archive=None
    ):
        if dest_distroseries is None:
            dest_distroseries = self.factory.makeDistroSeries()
        if dest_archive is None:
            dest_archive = dest_distroseries.main_archive
        return spph.copyTo(
            dest_distroseries,
            creator=copier,
            pocket=PackagePublishingPocket.UPDATES,
            archive=dest_archive,
        )

    def test_getLatestSynchronisedPublishings_most_recent_first(self):
        # getLatestSynchronisedPublishings returns the latest copies sorted
        # by most recent first.
        spph = self.factory.makeSourcePackagePublishingHistory()
        copier = self.factory.makePerson()
        copied_spph1 = self.createCopiedPackage(spph, copier)
        copied_spph2 = self.createCopiedPackage(spph, copier)
        synchronised_spphs = copier.getLatestSynchronisedPublishings()

        self.assertContentEqual(
            [copied_spph2, copied_spph1], synchronised_spphs
        )

    def test_getLatestSynchronisedPublishings_other_creator(self):
        spph = self.factory.makeSourcePackagePublishingHistory()
        copier = self.factory.makePerson()
        self.createCopiedPackage(spph, copier)
        someone_else = self.factory.makePerson()
        synchronised_spphs = someone_else.getLatestSynchronisedPublishings()

        self.assertEqual(0, synchronised_spphs.count())

    def test_getLatestSynchronisedPublishings_latest(self):
        # getLatestSynchronisedPublishings returns only the latest copy of
        # a package in a distroseries
        spph = self.factory.makeSourcePackagePublishingHistory()
        copier = self.factory.makePerson()
        dest_distroseries = self.factory.makeDistroSeries()
        self.createCopiedPackage(spph, copier, dest_distroseries)
        copied_spph2 = self.createCopiedPackage(
            spph, copier, dest_distroseries
        )
        synchronised_spphs = copier.getLatestSynchronisedPublishings()

        self.assertContentEqual([copied_spph2], synchronised_spphs)

    def test_getLatestSynchronisedPublishings_cross_archive_copies(self):
        # getLatestSynchronisedPublishings returns only the copies copied
        # cross archive.
        spph = self.factory.makeSourcePackagePublishingHistory()
        copier = self.factory.makePerson()
        dest_distroseries2 = self.factory.makeDistroSeries(
            distribution=spph.distroseries.distribution
        )
        self.createCopiedPackage(spph, copier, dest_distroseries2)
        synchronised_spphs = copier.getLatestSynchronisedPublishings()

        self.assertEqual(0, synchronised_spphs.count())

    def test_getLatestSynchronisedPublishings_main_archive(self):
        # getLatestSynchronisedPublishings returns only the copies copied in
        # a primary archive (as opposed to a ppa).
        spph = self.factory.makeSourcePackagePublishingHistory()
        copier = self.factory.makePerson()
        dest_distroseries = self.factory.makeDistroSeries()
        ppa = self.factory.makeArchive(
            distribution=dest_distroseries.distribution
        )
        self.createCopiedPackage(spph, copier, dest_distroseries, ppa)
        synchronised_spphs = copier.getLatestSynchronisedPublishings()

        self.assertEqual(0, synchronised_spphs.count())

    def test_product_isAnyPillarOwner(self):
        # Test isAnyPillarOwner for products
        person = self.factory.makePerson()
        owner = self.factory.makePerson()
        self.factory.makeProduct(owner=owner)
        self.assertTrue(owner.isAnyPillarOwner())
        self.assertFalse(person.isAnyPillarOwner())

    def test_projectgroup_isAnyPillarOwner(self):
        # Test isAnyPillarOwner for project groups
        person = self.factory.makePerson()
        owner = self.factory.makePerson()
        self.factory.makeProject(owner=owner)
        self.assertTrue(owner.isAnyPillarOwner())
        self.assertFalse(person.isAnyPillarOwner())

    def test_distribution_isAnyPillarOwner(self):
        # Test isAnyPillarOwner for distributions
        person = self.factory.makePerson()
        owner = self.factory.makePerson()
        self.factory.makeDistribution(owner=owner)
        self.assertTrue(owner.isAnyPillarOwner())
        self.assertFalse(person.isAnyPillarOwner())

    def test_has_current_commercial_subscription_product(self):
        # IPerson.hasCurrentCommercialSubscription() checks for one on a
        # product.
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )
        product = self.factory.makeProduct(owner=team)
        self.factory.makeCommercialSubscription(product)
        self.assertTrue(team.teamowner.hasCurrentCommercialSubscription())

    def test_has_current_commercial_subscription_distribution(self):
        # IPerson.hasCurrentCommercialSubscription() checks for one on a
        # distribution.
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )
        distro = self.factory.makeDistribution(owner=team)
        self.factory.makeCommercialSubscription(distro)
        self.assertTrue(team.teamowner.hasCurrentCommercialSubscription())

    def test_does_not_have_current_commercial_subscription(self):
        # IPerson.hasCurrentCommercialSubscription() is false if it has
        # expired.
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )
        product = self.factory.makeProduct(owner=team)
        self.factory.makeCommercialSubscription(product, expired=True)
        distro = self.factory.makeDistribution(owner=team)
        self.factory.makeCommercialSubscription(distro, expired=True)
        self.assertFalse(team.teamowner.hasCurrentCommercialSubscription())

    def test_does_not_have_commercial_subscription(self):
        # IPerson.hasCurrentCommercialSubscription() is false if they do
        # not have one.
        person = self.factory.makePerson()
        self.assertFalse(person.hasCurrentCommercialSubscription())

    def test_commercial_admin_with_checkAllowVisibility(self):
        admin = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        self.assertTrue(admin.checkAllowVisibility())

    def test_can_not_set_visibility(self):
        person = self.factory.makePerson()
        self.assertRaises(
            ImmutableVisibilityError,
            person.transitionVisibility,
            PersonVisibility.PRIVATE,
            person,
        )

    def test_private_team_has_personal_access_policy(self):
        # Private teams have a personal access policy.
        team = self.factory.makeTeam()
        admin = getUtility(IPersonSet).getByEmail(ADMIN_EMAIL)
        team.transitionVisibility(PersonVisibility.PRIVATE, admin)
        self.assertContentEqual(
            [team],
            [
                ap.person
                for ap in getUtility(IAccessPolicySource).findByTeam([team])
            ],
        )

    def test_public_team_has_no_personal_access_policy(self):
        # Public teams do not have a personal access policy.
        team = self.factory.makeTeam()
        self.assertContentEqual(
            [], getUtility(IAccessPolicySource).findByTeam([team])
        )


class TestPersonStates(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        TestCaseWithFactory.setUp(self, "foo.bar@canonical.com")
        person_set = getUtility(IPersonSet)
        self.myteam = person_set.getByName("myteam")
        self.otherteam = person_set.getByName("otherteam")
        self.guadamen = person_set.getByName("guadamen")
        product_set = getUtility(IProductSet)
        self.bzr = product_set.getByName("bzr")
        self.now = datetime.now(timezone.utc)

    def test_canDeactivate_private_projects(self):
        """A user owning non-public products cannot be deactivated."""
        user = self.factory.makePerson()
        self.factory.makeProduct(
            information_type=InformationType.PUBLIC, name="public", owner=user
        )
        self.factory.makeProduct(
            information_type=InformationType.PROPRIETARY,
            name="private",
            owner=user,
        )

        login(user.preferredemail.email)
        expected_error = (
            "This account cannot be deactivated because it owns "
            "the following non-public products: private"
        )
        self.assertEqual([expected_error], user.canDeactivate())

    def test_deactivate_copes_with_names_already_in_use(self):
        """When a user deactivates their account, their name is changed.

        We do that so that other users can use that name, which the original
        user doesn't seem to want anymore.

        It may happen that we attempt to rename an account to something that
        is already in use. If this happens, we'll simply append an integer to
        that name until we can find one that is free.
        """
        sample_person = IStore(Person).find(Person, name="name12").one()
        login(sample_person.preferredemail.email)
        sample_person.deactivate(comment="blah!")
        self.assertEqual(sample_person.name, "name12-deactivatedaccount")
        # Now that name12 is free Foo Bar can use it.
        foo_bar = IStore(Person).find(Person, name="name16").one()
        foo_bar.name = "name12"
        # If Foo Bar deactivates their account, though, we'll have to use a
        # name other than name12-deactivatedaccount because that is already
        # in use.
        login(foo_bar.preferredemail.email)
        foo_bar.deactivate(comment="blah!")
        self.assertEqual(foo_bar.name, "name12-deactivatedaccount1")

    def test_deactivate_reassigns_owner_and_driver(self):
        """Product owner and driver are reassigned.

        If a user is a product owner and/or driver, when the user is
        deactivated the roles are assigned to the registry experts team.  Note
        a person can have both roles and the method must handle both at once,
        that's why this is one test.
        """
        user = self.factory.makePerson()
        product = self.factory.makeProduct(owner=user)
        with person_logged_in(user):
            product.driver = user
            product.bug_supervisor = user
            user.deactivate(comment="Going off the grid.")
        registry_team = getUtility(ILaunchpadCelebrities).registry_experts
        self.assertEqual(registry_team, product.owner)
        self.assertIs(None, product.driver)
        self.assertIs(None, product.bug_supervisor)

    def test_getDirectMemberIParticipateIn(self):
        sample_person = IStore(Person).find(Person, name="name12").one()
        warty_team = IStore(Person).find(Person, name="name20").one()
        ubuntu_team = IStore(Person).find(Person, name="ubuntu-team").one()
        # Sample Person is an active member of Warty Security Team which in
        # turn is a proposed member of Ubuntu Team. That means
        # sample_person._getDirectMemberIParticipateIn(ubuntu_team) will fail
        # with an AssertionError.
        self.assertIn(sample_person, warty_team.activemembers)
        self.assertIn(warty_team, ubuntu_team.invited_members)
        self.assertRaises(
            AssertionError,
            sample_person._getDirectMemberIParticipateIn,
            ubuntu_team,
        )

        # If we make warty_team an active member of Ubuntu team, then the
        # _getDirectMemberIParticipateIn() call will actually return
        # warty_team.
        login(warty_team.teamowner.preferredemail.email)
        warty_team.acceptInvitationToBeMemberOf(ubuntu_team, comment="foo")
        self.assertIn(warty_team, ubuntu_team.activemembers)
        self.assertEqual(
            sample_person._getDirectMemberIParticipateIn(ubuntu_team),
            warty_team,
        )

    def test_AnswerContact_person_validator(self):
        answer_contact = IStore(AnswerContact).find(AnswerContact).first()
        self.assertRaises(
            PrivatePersonLinkageError,
            setattr,
            answer_contact,
            "person",
            self.myteam,
        )

    def test_Bug_person_validator(self):
        bug = IStore(Bug).find(Bug).first()
        for attr_name in ["owner", "who_made_private"]:
            self.assertRaises(
                PrivatePersonLinkageError, setattr, bug, attr_name, self.myteam
            )

    def test_Specification_person_validator(self):
        specification = IStore(Specification).find(Specification).first()
        for attr_name in [
            "assignee",
            "drafter",
            "approver",
            "owner",
            "goal_proposer",
            "goal_decider",
            "completer",
            "starter",
        ]:
            self.assertRaises(
                PrivatePersonLinkageError,
                setattr,
                specification,
                attr_name,
                self.myteam,
            )

    def test_visibility_validator_caching(self):
        # The method Person.visibilityConsistencyWarning can be called twice
        # when editing a team.  The first is part of the form validator.  It
        # is then called again as part of the database validator.  The test
        # can be expensive so the value is cached so that the queries are
        # needlessly run.
        fake_warning = "Warning!  Warning!"
        naked_team = removeSecurityProxy(self.otherteam)
        naked_team._visibility_warning_cache_key = PersonVisibility.PRIVATE
        naked_team._visibility_warning_cache = fake_warning
        warning = self.otherteam.visibilityConsistencyWarning(
            PersonVisibility.PRIVATE
        )
        self.assertEqual(fake_warning, warning)

    def test_visibility_validator_team_ss_prod_pub_to_private(self):
        # A PUBLIC team with a structural subscription to a product can
        # convert to a PRIVATE team.
        foo_bar = IStore(Person).find(Person, name="name16").one()
        self.bzr.addSubscription(self.otherteam, foo_bar)
        self.otherteam.visibility = PersonVisibility.PRIVATE

    def test_visibility_validator_team_private_to_public(self):
        # A PRIVATE team can transition to PUBLIC.
        self.otherteam.visibility = PersonVisibility.PRIVATE
        self.otherteam.visibility = PersonVisibility.PUBLIC

    def test_visibility_validator_team_private_to_public_with_forbidden(self):
        # A PRIVATE team that owns a distribution can't become PUBLIC.
        # XXX wgrant 2014-01-08: This probably isn't a sane constraint,
        # but it'll do to test the forbidden case until we decide to
        # relax it.
        self.otherteam.visibility = PersonVisibility.PRIVATE
        self.factory.makeDistribution(bug_supervisor=self.otherteam)
        Store.of(self.otherteam).flush()
        try:
            self.otherteam.visibility = PersonVisibility.PUBLIC
        except ImmutableVisibilityError as exc:
            self.assertEqual(
                str(exc),
                "This team cannot be converted to Public since it is "
                "referenced by a distribution.",
            )
        else:
            raise AssertionError("Expected exception.")

    def test_visibility_validator_subteam_public_to_private_view(self):
        team_owner = self.factory.makePerson()
        new_team = self.factory.makeTeam(
            owner=team_owner, visibility=PersonVisibility.PUBLIC
        )
        super_team = self.factory.makeTeam(
            owner=team_owner,
            visibility=PersonVisibility.PUBLIC,
            members=[new_team],
        )
        membershipset = getUtility(ITeamMembershipSet)
        membershipset.deactivateActiveMemberships(
            super_team, "gone", team_owner
        )
        view = create_initialized_view(
            new_team,
            "+edit",
            {
                "field.name": "newteam",
                "field.displayname": "New Team",
                "field.membership_policy": "RESTRICTED",
                "field.renewal_policy": "NONE",
                "field.visibility": "PRIVATE",
                "field.actions.save": "Save",
            },
        )
        self.assertEqual(len(view.errors), 0)
        self.assertEqual(len(view.request.notifications), 0)
        self.assertEqual(new_team.visibility, PersonVisibility.PRIVATE)

    def test_visibility_validator_team_private_to_public_view(self):
        # A PRIVATE team cannot convert to PUBLIC.
        self.otherteam.visibility = PersonVisibility.PRIVATE
        self.factory.makeDistribution(bug_supervisor=self.otherteam)
        Store.of(self.otherteam).flush()
        view = create_initialized_view(
            self.otherteam,
            "+edit",
            {
                "field.name": "otherteam",
                "field.displayname": "Other Team",
                "field.membership_policy": "RESTRICTED",
                "field.renewal_policy": "NONE",
                "field.visibility": "PUBLIC",
                "field.actions.save": "Save",
            },
        )
        self.assertEqual(len(view.errors), 0)
        self.assertEqual(len(view.request.notifications), 1)
        self.assertEqual(
            view.request.notifications[0].message,
            "This team cannot be converted to Public since it is "
            "referenced by a distribution.",
        )

    def test_person_snapshot(self):
        omitted = (
            "activemembers",
            "adminmembers",
            "allmembers",
            "api_all_members",
            "approvedmembers",
            "deactivatedmembers",
            "expiredmembers",
            "inactivemembers",
            "invited_members",
            "member_memberships",
            "pendingmembers",
            "ppas",
            "proposedmembers",
            "time_zone",
        )
        snap = Snapshot(self.myteam, providing=providedBy(self.myteam))
        for name in omitted:
            self.assertFalse(
                hasattr(snap, name),
                "%s should be omitted from the snapshot but is not." % name,
            )

    def test_person_repr_ansii(self):
        # Verify that ANSI displayname is ascii safe.
        person = self.factory.makePerson(
            name="user", displayname="\xdc-tester"
        )
        self.assertEqual("<Person user (\\xdc-tester)>", repr(person))

    def test_person_repr_unicode(self):
        # Verify that Unicode displayname is ascii safe.
        person = self.factory.makePerson(
            name="user", displayname="\u0170-tester"
        )
        self.assertEqual("<Person user (\\u0170-tester)>", repr(person))


class TestPersonRelatedBugTaskSearch(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.user = self.factory.makePerson(displayname="User")
        self.context = self.factory.makePerson(displayname="Context")

    def checkUserFields(
        self,
        params,
        assignee=None,
        bug_subscriber=None,
        owner=None,
        bug_commenter=None,
        bug_reporter=None,
        structural_subscriber=None,
    ):
        self.assertEqual(assignee, params.assignee)
        # fromSearchForm() takes a bug_subscriber parameter, but saves
        # it as subscriber on the parameter object.
        self.assertEqual(bug_subscriber, params.subscriber)
        self.assertEqual(owner, params.owner)
        self.assertEqual(bug_commenter, params.bug_commenter)
        self.assertEqual(bug_reporter, params.bug_reporter)
        self.assertEqual(structural_subscriber, params.structural_subscriber)

    def test_get_person_bugtasks_search_params(self):
        # With no specified options, get_person_bugtasks_search_params()
        # returns 5 BugTaskSearchParams objects, each with a different
        # user field set.
        search_params = get_person_bugtasks_search_params(
            self.user, self.context
        )
        self.assertEqual(len(search_params), 5)
        self.checkUserFields(search_params[0], assignee=self.context)
        self.checkUserFields(search_params[1], bug_subscriber=self.context)
        self.checkUserFields(
            search_params[2], owner=self.context, bug_reporter=self.context
        )
        self.checkUserFields(search_params[3], bug_commenter=self.context)
        self.checkUserFields(
            search_params[4], structural_subscriber=self.context
        )

    def test_get_person_bugtasks_search_params_with_assignee(self):
        # With assignee specified, get_person_bugtasks_search_params()
        # returns 4 BugTaskSearchParams objects.
        search_params = get_person_bugtasks_search_params(
            self.user, self.context, assignee=self.user
        )
        self.assertEqual(len(search_params), 4)
        self.checkUserFields(
            search_params[0], assignee=self.user, bug_subscriber=self.context
        )
        self.checkUserFields(
            search_params[1],
            assignee=self.user,
            owner=self.context,
            bug_reporter=self.context,
        )
        self.checkUserFields(
            search_params[2], assignee=self.user, bug_commenter=self.context
        )
        self.checkUserFields(
            search_params[3],
            assignee=self.user,
            structural_subscriber=self.context,
        )

    def test_get_person_bugtasks_search_params_with_owner(self):
        # With owner specified, get_person_bugtasks_search_params() returns
        # 4 BugTaskSearchParams objects.
        search_params = get_person_bugtasks_search_params(
            self.user, self.context, owner=self.user
        )
        self.assertEqual(len(search_params), 4)
        self.checkUserFields(
            search_params[0], owner=self.user, assignee=self.context
        )
        self.checkUserFields(
            search_params[1], owner=self.user, bug_subscriber=self.context
        )
        self.checkUserFields(
            search_params[2], owner=self.user, bug_commenter=self.context
        )
        self.checkUserFields(
            search_params[3],
            owner=self.user,
            structural_subscriber=self.context,
        )

    def test_get_person_bugtasks_search_params_with_bug_reporter(self):
        # With bug reporter specified, get_person_bugtasks_search_params()
        # returns 4 BugTaskSearchParams objects, but the bug reporter
        # is overwritten in one instance.
        search_params = get_person_bugtasks_search_params(
            self.user, self.context, bug_reporter=self.user
        )
        self.assertEqual(len(search_params), 5)
        self.checkUserFields(
            search_params[0], bug_reporter=self.user, assignee=self.context
        )
        self.checkUserFields(
            search_params[1],
            bug_reporter=self.user,
            bug_subscriber=self.context,
        )
        # When a BugTaskSearchParams is prepared with the owner filled
        # in, the bug reporter is overwritten to match.
        self.checkUserFields(
            search_params[2], bug_reporter=self.context, owner=self.context
        )
        self.checkUserFields(
            search_params[3],
            bug_reporter=self.user,
            bug_commenter=self.context,
        )
        self.checkUserFields(
            search_params[4],
            bug_reporter=self.user,
            structural_subscriber=self.context,
        )

    def test_get_person_bugtasks_search_params_illegal(self):
        self.assertRaises(
            IllegalRelatedBugTasksParams,
            get_person_bugtasks_search_params,
            self.user,
            self.context,
            assignee=self.user,
            owner=self.user,
            bug_commenter=self.user,
            bug_subscriber=self.user,
            structural_subscriber=self.user,
        )

    def test_get_person_bugtasks_search_params_illegal_context(self):
        # in case the `context` argument is not  of type IPerson an
        # AssertionError is raised
        self.assertRaises(
            AssertionError,
            get_person_bugtasks_search_params,
            self.user,
            "Username",
            assignee=self.user,
        )


class KarmaTestMixin:
    """Helper methods for setting karma."""

    def _makeKarmaCache(self, person, pillar, category_name_values):
        """Create a KarmaCache entry with the given arguments.

        'pillar' can be a Product or a Distribution.

        In order to create the KarmaCache record, we must switch to the DB
        user 'karma'. This invalidates the objects under test, so they
        must be retrieved again.
        """
        pillar_unproxied = removeSecurityProxy(pillar)
        pillar_kwargs = {}
        if isinstance(pillar_unproxied, Product):
            pillar_kwargs["product_id"] = pillar.id
        elif isinstance(pillar_unproxied, Distribution):
            pillar_kwargs["distribution_id"] = pillar.id
        else:
            raise ValueError("Pillar must be a Product or Distribution")
        with dbuser("karma"):
            total = 0
            # Insert category total for person and project.
            for category_name, value in category_name_values:
                category = (
                    IStore(KarmaCategory)
                    .find(KarmaCategory, name=category_name)
                    .one()
                )
                self.cache_manager.new(
                    value, person.id, category.id, **pillar_kwargs
                )
                total += value
            # Insert total cache for person and project.
            self.cache_manager.new(total, person.id, None, **pillar_kwargs)

    def _makeKarmaTotalCache(self, person, total):
        """Create a KarmaTotalCache entry.

        In order to create the KarmaTotalCache record we must switch to the DB
        user 'karma'. This invalidates the objects under test so they
        must be retrieved again.
        """
        with dbuser("karma"):
            KarmaTotalCache(person=person, karma_total=total)


class TestPersonKarma(TestCaseWithFactory, KarmaTestMixin):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        a_product = self.factory.makeProduct(name="aa")
        b_product = self.factory.makeProduct(name="bb")
        self.c_product = self.factory.makeProduct(name="cc")
        self.cache_manager = getUtility(IKarmaCacheManager)
        self._makeKarmaCache(self.person, a_product, [("bugs", 10)])
        self._makeKarmaCache(self.person, b_product, [("answers", 50)])
        self._makeKarmaCache(
            self.person, self.c_product, [("code", 100), (("bugs", 50))]
        )

    def test__getProjectsWithTheMostKarma_ordering(self):
        # Verify that pillars are ordered by karma.
        results = removeSecurityProxy(
            self.person
        )._getProjectsWithTheMostKarma(None)
        results = [
            ((distro or product).name, karma)
            for product, distro, karma in results
        ]
        self.assertEqual([("cc", 150), ("bb", 50), ("aa", 10)], results)

    def test__getContributedCategories(self):
        # Verify that a iterable of karma categories is returned.
        categories = removeSecurityProxy(
            self.person
        )._getContributedCategories(self.c_product)
        names = sorted(category.name for category in categories)
        self.assertEqual(["bugs", "code"], names)

    def test_getProjectsAndCategoriesContributedTo(self):
        # Verify that a list of projects and contributed karma categories
        # is returned.
        results = removeSecurityProxy(
            self.person
        ).getProjectsAndCategoriesContributedTo(None)
        names = [entry["project"].name for entry in results]
        self.assertEqual(["cc", "bb", "aa"], names)
        project_categories = results[0]
        names = [
            category.name for category in project_categories["categories"]
        ]
        self.assertEqual(["code", "bugs"], names)

    def test_getProjectsAndCategoriesContributedTo_active_only(self):
        # Verify that deactivated pillars are not included.
        login("admin@canonical.com")
        a_product = getUtility(IProductSet).getByName("cc")
        a_product.active = False
        results = removeSecurityProxy(
            self.person
        ).getProjectsAndCategoriesContributedTo(None)
        names = [entry["project"].name for entry in results]
        self.assertEqual(["bb", "aa"], names)

    def test_getProjectsAndCategoriesContributedTo_limit(self):
        # Verify the limit of 5 is honored.
        d_product = self.factory.makeProduct(name="dd")
        self._makeKarmaCache(self.person, d_product, [("bugs", 5)])
        e_product = self.factory.makeProduct(name="ee")
        self._makeKarmaCache(self.person, e_product, [("bugs", 4)])
        f_product = self.factory.makeProduct(name="ff")
        self._makeKarmaCache(self.person, f_product, [("bugs", 3)])
        results = removeSecurityProxy(
            self.person
        ).getProjectsAndCategoriesContributedTo(None)
        names = [entry["project"].name for entry in results]
        self.assertEqual(["cc", "bb", "aa", "dd", "ee"], names)

    def test_getProjectsAndCategoriesContributedTo_privacy(self):
        # Verify privacy is honored.
        d_owner = self.factory.makePerson()
        d_product = self.factory.makeProduct(
            name="dd",
            information_type=InformationType.PROPRIETARY,
            owner=d_owner,
        )
        self._makeKarmaCache(self.person, d_product, [("bugs", 5)])
        e_product = self.factory.makeProduct(name="ee")
        self._makeKarmaCache(self.person, e_product, [("bugs", 4)])
        f_product = self.factory.makeProduct(name="ff")
        self._makeKarmaCache(self.person, f_product, [("bugs", 3)])
        results = removeSecurityProxy(
            self.person
        ).getProjectsAndCategoriesContributedTo(None)
        names = [entry["project"].name for entry in results]
        self.assertEqual(["cc", "bb", "aa", "ee", "ff"], names)
        results = removeSecurityProxy(
            self.person
        ).getProjectsAndCategoriesContributedTo(d_owner)
        names = [entry["project"].name for entry in results]
        self.assertEqual(["cc", "bb", "aa", "dd", "ee"], names)


class TestAccessProfileView(BrowserTestCase, KarmaTestMixin):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.user = self.factory.makePerson(displayname="user_displayname")
        self.cache_manager = getUtility(IKarmaCacheManager)

    def test_own_profile_without_access_to_distribution(self):
        # Verify user without access to private distro cannot see it in
        # their own profile view, and can access their profile.
        distribution = self.factory.makeDistribution(
            name="distribution",
            displayname="distribution_displayname",
            information_type=InformationType.PROPRIETARY,
        )
        self._makeKarmaCache(self.user, distribution, [("code", 100)])
        # User does not have access to the private distro.
        results = removeSecurityProxy(
            self.user
        ).getProjectsAndCategoriesContributedTo(self.user)
        projects = [entry["project"].name for entry in results]
        self.assertNotIn("distribution", projects)
        # User can view own profile
        profile_url = canonical_url(self.user)
        browser = self.getUserBrowser(url=profile_url, user=self.user)
        browser.open(profile_url)
        self.assertEqual(browser.responseStatusCode, 200)
        self.assertNotIn("distribution_displayname", browser.contents)
        self.assertIn("user_displayname", browser.contents)

    def test_own_profile_with_access_to_distribution(self):
        # Verify user with access to distro can see it in
        # their own profile view, and can access their profile.
        distribution = self.factory.makeDistribution(
            name="distribution",
            displayname="distribution_displayname",
            information_type=InformationType.PUBLIC,
        )
        self._makeKarmaCache(self.user, distribution, [("code", 100)])
        # User has access to the private distro.
        results = removeSecurityProxy(
            self.user
        ).getProjectsAndCategoriesContributedTo(self.user)
        projects = [entry["project"].name for entry in results]
        self.assertIn("distribution", projects)
        # User can view own profile
        profile_url = canonical_url(self.user)
        browser = self.getUserBrowser(url=profile_url, user=self.user)
        browser.open(profile_url)
        self.assertEqual(browser.responseStatusCode, 200)
        self.assertIn("distribution_displayname", browser.contents)
        self.assertIn("user_displayname", browser.contents)


class TestAPIParticipation(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_participation_query_count(self):
        # The query count of team.participants is constant in the number of
        # members.
        team = self.factory.makeTeam()
        teamowner = team.teamowner
        webservice = LaunchpadWebServiceCaller()
        url = "/~%s/participants" % team.name

        def make_team_member():
            person = self.factory.makePerson()
            person.logo = self.factory.makeLibraryFileAlias(
                content_type="image/png", db_only=True
            )
            person.mugshot = self.factory.makeLibraryFileAlias(
                content_type="image/png", db_only=True
            )
            team.addMember(person, teamowner)

        def get_participants():
            logout()
            response = webservice.get(
                url, headers={"User-Agent": "AnonNeedsThis"}
            )
            self.assertEqual(
                200,
                response.status,
                "Got %d for url %r with response %r"
                % (response.status, url, response.body),
            )

        recorder1, recorder2 = record_two_runs(
            get_participants,
            make_team_member,
            1,
            2,
            login_method=login_admin,
            record_request=True,
        )
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))


class TestGetRecipients(TestCaseWithFactory):
    """Tests for get_recipients"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        login("foo.bar@canonical.com")

    def test_get_recipients_indirect(self):
        """Ensure get_recipients uses indirect memberships."""
        owner = self.factory.makePerson(
            displayname="Foo Bar", email="foo@bar.com"
        )
        team = self.factory.makeTeam(owner)
        super_team = self.factory.makeTeam(team)
        recipients = get_recipients(super_team)
        self.assertEqual({owner}, set(recipients))

    def test_get_recipients_team(self):
        """Ensure get_recipients uses teams with preferredemail."""
        owner = self.factory.makePerson(
            displayname="Foo Bar", email="foo@bar.com"
        )
        team = self.factory.makeTeam(owner, email="team@bar.com")
        super_team = self.factory.makeTeam(team)
        recipients = get_recipients(super_team)
        self.assertEqual({team}, set(recipients))

    def test_get_recipients_team_with_unvalidated_address(self):
        """Ensure get_recipients handles teams with non-preferred addresses.

        If there is no preferred address but one or more non-preferred ones,
        email should still be sent to the members.
        """
        owner = self.factory.makePerson(email="foo@bar.com")
        team = self.factory.makeTeam(owner, email="team@bar.com")
        self.assertContentEqual([team], get_recipients(team))
        team.preferredemail.status = EmailAddressStatus.NEW
        clear_property_cache(team)
        self.assertContentEqual([owner], get_recipients(team))

    def makePersonWithNoPreferredEmail(self, **kwargs):
        kwargs["email_address_status"] = EmailAddressStatus.NEW
        return self.factory.makePerson(**kwargs)

    def test_get_recipients_person(self):
        person = self.factory.makePerson()
        recipients = get_recipients(person)
        self.assertEqual({person}, set(recipients))

    def test_get_recipients_person_with_disabled_account(self):
        """Mail is not sent to a direct recipient whose account is disabled."""
        person = self.factory.makePerson()
        person.setAccountStatus(AccountStatus.DEACTIVATED, None, "gone")
        recipients = get_recipients(person)
        self.assertEqual(set(), set(recipients))

    def test_get_recipients_empty(self):
        """get_recipients returns set() for person with no preferredemail."""
        recipients = get_recipients(self.makePersonWithNoPreferredEmail())
        self.assertEqual(set(), set(recipients))

    def test_get_recipients_complex_indirect(self):
        """Ensure get_recipients uses indirect memberships."""
        owner = self.factory.makePerson(
            displayname="Foo Bar", email="foo@bar.com"
        )
        team = self.factory.makeTeam(owner)
        super_team_member_person = self.factory.makePerson(
            displayname="Bing Bar", email="bing@bar.com"
        )
        super_team_member_team = self.factory.makeTeam(email="baz@bar.com")
        super_team = self.factory.makeTeam(
            team,
            members=[
                super_team_member_person,
                super_team_member_team,
                self.makePersonWithNoPreferredEmail(),
            ],
        )
        super_team_member_team.acceptInvitationToBeMemberOf(
            super_team, "Go Team!"
        )
        recipients = list(get_recipients(super_team))
        self.assertEqual(
            {owner, super_team_member_person, super_team_member_team},
            set(recipients),
        )

    def test_get_recipients_team_with_disabled_owner_account(self):
        """Mail is not sent to a team owner whose account is disabled.

        See <https://bugs.launchpad.net/launchpad/+bug/855150>
        """
        owner = self.factory.makePerson(email="foo@bar.com")
        team = self.factory.makeTeam(owner)
        owner.setAccountStatus(AccountStatus.DEACTIVATED, None, "gbcw")
        self.assertContentEqual([], get_recipients(team))

    def test_get_recipients_team_with_disabled_member_account(self):
        """Mail is not sent to a team member whose account is disabled.

        See <https://bugs.launchpad.net/launchpad/+bug/855150>
        """
        person = self.factory.makePerson(email="foo@bar.com")
        person.setAccountStatus(AccountStatus.DEACTIVATED, None, "gbcw")
        team = self.factory.makeTeam(members=[person])
        self.assertContentEqual([team.teamowner], get_recipients(team))

    def test_get_recipients_team_with_nested_disabled_member_account(self):
        """Mail is not sent to transitive team member with disabled account.

        See <https://bugs.launchpad.net/launchpad/+bug/855150>
        """
        person = self.factory.makePerson(email="foo@bar.com")
        person.setAccountStatus(AccountStatus.DEACTIVATED, None, "gbcw")
        team1 = self.factory.makeTeam(members=[person])
        team2 = self.factory.makeTeam(members=[team1])
        self.assertContentEqual([team2.teamowner], get_recipients(team2))


class Test_getAssignedSpecificationWorkItemsDueBefore(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.team = self.factory.makeTeam()
        today = datetime.today().date()
        next_month = today + timedelta(days=30)
        next_year = today + timedelta(days=366)
        self.current_milestone = self.factory.makeMilestone(
            dateexpected=next_month
        )
        self.product = self.current_milestone.product
        self.future_milestone = self.factory.makeMilestone(
            dateexpected=next_year, product=self.product
        )

    def test_basic(self):
        assigned_spec = self.factory.makeSpecification(
            assignee=self.team.teamowner,
            milestone=self.current_milestone,
            product=self.product,
        )
        # Create a workitem with no explicit assignee/milestone. This way it
        # will inherit the ones from the spec it belongs to.
        workitem = self.factory.makeSpecificationWorkItem(
            title="workitem 1", specification=assigned_spec
        )

        # Create a workitem targeted to a milestone too far in the future.
        # This workitem must not be in the list returned by
        # getAssignedSpecificationWorkItemsDueBefore().
        self.factory.makeSpecificationWorkItem(
            title="workitem 2",
            specification=assigned_spec,
            milestone=self.future_milestone,
        )

        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            self.current_milestone.dateexpected, self.team
        )

        self.assertEqual([workitem], list(workitems))

    def test_skips_deleted_workitems(self):
        assigned_spec = self.factory.makeSpecification(
            assignee=self.team.teamowner,
            milestone=self.current_milestone,
            product=self.product,
        )
        # Create a deleted work item.
        self.factory.makeSpecificationWorkItem(
            title="workitem", specification=assigned_spec, deleted=True
        )

        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            self.current_milestone.dateexpected, self.team
        )
        self.assertEqual([], list(workitems))

    def test_workitems_assigned_to_others_working_on_blueprint(self):
        assigned_spec = self.factory.makeSpecification(
            assignee=self.team.teamowner,
            milestone=self.current_milestone,
            product=self.product,
        )
        # Create a workitem with no explicit assignee/milestone. This way it
        # will inherit the ones from the spec it belongs to.
        workitem = self.factory.makeSpecificationWorkItem(
            title="workitem 1", specification=assigned_spec
        )

        # Create a workitem with somebody who's not a member of our team as
        # the assignee. This workitem must be in the list returned by
        # getAssignedSpecificationWorkItemsDueBefore().
        workitem_for_other_person = self.factory.makeSpecificationWorkItem(
            title="workitem 2",
            specification=assigned_spec,
            assignee=self.factory.makePerson(),
        )

        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            self.current_milestone.dateexpected, self.team
        )

        self.assertContentEqual(
            [workitem, workitem_for_other_person], list(workitems)
        )

    def test_skips_workitems_with_milestone_in_the_past(self):
        today = datetime.today().date()
        milestone = self.factory.makeMilestone(
            dateexpected=today - timedelta(days=1)
        )
        spec = self.factory.makeSpecification(
            assignee=self.team.teamowner,
            milestone=milestone,
            product=milestone.product,
        )
        self.factory.makeSpecificationWorkItem(
            title="workitem 1", specification=spec
        )

        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            today, self.team
        )

        self.assertEqual([], list(workitems))

    def test_includes_workitems_from_future_spec(self):
        assigned_spec = self.factory.makeSpecification(
            assignee=self.team.teamowner,
            milestone=self.future_milestone,
            product=self.product,
        )
        # This workitem inherits the spec's milestone and that's too far in
        # the future so it won't be in the returned list.
        self.factory.makeSpecificationWorkItem(
            title="workitem 1", specification=assigned_spec
        )
        # This one, on the other hand, is explicitly targeted to the current
        # milestone, so it is included in the returned list even though its
        # spec is targeted to the future milestone.
        workitem = self.factory.makeSpecificationWorkItem(
            title="workitem 2",
            specification=assigned_spec,
            milestone=self.current_milestone,
        )

        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            self.current_milestone.dateexpected, self.team
        )

        self.assertEqual([workitem], list(workitems))

    def test_includes_workitems_from_foreign_spec(self):
        # This spec is assigned to a person who's not a member of our team, so
        # only the workitems that are explicitly assigned to a member of our
        # team will be in the returned list.
        foreign_spec = self.factory.makeSpecification(
            assignee=self.factory.makePerson(),
            milestone=self.current_milestone,
            product=self.product,
        )
        # This one is not explicitly assigned to anyone, so it inherits the
        # assignee of its spec and hence is not in the returned list.
        self.factory.makeSpecificationWorkItem(
            title="workitem 1", specification=foreign_spec
        )

        # This one, on the other hand, is explicitly assigned to the a member
        # of our team, so it is included in the returned list even though its
        # spec is not assigned to a member of our team.
        workitem = self.factory.makeSpecificationWorkItem(
            title="workitem 2",
            specification=foreign_spec,
            assignee=self.team.teamowner,
        )

        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            self.current_milestone.dateexpected, self.team
        )

        self.assertEqual([workitem], list(workitems))

    def test_listings_consider_spec_visibility(self):
        # This spec is visible only to the product owner, even though it is
        # assigned to self.team.teamowner.  Therefore, it is listed only for
        # product.owner, not the team.
        product = self.factory.makeProduct(
            information_type=InformationType.PROPRIETARY
        )
        with person_logged_in(removeSecurityProxy(product).owner):
            milestone = self.factory.makeMilestone(
                dateexpected=self.current_milestone.dateexpected,
                product=product,
            )
            spec = self.factory.makeSpecification(
                milestone=milestone,
                information_type=InformationType.PROPRIETARY,
            )
            workitem = self.factory.makeSpecificationWorkItem(
                specification=spec, assignee=self.team.teamowner
            )
            workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
                milestone.dateexpected, self.team
            )
        self.assertNotIn(workitem, workitems)
        workitems = self.team.getAssignedSpecificationWorkItemsDueBefore(
            removeSecurityProxy(milestone).dateexpected,
            removeSecurityProxy(product).owner,
        )
        self.assertIn(workitem, workitems)

    def _makeProductSpec(self, milestone_dateexpected):
        assignee = self.factory.makePerson()
        with person_logged_in(self.team.teamowner):
            self.team.addMember(assignee, reviewer=self.team.teamowner)
        milestone = self.factory.makeMilestone(
            dateexpected=milestone_dateexpected
        )
        spec = self.factory.makeSpecification(
            product=milestone.product, milestone=milestone, assignee=assignee
        )
        return spec

    def _makeDistroSpec(self, milestone_dateexpected):
        assignee = self.factory.makePerson()
        with person_logged_in(self.team.teamowner):
            self.team.addMember(assignee, reviewer=self.team.teamowner)
        distro = self.factory.makeDistribution()
        milestone = self.factory.makeMilestone(
            dateexpected=milestone_dateexpected, distribution=distro
        )
        spec = self.factory.makeSpecification(
            distribution=distro, milestone=milestone, assignee=assignee
        )
        return spec

    def test_query_count(self):
        dateexpected = self.current_milestone.dateexpected
        # Create 10 SpecificationWorkItems, each of them with a different
        # specification, milestone and assignee. Also, half of the
        # specifications will have a Product as a target and the other half
        # will have a Distribution.
        for i in range(5):
            spec = self._makeProductSpec(dateexpected)
            self.factory.makeSpecificationWorkItem(
                title="product work item %d" % i,
                assignee=spec.assignee,
                milestone=spec.milestone,
                specification=spec,
            )
            spec2 = self._makeDistroSpec(dateexpected)
            self.factory.makeSpecificationWorkItem(
                title="distro work item %d" % i,
                assignee=spec2.assignee,
                milestone=spec2.milestone,
                specification=spec2,
            )
        flush_database_updates()
        flush_database_caches()
        with StormStatementRecorder() as recorder:
            workitems = list(
                self.team.getAssignedSpecificationWorkItemsDueBefore(
                    dateexpected, self.team
                )
            )
            for workitem in workitems:
                workitem.assignee
                workitem.milestone
                workitem.specification
                workitem.specification.assignee
                workitem.specification.milestone
                workitem.specification.target
        self.assertEqual(10, len(workitems))
        # 1. One query to get all team members;
        # 2. One to get all SpecWorkItems;
        # 3. One to get all Specifications;
        # 4. One to get all SpecWorkItem/Specification assignees;
        # 5. One to get all SpecWorkItem/Specification milestones;
        # 6. One to get all Specification products;
        # 7. One to get all Specification distributions;
        self.assertThat(recorder, HasQueryCount(Equals(7)))


class Test_getAssignedBugTasksDueBefore(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.team = self.factory.makeTeam()
        self.today = datetime.today().date()

    def _assignBugTaskToTeamOwner(self, bugtask):
        removeSecurityProxy(bugtask).assignee = self.team.teamowner

    def test_basic(self):
        milestone = self.factory.makeMilestone(dateexpected=self.today)
        # This bug is assigned to a team member and targeted to a milestone
        # whose due date is before the cutoff date we pass in, so it will be
        # included in the return of getAssignedBugTasksDueBefore().
        milestoned_bug = self.factory.makeBug(milestone=milestone)
        self._assignBugTaskToTeamOwner(milestoned_bug.bugtasks[0])
        # This one is assigned to a team member but not milestoned, so it is
        # not included in the return of getAssignedBugTasksDueBefore().
        non_milestoned_bug = self.factory.makeBug()
        self._assignBugTaskToTeamOwner(non_milestoned_bug.bugtasks[0])
        # This one is milestoned but not assigned to a team member, so it is
        # not included in the return of getAssignedBugTasksDueBefore() either.
        non_assigned_bug = self.factory.makeBug()
        self._assignBugTaskToTeamOwner(non_assigned_bug.bugtasks[0])

        bugtasks = list(
            self.team.getAssignedBugTasksDueBefore(
                self.today + timedelta(days=1), user=None
            )
        )

        self.assertEqual(1, len(bugtasks))
        self.assertEqual(milestoned_bug.bugtasks[0], bugtasks[0])

    def test_skips_tasks_targeted_to_old_milestones(self):
        past_milestone = self.factory.makeMilestone(
            dateexpected=self.today - timedelta(days=1)
        )
        bug = self.factory.makeBug(milestone=past_milestone)
        self._assignBugTaskToTeamOwner(bug.bugtasks[0])

        bugtasks = list(
            self.team.getAssignedBugTasksDueBefore(
                self.today + timedelta(days=1), user=None
            )
        )

        self.assertEqual(0, len(bugtasks))

    def test_skips_private_bugs_the_user_is_not_allowed_to_see(self):
        milestone = self.factory.makeMilestone(dateexpected=self.today)
        private_bug = removeSecurityProxy(
            self.factory.makeBug(
                milestone=milestone, information_type=InformationType.USERDATA
            )
        )
        self._assignBugTaskToTeamOwner(private_bug.bugtasks[0])
        private_bug2 = removeSecurityProxy(
            self.factory.makeBug(
                milestone=milestone, information_type=InformationType.USERDATA
            )
        )
        self._assignBugTaskToTeamOwner(private_bug2.bugtasks[0])

        with person_logged_in(private_bug2.owner):
            bugtasks = list(
                self.team.getAssignedBugTasksDueBefore(
                    self.today + timedelta(days=1),
                    removeSecurityProxy(private_bug2).owner,
                )
            )

            self.assertEqual(private_bug2.bugtasks, bugtasks)

    def test_skips_distroseries_task_that_is_a_conjoined_primary(self):
        distroseries = self.factory.makeDistroSeries()
        sourcepackagename = self.factory.makeSourcePackageName()
        sp = distroseries.getSourcePackage(sourcepackagename.name)
        milestone = self.factory.makeMilestone(
            distroseries=distroseries, dateexpected=self.today
        )
        bug = self.factory.makeBug(
            milestone=milestone, target=sp.distribution_sourcepackage
        )
        removeSecurityProxy(bug).addTask(bug.owner, sp)
        self.assertEqual(2, len(bug.bugtasks))
        replica, primary = bug.bugtasks
        self._assignBugTaskToTeamOwner(primary)
        self.assertEqual(None, primary.conjoined_primary)
        self.assertEqual(primary, replica.conjoined_primary)
        self.assertEqual(replica.milestone, primary.milestone)
        self.assertEqual(replica.assignee, primary.assignee)

        bugtasks = list(
            self.team.getAssignedBugTasksDueBefore(
                self.today + timedelta(days=1), user=None
            )
        )

        self.assertEqual([replica], bugtasks)

    def test_skips_productseries_task_that_is_a_conjoined_primary(self):
        milestone = self.factory.makeMilestone(dateexpected=self.today)
        removeSecurityProxy(milestone.product).development_focus = (
            milestone.productseries
        )
        bug = self.factory.makeBug(
            series=milestone.productseries, milestone=milestone
        )
        self.assertEqual(2, len(bug.bugtasks))
        replica, primary = bug.bugtasks

        # This will cause the assignee to propagate to the other bugtask as
        # well since they're conjoined.
        self._assignBugTaskToTeamOwner(replica)
        self.assertEqual(primary, replica.conjoined_primary)
        self.assertEqual(replica.milestone, primary.milestone)
        self.assertEqual(replica.assignee, primary.assignee)

        bugtasks = list(
            self.team.getAssignedBugTasksDueBefore(
                self.today + timedelta(days=1), user=None
            )
        )

        self.assertEqual([replica], bugtasks)

    def _assignBugTaskToTeamOwnerAndSetMilestone(self, task, milestone):
        self._assignBugTaskToTeamOwner(task)
        removeSecurityProxy(task).milestone = milestone

    def test_query_count(self):
        # Create one Product bugtask;
        milestone = self.factory.makeMilestone(dateexpected=self.today)
        product_bug = self.factory.makeBug(target=milestone.product)
        self._assignBugTaskToTeamOwnerAndSetMilestone(
            product_bug.bugtasks[0], milestone
        )

        # One ProductSeries bugtask;
        productseries_bug = self.factory.makeBug(
            series=milestone.productseries
        )
        self._assignBugTaskToTeamOwnerAndSetMilestone(
            productseries_bug.bugtasks[1], milestone
        )

        # One DistroSeries bugtask;
        distro = self.factory.makeDistribution()
        distro_milestone = self.factory.makeMilestone(
            distribution=distro, dateexpected=self.today
        )
        distroseries_bug = self.factory.makeBug(
            series=distro_milestone.distroseries
        )
        self._assignBugTaskToTeamOwnerAndSetMilestone(
            distroseries_bug.bugtasks[1], distro_milestone
        )

        # One Distribution bugtask;
        distro_bug = self.factory.makeBug(target=distro_milestone.distribution)
        self._assignBugTaskToTeamOwnerAndSetMilestone(
            distro_bug.bugtasks[0], distro_milestone
        )

        # One SourcePackage bugtask;
        distroseries = distro_milestone.distroseries
        dsp = self.factory.makeDistributionSourcePackage(
            distribution=distroseries.distribution
        )
        sourcepackage_bug = self.factory.makeBug(target=dsp)
        self._assignBugTaskToTeamOwnerAndSetMilestone(
            sourcepackage_bug.bugtasks[0], distro_milestone
        )

        flush_database_updates()
        flush_database_caches()
        with StormStatementRecorder() as recorder:
            tasks = list(
                self.team.getAssignedBugTasksDueBefore(
                    self.today + timedelta(days=1), user=None
                )
            )
            for task in tasks:
                task.bug
                task.target
                task.milestone
                task.assignee
        self.assertEqual(5, len(tasks))
        # 1. One query to get all team members;
        # 2. One to get all BugTasks;
        # 3. One to get all assignees;
        # 4. One to get all milestones;
        # 5. One to get all products;
        # 6. One to get all productseries;
        # 7. One to get all distributions;
        # 8. One to get all distroseries;
        # 9. One to get all sourcepackagenames;
        # 10. One to get all distroseries of a bug's distro. (See comment on
        # getAssignedBugTasksDueBefore() to understand why it's needed)
        self.assertThat(recorder, HasQueryCount(Equals(12)))


def list_result(sprint, filter=None, user=None):
    result = sprint.specifications(user, SpecificationSort.DATE, filter=filter)
    return list(result)


def get_specs(context, user=None, **kwargs):
    return context.specifications(user, **kwargs)


class TestSpecifications(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.date_created = datetime.now(timezone.utc)

    def makeSpec(
        self,
        owner=None,
        date_created=0,
        title=None,
        status=NewSpecificationDefinitionStatus.NEW,
        name=None,
        priority=None,
        information_type=None,
    ):
        blueprint = self.factory.makeSpecification(
            title=title,
            status=status,
            name=name,
            priority=priority,
            information_type=information_type,
            owner=owner,
        )
        removeSecurityProxy(blueprint).datecreated = (
            self.date_created + timedelta(date_created)
        )
        return blueprint

    def test_specifications_quantity(self):
        # Ensure the quantity controls the maximum number of entries.
        owner = self.factory.makePerson()
        for _ in range(10):
            self.factory.makeSpecification(owner=owner)
        self.assertEqual(10, get_specs(owner).count())
        self.assertEqual(10, get_specs(owner, quantity=None).count())
        self.assertEqual(8, get_specs(owner, quantity=8).count())
        self.assertEqual(10, get_specs(owner, quantity=11).count())

    def test_date_sort(self):
        # Sort on date_created.
        owner = self.factory.makePerson()
        blueprint1 = self.makeSpec(owner, date_created=0)
        blueprint2 = self.makeSpec(owner, date_created=-1)
        blueprint3 = self.makeSpec(owner, date_created=1)
        result = list_result(owner)
        self.assertEqual([blueprint3, blueprint1, blueprint2], result)

    def test_date_sort_id(self):
        # date-sorting when no date varies uses object id.
        owner = self.factory.makePerson()
        blueprint1 = self.makeSpec(owner)
        blueprint2 = self.makeSpec(owner)
        blueprint3 = self.makeSpec(owner)
        result = list_result(owner)
        self.assertEqual([blueprint1, blueprint2, blueprint3], result)

    def test_priority_sort(self):
        # Sorting by priority works and is the default.
        # When priority is supplied, status is ignored.
        blueprint1 = self.makeSpec(
            priority=SpecificationPriority.UNDEFINED,
            status=SpecificationDefinitionStatus.NEW,
        )
        owner = blueprint1.owner
        blueprint2 = self.makeSpec(
            owner,
            priority=SpecificationPriority.NOTFORUS,
            status=SpecificationDefinitionStatus.APPROVED,
        )
        blueprint3 = self.makeSpec(
            owner,
            priority=SpecificationPriority.LOW,
            status=SpecificationDefinitionStatus.NEW,
        )
        result = get_specs(owner)
        self.assertEqual([blueprint3, blueprint1, blueprint2], list(result))
        result = get_specs(owner, sort=SpecificationSort.PRIORITY)
        self.assertEqual([blueprint3, blueprint1, blueprint2], list(result))

    def test_priority_sort_fallback_status(self):
        # Sorting by priority falls back to defintion_status.
        # When status is supplied, name is ignored.
        blueprint1 = self.makeSpec(
            status=SpecificationDefinitionStatus.NEW, name="a"
        )
        owner = blueprint1.owner
        blueprint2 = self.makeSpec(
            owner, status=SpecificationDefinitionStatus.APPROVED, name="c"
        )
        blueprint3 = self.makeSpec(
            owner, status=SpecificationDefinitionStatus.DISCUSSION, name="b"
        )
        result = get_specs(owner)
        self.assertEqual([blueprint2, blueprint3, blueprint1], list(result))
        result = get_specs(owner, sort=SpecificationSort.PRIORITY)
        self.assertEqual([blueprint2, blueprint3, blueprint1], list(result))

    def test_priority_sort_fallback_name(self):
        # Sorting by priority falls back to name
        blueprint1 = self.makeSpec(name="b")
        owner = blueprint1.owner
        blueprint2 = self.makeSpec(owner, name="c")
        blueprint3 = self.makeSpec(owner, name="a")
        result = get_specs(owner)
        self.assertEqual([blueprint3, blueprint1, blueprint2], list(result))
        result = get_specs(owner, sort=SpecificationSort.PRIORITY)
        self.assertEqual([blueprint3, blueprint1, blueprint2], list(result))

    def test_ignore_inactive(self):
        # Specs for inactive products are skipped.
        product = self.factory.makeProduct()
        with celebrity_logged_in("admin"):
            product.active = False
        spec = self.factory.makeSpecification(product=product)
        self.assertNotIn(spec, get_specs(spec.owner))

    def test_include_distro(self):
        # Specs for distributions are included.
        distribution = self.factory.makeDistribution()
        spec = self.factory.makeSpecification(distribution=distribution)
        self.assertIn(spec, get_specs(spec.owner))

    def test_informational(self):
        # INFORMATIONAL causes only informational specs to be shown.
        enum = SpecificationImplementationStatus
        informational = self.factory.makeSpecification(
            implementation_status=enum.INFORMATIONAL
        )
        owner = informational.owner
        plain = self.factory.makeSpecification(owner=owner)
        result = get_specs(owner)
        self.assertIn(informational, result)
        self.assertIn(plain, result)
        result = get_specs(owner, filter=[SpecificationFilter.INFORMATIONAL])
        self.assertIn(informational, result)
        self.assertNotIn(plain, result)

    def test_completeness(self):
        # If COMPLETE is specified, completed specs are listed.  If INCOMPLETE
        # is specified or neither is specified, only incomplete specs are
        # listed.
        enum = SpecificationImplementationStatus
        implemented = self.factory.makeSpecification(
            implementation_status=enum.IMPLEMENTED
        )
        owner = implemented.owner
        non_implemented = self.factory.makeSpecification(owner=owner)
        result = get_specs(owner, filter=[SpecificationFilter.COMPLETE])
        self.assertIn(implemented, result)
        self.assertNotIn(non_implemented, result)
        result = get_specs(owner, filter=[SpecificationFilter.INCOMPLETE])
        self.assertNotIn(implemented, result)
        self.assertIn(non_implemented, result)
        result = get_specs(owner)
        self.assertNotIn(implemented, result)
        self.assertIn(non_implemented, result)

    def test_all(self):
        # ALL causes both complete and incomplete to be listed.
        enum = SpecificationImplementationStatus
        implemented = self.factory.makeSpecification(
            implementation_status=enum.IMPLEMENTED
        )
        owner = implemented.owner
        non_implemented = self.factory.makeSpecification(owner=owner)
        result = get_specs(owner, filter=[SpecificationFilter.ALL])
        self.assertContentEqual([implemented, non_implemented], result)

    def test_valid(self):
        # VALID adjusts COMPLETE to exclude OBSOLETE and SUPERSEDED specs.
        # (INCOMPLETE already excludes OBSOLETE and SUPERSEDED.)
        i_enum = SpecificationImplementationStatus
        d_enum = SpecificationDefinitionStatus
        implemented = self.factory.makeSpecification(
            implementation_status=i_enum.IMPLEMENTED
        )
        owner = implemented.owner
        self.factory.makeSpecification(owner=owner, status=d_enum.SUPERSEDED)
        self.factory.makeSpecification(owner=owner, status=d_enum.OBSOLETE)
        results = get_specs(
            owner,
            filter=[SpecificationFilter.VALID, SpecificationFilter.COMPLETE],
        )
        self.assertContentEqual([implemented], results)

    def test_roles(self):
        # If roles are specified, they control which specifications are shown.
        # If no roles are specified, all roles are used.
        created = self.factory.makeSpecification()
        person = created.owner

        def rlist(filter=None):
            return list(get_specs(person, filter=filter))

        assigned = self.factory.makeSpecification(assignee=person)
        drafting = self.factory.makeSpecification(drafter=person)
        approving = self.factory.makeSpecification(approver=person)
        subscribed = self.factory.makeSpecification()
        subscribed.subscribe(person)
        self.assertEqual(
            [created, assigned, drafting, approving, subscribed], rlist([])
        )
        self.assertEqual([created], rlist([SpecificationFilter.CREATOR]))
        self.assertEqual([assigned], rlist([SpecificationFilter.ASSIGNEE]))
        self.assertEqual([drafting], rlist([SpecificationFilter.DRAFTER]))
        self.assertEqual([approving], rlist([SpecificationFilter.APPROVER]))
        self.assertEqual([subscribed], rlist([SpecificationFilter.SUBSCRIBER]))

    def test_text_search(self):
        # Text searches work.
        blueprint1 = self.makeSpec(title="abc")
        owner = blueprint1.owner
        blueprint2 = self.makeSpec(owner, title="def")
        result = list_result(owner, ["abc"])
        self.assertEqual([blueprint1], result)
        result = list_result(owner, ["def"])
        self.assertEqual([blueprint2], result)

    def test_proprietary_not_listed(self):
        # Proprietary blueprints are not listed for random users
        blueprint1 = self.makeSpec(
            information_type=InformationType.PROPRIETARY
        )
        owner = removeSecurityProxy(blueprint1).owner
        self.assertEqual([], list_result(owner))

    def test_proprietary_listed_for_artifact_grant(self):
        # Proprietary blueprints are listed for users with an artifact grant.
        blueprint1 = self.makeSpec(
            information_type=InformationType.PROPRIETARY
        )
        grant = self.factory.makeAccessArtifactGrant(
            concrete_artifact=blueprint1
        )
        owner = removeSecurityProxy(blueprint1).owner
        self.assertEqual([blueprint1], list_result(owner, user=grant.grantee))

    def test_proprietary_listed_for_policy_grant(self):
        # Proprietary blueprints are listed for users with a policy grant.
        blueprint1 = self.makeSpec(
            information_type=InformationType.PROPRIETARY
        )
        product = removeSecurityProxy(blueprint1).product
        policy_source = getUtility(IAccessPolicySource)
        (policy,) = policy_source.find(
            [(product, InformationType.PROPRIETARY)]
        )
        grant = self.factory.makeAccessPolicyGrant(policy)
        owner = removeSecurityProxy(blueprint1).owner
        self.assertEqual([blueprint1], list_result(owner, user=grant.grantee))

    def test_storm_sort(self):
        # A Storm expression can be used to sort specs.
        owner = self.factory.makePerson()
        spec = self.factory.makeSpecification(owner=owner, name="a")
        spec2 = self.factory.makeSpecification(owner=owner, name="z")
        spec3 = self.factory.makeSpecification(owner=owner, name="b")
        self.assertContentEqual(
            [spec2, spec3, spec],
            get_specs(owner, sort=Desc(Specification.name)),
        )

    def test_in_progress(self):
        # In-progress filters to exclude not-started and completed.
        enum = SpecificationImplementationStatus
        notstarted = self.factory.makeSpecification(
            implementation_status=enum.NOTSTARTED
        )
        owner = notstarted.owner
        started = self.factory.makeSpecification(
            owner=owner, implementation_status=enum.STARTED
        )
        self.factory.makeSpecification(
            owner=owner, implementation_status=enum.IMPLEMENTED
        )
        self.assertContentEqual([started], get_specs(owner, in_progress=True))

    def test_in_progress_all(self):
        # SpecificationFilter.ALL overrides in_progress.
        enum = SpecificationImplementationStatus
        notstarted = self.factory.makeSpecification(
            implementation_status=enum.NOTSTARTED
        )
        self.assertContentEqual(
            [notstarted],
            get_specs(
                notstarted.owner,
                filter=[SpecificationFilter.ALL],
                in_progress=True,
            ),
        )

    def test_complete_overrides_in_progress(self):
        # SpecificationFilter.COMPLETE overrides in_progress.
        enum = SpecificationImplementationStatus
        started = self.factory.makeSpecification(
            implementation_status=enum.STARTED
        )
        owner = started.owner
        implemented = self.factory.makeSpecification(
            implementation_status=enum.IMPLEMENTED, owner=owner
        )
        specs = get_specs(
            owner, filter=[SpecificationFilter.COMPLETE], in_progress=True
        )
        self.assertContentEqual([implemented], specs)

    def test_incomplete_overrides_in_progress(self):
        # SpecificationFilter.INCOMPLETE overrides in_progress.
        enum = SpecificationImplementationStatus
        notstarted = self.factory.makeSpecification(
            implementation_status=enum.NOTSTARTED
        )
        specs = get_specs(
            notstarted.owner,
            filter=[SpecificationFilter.INCOMPLETE],
            in_progress=True,
        )
        self.assertContentEqual([notstarted], specs)
