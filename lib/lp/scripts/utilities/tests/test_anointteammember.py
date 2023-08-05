# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction

from lp.scripts.utilities.anointteammember import AnointTeamMemberScript
from lp.services.log.logger import BufferLogger
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


class TestAnointTeamMember(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def makeScript(self, test_args):
        script = AnointTeamMemberScript(test_args=test_args)
        script.logger = BufferLogger()
        script.txn = transaction
        return script

    def test_refuses_on_production(self):
        self.pushConfig("vhost.mainsite", hostname="launchpad.net")
        script = self.makeScript(["person", "team"])
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "This script may not be used on production.  Use normal team "
            "processes instead, or ask an existing member of ~admins.",
            script.main,
        )
        self.assertEqual("", script.logger.getLogBuffer())

    def test_no_such_person(self):
        script = self.makeScript(["nonexistent-person", "admins"])
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "There is no person named 'nonexistent-person'.",
            script.main,
        )
        self.assertEqual("", script.logger.getLogBuffer())

    def test_no_such_team(self):
        script = self.makeScript(
            [self.factory.makePerson().name, "nonexistent-team"]
        )
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "There is no team named 'nonexistent-team'.",
            script.main,
        )
        self.assertEqual("", script.logger.getLogBuffer())

    def test_person_not_a_team(self):
        persons = [self.factory.makePerson() for _ in range(2)]
        script = self.makeScript([persons[0].name, persons[1].name])
        self.assertRaisesWithContent(
            LaunchpadScriptFailure,
            "The person named '%s' is not a team." % persons[1].name,
            script.main,
        )
        self.assertEqual("", script.logger.getLogBuffer())

    def test_success(self):
        person = self.factory.makePerson()
        team = self.factory.makeTeam()
        self.assertFalse(person.inTeam(team))
        script = self.makeScript([person.name, team.name])
        script.main()
        self.assertTrue(person.inTeam(team))
        self.assertEqual(
            "INFO Anointed ~%s as a member of ~%s.\n"
            "INFO Use http://launchpad.test/~%s/+leave to leave.\n"
            % (person.name, team.name, team.name),
            script.logger.getLogBuffer(),
        )
