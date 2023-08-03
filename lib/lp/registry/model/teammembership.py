# Copyright 2009-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "find_team_participations",
    "TeamMembership",
    "TeamMembershipSet",
    "TeamParticipation",
]

from datetime import datetime, timedelta, timezone

from storm.expr import Func
from storm.info import ClassAlias
from storm.locals import DateTime, Int, Reference, Unicode
from storm.store import Store
from zope.component import getUtility
from zope.interface import implementer

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.enums import TeamMembershipRenewalPolicy
from lp.registry.errors import (
    TeamMembershipTransitionError,
    UserCannotChangeMembershipSilently,
)
from lp.registry.interfaces.person import (
    validate_person,
    validate_public_person,
)
from lp.registry.interfaces.persontransferjob import (
    IExpiringMembershipNotificationJobSource,
    IMembershipNotificationJobSource,
    ISelfRenewalNotificationJobSource,
)
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.interfaces.sharingjob import (
    IRemoveArtifactSubscriptionsJobSource,
)
from lp.registry.interfaces.teammembership import (
    ACTIVE_STATES,
    DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT,
    CyclicalTeamMembershipError,
    ITeamMembership,
    ITeamMembershipSet,
    ITeamParticipation,
    TeamMembershipStatus,
)
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import flush_database_updates, sqlvalues
from lp.services.database.stormbase import StormBase


@implementer(ITeamMembership)
class TeamMembership(StormBase):
    """See `ITeamMembership`."""

    __storm_table__ = "TeamMembership"
    __storm_order__ = "id"

    id = Int(primary=True)
    team_id = Int(name="team", allow_none=False)
    team = Reference(team_id, "Person.id")
    person_id = Int(name="person", validator=validate_person, allow_none=False)
    person = Reference(person_id, "Person.id")
    last_changed_by_id = Int(
        name="last_changed_by", validator=validate_public_person, default=None
    )
    last_changed_by = Reference(last_changed_by_id, "Person.id")
    proposed_by_id = Int(
        name="proposed_by", validator=validate_public_person, default=None
    )
    proposed_by = Reference(proposed_by_id, "Person.id")
    acknowledged_by_id = Int(
        name="acknowledged_by", validator=validate_public_person, default=None
    )
    acknowledged_by = Reference(acknowledged_by_id, "Person.id")
    reviewed_by_id = Int(
        name="reviewed_by", validator=validate_public_person, default=None
    )
    reviewed_by = Reference(reviewed_by_id, "Person.id")
    status = DBEnum(name="status", allow_none=False, enum=TeamMembershipStatus)
    # XXX: salgado, 2008-03-06: Need to rename datejoined and dateexpires to
    # match their db names.
    datejoined = DateTime(
        name="date_joined", default=None, tzinfo=timezone.utc
    )
    dateexpires = DateTime(
        name="date_expires", default=None, tzinfo=timezone.utc
    )
    date_created = DateTime(default=UTC_NOW, tzinfo=timezone.utc)
    date_proposed = DateTime(default=None, tzinfo=timezone.utc)
    date_acknowledged = DateTime(default=None, tzinfo=timezone.utc)
    date_reviewed = DateTime(default=None, tzinfo=timezone.utc)
    date_last_changed = DateTime(default=None, tzinfo=timezone.utc)
    last_change_comment = Unicode(default=None)
    proponent_comment = Unicode(default=None)
    acknowledger_comment = Unicode(default=None)
    reviewer_comment = Unicode(default=None)

    def __init__(self, team, person, status, dateexpires=None):
        super().__init__()
        self.team = team
        self.person = person
        self.status = status
        self.dateexpires = dateexpires

    def isExpired(self):
        """See `ITeamMembership`."""
        return self.status == TeamMembershipStatus.EXPIRED

    def canBeRenewedByMember(self):
        """See `ITeamMembership`."""
        ondemand = TeamMembershipRenewalPolicy.ONDEMAND
        admin = TeamMembershipStatus.APPROVED
        approved = TeamMembershipStatus.ADMIN
        # We add a grace period of one day to the limit to
        # cover the fencepost error when `date_limit` is
        # earlier than `self.dateexpires`, which happens later
        # in the same day.
        date_limit = datetime.now(timezone.utc) + timedelta(
            days=DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT + 1
        )
        return (
            self.status in (admin, approved)
            and self.team.renewal_policy == ondemand
            and self.dateexpires is not None
            and self.dateexpires < date_limit
        )

    def sendSelfRenewalNotification(self):
        """See `ITeamMembership`."""
        getUtility(ISelfRenewalNotificationJobSource).create(
            self.person, self.team, self.dateexpires
        )

    def canChangeStatusSilently(self, user):
        """Ensure that the user is in the Launchpad Administrators group.

        Then the user can silently make changes to their membership status.
        """
        return user.inTeam(getUtility(ILaunchpadCelebrities).admin)

    def canChangeExpirationDate(self, person):
        """See `ITeamMembership`."""
        person_is_team_admin = self.team in person.getAdministratedTeams()
        person_is_lp_admin = IPersonRoles(person).in_admin
        return person_is_team_admin or person_is_lp_admin

    def setExpirationDate(self, date, user):
        """See `ITeamMembership`."""
        if date == self.dateexpires:
            return

        assert self.canChangeExpirationDate(
            user
        ), "This user can't change this membership's expiration date."
        self._setExpirationDate(date, user)

    def _setExpirationDate(self, date, user):
        assert (
            date is None or date.date() >= datetime.now(timezone.utc).date()
        ), (
            "The given expiration date must be None or be in the future: %s"
            % date.strftime("%Y-%m-%d")
        )
        self.dateexpires = date
        self.last_changed_by = user

    def sendExpirationWarningEmail(self):
        """See `ITeamMembership`."""
        if self.dateexpires is None:
            raise AssertionError(
                "%s in team %s has no membership expiration date."
                % (self.person.name, self.team.name)
            )
        if self.dateexpires < datetime.now(timezone.utc):
            # The membership has reached expiration. Silently return because
            # there is nothing to do. The member will have received emails
            # from previous calls by flag-expired-memberships.py
            return
        getUtility(IExpiringMembershipNotificationJobSource).create(
            self.person, self.team, self.dateexpires
        )

    def setStatus(self, status, user, comment=None, silent=False):
        """See `ITeamMembership`."""
        if status == self.status:
            return False

        if silent and not self.canChangeStatusSilently(user):
            raise UserCannotChangeMembershipSilently(
                "Only Launchpad administrators may change membership "
                "statuses silently."
            )

        approved = TeamMembershipStatus.APPROVED
        admin = TeamMembershipStatus.ADMIN
        expired = TeamMembershipStatus.EXPIRED
        declined = TeamMembershipStatus.DECLINED
        deactivated = TeamMembershipStatus.DEACTIVATED
        proposed = TeamMembershipStatus.PROPOSED
        invited = TeamMembershipStatus.INVITED
        invitation_declined = TeamMembershipStatus.INVITATION_DECLINED

        self.person.clearInTeamCache()

        # Make sure the transition from the current status to the given one
        # is allowed. All allowed transitions are in the TeamMembership spec.
        state_transition = {
            admin: [approved, expired, deactivated],
            approved: [admin, expired, deactivated],
            deactivated: [proposed, approved, admin, invited],
            expired: [proposed, approved, admin, invited],
            proposed: [approved, admin, declined],
            declined: [proposed, approved, admin, invited],
            invited: [approved, admin, invitation_declined],
            invitation_declined: [invited, approved, admin],
        }

        if self.status not in state_transition:
            raise TeamMembershipTransitionError(
                "Unknown status: %s" % self.status.name
            )
        if status not in state_transition[self.status]:
            raise TeamMembershipTransitionError(
                "Bad state transition from %s to %s"
                % (self.status.name, status.name)
            )

        if status in ACTIVE_STATES and self.team in self.person.allmembers:
            raise CyclicalTeamMembershipError(
                "Cannot make %(person)s a member of %(team)s because "
                "%(team)s is a member of %(person)s."
                % dict(person=self.person.name, team=self.team.name)
            )

        old_status = self.status
        self.status = status

        now = datetime.now(timezone.utc)
        if status in [proposed, invited]:
            self.proposed_by = user
            self.proponent_comment = comment
            self.date_proposed = now
        elif (
            status in ACTIVE_STATES and old_status not in ACTIVE_STATES
        ) or status == declined:
            self.reviewed_by = user
            self.reviewer_comment = comment
            self.date_reviewed = now
            if self.datejoined is None and status in ACTIVE_STATES:
                # This is the first time this membership is made active.
                self.datejoined = now
        else:
            # No need to set proponent or reviewer.
            pass

        if old_status == invited:
            # This member has been invited by an admin and is now accepting or
            # declining the invitation.
            self.acknowledged_by = user
            self.date_acknowledged = now
            self.acknowledger_comment = comment

        self.last_changed_by = user
        self.last_change_comment = comment
        self.date_last_changed = now

        if status in ACTIVE_STATES:
            _fillTeamParticipation(self.person, self.team)
        elif old_status in ACTIVE_STATES:
            _cleanTeamParticipation(self.person, self.team)
            # A person has left the team so they may no longer have access
            # to some artifacts shared with the team. We need to run a job
            # to remove any subscriptions to such artifacts.
            getUtility(IRemoveArtifactSubscriptionsJobSource).create(
                user, grantee=self.person
            )
        else:
            # Changed from an inactive state to another inactive one, so no
            # need to fill/clean the TeamParticipation table.
            pass

        # Flush all updates to ensure any subsequent calls to this method on
        # the same transaction will operate on the correct data.  That is the
        # case with our script to expire team memberships.
        flush_database_updates()

        # When a member proposes themselves, a more detailed notification is
        # sent to the team admins by a subscriber of JoinTeamEvent; that's
        # why we don't send anything here.
        if (
            self.person != self.last_changed_by or self.status != proposed
        ) and not silent:
            self._sendStatusChangeNotification(old_status)
        return True

    def _sendStatusChangeNotification(self, old_status):
        """Send a status change notification to all team admins and the
        member whose membership's status changed.
        """
        reviewer = self.last_changed_by
        new_status = self.status
        getUtility(IMembershipNotificationJobSource).create(
            self.person,
            self.team,
            reviewer,
            old_status,
            new_status,
            self.last_change_comment,
        )

    def destroySelf(self):
        Store.of(self).remove(self)


@implementer(ITeamMembershipSet)
class TeamMembershipSet:
    """See `ITeamMembershipSet`."""

    def new(self, person, team, status, user, dateexpires=None, comment=None):
        """See `ITeamMembershipSet`."""
        proposed = TeamMembershipStatus.PROPOSED
        approved = TeamMembershipStatus.APPROVED
        admin = TeamMembershipStatus.ADMIN
        invited = TeamMembershipStatus.INVITED
        assert status in [proposed, approved, admin, invited]

        person.clearInTeamCache()

        tm = TeamMembership(
            person=person, team=team, status=status, dateexpires=dateexpires
        )

        now = datetime.now(timezone.utc)
        tm.proposed_by = user
        tm.date_proposed = now
        tm.proponent_comment = comment
        if status in [approved, admin]:
            tm.datejoined = now
            tm.reviewed_by = user
            tm.date_reviewed = now
            tm.reviewer_comment = comment
            _fillTeamParticipation(person, team)

        return tm

    def handleMembershipsExpiringToday(self, reviewer, logger=None):
        """See `ITeamMembershipSet`."""
        memberships = self.getMembershipsToExpire()
        for membership in memberships:
            membership.setStatus(TeamMembershipStatus.EXPIRED, reviewer)
            if logger is not None:
                logger.info(
                    "The membership for %s in team %s has expired."
                    % (membership.person.name, membership.team.name)
                )

    def getByPersonAndTeam(self, person, team):
        """See `ITeamMembershipSet`."""
        return (
            IStore(TeamMembership)
            .find(TeamMembership, person=person, team=team)
            .one()
        )

    def getMembershipsToExpire(self, when=None):
        """See `ITeamMembershipSet`."""
        if when is None:
            when = datetime.now(timezone.utc)
        conditions = [
            TeamMembership.dateexpires <= when,
            TeamMembership.status.is_in(
                [TeamMembershipStatus.ADMIN, TeamMembershipStatus.APPROVED]
            ),
        ]
        return IStore(TeamMembership).find(TeamMembership, *conditions)

    def getExpiringMembershipsToWarn(self):
        """See `ITeamMembershipSet`,"""
        now = datetime.now(timezone.utc)
        min_date_for_daily_warning = now + timedelta(days=7)
        memberships_to_warn = set(
            self.getMembershipsToExpire(min_date_for_daily_warning)
        )
        weekly_reminder_dates = [
            (now + timedelta(days=weeks * 7)).date()
            for weeks in range(
                2, DAYS_BEFORE_EXPIRATION_WARNING_IS_SENT // 7 + 1
            )
        ]
        memberships_to_warn.update(
            list(self.getMembershipsExpiringOnDates(weekly_reminder_dates))
        )
        return memberships_to_warn

    def getMembershipsExpiringOnDates(self, dates):
        """See `ITeamMembershipSet`."""
        return IStore(TeamMembership).find(
            TeamMembership,
            Func("date_trunc", "day", TeamMembership.dateexpires).is_in(dates),
            TeamMembership.status.is_in(
                [TeamMembershipStatus.ADMIN, TeamMembershipStatus.APPROVED]
            ),
        )

    def deactivateActiveMemberships(self, team, comment, reviewer):
        """See `ITeamMembershipSet`."""
        now = datetime.now(timezone.utc)
        all_members = list(team.activemembers)
        IStore(TeamMembership).find(
            TeamMembership,
            TeamMembership.team == team,
            TeamMembership.status.is_in(ACTIVE_STATES),
        ).set(
            status=TeamMembershipStatus.DEACTIVATED,
            last_changed_by_id=reviewer.id,
            last_change_comment=comment,
            date_last_changed=now,
        )
        for member in all_members:
            # store.invalidate() is called for each iteration.
            _cleanTeamParticipation(member, team)


@implementer(ITeamParticipation)
class TeamParticipation(StormBase):
    __storm_table__ = "TeamParticipation"

    id = Int(primary=True)
    team_id = Int(name="team", allow_none=False)
    team = Reference(team_id, "Person.id")
    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")


def _cleanTeamParticipation(child, parent):
    """Remove child from team and clean up child's subteams.

    A participant of child is removed from parent's TeamParticipation
    entries if the only path from the participant to parent is via
    child.
    """
    # Delete participation entries for the child and the child's
    # direct/indirect members in other ancestor teams, unless those
    # ancestor teams have another path the child besides the
    # membership that has just been deactivated.
    store = Store.of(parent)
    store.execute(
        """
        DELETE FROM TeamParticipation
        USING (
            /* Get all the participation entries that might need to be
             * deleted, i.e. all the entries where the
             * TeamParticipation.person is a participant of child, and
             * where child participated in TeamParticipation.team until
             * child was removed from parent.
             */
            SELECT person, team
            FROM TeamParticipation
            WHERE person IN (
                    SELECT person
                    FROM TeamParticipation
                    WHERE team = %(child)s
                )
                AND team IN (
                    SELECT team
                    FROM TeamParticipation
                    WHERE person = %(child)s
                        AND team != %(child)s
                )


            EXCEPT (

                /* Compute the TeamParticipation entries that we need to
                 * keep by walking the tree in the TeamMembership table.
                 */
                WITH RECURSIVE parent(person, team) AS (
                    /* Start by getting all the ancestors of the child
                     * from the TeamParticipation table, then get those
                     * ancestors' direct members to recurse through the
                     * tree from the top.
                     */
                    SELECT ancestor.person, ancestor.team
                    FROM TeamMembership ancestor
                    WHERE ancestor.status IN %(active_states)s
                        AND ancestor.team IN (
                            SELECT team
                            FROM TeamParticipation
                            WHERE person = %(child)s
                        )

                    UNION

                    /* Find the next level of direct members, but hold
                     * onto the parent.team, since we want the top and
                     * bottom of the hierarchy to calculate the
                     * TeamParticipation. The query above makes sure
                     * that we do this for all the ancestors.
                     */
                    SELECT child.person, parent.team
                    FROM TeamMembership child
                        JOIN parent ON child.team = parent.person
                    WHERE child.status IN %(active_states)s
                )
                SELECT person, team
                FROM parent
            )
        ) AS keeping
        WHERE TeamParticipation.person = keeping.person
            AND TeamParticipation.team = keeping.team
        """
        % sqlvalues(child=child.id, active_states=ACTIVE_STATES)
    )
    store.invalidate()


def _fillTeamParticipation(member, accepting_team):
    """Add relevant entries in TeamParticipation for given member and team.

    Add a tuple "member, team" in TeamParticipation for the given team and all
    of its superteams. More information on how to use the TeamParticipation
    table can be found in the TeamParticipationUsage spec.
    """
    if member.is_team:
        # The submembers will be all the members of the team that is
        # being added as a member. The superteams will be all the teams
        # that the accepting_team belongs to, so all the members will
        # also be joining the superteams indirectly. It is important to
        # remember that teams are members of themselves, so the member
        # team will also be one of the submembers, and the
        # accepting_team will also be one of the superteams.
        query = """
            INSERT INTO TeamParticipation (person, team)
            SELECT submember.person, superteam.team
            FROM TeamParticipation submember
                JOIN TeamParticipation superteam ON TRUE
            WHERE submember.team = %(member)d
                AND superteam.person = %(accepting_team)d
                AND NOT EXISTS (
                    SELECT 1
                    FROM TeamParticipation
                    WHERE person = submember.person
                        AND team = superteam.team
                    )
            """ % dict(
            member=member.id, accepting_team=accepting_team.id
        )
    else:
        query = """
            INSERT INTO TeamParticipation (person, team)
            SELECT %(member)d, superteam.team
            FROM TeamParticipation superteam
            WHERE superteam.person = %(accepting_team)d
                AND NOT EXISTS (
                    SELECT 1
                    FROM TeamParticipation
                    WHERE person = %(member)d
                        AND team = superteam.team
                    )
            """ % dict(
            member=member.id, accepting_team=accepting_team.id
        )

    store = Store.of(member)
    store.execute(query)


def find_team_participations(people, teams=None):
    """Find the teams the given people participate in.

    :param people: The people for which to query team participation.
    :param teams: Optionally, limit the participation check to these teams.

    This method performs its work with at most a single database query.
    It first does similar checks to those performed by IPerson.in_team() and
    it may turn out that no database query is required at all.
    """

    teams_to_query = []
    people_teams = {}

    def add_team_to_result(person, team):
        teams = people_teams.get(person)
        if teams is None:
            teams = set()
            people_teams[person] = teams
        teams.add(team)

    # Check for the simple cases - self membership etc.
    if teams:
        for team in teams:
            if team is None:
                continue
            for person in people:
                if team.id == person.id:
                    add_team_to_result(person, team)
                    continue
            if not team.is_team:
                continue
            teams_to_query.append(team)

    # Avoid circular imports
    from lp.registry.model.person import Person

    # We are either checking for membership of any team or didn't eliminate
    # all the specific team participation checks above.
    if teams_to_query or not teams:
        Team = ClassAlias(Person, "Team")
        person_ids = [person.id for person in people]
        conditions = [
            TeamParticipation.person_id == Person.id,
            TeamParticipation.team_id == Team.id,
            Person.id.is_in(person_ids),
        ]
        team_ids = [team.id for team in teams_to_query]
        if team_ids:
            conditions.append(Team.id.is_in(team_ids))

        store = IStore(Person)
        rs = store.find((Person, Team), *conditions)

        for person, team in rs:
            add_team_to_result(person, team)
    return people_teams
