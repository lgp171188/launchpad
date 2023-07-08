# Copyright 2010-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Testing registry-related xmlrpc calls."""

import xmlrpc.client
from email import message_from_string
from textwrap import dedent

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
from lp.registry.interfaces.mailinglist import (
    IMailingListSet,
    IMessageApprovalSet,
    MailingListStatus,
    PostedMessageStatus,
)
from lp.registry.interfaces.person import PersonalStanding
from lp.services.compat import message_as_bytes
from lp.services.config import config
from lp.testing import TestCaseWithFactory, admin_logged_in, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadFunctionalLayer
from lp.testing.mail_helpers import pop_notifications
from lp.testing.xmlrpc import XMLRPCTestTransport


class TestCanonicalSSOApplication(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.rpc_proxy = xmlrpc.client.ServerProxy(
            "http://xmlrpc-private.launchpad.test:8087/canonicalsso",
            transport=XMLRPCTestTransport(),
        )

    def test_getPersonDetailsByOpenIDIdentifier(self):
        person = self.factory.makePerson(time_zone="Australia/Melbourne")
        self.factory.makeTeam(
            name="pubteam",
            members=[person],
            visibility=PersonVisibility.PUBLIC,
        )
        self.factory.makeTeam(
            name="privteam",
            members=[person],
            visibility=PersonVisibility.PRIVATE,
        )
        openid_identifier = (
            removeSecurityProxy(person.account)
            .openid_identifiers.any()
            .identifier
        )
        result = self.rpc_proxy.getPersonDetailsByOpenIDIdentifier(
            openid_identifier
        )
        self.assertEqual(
            dict(
                name=person.name,
                time_zone=person.location.time_zone,
                teams={"pubteam": False, "privteam": True},
            ),
            result,
        )

    def test_not_available_on_public_api(self):
        # The person set api is not available on the public xmlrpc
        # service.
        person = self.factory.makePerson()
        openid_identifier = (
            removeSecurityProxy(person.account)
            .openid_identifiers.any()
            .identifier
        )
        public_rpc_proxy = xmlrpc.client.ServerProxy(
            "http://test@canonical.com:test@"
            "xmlrpc.launchpad.test/canonicalsso",
            transport=XMLRPCTestTransport(),
        )
        e = self.assertRaises(
            xmlrpc.client.ProtocolError,
            public_rpc_proxy.getPersonDetailsByOpenIDIdentifier,
            openid_identifier,
        )
        self.assertEqual(404, e.errcode)


class TestMailingListXMLRPC(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.rpc_proxy = xmlrpc.client.ServerProxy(
            "http://xmlrpc-private.launchpad.test:8087/mailinglists",
            transport=XMLRPCTestTransport(),
        )

    def test_getMembershipInformation(self):
        team, member = self.factory.makeTeamWithMailingListSubscribers(
            "team", auto_subscribe=False
        )
        result = self.rpc_proxy.getMembershipInformation([team.name])
        self.assertIn(team.name, result.keys())

    def test_reportStatus(self):
        # Successful constructions lead to ACTIVE lists.
        team = self.factory.makeTeam(name="team")
        team_list = getUtility(IMailingListSet).new(team, team.teamowner)
        self.rpc_proxy.getPendingActions()
        self.rpc_proxy.reportStatus({"team": "success"})
        self.assertEqual(MailingListStatus.ACTIVE, team_list.status)

    def test_isTeamPublic(self):
        self.factory.makeTeam(
            name="team-a", visibility=PersonVisibility.PUBLIC
        )
        self.factory.makeTeam(
            name="team-b", visibility=PersonVisibility.PRIVATE
        )
        self.assertIs(True, self.rpc_proxy.isTeamPublic("team-a"))
        self.assertIs(False, self.rpc_proxy.isTeamPublic("team-b"))

    def test_isRegisteredInLaunchpad(self):
        self.factory.makeTeam(email="me@fndor.dom")
        self.assertFalse(
            self.rpc_proxy.isRegisteredInLaunchpad("me@fndor.dom")
        )

    def test_inGoodStanding(self):
        self.factory.makePerson(email="no@eg.dom")
        yes_person = self.factory.makePerson(email="yes@eg.dom")
        with admin_logged_in():
            yes_person.personal_standing = PersonalStanding.GOOD
        self.assertIs(True, self.rpc_proxy.inGoodStanding("yes@eg.dom"))
        self.assertIs(False, self.rpc_proxy.inGoodStanding("no@eg.dom"))

    def test_updateTeamAddresses(self):
        staging_config_name = self.factory.getUniqueString()
        config.push(
            staging_config_name,
            "\n[launchpad]\nis_demo: True\n"
            "\n[mailman]\nbuild_host_name: lists.launchpad.test\n",
        )
        try:
            self.rpc_proxy.updateTeamAddresses("lists.launchpad.net")
        finally:
            config.pop(staging_config_name)


class TestMailingListXMLRPCMessage(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def setUp(self):
        super().setUp()
        self.rpc_proxy = xmlrpc.client.ServerProxy(
            "http://xmlrpc-private.launchpad.test:8087/mailinglists",
            transport=XMLRPCTestTransport(),
        )

    def makeMailingListAndHeldMessage(self, private=False):
        if private:
            visibility = PersonVisibility.PRIVATE
        else:
            visibility = PersonVisibility.PUBLIC
        owner = self.factory.makePerson()
        team = self.factory.makeTeam(
            name="team",
            owner=owner,
            visibility=visibility,
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        with person_logged_in(owner):
            self.factory.makeMailingList(team, owner)
        sender = self.factory.makePerson(email="me@eg.dom")
        with person_logged_in(sender):
            message = message_from_string(
                dedent(
                    """\
                From: me@eg.dom
                To: team@lists.launchpad.test
                Subject: A question
                Message-ID: <first-post>
                Date: Fri, 01 Aug 2000 01:08:59 -0000\n
                I have a question about this team.
                """
                )
            )
        return team, sender, message

    def test_holdMessage(self):
        # Calling holdMessages send a copy of the message text to Lp
        # and notifies a team admins to moderate it.
        team, sender, message = self.makeMailingListAndHeldMessage()
        pop_notifications()
        info = self.rpc_proxy.holdMessage("team", message_as_bytes(message))
        notifications = pop_notifications()
        found = getUtility(IMessageApprovalSet).getMessageByMessageID(
            "<first-post>"
        )
        self.assertIs(True, info)
        self.assertIsNot(None, found)
        self.assertEqual(1, len(notifications))
        self.assertEqual(
            "New mailing list message requiring approval for Team",
            notifications[0]["subject"],
        )
        self.assertTextMatchesExpressionIgnoreWhitespace(
            r".*http://launchpad.test/~team/\+mailinglist-moderate.*",
            notifications[0].get_payload(),
        )
        self.assertEqual({}, self.rpc_proxy.getMessageDispositions())

    def test_getMessageDispositions_accept(self):
        # List moderators can approve messages.
        team, sender, message = self.makeMailingListAndHeldMessage()
        pop_notifications()
        self.rpc_proxy.holdMessage("team", message_as_bytes(message))
        found = getUtility(IMessageApprovalSet).getMessageByMessageID(
            "<first-post>"
        )
        found.approve(team.teamowner)
        self.assertEqual(PostedMessageStatus.APPROVAL_PENDING, found.status)
        self.assertEqual(
            {"<first-post>": ["team", "accept"]},
            self.rpc_proxy.getMessageDispositions(),
        )
        self.assertEqual(PostedMessageStatus.APPROVED, found.status)
