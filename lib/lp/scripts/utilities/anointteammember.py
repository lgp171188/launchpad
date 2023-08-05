# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Script to add a user to a team."""

__all__ = ["AnointTeamMemberScript"]

from textwrap import dedent

import transaction
from zope.component import getUtility

from lp.registry.interfaces.person import IPersonSet
from lp.services.config import config
from lp.services.scripts.base import (
    LaunchpadScript,
    LaunchpadScriptFailure,
    SilentLaunchpadScriptFailure,
)
from lp.services.webapp.publisher import canonical_url


class AnointTeamMemberScript(LaunchpadScript):
    """
    Add a user to a team, bypassing the normal workflows.

    This is particularly useful for making a local user be a member of the
    "admins" team in a development environment.

    This script is for testing purposes only.  Do NOT use it in production
    environments.
    """

    usage = "%(prog)s <person> <team>"
    description = dedent(__doc__)

    def main(self):
        if len(self.args) != 2:
            self.parser.print_help()
            raise SilentLaunchpadScriptFailure(2)
        if config.vhost.mainsite.hostname == "launchpad.net":
            raise LaunchpadScriptFailure(
                "This script may not be used on production.  Use normal team "
                "processes instead, or ask an existing member of ~admins."
            )

        person_name, team_name = self.args
        person = getUtility(IPersonSet).getByName(person_name)
        if person is None:
            raise LaunchpadScriptFailure(
                "There is no person named '%s'." % person_name
            )
        team = getUtility(IPersonSet).getByName(team_name)
        if team is None:
            raise LaunchpadScriptFailure(
                "There is no team named '%s'." % team_name
            )
        if not team.is_team:
            raise LaunchpadScriptFailure(
                "The person named '%s' is not a team." % team_name
            )

        team.addMember(person, person)
        transaction.commit()
        self.logger.info(
            "Anointed ~%s as a member of ~%s.", person_name, team_name
        )
        self.logger.info(
            "Use %s to leave.", canonical_url(team, view_name="+leave")
        )
