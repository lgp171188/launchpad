# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the generate_ppa_htaccess.py script. """

from __future__ import absolute_import, print_function, unicode_literals

from datetime import (
    datetime,
    timedelta,
    )
import os
import subprocess
import sys

import pytz
from zope.component import getUtility

from lp.archivepublisher.scripts.generate_ppa_htaccess import (
    HtaccessTokenGenerator,
    )
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.teammembership import TeamMembershipStatus
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.log.logger import BufferLogger
from lp.soyuz.enums import ArchiveSubscriberStatus
from lp.soyuz.interfaces.archive import NAMED_AUTH_TOKEN_FEATURE_FLAG
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import (
    lp_dbuser,
    switch_dbuser,
    )
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.mail_helpers import pop_notifications


class TestPPAHtaccessTokenGeneration(TestCaseWithFactory):
    """Test the generate_ppa_htaccess.py script."""

    layer = LaunchpadZopelessLayer
    dbuser = config.generateppahtaccess.dbuser

    SCRIPT_NAME = 'test tokens'

    def setUp(self):
        super(TestPPAHtaccessTokenGeneration, self).setUp()
        self.owner = self.factory.makePerson(
            name="joe", displayname="Joe Smith")
        self.ppa = self.factory.makeArchive(
            owner=self.owner, name="myppa", private=True)

        # "Ubuntu" doesn't have a proper publisher config but Ubuntutest
        # does, so override the PPA's distro here.
        ubuntutest = getUtility(IDistributionSet)['ubuntutest']
        self.ppa.distribution = ubuntutest

        # Enable named auth tokens.
        self.useFixture(FeatureFixture({NAMED_AUTH_TOKEN_FEATURE_FLAG: "on"}))

    def getScript(self, test_args=None):
        """Return a HtaccessTokenGenerator instance."""
        if test_args is None:
            test_args = []
        script = HtaccessTokenGenerator(self.SCRIPT_NAME, test_args=test_args)
        script.logger = BufferLogger()
        script.txn = self.layer.txn
        switch_dbuser(self.dbuser)
        return script

    def runScript(self):
        """Run the expiry script.

        :return: a tuple of return code, stdout and stderr.
        """
        script = os.path.join(
            config.root, "cronscripts", "generate-ppa-htaccess.py")
        args = [sys.executable, script, "-v"]
        process = subprocess.Popen(
            args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = process.communicate()
        return process.returncode, stdout, stderr

    def assertDeactivated(self, token):
        """Helper function to test token deactivation state."""
        return self.assertNotEqual(token.date_deactivated, None)

    def assertNotDeactivated(self, token):
        """Helper function to test token deactivation state."""
        self.assertEqual(token.date_deactivated, None)

    def setupSubscriptionsAndTokens(self):
        """Set up a few subscriptions and test tokens and return them."""
        # Set up some teams.  We need to test a few scenarios:
        # - someone in one subscribed team and leaving that team loses
        #    their token.
        # - someone in two subscribed teams leaving one team does not
        #   lose their token.
        # - All members of a team lose their tokens when a team of a
        #   subscribed team leaves it.

        persons1 = []
        persons2 = []
        name12 = getUtility(IPersonSet).getByName("name12")
        team1 = self.factory.makeTeam(owner=name12)
        team2 = self.factory.makeTeam(owner=name12)
        for count in range(5):
            person = self.factory.makePerson()
            team1.addMember(person, name12)
            persons1.append(person)
            person = self.factory.makePerson()
            team2.addMember(person, name12)
            persons2.append(person)

        all_persons = persons1 + persons2

        parent_team = self.factory.makeTeam(owner=name12)
        # This needs to be forced or TeamParticipation is not updated.
        parent_team.addMember(team2, name12, force_team_add=True)

        promiscuous_person = self.factory.makePerson()
        team1.addMember(promiscuous_person, name12)
        team2.addMember(promiscuous_person, name12)
        all_persons.append(promiscuous_person)

        lonely_person = self.factory.makePerson()
        all_persons.append(lonely_person)

        # At this point we have team1, with 5 people in it, team2 with 5
        # people in it, team3 with only team2 in it, promiscuous_person
        # who is in team1 and team2, and lonely_person who is in no
        # teams.

        # Ok now do some subscriptions and ensure everyone has a token.
        self.ppa.newSubscription(team1, self.ppa.owner)
        self.ppa.newSubscription(parent_team, self.ppa.owner)
        self.ppa.newSubscription(lonely_person, self.ppa.owner)
        tokens = {}
        for person in all_persons:
            tokens[person] = self.ppa.newAuthToken(person)

        return (
            team1, team2, parent_team, lonely_person,
            promiscuous_person, all_persons, persons1, persons2, tokens)

    def testDeactivatingTokens(self):
        """Test that token deactivation happens properly."""
        data = self.setupSubscriptionsAndTokens()
        (team1, team2, parent_team, lonely_person, promiscuous_person,
            all_persons, persons1, persons2, tokens) = data
        team1_person = persons1[0]

        # Named tokens should be ignored for deactivation.
        self.ppa.newNamedAuthToken("tokenname1")
        named_token = self.ppa.newNamedAuthToken("tokenname2")
        named_token.deactivate()

        # Initially, nothing is eligible for deactivation.
        script = self.getScript()
        script.deactivateInvalidTokens()
        for person in tokens:
            self.assertNotDeactivated(tokens[person])

        # Now remove someone from team1. They will lose their token but
        # everyone else keeps theirs.
        with lp_dbuser():
            team1_person.leave(team1)
        # Clear out emails generated when leaving a team.
        pop_notifications()

        script.deactivateInvalidTokens(send_email=True)
        self.assertDeactivated(tokens[team1_person])
        del tokens[team1_person]
        for person in tokens:
            self.assertNotDeactivated(tokens[person])

        # Ensure that a cancellation email was sent.
        self.assertEmailQueueLength(1)

        # Promiscuous_person now leaves team1, but does not lose their
        # token because they're also in team2. No other tokens are
        # affected.
        with lp_dbuser():
            promiscuous_person.leave(team1)
        # Clear out emails generated when leaving a team.
        pop_notifications()
        script.deactivateInvalidTokens(send_email=True)
        self.assertNotDeactivated(tokens[promiscuous_person])
        for person in tokens:
            self.assertNotDeactivated(tokens[person])

        # Ensure that a cancellation email was not sent.
        self.assertEmailQueueLength(0)

        # Team 2 now leaves parent_team, and all its members lose their
        # tokens.
        with lp_dbuser():
            name12 = getUtility(IPersonSet).getByName("name12")
            parent_team.setMembershipData(
                team2, TeamMembershipStatus.APPROVED, name12)
            parent_team.setMembershipData(
                team2, TeamMembershipStatus.DEACTIVATED, name12)
            self.assertFalse(team2.inTeam(parent_team))
        script.deactivateInvalidTokens()
        for person in persons2:
            self.assertDeactivated(tokens[person])

        # promiscuous_person also loses the token because they're not in
        # either team now.
        self.assertDeactivated(tokens[promiscuous_person])

        # lonely_person still has their token; they're not in any teams.
        self.assertNotDeactivated(tokens[lonely_person])

    def setupDummyTokens(self):
        """Helper function to set up some tokens."""
        name12 = getUtility(IPersonSet).getByName("name12")
        name16 = getUtility(IPersonSet).getByName("name16")
        sub1 = self.ppa.newSubscription(name12, self.ppa.owner)
        sub2 = self.ppa.newSubscription(name16, self.ppa.owner)
        token1 = self.ppa.newAuthToken(name12)
        token2 = self.ppa.newAuthToken(name16)
        token3 = self.ppa.newNamedAuthToken("tokenname3")
        self.layer.txn.commit()
        return (sub1, sub2), (token1, token2, token3)

    def testSubscriptionExpiry(self):
        """Ensure subscriptions' statuses are set to EXPIRED properly."""
        subs, tokens = self.setupDummyTokens()
        now = datetime.now(pytz.UTC)

        # Expire the first subscription.
        subs[0].date_expires = now - timedelta(minutes=3)
        self.assertEqual(subs[0].status, ArchiveSubscriberStatus.CURRENT)

        # Set the expiry in the future for the second.
        subs[1].date_expires = now + timedelta(minutes=3)
        self.assertEqual(subs[0].status, ArchiveSubscriberStatus.CURRENT)

        # Run the script and make sure only the first was expired.
        script = self.getScript()
        script.main()
        self.assertEqual(subs[0].status, ArchiveSubscriberStatus.EXPIRED)
        self.assertEqual(subs[1].status, ArchiveSubscriberStatus.CURRENT)

    def _setupOptionsData(self):
        """Setup test data for option testing."""
        subs, tokens = self.setupDummyTokens()

        # Cancel the first subscription.
        subs[0].cancel(self.ppa.owner)
        self.assertNotDeactivated(tokens[0])
        return subs, tokens

    def testDryrunOption(self):
        """Test that the dryrun and no-deactivation option works."""
        subs, tokens = self._setupOptionsData()

        script = self.getScript(test_args=["--dry-run"])
        script.main()

        # Assert that the cancelled subscription did not cause the token
        # to get deactivated.
        self.assertNotDeactivated(tokens[0])

    def testNoDeactivationOption(self):
        """Test that the --no-deactivation option works."""
        subs, tokens = self._setupOptionsData()
        script = self.getScript(test_args=["--no-deactivation"])
        script.main()
        self.assertNotDeactivated(tokens[0])
        script = self.getScript()
        script.main()
        self.assertDeactivated(tokens[0])

    def testSendingCancellationEmail(self):
        """Test that when a token is deactivated, its user gets an email.

        The email must contain the right headers and text.
        """
        subs, tokens = self.setupDummyTokens()
        script = self.getScript()

        # Clear out any existing email.
        pop_notifications()

        script.sendCancellationEmail(tokens[0])

        [email] = pop_notifications()
        self.assertEqual(
            email['Subject'],
            "PPA access cancelled for PPA named myppa for Joe Smith")
        self.assertEqual(email['To'], "test@canonical.com")
        self.assertEqual(
            email['From'],
            "PPA named myppa for Joe Smith <noreply@launchpad.net>")
        self.assertEqual(email['Sender'], "bounces@canonical.com")

        body = email.get_payload()
        self.assertEqual(
            body,
            "Hello Sample Person,\n\n"
            "Launchpad: cancellation of archive access\n"
            "-----------------------------------------\n\n"
            "Your access to the private software archive "
                "\"PPA named myppa for Joe\nSmith\", "
            "which is hosted by Launchpad, has been "
                "cancelled.\n\n"
            "You will now no longer be able to download software from this "
                "archive.\n"
            "If you think this cancellation is in error, you should contact "
                "the owner\n"
            "of the archive to verify it.\n\n"
            "You can contact the archive owner by visiting their Launchpad "
                "page here:\n\n"
            "<http://launchpad.test/~joe>\n\n"
            "If you have any concerns you can contact the Launchpad team by "
                "emailing\n"
            "feedback@launchpad.net\n\n"
            "Regards,\n"
            "The Launchpad team")

    def testNoEmailOnCancellationForSuppressedArchive(self):
        """No email should be sent if the archive has
        suppress_subscription_notifications set."""
        subs, tokens = self.setupDummyTokens()
        token = tokens[0]
        token.archive.suppress_subscription_notifications = True
        script = self.getScript()

        # Clear out any existing email.
        pop_notifications()

        script.sendCancellationEmail(token)

        self.assertEmailQueueLength(0)
