# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "HeldMessageDetails",
    "MailingList",
    "MailingListSet",
    "MailingListSubscription",
    "MessageApproval",
    "MessageApprovalSet",
]


import collections
import operator
from datetime import timezone
from socket import getfqdn
from string import Template

from lazr.lifecycle.event import ObjectCreatedEvent
from storm.expr import Func
from storm.info import ClassAlias
from storm.locals import (
    And,
    DateTime,
    Int,
    Join,
    Or,
    Reference,
    Select,
    Unicode,
)
from storm.store import Store
from zope.component import getUtility, queryAdapter
from zope.event import notify
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp import _
from lp.registry.interfaces.mailinglist import (
    PURGE_STATES,
    CannotChangeSubscription,
    CannotSubscribe,
    CannotUnsubscribe,
    IHeldMessageDetails,
    IMailingList,
    IMailingListSet,
    IMailingListSubscription,
    IMessageApproval,
    IMessageApprovalSet,
    MailingListStatus,
    PostedMessageStatus,
    UnsafeToPurge,
)
from lp.registry.interfaces.person import validate_public_person
from lp.registry.model.person import Person
from lp.registry.model.teammembership import TeamParticipation
from lp.services.config import config
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import Concatenate
from lp.services.identity.interfaces.account import AccountStatus
from lp.services.identity.interfaces.emailaddress import (
    EmailAddressStatus,
    IEmailAddressSet,
)
from lp.services.identity.model.account import Account
from lp.services.identity.model.emailaddress import EmailAddress
from lp.services.messages.model.message import Message
from lp.services.privacy.interfaces import IObjectPrivacy
from lp.services.propertycache import cachedproperty
from lp.services.webapp.snapshot import notify_modified

EMAIL_ADDRESS_STATUSES = (
    EmailAddressStatus.VALIDATED,
    EmailAddressStatus.PREFERRED,
)
MESSAGE_APPROVAL_STATUSES = (
    PostedMessageStatus.APPROVED,
    PostedMessageStatus.APPROVAL_PENDING,
)


USABLE_STATUSES = (
    MailingListStatus.ACTIVE,
    MailingListStatus.MODIFIED,
    MailingListStatus.UPDATING,
    MailingListStatus.MOD_FAILED,
)


@implementer(IMessageApproval)
class MessageApproval(StormBase):
    """A held message."""

    __storm_table__ = "MessageApproval"

    id = Int(primary=True)

    _message_id = Int(name="message", allow_none=False)
    message = Reference(_message_id, "Message.id")

    posted_by_id = Int(
        name="posted_by", validator=validate_public_person, allow_none=False
    )
    posted_by = Reference(posted_by_id, "Person.id")

    posted_message_id = Int(name="posted_message", allow_none=False)
    posted_message = Reference(posted_message_id, "LibraryFileAlias.id")

    posted_date = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )

    mailing_list_id = Int(name="mailing_list", allow_none=False)
    mailing_list = Reference(mailing_list_id, "MailingList.id")

    status = DBEnum(
        enum=PostedMessageStatus,
        default=PostedMessageStatus.NEW,
        allow_none=False,
    )

    disposed_by_id = Int(
        name="disposed_by", validator=validate_public_person, default=None
    )
    disposed_by = Reference(disposed_by_id, "Person.id")

    disposal_date = DateTime(tzinfo=timezone.utc, default=None)

    def __init__(
        self, message, posted_by, posted_message, posted_date, mailing_list
    ):
        super().__init__()
        self.message = message
        self.posted_by = posted_by
        self.posted_message = posted_message
        self.posted_date = posted_date
        self.mailing_list = mailing_list

    @property
    def message_id(self):
        """See `IMessageApproval`."""
        return self.message.rfc822msgid

    def approve(self, reviewer):
        """See `IMessageApproval`."""
        self.disposed_by = reviewer
        self.disposal_date = UTC_NOW
        self.status = PostedMessageStatus.APPROVAL_PENDING

    def reject(self, reviewer):
        """See `IMessageApproval`."""
        self.disposed_by = reviewer
        self.disposal_date = UTC_NOW
        self.status = PostedMessageStatus.REJECTION_PENDING

    def discard(self, reviewer):
        """See `IMessageApproval`."""
        self.disposed_by = reviewer
        self.disposal_date = UTC_NOW
        self.status = PostedMessageStatus.DISCARD_PENDING

    def acknowledge(self):
        """See `IMessageApproval`."""
        if self.status == PostedMessageStatus.APPROVAL_PENDING:
            self.status = PostedMessageStatus.APPROVED
        elif self.status == PostedMessageStatus.REJECTION_PENDING:
            self.status = PostedMessageStatus.REJECTED
        elif self.status == PostedMessageStatus.DISCARD_PENDING:
            self.status = PostedMessageStatus.DISCARDED
        else:
            raise AssertionError(
                "Not an acknowledgeable state: %s" % self.status
            )


@implementer(IMailingList)
class MailingList(StormBase):
    """The mailing list for a team.

    Teams may have at most one mailing list, and a mailing list is associated
    with exactly one team.  This table manages the state changes that a team
    mailing list can go through, and it contains information that will be used
    to instruct Mailman how to create, delete, and modify mailing lists (via
    XMLRPC).
    """

    __storm_table__ = "MailingList"

    id = Int(primary=True)

    team_id = Int(name="team", allow_none=False)
    team = Reference(team_id, "Person.id")

    registrant_id = Int(
        name="registrant", validator=validate_public_person, allow_none=False
    )
    registrant = Reference(registrant_id, "Person.id")

    date_registered = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=DEFAULT
    )

    reviewer_id = Int(
        name="reviewer", validator=validate_public_person, default=None
    )
    reviewer = Reference(reviewer_id, "Person.id")

    date_reviewed = DateTime(
        tzinfo=timezone.utc, allow_none=True, default=None
    )

    date_activated = DateTime(
        tzinfo=timezone.utc, allow_none=True, default=None
    )

    status = DBEnum(
        enum=MailingListStatus,
        default=MailingListStatus.APPROVED,
        allow_none=False,
    )

    _welcome_message = Unicode(default=None, name="welcome_message")

    def __init__(self, team, registrant, date_registered=DEFAULT):
        super().__init__()
        self.team = team
        self.registrant = registrant
        self.date_registered = date_registered

    @property
    def address(self):
        """See `IMailingList`."""
        if config.mailman.build_host_name:
            host_name = config.mailman.build_host_name
        else:
            host_name = getfqdn()
        return "%s@%s" % (self.team.name, host_name)

    @property
    def archive_url(self):
        """See `IMailingList`."""
        # These represent states that can occur at or after a mailing list has
        # been activated.  Once it's been activated, a mailing list could have
        # an archive.
        if self.status not in [
            MailingListStatus.ACTIVE,
            MailingListStatus.INACTIVE,
            MailingListStatus.MODIFIED,
            MailingListStatus.UPDATING,
            MailingListStatus.DEACTIVATING,
            MailingListStatus.MOD_FAILED,
        ]:
            return None
        # There could be an archive, return its url.
        template = Template(config.mailman.archive_url_template)
        return template.safe_substitute(team_name=self.team.name)

    def __repr__(self):
        return '<MailingList for team "%s"; status=%s; address=%s at %#x>' % (
            self.team.name,
            self.status.name,
            self.address,
            id(self),
        )

    def startConstructing(self):
        """See `IMailingList`."""
        assert (
            self.status == MailingListStatus.APPROVED
        ), "Only approved mailing lists may be constructed"
        self.status = MailingListStatus.CONSTRUCTING

    def startUpdating(self):
        """See `IMailingList`."""
        assert (
            self.status == MailingListStatus.MODIFIED
        ), "Only modified mailing lists may be updated"
        self.status = MailingListStatus.UPDATING

    def transitionToStatus(self, target_state):
        """See `IMailingList`."""
        # State: From CONSTRUCTING to either ACTIVE or FAILED
        if self.status == MailingListStatus.CONSTRUCTING:
            assert target_state in (
                MailingListStatus.ACTIVE,
                MailingListStatus.FAILED,
            ), "target_state result must be active or failed"
        # State: From UPDATING to either ACTIVE or MOD_FAILED
        elif self.status == MailingListStatus.UPDATING:
            assert target_state in (
                MailingListStatus.ACTIVE,
                MailingListStatus.MOD_FAILED,
            ), "target_state result must be active or mod_failed"
        # State: From DEACTIVATING to INACTIVE or MOD_FAILED
        elif self.status == MailingListStatus.DEACTIVATING:
            assert target_state in (
                MailingListStatus.INACTIVE,
                MailingListStatus.MOD_FAILED,
            ), "target_state result must be inactive or mod_failed"
        else:
            raise AssertionError(
                "Not a valid state transition: %s -> %s"
                % (self.status, target_state)
            )
        self.status = target_state
        if target_state == MailingListStatus.ACTIVE:
            self._setAndNotifyDateActivated()
            email_set = getUtility(IEmailAddressSet)
            email = email_set.getByEmail(self.address)
            if email is None:
                email = email_set.new(self.address, self.team)
            if email.status in [
                EmailAddressStatus.NEW,
                EmailAddressStatus.OLD,
            ]:
                # Without this conditional, if the mailing list is the
                # contact method
                # (email.status==EmailAddressStatus.PREFERRED), and a
                # user changes the mailing list configuration, then
                # when the list status goes back to ACTIVE the email
                # will go from PREFERRED to VALIDATED and the list
                # will stop being the contact method.
                # We also need to remove the email's security proxy because
                # this method will be called via the internal XMLRPC rather
                # than as a response to a user action.
                removeSecurityProxy(
                    email
                ).status = EmailAddressStatus.VALIDATED
            assert (
                email.personID == self.team_id
            ), "Email already associated with another team."

    def _setAndNotifyDateActivated(self):
        """Set the date_activated field and fire a
        SQLObjectModified event.

        The date_activated field is only set once - repeated calls
        will not change the field's value.

        Similarly, the modification event only fires the first time
        that the field is set.
        """
        if self.date_activated is not None:
            return

        with notify_modified(self, ["date_activated"]):
            self.date_activated = UTC_NOW

    def deactivate(self):
        """See `IMailingList`."""
        assert (
            self.status == MailingListStatus.ACTIVE
        ), "Only active mailing lists may be deactivated"
        self.status = MailingListStatus.DEACTIVATING
        email = getUtility(IEmailAddressSet).getByEmail(self.address)
        if email is not None and self.team.preferredemail is not None:
            if email.id == self.team.preferredemail.id:
                self.team.setContactAddress(None)
        assert email.personID == self.team_id, "Incorrectly linked email."
        # Anyone with permission to deactivate a list can also set the
        # email address status to NEW.
        removeSecurityProxy(email).status = EmailAddressStatus.NEW

    def reactivate(self):
        """See `IMailingList`."""
        assert (
            self.status == MailingListStatus.INACTIVE
        ), "Only inactive mailing lists may be reactivated"
        self.status = MailingListStatus.APPROVED

    @property
    def is_public(self):
        """See `IMailingList`."""
        return not queryAdapter(self.team, IObjectPrivacy).is_private

    @property
    def is_usable(self):
        """See `IMailingList`."""
        return self.status in USABLE_STATUSES

    @property
    def welcome_message(self):
        return self._welcome_message

    @welcome_message.setter
    def welcome_message(self, text):
        if self.status == MailingListStatus.REGISTERED:
            # Do nothing because the status does not change.  When setting the
            # welcome_message on a newly registered mailing list the XMLRPC
            # layer will essentially tell Mailman to initialize this attribute
            # at list construction time.  It is enough to just set the
            # database attribute to properly notify Mailman what to do.
            pass
        elif self.is_usable:
            # Transition the status to MODIFIED so that the XMLRPC layer knows
            # that it has to inform Mailman that a mailing list attribute has
            # been changed on an active list.
            self.status = MailingListStatus.MODIFIED
        else:
            raise AssertionError("Only usable mailing lists may be modified")
        self._welcome_message = text

    def getSubscription(self, person):
        """See `IMailingList`."""
        return (
            Store.of(self)
            .find(MailingListSubscription, person=person, mailing_list=self)
            .one()
        )

    def getSubscribers(self):
        """See `IMailingList`."""
        store = Store.of(self)
        results = store.find(
            Person,
            TeamParticipation.person == Person.id,
            TeamParticipation.team == self.team,
            MailingListSubscription.person == Person.id,
            MailingListSubscription.mailing_list == self,
        )
        return results.order_by(Person.display_name, Person.name)

    def subscribe(self, person, address=None):
        """See `IMailingList`."""
        if not self.is_usable:
            raise CannotSubscribe(
                "Mailing list is not usable: %s" % self.team.displayname
            )
        if person.is_team:
            raise CannotSubscribe(
                "Teams cannot be mailing list members: %s" % person.displayname
            )
        if address is not None and address.personID != person.id:
            raise CannotSubscribe(
                "%s does not own the email address: %s"
                % (person.displayname, address.email)
            )
        subscription = self.getSubscription(person)
        if subscription is not None:
            raise CannotSubscribe(
                "%s is already subscribed to list %s"
                % (person.displayname, self.team.displayname)
            )
        # Add the subscription for this person to this mailing list.
        MailingListSubscription(
            person=person, mailing_list=self, email_address=address
        )

    def unsubscribe(self, person):
        """See `IMailingList`."""
        subscription = self.getSubscription(person)
        if subscription is None:
            raise CannotUnsubscribe(
                "%s is not a member of the mailing list: %s"
                % (person.displayname, self.team.displayname)
            )
        Store.of(subscription).remove(subscription)

    def changeAddress(self, person, address):
        """See `IMailingList`."""
        subscription = self.getSubscription(person)
        if subscription is None:
            raise CannotChangeSubscription(
                "%s is not a member of the mailing list: %s"
                % (person.displayname, self.team.displayname)
            )
        if address is not None and address.personID != person.id:
            raise CannotChangeSubscription(
                "%s does not own the email address: %s"
                % (person.displayname, address.email)
            )
        subscription.email_address = address

    def holdMessage(self, message):
        """See `IMailingList`."""
        held_message = MessageApproval(
            message=message,
            posted_by=message.owner,
            posted_message=message.raw,
            posted_date=message.datecreated,
            mailing_list=self,
        )
        notify(ObjectCreatedEvent(held_message))
        return held_message

    def getReviewableMessages(self, message_id_filter=None):
        """See `IMailingList`."""
        store = Store.of(self)
        clauses = [
            MessageApproval.mailing_list == self,
            MessageApproval.status == PostedMessageStatus.NEW,
            MessageApproval.message == Message.id,
            MessageApproval.posted_by == Person.id,
        ]
        if message_id_filter is not None:
            clauses.append(Message.rfc822msgid.is_in(message_id_filter))
        results = store.find((MessageApproval, Message, Person), *clauses)
        results.order_by(MessageApproval.posted_date, Message.rfc822msgid)
        return DecoratedResultSet(results, operator.itemgetter(0))

    def purge(self):
        """See `IMailingList`."""
        # At first glance, it would seem that we could use
        # transitionToStatus(), but it actually doesn't quite match the
        # semantics we want.  For example, if we try to purge an active
        # mailing list we really want an UnsafeToPurge exception instead of an
        # AssertionError.  Fitting that in to transitionToStatus()'s logic is
        # a bit tortured, so just do it here.
        if self.status in PURGE_STATES:
            self.status = MailingListStatus.PURGED
            email = getUtility(IEmailAddressSet).getByEmail(self.address)
            if email is not None:
                removeSecurityProxy(email).destroySelf()
        else:
            assert self.status != MailingListStatus.PURGED, "Already purged"
            raise UnsafeToPurge(self)


@implementer(IMailingListSet)
class MailingListSet:
    title = _("Team mailing lists")

    def new(self, team, registrant=None):
        """See `IMailingListSet`."""
        if not team.is_team:
            raise ValueError("Cannot register a list for a user.")
        if registrant is None:
            registrant = team.teamowner
        else:
            # Check to make sure that registrant is a team owner or admin.
            # This gets tricky because an admin can be a team, and if the
            # registrant is a member of that team, they are by definition an
            # administrator of the team we're creating the mailing list for.
            # So you can't just do "registrant in
            # team.getDirectAdministrators()".  It's okay to use .inTeam() for
            # all cases because a person is always a member of themselves.
            for admin in team.getDirectAdministrators():
                if registrant.inTeam(admin):
                    break
            else:
                raise ValueError(
                    "registrant is not a team owner or administrator"
                )
        # See if the mailing list already exists.  If so, it must be in the
        # purged state for us to be able to recreate it.
        existing_list = self.get(team.name)
        if existing_list is None:
            # We have no record for the mailing list, so just create it.
            return MailingList(
                team=team, registrant=registrant, date_registered=UTC_NOW
            )
        else:
            if existing_list.status != MailingListStatus.PURGED:
                raise ValueError(
                    'Mailing list for team "%s" already exists' % team.name
                )
            if existing_list.team != team:
                raise ValueError("Team mismatch.")
            # It's in the PURGED state, so just tweak the existing record.
            existing_list.registrant = registrant
            existing_list.date_registered = UTC_NOW
            existing_list.reviewer = None
            existing_list.date_reviewed = None
            existing_list.date_activated = None
            # This is a little wacky, but it's this way for historical
            # purposes.  When mailing lists required approval before being
            # created, it was okay to change the welcome message while in the
            # REGISTERED state.  Now that we don't use REGISTERED any more,
            # resurrecting a purged mailing list means setting it directly to
            # the APPROVED state, but we're not allowed to change the welcome
            # message in that state because it will get us out of sync with
            # Mailman.  We really don't want to change _set_welcome_message()
            # because that will have other consequences, so set to REGISTERED
            # just long enough to set the welcome message, then set to
            # APPROVED.  Mailman will catch up correctly.
            existing_list.status = MailingListStatus.REGISTERED
            existing_list.welcome_message = None
            existing_list.status = MailingListStatus.APPROVED
            return existing_list

    def get(self, team_name):
        """See `IMailingListSet`."""
        assert isinstance(
            team_name, str
        ), "team_name must be a text string, not %s" % type(team_name)
        return (
            IStore(MailingList)
            .find(
                MailingList,
                MailingList.team == Person.id,
                Person.name == team_name,
                Person.teamowner != None,
            )
            .one()
        )

    def getSubscriptionsForTeams(self, person, teams):
        """See `IMailingListSet`."""
        store = IStore(MailingList)
        team_ids = set(map(operator.attrgetter("id"), teams))
        lists = dict(
            store.find(
                (MailingList.team_id, MailingList.id),
                MailingList.team_id.is_in(team_ids),
                MailingList.status.is_in(USABLE_STATUSES),
            )
        )
        subscriptions = dict(
            store.find(
                (
                    MailingListSubscription.mailing_list_id,
                    MailingListSubscription.id,
                ),
                MailingListSubscription.person == person,
                MailingListSubscription.mailing_list_id.is_in(lists.values()),
            )
        )
        by_team = {}
        for team, mailing_list in lists.items():
            by_team[team] = (mailing_list, subscriptions.get(mailing_list))
        return by_team

    def _getTeamIdsAndMailingListIds(self, team_names):
        """Return a tuple of team and mailing list Ids for the team names."""
        store = IStore(MailingList)
        tables = (Person, Join(MailingList, MailingList.team == Person.id))
        results = set(
            store.using(*tables).find(
                (Person.id, MailingList.id),
                And(Person.name.is_in(team_names), Person.teamowner != None),
            )
        )
        team_ids = [result[0] for result in results]
        list_ids = [result[1] for result in results]
        return team_ids, list_ids

    def getSubscribedAddresses(self, team_names):
        """See `IMailingListSet`."""
        store = IStore(MailingList)
        Team = ClassAlias(Person)
        tables = (
            EmailAddress,
            Join(Person, Person.id == EmailAddress.personID),
            Join(Account, Account.id == Person.account_id),
            Join(TeamParticipation, TeamParticipation.personID == Person.id),
            Join(
                MailingListSubscription,
                MailingListSubscription.person_id == Person.id,
            ),
            Join(
                MailingList,
                MailingList.id == MailingListSubscription.mailing_list_id,
            ),
            Join(Team, Team.id == MailingList.team_id),
        )
        team_ids, list_ids = self._getTeamIdsAndMailingListIds(team_names)
        preferred = store.using(*tables).find(
            (EmailAddress.email, Person.display_name, Team.name),
            And(
                MailingListSubscription.mailing_list_id.is_in(list_ids),
                TeamParticipation.teamID.is_in(team_ids),
                MailingList.team_id == TeamParticipation.teamID,
                MailingList.status != MailingListStatus.INACTIVE,
                Account.status == AccountStatus.ACTIVE,
                Or(
                    And(
                        MailingListSubscription.email_address_id == None,
                        EmailAddress.status == EmailAddressStatus.PREFERRED,
                    ),
                    EmailAddress.id
                    == MailingListSubscription.email_address_id,
                ),
            ),
        )
        # Sort by team name.
        by_team = collections.defaultdict(set)
        for email, display_name, team_name in preferred:
            assert team_name in team_names, (
                "Unexpected team name in results: %s" % team_name
            )
            value = (display_name, email.lower())
            by_team[team_name].add(value)
        # Turn the results into a mapping of lists.
        results = {}
        for team_name, address_set in by_team.items():
            results[team_name] = list(address_set)
        return results

    def getSenderAddresses(self, team_names):
        """See `IMailingListSet`."""
        store = IStore(MailingList)
        # First, we need to find all the members of all the mailing lists for
        # the given teams.  Find all of their validated and preferred email
        # addresses of those team members.  Every one of those email addresses
        # are allowed to post to the mailing list.
        Team = ClassAlias(Person)
        tables = (
            Person,
            Join(Account, Account.id == Person.account_id),
            Join(EmailAddress, EmailAddress.personID == Person.id),
            Join(TeamParticipation, TeamParticipation.personID == Person.id),
            Join(MailingList, MailingList.team_id == TeamParticipation.teamID),
            Join(Team, Team.id == MailingList.team_id),
        )
        team_ids, list_ids = self._getTeamIdsAndMailingListIds(team_names)
        team_members = store.using(*tables).find(
            (Team.name, Person.display_name, EmailAddress.email),
            And(
                TeamParticipation.teamID.is_in(team_ids),
                MailingList.status != MailingListStatus.INACTIVE,
                Person.teamowner == None,
                EmailAddress.status.is_in(EMAIL_ADDRESS_STATUSES),
                Account.status == AccountStatus.ACTIVE,
            ),
        )
        # Second, find all of the email addresses for all of the people who
        # have been explicitly approved for posting to the team mailing lists.
        # This occurs as part of first post moderation, but since they've
        # already been approved for the specific list, we don't need to wait
        # for three global approvals.
        tables = (
            Person,
            Join(Account, Account.id == Person.account_id),
            Join(EmailAddress, EmailAddress.personID == Person.id),
            Join(MessageApproval, MessageApproval.posted_by_id == Person.id),
            Join(
                MailingList, MailingList.id == MessageApproval.mailing_list_id
            ),
            Join(Team, Team.id == MailingList.team_id),
        )
        approved_posters = store.using(*tables).find(
            (Team.name, Person.display_name, EmailAddress.email),
            And(
                MessageApproval.mailing_list_id.is_in(list_ids),
                MessageApproval.status.is_in(MESSAGE_APPROVAL_STATUSES),
                EmailAddress.status.is_in(EMAIL_ADDRESS_STATUSES),
                Account.status == AccountStatus.ACTIVE,
            ),
        )
        # Sort allowed posters by team/mailing list.
        by_team = collections.defaultdict(set)
        all_posters = team_members.union(approved_posters)
        for team_name, person_displayname, email in all_posters:
            assert team_name in team_names, (
                "Unexpected team name in results: %s" % team_name
            )
            value = (person_displayname, email.lower())
            by_team[team_name].add(value)
        # Turn the results into a mapping of lists.
        results = {}
        for team_name, address_set in by_team.items():
            results[team_name] = list(address_set)
        return results

    @property
    def approved_lists(self):
        """See `IMailingListSet`."""
        return IStore(MailingList).find(
            MailingList, status=MailingListStatus.APPROVED
        )

    @property
    def active_lists(self):
        """See `IMailingListSet`."""
        return IStore(MailingList).find(
            MailingList, status=MailingListStatus.ACTIVE
        )

    @property
    def modified_lists(self):
        """See `IMailingListSet`."""
        return IStore(MailingList).find(
            MailingList, status=MailingListStatus.MODIFIED
        )

    @property
    def deactivated_lists(self):
        """See `IMailingListSet`."""
        return IStore(MailingList).find(
            MailingList, status=MailingListStatus.DEACTIVATING
        )

    @property
    def unsynchronized_lists(self):
        """See `IMailingListSet`."""
        return IStore(MailingList).find(
            MailingList,
            MailingList.status.is_in(
                (MailingListStatus.CONSTRUCTING, MailingListStatus.UPDATING)
            ),
        )

    def updateTeamAddresses(self, old_hostname):
        """See `IMailingListSet`."""
        # Circular import.
        from lp.registry.model.person import Person

        # This is really an operation on EmailAddress rows, but it's so
        # specific to mailing lists that it seems better to keep it here.
        old_suffix = "@" + old_hostname
        if config.mailman.build_host_name:
            new_suffix = "@" + config.mailman.build_host_name
        else:
            new_suffix = "@" + getfqdn()
        clauses = [
            EmailAddress.person == Person.id,
            Person.teamowner != None,
            Person.id == MailingList.team_id,
            EmailAddress.email.endswith(old_suffix),
        ]
        addresses = IPrimaryStore(EmailAddress).find(
            EmailAddress,
            EmailAddress.id.is_in(Select(EmailAddress.id, And(*clauses))),
        )
        addresses.set(
            email=Concatenate(
                Func("left", EmailAddress.email, -len(old_suffix)), new_suffix
            )
        )


@implementer(IMailingListSubscription)
class MailingListSubscription(StormBase):
    """A mailing list subscription."""

    __storm_table__ = "MailingListSubscription"

    id = Int(primary=True)

    person_id = Int(
        name="person", validator=validate_public_person, allow_none=False
    )
    person = Reference(person_id, "Person.id")

    mailing_list_id = Int(name="mailing_list", allow_none=False)
    mailing_list = Reference(mailing_list_id, "MailingList.id")

    date_joined = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )

    email_address_id = Int(name="email_address")
    email_address = Reference(email_address_id, "EmailAddress.id")

    def __init__(self, person, mailing_list, email_address):
        super().__init__()
        self.person = person
        self.mailing_list = mailing_list
        self.email_address = email_address

    @property
    def subscribed_address(self):
        """See `IMailingListSubscription`."""
        if self.email_address is None:
            # Use the person's preferred email address.
            return self.person.preferredemail
        else:
            # Use the subscribed email address.
            return self.email_address


@implementer(IMessageApprovalSet)
class MessageApprovalSet:
    """Sets of held messages."""

    def getMessageByMessageID(self, message_id):
        """See `IMessageApprovalSet`."""
        return (
            IStore(MessageApproval)
            .find(
                MessageApproval,
                MessageApproval.message == Message.id,
                Message.rfc822msgid == message_id,
            )
            .config(distinct=True)
            .one()
        )

    def getHeldMessagesWithStatus(self, status):
        """See `IMessageApprovalSet`."""
        # Use the primary store as the messages will also be acknowledged and
        # we want to make sure we are acknowledging the same messages that we
        # iterate over.
        return IPrimaryStore(MessageApproval).find(
            (Message.rfc822msgid, Person.name),
            MessageApproval.status == status,
            MessageApproval.message == Message.id,
            MessageApproval.mailing_list == MailingList.id,
            MailingList.team == Person.id,
        )

    def acknowledgeMessagesWithStatus(self, status):
        """See `IMessageApprovalSet`."""
        transitions = {
            PostedMessageStatus.APPROVAL_PENDING: PostedMessageStatus.APPROVED,
            PostedMessageStatus.REJECTION_PENDING: (
                PostedMessageStatus.REJECTED
            ),
            PostedMessageStatus.DISCARD_PENDING: PostedMessageStatus.DISCARDED,
        }
        try:
            next_state = transitions[status]
        except KeyError:
            raise AssertionError("Not an acknowledgeable state: %s" % status)
        approvals = IPrimaryStore(MessageApproval).find(
            MessageApproval, MessageApproval.status == status
        )
        approvals.set(status=next_state)


@implementer(IHeldMessageDetails)
class HeldMessageDetails:
    """Details about a held message."""

    def __init__(self, message_approval):
        self.message_approval = message_approval
        self.message = message_approval.message
        self.message_id = message_approval.message_id
        self.subject = self.message.subject
        self.date = self.message.datecreated
        self.author = self.message_approval.posted_by

    @cachedproperty
    def body(self):
        """See `IHeldMessageDetails`."""
        return self.message.text_contents
