#!/usr/bin/python3 -S
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Flag expired team memberships and warn about impending expiration."""

import _pythonpath  # noqa: F401

from zope.component import getUtility

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.teammembership import ITeamMembershipSet
from lp.services.config import config
from lp.services.scripts.base import (
    LaunchpadCronScript,
    LaunchpadScriptFailure,
)


class ExpireMemberships(LaunchpadCronScript):
    """A script for expired team memberships."""

    def flag_expired_memberships_and_send_warnings(self):
        """Flag expired team memberships and warn about impending expiration.

        Flag expired team memberships and send warnings for members whose
        team memberships are expiring soon.
        """
        membershipset = getUtility(ITeamMembershipSet)
        self.txn.begin()
        reviewer = getUtility(ILaunchpadCelebrities).janitor
        membershipset.handleMembershipsExpiringToday(reviewer, self.logger)
        self.txn.commit()

        self.txn.begin()
        memberships_to_warn = membershipset.getExpiringMembershipsToWarn()
        for membership in memberships_to_warn:
            membership.sendExpirationWarningEmail()
            self.logger.debug(
                "Sent warning email to %s in %s team."
                % (membership.person.name, membership.team.name)
            )
        self.txn.commit()

    def main(self):
        """Flag expired team memberships."""
        if self.args:
            raise LaunchpadScriptFailure(
                "Unhandled arguments %s" % repr(self.args)
            )
        self.logger.info("Flagging expired team memberships.")
        self.flag_expired_memberships_and_send_warnings()
        self.logger.info("Finished flagging expired team memberships.")


if __name__ == "__main__":
    script = ExpireMemberships(
        "flag-expired-memberships",
        dbuser=config.expiredmembershipsflagger.dbuser,
    )
    script.lock_and_run()
