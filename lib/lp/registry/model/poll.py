# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "Poll",
    "PollOption",
    "PollOptionSet",
    "PollSet",
    "VoteCast",
    "Vote",
    "VoteSet",
    "VoteCastSet",
]

from datetime import datetime, timezone

from storm.locals import (
    And,
    Bool,
    DateTime,
    Desc,
    Int,
    Or,
    Reference,
    Store,
    Unicode,
)
from zope.component import getUtility
from zope.interface import implementer

from lp.registry.enums import PollSort
from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.poll import (
    CannotCreatePoll,
    IPoll,
    IPollOption,
    IPollOptionSet,
    IPollSet,
    IVote,
    IVoteCast,
    IVoteCastSet,
    IVoteSet,
    OptionIsNotFromSimplePoll,
    PollAlgorithm,
    PollSecrecy,
    PollStatus,
)
from lp.registry.model.person import Person
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import sqlvalues
from lp.services.database.stormbase import StormBase
from lp.services.tokens import create_token
from lp.services.webapp.authorization import check_permission


@implementer(IPoll)
class Poll(StormBase):
    """See IPoll."""

    __storm_table__ = "Poll"
    sortingColumns = ["title", "id"]
    __storm_order__ = sortingColumns

    id = Int(primary=True)

    team_id = Int(
        name="team", validator=validate_public_person, allow_none=False
    )
    team = Reference(team_id, "Person.id")

    name = Unicode(name="name", allow_none=False)

    title = Unicode(name="title", allow_none=False)

    dateopens = DateTime(
        tzinfo=timezone.utc, name="dateopens", allow_none=False
    )

    datecloses = DateTime(
        tzinfo=timezone.utc, name="datecloses", allow_none=False
    )

    proposition = Unicode(name="proposition", allow_none=False)

    type = DBEnum(
        name="type", enum=PollAlgorithm, default=PollAlgorithm.SIMPLE
    )

    allowspoilt = Bool(name="allowspoilt", default=True, allow_none=False)

    secrecy = DBEnum(
        name="secrecy", enum=PollSecrecy, default=PollSecrecy.SECRET
    )

    def __init__(
        self,
        team,
        name,
        title,
        proposition,
        dateopens,
        datecloses,
        secrecy=PollSecrecy.SECRET,
        allowspoilt=True,
        type=PollAlgorithm.SIMPLE,
    ):
        super().__init__()
        self.team = team
        self.name = name
        self.title = title
        self.proposition = proposition
        self.dateopens = dateopens
        self.datecloses = datecloses
        self.secrecy = secrecy
        self.allowspoilt = allowspoilt
        self.type = type

    def newOption(self, name, title, active=True):
        """See IPoll."""
        return getUtility(IPollOptionSet).new(self, name, title, active)

    def isOpen(self, when=None):
        """See IPoll."""
        if when is None:
            when = datetime.now(timezone.utc)
        return self.datecloses >= when and self.dateopens <= when

    @property
    def closesIn(self):
        """See IPoll."""
        return self.datecloses - datetime.now(timezone.utc)

    @property
    def opensIn(self):
        """See IPoll."""
        return self.dateopens - datetime.now(timezone.utc)

    def isClosed(self, when=None):
        """See IPoll."""
        if when is None:
            when = datetime.now(timezone.utc)
        return self.datecloses <= when

    def isNotYetOpened(self, when=None):
        """See IPoll."""
        if when is None:
            when = datetime.now(timezone.utc)
        return self.dateopens > when

    def getAllOptions(self):
        """See IPoll."""
        return getUtility(IPollOptionSet).findByPoll(self)

    def getActiveOptions(self):
        """See IPoll."""
        return getUtility(IPollOptionSet).findByPoll(self, only_active=True)

    def getVotesByPerson(self, person):
        """See IPoll."""
        return IStore(Vote).find(Vote, person=person, poll=self)

    def personVoted(self, person):
        """See IPoll."""
        results = IStore(VoteCast).find(VoteCast, person=person, poll=self)
        return not results.is_empty()

    def removeOption(self, option, when=None):
        """See IPoll."""
        assert self.isNotYetOpened(when=when)
        if option.poll != self:
            raise ValueError(
                "Can't remove an option that doesn't belong to this poll"
            )
        option.destroySelf()

    def getOptionByName(self, name):
        """See IPoll."""
        return IStore(PollOption).find(PollOption, poll=self, name=name).one()

    def _assertEverythingOkAndGetVoter(self, person, when=None):
        """Use assertions to Make sure all pre-conditions for a person to vote
        are met.

        Return the person if this is not a secret poll or None if it's a
        secret one.
        """
        assert self.isOpen(when=when), "This poll is not open"
        assert not self.personVoted(person), "Can't vote twice in one poll"
        assert person.inTeam(self.team), (
            "Person %r is not a member of this poll's team." % person
        )

        # We only associate the option with the person if the poll is not a
        # SECRET one.
        if self.secrecy == PollSecrecy.SECRET:
            voter = None
        else:
            voter = person
        return voter

    def storeCondorcetVote(self, person, options, when=None):
        """See IPoll."""
        voter = self._assertEverythingOkAndGetVoter(person, when=when)
        assert self.type == PollAlgorithm.CONDORCET
        voteset = getUtility(IVoteSet)

        token = create_token(20)
        votes = []
        activeoptions = self.getActiveOptions()
        for option, preference in options.items():
            assert option.poll == self, (
                "The option %r doesn't belong to this poll" % option
            )
            assert option.active, "Option %r is not active" % option
            votes.append(voteset.new(self, option, preference, token, voter))

        # Store a vote with preference = None for each active option of this
        # poll that wasn't in the options argument.
        for option in activeoptions:
            if option not in options:
                votes.append(voteset.new(self, option, None, token, voter))

        getUtility(IVoteCastSet).new(self, person)
        return votes

    def storeSimpleVote(self, person, option, when=None):
        """See IPoll."""
        voter = self._assertEverythingOkAndGetVoter(person, when=when)
        assert self.type == PollAlgorithm.SIMPLE
        voteset = getUtility(IVoteSet)

        if option is None and not self.allowspoilt:
            raise ValueError("This poll doesn't allow spoilt votes.")
        elif option is not None:
            assert option.poll == self, (
                "The option %r doesn't belong to this poll" % option
            )
            assert option.active, "Option %r is not active" % option
        token = create_token(20)
        # This is a simple-style poll, so you can vote only on a single option
        # and this option's preference must be 1
        preference = 1
        vote = voteset.new(self, option, preference, token, voter)
        getUtility(IVoteCastSet).new(self, person)
        return vote

    def getTotalVotes(self):
        """See IPoll."""
        assert self.isClosed()
        return IStore(Vote).find(Vote, poll=self).count()

    def getWinners(self):
        """See IPoll."""
        assert self.isClosed()
        # XXX: GuilhermeSalgado 2005-08-24:
        # For now, this method works only for SIMPLE-style polls. This is
        # not a problem as CONDORCET-style polls are disabled.
        assert self.type == PollAlgorithm.SIMPLE
        query = """
            SELECT option
            FROM Vote
            WHERE poll = %d AND option IS NOT NULL
            GROUP BY option
            HAVING COUNT(*) = (
                SELECT COUNT(*)
                FROM Vote
                WHERE poll = %d
                GROUP BY option
                ORDER BY COUNT(*) DESC LIMIT 1
                )
            """ % (
            self.id,
            self.id,
        )
        results = Store.of(self).execute(query).get_all()
        if not results:
            return None
        return [IStore(PollOption).get(PollOption, id) for (id,) in results]

    def getPairwiseMatrix(self):
        """See IPoll."""
        assert self.type == PollAlgorithm.CONDORCET
        options = list(self.getAllOptions())
        pairwise_matrix = []
        for option1 in options:
            pairwise_row = []
            for option2 in options:
                points_query = """
                    SELECT COUNT(*) FROM Vote as v1, Vote as v2 WHERE
                        v1.token = v2.token AND
                        v1.option = %s AND v2.option = %s AND
                        (
                         (
                          v1.preference IS NOT NULL AND
                          v2.preference IS NOT NULL AND
                          v1.preference < v2.preference
                         )
                          OR
                         (
                          v1.preference IS NOT NULL AND
                          v2.preference IS NULL
                         )
                        )
                    """ % sqlvalues(
                    option1.id, option2.id
                )
                if option1 == option2:
                    pairwise_row.append(None)
                else:
                    points = Store.of(self).execute(points_query).get_one()[0]
                    pairwise_row.append(points)
            pairwise_matrix.append(pairwise_row)
        return pairwise_matrix


@implementer(IPollSet)
class PollSet:
    """See IPollSet."""

    def new(
        self,
        team,
        name,
        title,
        proposition,
        dateopens,
        datecloses,
        secrecy,
        allowspoilt,
        poll_type=PollAlgorithm.SIMPLE,
        check_permissions=True,
    ):
        """See IPollSet."""
        if check_permissions and not check_permission(
            "launchpad.AnyLegitimatePerson", team
        ):
            raise CannotCreatePoll(
                "You do not have permission to create polls."
            )
        poll = Poll(
            team=team,
            name=name,
            title=title,
            proposition=proposition,
            dateopens=dateopens,
            datecloses=datecloses,
            secrecy=secrecy,
            allowspoilt=allowspoilt,
            type=poll_type,
        )
        IStore(Poll).add(poll)
        return poll

    @staticmethod
    def _convertPollSortToOrderBy(sort_by):
        """Compute a value to pass to `order_by` on a poll collection.

        :param sort_by: An item from the `PollSort` enumeration.
        """
        return {
            PollSort.OLDEST_FIRST: [Poll.id],
            PollSort.NEWEST_FIRST: [Desc(Poll.id)],
            PollSort.OPENING: [Poll.dateopens, Poll.id],
            PollSort.CLOSING: [Poll.datecloses, Poll.id],
        }[sort_by]

    def find(
        self, team=None, status=None, order_by=PollSort.NEWEST_FIRST, when=None
    ):
        """See IPollSet."""
        if status is None:
            status = PollStatus.ALL
        if when is None:
            when = datetime.now(timezone.utc)

        status = set(status)
        status_clauses = []
        if PollStatus.OPEN in status:
            status_clauses.append(
                And(Poll.dateopens <= when, Poll.datecloses > when)
            )
        if PollStatus.CLOSED in status:
            status_clauses.append(Poll.datecloses <= when)
        if PollStatus.NOT_YET_OPENED in status:
            status_clauses.append(Poll.dateopens > when)

        assert len(status_clauses) > 0, "No poll statuses were selected"

        clauses = []
        if team is not None:
            clauses.append(Poll.team == team)
        else:
            clauses.extend([Poll.team == Person.id, Person.merged == None])
        clauses.append(Or(*status_clauses))

        results = IStore(Poll).find(Poll, *clauses)

        return results.order_by(self._convertPollSortToOrderBy(order_by))

    def findByTeam(
        self, team, status=None, order_by=PollSort.NEWEST_FIRST, when=None
    ):
        """See IPollSet."""
        return self.find(
            team=team, status=status, order_by=order_by, when=when
        )

    def getByTeamAndName(self, team, name, default=None):
        """See IPollSet."""
        poll = IStore(Poll).find(Poll, team=team, name=name).one()
        return poll if poll is not None else default

    def emptyList(self):
        """See IPollSet."""
        return []


@implementer(IPollOption)
class PollOption(StormBase):
    """See IPollOption."""

    __storm_table__ = "PollOption"
    __storm_order__ = ["title", "id"]

    id = Int(primary=True)

    poll_id = Int(name="poll", allow_none=False)
    poll = Reference(poll_id, "Poll.id")

    name = Unicode(allow_none=False)

    title = Unicode(allow_none=False)

    active = Bool(allow_none=False, default=False)

    def __init__(self, poll, name, title, active=False):
        super().__init__()
        self.poll = poll
        self.name = name
        self.title = title
        self.active = active

    def destroySelf(self):
        IStore(PollOption).remove(self)


@implementer(IPollOptionSet)
class PollOptionSet:
    """See IPollOptionSet."""

    def new(self, poll, name, title, active=True):
        """See IPollOptionSet."""
        option = PollOption(poll=poll, name=name, title=title, active=active)
        IStore(PollOption).add(option)
        return option

    def findByPoll(self, poll, only_active=False):
        """See IPollOptionSet."""
        clauses = [PollOption.poll == poll]
        if only_active:
            clauses.append(PollOption.active)
        return IStore(PollOption).find(PollOption, *clauses)

    def getByPollAndId(self, poll, option_id, default=None):
        """See IPollOptionSet."""
        option = (
            IStore(PollOption).find(PollOption, poll=poll, id=option_id).one()
        )
        return option if option is not None else default


@implementer(IVoteCast)
class VoteCast(StormBase):
    """See IVoteCast."""

    __storm_table__ = "VoteCast"
    __storm_order__ = "id"

    id = Int(primary=True)

    person_id = Int(
        name="person", validator=validate_public_person, allow_none=False
    )
    person = Reference(person_id, "Person.id")

    poll_id = Int(name="poll", allow_none=False)
    poll = Reference(poll_id, "Poll.id")

    def __init__(self, person, poll):
        super().__init__()
        self.person = person
        self.poll = poll


@implementer(IVoteCastSet)
class VoteCastSet:
    """See IVoteCastSet."""

    def new(self, poll, person):
        """See IVoteCastSet."""
        vote_cast = VoteCast(poll=poll, person=person)
        IStore(VoteCast).add(vote_cast)
        return vote_cast


@implementer(IVote)
class Vote(StormBase):
    """See IVote."""

    __storm_table__ = "Vote"
    __storm_order__ = ["preference", "id"]

    id = Int(primary=True)

    person_id = Int(name="person", validator=validate_public_person)
    person = Reference(person_id, "Person.id")

    poll_id = Int(name="poll", allow_none=False)
    poll = Reference(poll_id, "Poll.id")

    option_id = Int(name="option")
    option = Reference(option_id, "PollOption.id")

    preference = Int(name="preference")

    token = Unicode(name="token", allow_none=False)

    def __init__(self, poll, token, person=None, option=None, preference=None):
        super().__init__()
        self.poll = poll
        self.token = token
        self.person = person
        self.option = option
        self.preference = preference


@implementer(IVoteSet)
class VoteSet:
    """See IVoteSet."""

    def new(self, poll, option, preference, token, person):
        """See IVoteSet."""
        vote = Vote(
            poll=poll,
            option=option,
            preference=preference,
            token=token,
            person=person,
        )
        IStore(Vote).add(vote)
        return vote

    def getByToken(self, token):
        """See IVoteSet."""
        return IStore(Vote).find(Vote, token=token)

    def getVotesByOption(self, option):
        """See IVoteSet."""
        if option.poll.type != PollAlgorithm.SIMPLE:
            raise OptionIsNotFromSimplePoll(
                "%r is not an option of a simple-style poll." % option
            )
        return IStore(Vote).find(Vote, option=option).count()
