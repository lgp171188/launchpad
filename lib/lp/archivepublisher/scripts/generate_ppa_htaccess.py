#!/usr/bin/python2
#
# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from datetime import datetime

import pytz

from lp.registry.model.teammembership import TeamParticipation
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.mail.helpers import get_email_template
from lp.services.mail.mailwrapper import MailWrapper
from lp.services.mail.sendmail import (
    format_address,
    simple_sendmail,
    )
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.webapp import canonical_url
from lp.soyuz.enums import ArchiveSubscriberStatus
from lp.soyuz.model.archiveauthtoken import ArchiveAuthToken
from lp.soyuz.model.archivesubscriber import ArchiveSubscriber


class HtaccessTokenGenerator(LaunchpadCronScript):
    """Expire archive subscriptions and deactivate invalid tokens."""

    # XXX cjwatson 2021-04-21: This script and class are now misnamed, as we
    # no longer generate .htaccess or .htpasswd files, but instead check
    # archive authentication dynamically.  We can remove this script once we
    # stop running it on production and move its remaining functions
    # elsewhere (probably garbo).

    def add_my_options(self):
        """Add script command line options."""
        self.parser.add_option(
            "-n", "--dry-run", action="store_true",
            dest="dryrun", default=False,
            help="If set, no files are changed and no tokens are "
                 "deactivated.")
        self.parser.add_option(
            "-d", "--no-deactivation", action="store_true",
            dest="no_deactivation", default=False,
            help="If set, tokens are not deactivated.")

    def sendCancellationEmail(self, token):
        """Send an email to the person whose subscription was cancelled."""
        if token.archive.suppress_subscription_notifications:
            # Don't send an email if they should be suppresed for the
            # archive
            return
        send_to_person = token.person
        ppa_name = token.archive.displayname
        ppa_owner_url = canonical_url(token.archive.owner)
        subject = "PPA access cancelled for %s" % ppa_name
        template = get_email_template(
            "ppa-subscription-cancelled.txt", app='soyuz')

        assert not send_to_person.is_team, (
            "Token.person is a team, it should always be individuals.")

        if send_to_person.preferredemail is None:
            # The person has no preferred email set, so we don't
            # email them.
            return

        to_address = [send_to_person.preferredemail.email]
        replacements = {
            'recipient_name': send_to_person.displayname,
            'ppa_name': ppa_name,
            'ppa_owner_url': ppa_owner_url,
            }
        body = MailWrapper(72).format(
            template % replacements, force_wrap=True)

        from_address = format_address(
            ppa_name,
            config.canonical.noreply_from_address)

        headers = {
            'Sender': config.canonical.bounce_address,
            }

        simple_sendmail(from_address, to_address, subject, body, headers)

    def _getInvalidTokens(self):
        """Return all invalid tokens.

        A token is invalid if it is active and the token owner is *not* a
        subscriber to the archive that the token is for. The subscription can
        be either direct or through a team.
        """
        # First we grab all the active tokens for which there is a
        # matching current archive subscription for a team of which the
        # token owner is a member.
        store = IStore(ArchiveSubscriber)
        valid_tokens = store.find(
            ArchiveAuthToken,
            ArchiveAuthToken.name == None,
            ArchiveAuthToken.date_deactivated == None,
            ArchiveAuthToken.archive_id == ArchiveSubscriber.archive_id,
            ArchiveSubscriber.status == ArchiveSubscriberStatus.CURRENT,
            ArchiveSubscriber.subscriber_id == TeamParticipation.teamID,
            TeamParticipation.personID == ArchiveAuthToken.person_id)

        # We can then evaluate the invalid tokens by the difference of
        # all active tokens and valid tokens.
        all_active_tokens = store.find(
            ArchiveAuthToken,
            ArchiveAuthToken.name == None,
            ArchiveAuthToken.date_deactivated == None)

        return all_active_tokens.difference(valid_tokens)

    def deactivateTokens(self, tokens, send_email=False):
        """Deactivate the given tokens.

        :return: A set of PPAs affected by the deactivations.
        """
        affected_ppas = set()
        num_tokens = 0
        for token in tokens:
            if send_email:
                self.sendCancellationEmail(token)
            # Deactivate tokens one at a time, as 'tokens' is the result of a
            # set expression and storm does not allow setting on such things.
            token.deactivate()
            affected_ppas.add(token.archive)
            num_tokens += 1
        self.logger.debug(
            "Deactivated %s tokens, %s PPAs affected"
            % (num_tokens, len(affected_ppas)))
        return affected_ppas

    def deactivateInvalidTokens(self, send_email=False):
        """Deactivate tokens as necessary.

        If an active token for a PPA no longer has any subscribers,
        we deactivate the token.

        :param send_email: Whether to send a cancellation email to the owner
            of the token.  This defaults to False to speed up the test
            suite.
        :return: the set of ppas affected by token deactivations.
        """
        invalid_tokens = self._getInvalidTokens()
        return self.deactivateTokens(invalid_tokens, send_email=send_email)

    def expireSubscriptions(self):
        """Expire subscriptions as necessary.

        If an `ArchiveSubscriber`'s date_expires has passed, then
        set its status to EXPIRED.
        """
        now = datetime.now(pytz.UTC)

        store = IStore(ArchiveSubscriber)
        newly_expired_subscriptions = store.find(
            ArchiveSubscriber,
            ArchiveSubscriber.status == ArchiveSubscriberStatus.CURRENT,
            ArchiveSubscriber.date_expires != None,
            ArchiveSubscriber.date_expires <= now)

        subscription_names = [
            subs.displayname for subs in newly_expired_subscriptions]
        if subscription_names:
            newly_expired_subscriptions.set(
                status=ArchiveSubscriberStatus.EXPIRED)
            self.logger.info(
                "Expired subscriptions: %s" % ", ".join(subscription_names))

    def main(self):
        """Script entry point."""
        self.logger.info('Starting the PPA .htaccess generation')
        self.expireSubscriptions()
        affected_ppas = self.deactivateInvalidTokens(send_email=True)
        self.logger.debug(
            '%s PPAs with deactivated tokens' % len(affected_ppas))

        if self.options.no_deactivation or self.options.dryrun:
            self.logger.info('Dry run, so not committing transaction.')
            self.txn.abort()
        else:
            self.logger.info('Committing transaction...')
            self.txn.commit()

        self.logger.info('Finished PPA .htaccess generation')
