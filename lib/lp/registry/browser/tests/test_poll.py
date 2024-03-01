# Copyright 2010-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for IPoll views."""

import os
from datetime import datetime, timedelta, timezone

from fixtures import FakeLogger

from lp.registry.interfaces.poll import CannotCreatePoll, PollAlgorithm
from lp.testing import BrowserTestCase, TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_view


class TestPollVoteView(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.team = self.factory.makeTeam()

    def test_simple_poll_template(self):
        poll = self.factory.makePoll(
            self.team,
            "name",
            "title",
            "proposition",
            poll_type=PollAlgorithm.SIMPLE,
        )
        view = create_view(poll, name="+vote")
        self.assertEqual(
            "poll-vote-simple.pt", os.path.basename(view.template.filename)
        )

    def test_condorcet_poll_template(self):
        poll = self.factory.makePoll(
            self.team,
            "name",
            "title",
            "proposition",
            poll_type=PollAlgorithm.CONDORCET,
        )
        view = create_view(poll, name="+vote")
        self.assertEqual(
            "poll-vote-condorcet.pt", os.path.basename(view.template.filename)
        )


class TestPollAddView(BrowserTestCase):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.pushConfig(
            "launchpad", min_legitimate_karma=5, min_legitimate_account_age=5
        )

    def test_new_user(self):
        # A brand new user cannot create polls.
        self.useFixture(FakeLogger())
        new_person = self.factory.makePerson()
        team = self.factory.makeTeam(owner=new_person)
        now = datetime.now(timezone.utc)
        browser = self.getViewBrowser(
            team, view_name="+newpoll", user=new_person
        )
        browser.getControl("The unique name of this poll").value = "colour"
        browser.getControl("The title of this poll").value = "Favourite Colour"
        browser.getControl("The date and time when this poll opens").value = (
            str(now + timedelta(days=1))
        )
        browser.getControl("The date and time when this poll closes").value = (
            str(now + timedelta(days=2))
        )
        browser.getControl(
            "The proposition that is going to be voted"
        ).value = "What is your favourite colour?"
        self.assertRaises(
            CannotCreatePoll, browser.getControl("Continue").click
        )

    def test_legitimate_user(self):
        # A user with some kind of track record can create polls.
        person = self.factory.makePerson(karma=10)
        team = self.factory.makeTeam(owner=person)
        now = datetime.now(timezone.utc)
        browser = self.getViewBrowser(team, view_name="+newpoll", user=person)
        browser.getControl("The unique name of this poll").value = "colour"
        browser.getControl("The title of this poll").value = "Favourite Colour"
        browser.getControl("The date and time when this poll opens").value = (
            str(now + timedelta(days=1))
        )
        browser.getControl("The date and time when this poll closes").value = (
            str(now + timedelta(days=2))
        )
        browser.getControl(
            "The proposition that is going to be voted"
        ).value = "What is your favourite colour?"
        browser.getControl("Continue").click()
