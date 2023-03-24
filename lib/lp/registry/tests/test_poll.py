# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import datetime, timedelta, timezone
from operator import attrgetter

from testtools.matchers import ContainsDict, Equals, MatchesListwise
from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.poll import IPollSet, PollSecrecy
from lp.registry.model.poll import Poll
from lp.registry.personmerge import merge_people
from lp.services.database.interfaces import IStore
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    TestCaseWithFactory,
    api_url,
    login,
    login_person,
    logout,
)
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.pages import webservice_for_person


class TestPoll(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_getWinners_handle_polls_with_only_spoilt_votes(self):
        login("mark@example.com")
        owner = self.factory.makePerson()
        team = self.factory.makeTeam(owner)
        poll = self.factory.makePoll(team, "name", "title", "proposition")
        # Force opening of poll so that we can vote.
        poll.dateopens = datetime.now(timezone.utc) - timedelta(minutes=2)
        poll.storeSimpleVote(owner, None)
        # Force closing of the poll so that we can call getWinners().
        poll.datecloses = datetime.now(timezone.utc)
        self.assertIsNone(poll.getWinners(), poll.getWinners())


class MatchesPollAPI(ContainsDict):
    def __init__(self, webservice, poll):
        super().__init__(
            {
                "team_link": Equals(
                    webservice.getAbsoluteUrl(api_url(poll.team))
                ),
                "name": Equals(poll.name),
                "title": Equals(poll.title),
                "dateopens": Equals(poll.dateopens.isoformat()),
                "datecloses": Equals(poll.datecloses.isoformat()),
                "proposition": Equals(poll.proposition),
                "type": Equals(poll.type.title),
                "allowspoilt": Equals(poll.allowspoilt),
                "secrecy": Equals(poll.secrecy.title),
            }
        )


class TestPollWebservice(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        self.pushConfig("launchpad", default_batch_size=50)

    def makePolls(self):
        teams = [self.factory.makeTeam() for _ in range(3)]
        polls = []
        for team in teams:
            for offset in (-8, -1, 1):
                dateopens = datetime.now(timezone.utc) + timedelta(days=offset)
                datecloses = dateopens + timedelta(days=7)
                polls.append(
                    getUtility(IPollSet).new(
                        team=team,
                        name=self.factory.getUniqueUnicode(),
                        title=self.factory.getUniqueUnicode(),
                        proposition=self.factory.getUniqueUnicode(),
                        dateopens=dateopens,
                        datecloses=datecloses,
                        secrecy=PollSecrecy.SECRET,
                        allowspoilt=True,
                        check_permissions=False,
                    )
                )
        return polls

    def test_find_all(self):
        polls = list(IStore(Poll).find(Poll)) + self.makePolls()
        webservice = webservice_for_person(
            self.person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get("/+polls", "find")
        login_person(self.person)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody()["entries"],
            MatchesListwise(
                [
                    MatchesPollAPI(webservice, poll)
                    for poll in sorted(
                        polls, key=attrgetter("id"), reverse=True
                    )
                ]
            ),
        )

    def test_find_all_ordered(self):
        polls = list(IStore(Poll).find(Poll)) + self.makePolls()
        webservice = webservice_for_person(
            self.person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get(
            "/+polls", "find", order_by="by opening date"
        )
        login_person(self.person)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody()["entries"],
            MatchesListwise(
                [
                    MatchesPollAPI(webservice, poll)
                    for poll in sorted(
                        polls, key=attrgetter("dateopens", "id")
                    )
                ]
            ),
        )

    def test_find_ignores_merged(self):
        sampledata_polls = list(IStore(Poll).find(Poll))
        new_polls = self.makePolls()
        merge_people(
            new_polls[0].team,
            getUtility(ILaunchpadCelebrities).registry_experts,
            self.person,
            delete=True,
        )
        webservice = webservice_for_person(
            self.person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get(
            "/+polls", "find", order_by="by opening date"
        )
        login_person(self.person)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody()["entries"],
            MatchesListwise(
                [
                    MatchesPollAPI(webservice, poll)
                    for poll in sorted(
                        sampledata_polls + new_polls[3:],
                        key=attrgetter("dateopens", "id"),
                    )
                ]
            ),
        )

    def test_find_by_team(self):
        polls = self.makePolls()
        team_url = api_url(polls[0].team)
        webservice = webservice_for_person(
            self.person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get("/+polls", "find", team=team_url)
        login_person(self.person)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody()["entries"],
            MatchesListwise(
                [
                    MatchesPollAPI(webservice, poll)
                    for poll in sorted(
                        polls[:3], key=attrgetter("id"), reverse=True
                    )
                ]
            ),
        )

    def test_find_by_team_and_status(self):
        polls = self.makePolls()
        team_url = api_url(polls[0].team)
        webservice = webservice_for_person(
            self.person, permission=OAuthPermission.READ_PUBLIC
        )
        webservice.default_api_version = "devel"
        logout()
        response = webservice.named_get(
            "/+polls", "find", team=team_url, status=["open", "not-yet-opened"]
        )
        login_person(self.person)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody()["entries"],
            MatchesListwise(
                [
                    MatchesPollAPI(webservice, poll)
                    for poll in sorted(
                        polls[1:3], key=attrgetter("id"), reverse=True
                    )
                ]
            ),
        )
        logout()
        response = webservice.named_get(
            "/+polls", "find", team=team_url, status=["closed", "open"]
        )
        login_person(self.person)
        self.assertEqual(200, response.status)
        self.assertThat(
            response.jsonBody()["entries"],
            MatchesListwise(
                [
                    MatchesPollAPI(webservice, poll)
                    for poll in sorted(
                        polls[:2], key=attrgetter("id"), reverse=True
                    )
                ]
            ),
        )
