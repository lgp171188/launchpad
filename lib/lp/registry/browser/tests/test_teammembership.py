# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from testtools.matchers import LessThan
from zope.component import getUtility

from lp.registry.interfaces.teammembership import (
    ITeamMembershipSet,
    TeamMembershipStatus,
)
from lp.testing import (
    StormStatementRecorder,
    TestCaseWithFactory,
    login_celebrity,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.views import create_view


class TestTeamMenu(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        login_celebrity("admin")
        self.membership_set = getUtility(ITeamMembershipSet)
        self.team = self.factory.makeTeam()
        self.member = self.factory.makeTeam()

    def test_deactivate_member_query_count(self):
        # Only these queries should be run, no matter what the
        # membership tree looks like, although the number of queries
        # could change slightly if a different user is logged in.
        #   1.  Check whether the user is the team owner.
        #   2.  Deactivate the membership in the TeamMembership table.
        #   3.  Delete from TeamParticipation table.
        #       (Queries #4, #5, #8, and #9 are run because the storm
        #       objects have been invalidated.)
        #   4.  Get the TeamMembership entry.
        #   5.  Verify that the member exists in the db.
        #   6.  Insert into Job table.
        #   7.  Insert into SharingJob table to schedule removal of
        #       subscriptions to artifacts shared with the team.
        #   8.  Verify that the user exists in the db.
        #   9.  Verify that the team exists in the db.
        #   10. Insert into Job table.
        #   11. Insert into PersonTransferJob table to schedule sending
        #       email. (This requires the data from queries #5, #8, and #9.)
        self.team.addMember(
            self.member, self.team.teamowner, force_team_add=True
        )
        form = {
            "editactive": 1,
            "expires": "never",
            "deactivate": "Deactivate",
        }
        membership = self.membership_set.getByPersonAndTeam(
            self.member, self.team
        )
        view = create_view(membership, "+index", method="POST", form=form)
        with StormStatementRecorder() as recorder:
            view.processForm()
        self.assertEqual("", view.errormessage)
        self.assertEqual(TeamMembershipStatus.DEACTIVATED, membership.status)
        self.assertThat(recorder, HasQueryCount(LessThan(12)))
