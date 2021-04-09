# Copyright 2010-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Job classes related to PersonTransferJob."""

__metaclass__ = type
__all__ = [
    'MembershipNotificationJob',
    'PersonCloseAccountJob',
    'PersonTransferJob',
    ]

from datetime import datetime

from lazr.delegates import delegate_to
import pytz
import simplejson
import six
from storm.exceptions import IntegrityError
from storm.expr import (
    And,
    LeftJoin,
    Lower,
    Or,
    )
from storm.locals import (
    Int,
    Reference,
    Unicode,
    )
import transaction
from zope.component import getUtility
from zope.interface import (
    implementer,
    provider,
    )
from zope.security.proxy import removeSecurityProxy

from lp.answers.enums import QuestionStatus
from lp.answers.model.question import Question
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.bugs.model.bugtask import BugTask
from lp.registry.enums import PersonTransferJobType
from lp.registry.interfaces.person import (
    IPerson,
    IPersonSet,
    ITeam,
    PersonCreationRationale,
    )
from lp.registry.interfaces.persontransferjob import (
    IExpiringMembershipNotificationJob,
    IExpiringMembershipNotificationJobSource,
    IMembershipNotificationJob,
    IMembershipNotificationJobSource,
    IPersonCloseAccountJob,
    IPersonCloseAccountJobSource,
    IPersonDeactivateJob,
    IPersonDeactivateJobSource,
    IPersonMergeJob,
    IPersonMergeJobSource,
    IPersonTransferJob,
    IPersonTransferJobSource,
    ISelfRenewalNotificationJob,
    ISelfRenewalNotificationJobSource,
    ITeamInvitationNotificationJob,
    ITeamInvitationNotificationJobSource,
    ITeamJoinNotificationJob,
    ITeamJoinNotificationJobSource,
    )
from lp.registry.interfaces.teammembership import TeamMembershipStatus
from lp.registry.mail.teammembership import TeamMembershipMailer
from lp.registry.model.person import (
    Person,
    PersonSettings,
    )
from lp.registry.model.product import Product
from lp.registry.model.productseries import ProductSeries
from lp.registry.personmerge import merge_people
from lp.services.config import config
from lp.services.database import postgresql
from lp.services.database.constants import DEFAULT
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import EnumCol
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.sqlbase import cursor
from lp.services.database.stormbase import StormBase
from lp.services.identity.interfaces.account import (
    AccountCreationRationale,
    AccountStatus,
    )
from lp.services.identity.model.emailaddress import EmailAddress
from lp.services.job.model.job import (
    EnumeratedSubclass,
    Job,
    )
from lp.services.job.runner import BaseRunnableJob
from lp.services.mail.sendmail import format_address_for_person
from lp.services.openid.model.openididentifier import OpenIdIdentifier
from lp.services.scripts import log
from lp.services.scripts.base import LaunchpadScriptFailure
from lp.soyuz.enums import (
    ArchiveStatus,
    ArchiveSubscriberStatus,
    )
from lp.soyuz.interfaces.archivesubscriber import IArchiveSubscriberSet
from lp.soyuz.model.archive import Archive
from lp.soyuz.model.archivesubscriber import ArchiveSubscriber


@implementer(IPersonTransferJob)
class PersonTransferJob(StormBase):
    """Base class for team membership and person merge jobs."""

    __storm_table__ = 'PersonTransferJob'

    id = Int(primary=True)

    job_id = Int(name='job')
    job = Reference(job_id, Job.id)

    major_person_id = Int(name='major_person')
    major_person = Reference(major_person_id, Person.id)

    minor_person_id = Int(name='minor_person')
    minor_person = Reference(minor_person_id, Person.id)

    job_type = EnumCol(enum=PersonTransferJobType, notNull=True)

    _json_data = Unicode('json_data')

    @property
    def metadata(self):
        return simplejson.loads(self._json_data)

    def __init__(self, minor_person, major_person, job_type, metadata,
                 requester=None):
        """Constructor.

        :param minor_person: The person or team being added to or removed
                             from the major_person.
        :param major_person: The person or team that is receiving or losing
                             the minor person.
        :param job_type: The specific membership action being performed.
        :param metadata: The type-specific variables, as a JSON-compatible
                         dict.
        """
        super(PersonTransferJob, self).__init__()
        self.job = Job(requester=requester)
        self.job_type = job_type
        self.major_person = major_person
        self.minor_person = minor_person

        json_data = simplejson.dumps(metadata)
        # XXX AaronBentley 2009-01-29 bug=322819: This should be a bytestring,
        # but the DB representation is unicode.
        self._json_data = six.ensure_text(json_data)

    def makeDerived(self):
        return PersonTransferJobDerived.makeSubclass(self)


@delegate_to(IPersonTransferJob)
@provider(IPersonTransferJobSource)
class PersonTransferJobDerived(
        six.with_metaclass(EnumeratedSubclass, BaseRunnableJob)):
    """Intermediate class for deriving from PersonTransferJob.

    Storm classes can't simply be subclassed or you can end up with
    multiple objects referencing the same row in the db. This class uses
    lazr.delegates, which is a little bit simpler than storm's
    infoheritance solution to the problem. Subclasses need to override
    the run() method.
    """

    def __init__(self, job):
        self.context = job

    @classmethod
    def create(cls, minor_person, major_person, metadata, requester=None):
        """See `IPersonTransferJob`."""
        if not IPerson.providedBy(minor_person):
            raise TypeError("minor_person must be IPerson: %s"
                            % repr(minor_person))
        if not IPerson.providedBy(major_person):
            raise TypeError("major_person must be IPerson: %s"
                            % repr(major_person))
        job = PersonTransferJob(
            minor_person=minor_person,
            major_person=major_person,
            job_type=cls.class_job_type,
            metadata=metadata,
            requester=requester)
        derived = cls(job)
        derived.celeryRunOnCommit()
        return derived

    @classmethod
    def iterReady(cls):
        """Iterate through all ready PersonTransferJobs."""
        store = IMasterStore(PersonTransferJob)
        jobs = store.find(
            PersonTransferJob,
            And(PersonTransferJob.job_type == cls.class_job_type,
                PersonTransferJob.job_id.is_in(Job.ready_jobs)))
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        vars = BaseRunnableJob.getOopsVars(self)
        vars.extend([
            ('major_person_name', self.context.major_person.name),
            ('minor_person_name', self.context.minor_person.name),
            ])
        return vars

    _time_format = '%Y-%m-%d %H:%M:%S.%f'

    @classmethod
    def _serialiseDateTime(cls, dt):
        return dt.strftime(cls._time_format)

    @classmethod
    def _deserialiseDateTime(cls, dt_str):
        dt = datetime.strptime(dt_str, cls._time_format)
        return dt.replace(tzinfo=pytz.UTC)


@implementer(IMembershipNotificationJob)
@provider(IMembershipNotificationJobSource)
class MembershipNotificationJob(PersonTransferJobDerived):
    """A Job that sends notifications about team membership changes."""

    class_job_type = PersonTransferJobType.MEMBERSHIP_NOTIFICATION

    config = config.IMembershipNotificationJobSource

    @classmethod
    def create(cls, member, team, reviewer, old_status, new_status,
               last_change_comment=None):
        if not ITeam.providedBy(team):
            raise TypeError('team must be ITeam: %s' % repr(team))
        if not IPerson.providedBy(reviewer):
            raise TypeError('reviewer must be IPerson: %s' % repr(reviewer))
        if old_status not in TeamMembershipStatus:
            raise TypeError("old_status must be TeamMembershipStatus: %s"
                            % repr(old_status))
        if new_status not in TeamMembershipStatus:
            raise TypeError("new_status must be TeamMembershipStatus: %s"
                            % repr(new_status))
        metadata = {
            'reviewer': reviewer.id,
            'old_status': old_status.name,
            'new_status': new_status.name,
            'last_change_comment': last_change_comment,
            }
        return super(MembershipNotificationJob, cls).create(
            minor_person=member, major_person=team, metadata=metadata)

    @property
    def member(self):
        return self.minor_person

    @property
    def team(self):
        return self.major_person

    @property
    def reviewer(self):
        return getUtility(IPersonSet).get(self.metadata['reviewer'])

    @property
    def old_status(self):
        return TeamMembershipStatus.items[self.metadata['old_status']]

    @property
    def new_status(self):
        return TeamMembershipStatus.items[self.metadata['new_status']]

    @property
    def last_change_comment(self):
        return self.metadata['last_change_comment']

    def run(self):
        """See `IMembershipNotificationJob`."""
        TeamMembershipMailer.forMembershipStatusChange(
            self.member, self.team, self.reviewer, self.old_status,
            self.new_status, self.last_change_comment).sendAll()
        log.debug('MembershipNotificationJob sent email')

    def __repr__(self):
        return (
            "<{self.__class__.__name__} about "
            "~{self.minor_person.name} in ~{self.major_person.name}; "
            "status={self.job.status}>").format(self=self)


@implementer(IPersonMergeJob)
@provider(IPersonMergeJobSource)
class PersonMergeJob(PersonTransferJobDerived):
    """A Job that merges one person or team into another."""

    class_job_type = PersonTransferJobType.MERGE

    config = config.IPersonMergeJobSource

    @classmethod
    def create(cls, from_person, to_person, requester, reviewer=None,
               delete=False):
        """See `IPersonMergeJobSource`."""
        if (from_person.isMergePending() or
            (not delete and to_person.isMergePending())):
            return None
        if from_person.is_team:
            metadata = {'reviewer': reviewer.id}
        else:
            metadata = {}
        metadata['delete'] = bool(delete)
        if metadata['delete']:
            # Ideally not needed, but the DB column is not-null at the moment
            # and this minor bit of friction isn't worth changing that over.
            to_person = getUtility(ILaunchpadCelebrities).registry_experts
        return super(PersonMergeJob, cls).create(
            minor_person=from_person, major_person=to_person,
            metadata=metadata, requester=requester)

    @classmethod
    def find(cls, from_person=None, to_person=None, any_person=False):
        """See `IPersonMergeJobSource`."""
        conditions = [
            PersonTransferJob.job_type == cls.class_job_type,
            PersonTransferJob.job_id == Job.id,
            Job._status.is_in(Job.PENDING_STATUSES)]
        arg_conditions = []
        if from_person is not None:
            arg_conditions.append(
                PersonTransferJob.minor_person == from_person)
        if to_person is not None:
            arg_conditions.append(
                PersonTransferJob.major_person == to_person)
        if any_person and from_person is not None and to_person is not None:
            arg_conditions = [Or(*arg_conditions)]
        conditions.extend(arg_conditions)
        return DecoratedResultSet(
            IStore(PersonTransferJob).find(
                PersonTransferJob, *conditions), cls)

    @property
    def from_person(self):
        """See `IPersonMergeJob`."""
        return self.minor_person

    @property
    def to_person(self):
        """See `IPersonMergeJob`."""
        return self.major_person

    @property
    def reviewer(self):
        if 'reviewer' in self.metadata:
            return getUtility(IPersonSet).get(self.metadata['reviewer'])
        else:
            return None

    @property
    def log_name(self):
        return self.__class__.__name__

    def getErrorRecipients(self):
        """See `IPersonMergeJob`."""
        return [format_address_for_person(self.requester)]

    def run(self):
        """Perform the merge."""
        from_person_name = self.from_person.name
        to_person_name = self.to_person.name

        if self.metadata.get('delete', False):
            log.debug(
                "%s is about to delete ~%s", self.log_name,
                from_person_name)
            merge_people(
                from_person=self.from_person,
                to_person=getUtility(ILaunchpadCelebrities).registry_experts,
                reviewer=self.reviewer, delete=True)
            log.debug(
                "%s has deleted ~%s", self.log_name,
                from_person_name)
        else:
            log.debug(
                "%s is about to merge ~%s into ~%s", self.log_name,
                from_person_name, to_person_name)
            merge_people(
                from_person=self.from_person, to_person=self.to_person,
                reviewer=self.reviewer)
            log.debug(
                "%s has merged ~%s into ~%s", self.log_name,
                from_person_name, to_person_name)

    def __repr__(self):
        return (
            "<{self.__class__.__name__} to merge "
            "~{self.from_person.name} into ~{self.to_person.name}; "
            "status={self.job.status}>").format(self=self)

    def getOperationDescription(self):
        return ('merging ~%s into ~%s' %
                (self.from_person.name, self.to_person.name))


@implementer(IPersonDeactivateJob)
@provider(IPersonDeactivateJobSource)
class PersonDeactivateJob(PersonTransferJobDerived):
    """A Job that deactivates a person."""

    class_job_type = PersonTransferJobType.DEACTIVATE

    config = config.IPersonMergeJobSource

    @classmethod
    def create(cls, person):
        """See `IPersonMergeJobSource`."""
        # Minor person has to be not null, so use the janitor.
        janitor = getUtility(ILaunchpadCelebrities).janitor
        return super(PersonDeactivateJob, cls).create(
            minor_person=janitor, major_person=person, metadata={})

    @classmethod
    def find(cls, person=None):
        """See `IPersonMergeJobSource`."""
        conditions = [
            PersonTransferJob.job_type == cls.class_job_type,
            PersonTransferJob.job_id == Job.id,
            Job._status.is_in(Job.PENDING_STATUSES)]
        arg_conditions = []
        if person:
            arg_conditions.append(PersonTransferJob.major_person == person)
        conditions.extend(arg_conditions)
        return DecoratedResultSet(
            IStore(PersonTransferJob).find(
                PersonTransferJob, *conditions), cls)

    @property
    def person(self):
        """See `IPersonMergeJob`."""
        return self.major_person

    @property
    def log_name(self):
        return self.__class__.__name__

    def getErrorRecipients(self):
        """See `IPersonMergeJob`."""
        return [format_address_for_person(self.person)]

    def run(self):
        """Perform the merge."""
        person_name = self.person.name
        log.debug('about to deactivate ~%s', person_name)
        self.person.deactivate(validate=False, pre_deactivate=False)
        log.debug('done deactivating ~%s', person_name)

    def __repr__(self):
        return (
            "<{self.__class__.__name__} to deactivate "
            "~{self.person.name}").format(self=self)

    def getOperationDescription(self):
        return 'deactivating ~%s' % self.person.name


@implementer(IPersonCloseAccountJob)
@provider(IPersonCloseAccountJobSource)
class PersonCloseAccountJob(PersonTransferJobDerived):
    """A Job that closes account for a person."""

    class_job_type = PersonTransferJobType.CLOSE_ACCOUNT

    config = config.IPersonCloseAccountJobSource

    @classmethod
    def create(cls, username):
        """See `IPersonCloseAccountJobSource`."""
        # Minor person has to be not null, so use the janitor.
        store = IMasterStore(Person)
        janitor = getUtility(ILaunchpadCelebrities).janitor

        person = store.using(
            Person,
            LeftJoin(EmailAddress, Person.id == EmailAddress.personID)
        ).find(
            Person,
            Or(Person.name == username,
               Lower(EmailAddress.email) == Lower(username))
        ).order_by(Person.id).config(distinct=True).one()

        if person is None:
            raise TypeError("User %s does not exist" % username)
        person_name = person.name

        # We don't do teams
        if person.is_team:
            raise TypeError("%s is a team" % person_name)

        log.info("Closing %s's account" % person_name)

        return super(PersonCloseAccountJob, cls).create(
            minor_person=janitor, major_person=person, metadata={})

    @classmethod
    def find(cls, person=None):
        """See `IPersonMergeJobSource`."""
        conditions = [
            PersonCloseAccountJob.job_type == cls.class_job_type,
            PersonCloseAccountJob.job_id == Job.id,
            Job._status.is_in(Job.PENDING_STATUSES)]
        arg_conditions = []
        if person:
            arg_conditions.append(PersonCloseAccountJob.major_person == person)
        conditions.extend(arg_conditions)
        return DecoratedResultSet(
            IStore(PersonCloseAccountJob).find(
                PersonCloseAccountJob, *conditions), cls)

    @property
    def person(self):
        """See `IPersonCloseAccountJob`."""
        return self.major_person

    @property
    def log_name(self):
        return self.__class__.__name__

    def getErrorRecipients(self):
        """See `IPersonCloseAccountJob`."""
        return [format_address_for_person(self.person)]

    def run(self):
        """Perform the account closure."""
        try:
            self.close_account(self.person)
        except Exception:
            log.error(
                "%s Account clossure failed for user %s", self.log_name,
                self.person.name)
            transaction.abort()

    def __repr__(self):
        return (
            "<{self.__class__.__name__} to close account "
            "~{self.person.name}").format(self=self)

    def getOperationDescription(self):
        return 'closing account for ~%s' % self.person.name

    def close_account(self, person):
        """Close a person's account.

        Return True on success, or log an error message and return False
        """
        store = IMasterStore(Person)
        janitor = getUtility(ILaunchpadCelebrities).janitor
        cur = cursor()
        references = list(postgresql.listReferences(cur, 'person', 'id'))
        postgresql.check_indirect_references(references)
        username = self.person.name

        def table_notification(table):
            log.debug("Handling the %s table" % table)

        # All names starting with 'removed' are blacklisted,
        # so this will always succeed.
        new_name = 'removed%d' % person.id

        # Some references can safely remain in place and link
        # to the cleaned-out Person row.
        skip = {
            # These references express some kind of audit trail.
            # The actions in question still happened, and in some cases
            # the rows may still have functional significance
            # (e.g. subscriptions or access grants), but we no longer
            # identify the actor.
            ('accessartifactgrant', 'grantor'),
            ('accesspolicygrant', 'grantor'),
            ('binarypackagepublishinghistory', 'removed_by'),
            ('branch', 'registrant'),
            ('branchmergeproposal', 'merge_reporter'),
            ('branchmergeproposal', 'merger'),
            ('branchmergeproposal', 'queuer'),
            ('branchmergeproposal', 'registrant'),
            ('branchmergeproposal', 'reviewer'),
            ('branchsubscription', 'subscribed_by'),
            ('bug', 'owner'),
            ('bug', 'who_made_private'),
            ('bugactivity', 'person'),
            ('bugnomination', 'decider'),
            ('bugnomination', 'owner'),
            ('bugtask', 'owner'),
            ('bugsubscription', 'subscribed_by'),
            ('codeimport', 'owner'),
            ('codeimport', 'registrant'),
            ('codeimportjob', 'requesting_user'),
            ('codeimportevent', 'person'),
            ('codeimportresult', 'requesting_user'),
            ('distroarchseriesfilter', 'creator'),
            ('faq', 'last_updated_by'),
            ('featureflagchangelogentry', 'person'),
            ('gitactivity', 'changee'),
            ('gitactivity', 'changer'),
            ('gitrepository', 'registrant'),
            ('gitrule', 'creator'),
            ('gitrulegrant', 'grantor'),
            ('gitsubscription', 'subscribed_by'),
            ('job', 'requester'),
            ('message', 'owner'),
            ('messageapproval', 'disposed_by'),
            ('messageapproval', 'posted_by'),
            ('packagecopyrequest', 'requester'),
            ('packagediff', 'requester'),
            ('packageupload', 'signing_key_owner'),
            ('personlocation', 'last_modified_by'),
            ('persontransferjob', 'major_person'),
            ('persontransferjob', 'minor_person'),
            ('poexportrequest', 'person'),
            ('pofile', 'lasttranslator'),
            ('pofiletranslator', 'person'),
            ('product', 'registrant'),
            ('question', 'answerer'),
            ('questionreopening', 'answerer'),
            ('questionreopening', 'reopener'),
            ('snapbuild', 'requester'),
            ('sourcepackagepublishinghistory', 'creator'),
            ('sourcepackagepublishinghistory', 'removed_by'),
            ('sourcepackagepublishinghistory', 'sponsor'),
            ('sourcepackagerecipebuild', 'requester'),
            ('sourcepackagerelease', 'creator'),
            ('sourcepackagerelease', 'maintainer'),
            ('sourcepackagerelease', 'signing_key_owner'),
            ('specification', 'approver'),
            ('specification', 'completer'),
            ('specification', 'drafter'),
            ('specification', 'goal_decider'),
            ('specification', 'goal_proposer'),
            ('specification', 'last_changed_by'),
            ('specification', 'owner'),
            ('specification', 'starter'),
            ('structuralsubscription', 'subscribed_by'),
            ('teammembership', 'acknowledged_by'),
            ('teammembership', 'last_changed_by'),
            ('teammembership', 'proposed_by'),
            ('teammembership', 'reviewed_by'),
            ('translationimportqueueentry', 'importer'),
            ('translationmessage', 'reviewer'),
            ('translationmessage', 'submitter'),
            ('translationrelicensingagreement', 'person'),
            ('usertouseremail', 'recipient'),
            ('usertouseremail', 'sender'),
            ('xref', 'creator'),

            # This is maintained by trigger functions and a garbo job.  It
            # doesn't need to be updated immediately.
            ('bugsummary', 'viewed_by'),

            # XXX cjwatson 2019-05-02 bug=1827399: This is suboptimal because
            # it does retain some personal information, but it's currently hard
            # to deal with due to the size and complexity of references to it.
            # We can hopefully provide a garbo job for this eventually.
            ('revisionauthor', 'person'),
            }

        # If all the teams that the user owns
        # have been deleted (not just one) skip Person.teamowner
        teams = store.find(Person, Person.teamowner == person)
        if all(team.merged is not None for team in teams):
            skip.add(('person', 'teamowner'))

        reference_names = {
            (src_tab, src_col) for src_tab, src_col, _, _, _, _ in references}
        for src_tab, src_col in skip:
            if (src_tab, src_col) not in reference_names:
                raise AssertionError(
                    "%s.%s is not a Person reference; possible typo?" %
                    (src_tab, src_col))

        # XXX cjwatson 2018-11-29: Registrants could possibly be left as-is,
        # but perhaps we should pretend that the registrant was ~registry in
        # that case instead?

        # Remove the EmailAddress. This is the most important step, as
        # people requesting account removal seem to primarily be interested
        # in ensuring we no longer store this information.
        table_notification('EmailAddress')
        store.find(EmailAddress, EmailAddress.personID == person.id).remove()

        # Clean out personal details from the Person table
        table_notification('Person')
        person.display_name = 'Removed by request'
        person.name = new_name
        person.homepage_content = None
        person.icon = None
        person.mugshot = None
        person.hide_email_addresses = False
        person.registrant = None
        person.logo = None
        person.creation_rationale = PersonCreationRationale.UNKNOWN
        person.creation_comment = None

        # Keep the corresponding PersonSettings row, but reset everything to
        # the defaults.
        table_notification('PersonSettings')
        store.find(PersonSettings, PersonSettings.personID == person.id).set(
            selfgenerated_bugnotifications=DEFAULT,
            # XXX cjwatson 2018-11-29: These two columns have NULL defaults,
            # but perhaps shouldn't?
            expanded_notification_footers=False,
            require_strong_email_authentication=False)
        skip.add(('personsettings', 'person'))

        # Remove almost everything from the Account row and the corresponding
        # OpenIdIdentifier rows, preserving only a minimal audit trail.
        if person.account is not None:
            table_notification('Account')
            account = removeSecurityProxy(person.account)
            account.displayname = 'Removed by request'
            account.creation_rationale = AccountCreationRationale.UNKNOWN
            person.setAccountStatus(
                AccountStatus.CLOSED, janitor, "Closed using close-account.")

            table_notification('OpenIdIdentifier')
            store.find(
                OpenIdIdentifier,
                OpenIdIdentifier.account_id == account.id).remove()

        # Reassign their bugs
        table_notification('BugTask')
        store.find(
            BugTask, BugTask.assignee_id == person.id).set(assignee_id=None)

        # Reassign questions assigned to the user, and close all their
        # questions in non-final states since nobody else can.
        table_notification('Question')
        store.find(Question, Question.assignee_id == person.id).set(
            assignee_id=None)
        owned_non_final_questions = store.find(
            Question, Question.owner_id == person.id,
            Question.status.is_in([
                QuestionStatus.OPEN, QuestionStatus.NEEDSINFO,
                QuestionStatus.ANSWERED,
                ]))
        owned_non_final_questions.set(
            status=QuestionStatus.SOLVED,
            whiteboard=(
                u'Closed by Launchpad due to owner requesting '
                u'account removal'))
        skip.add(('question', 'owner'))

        # Remove rows from tables in simple cases in the given order
        removals = [
            # Trash their email addresses. People who request complete account
            # removal would be unhappy if they reregistered with their old
            # email address and this resurrected their deleted account, as the
            # email address is probably the piece of data we store that they
            # were most concerned with being removed from our systems.
            ('EmailAddress', 'person'),

            # Login and OAuth tokens are no longer interesting if the user can
            # no longer log in.
            ('LoginToken', 'requester'),
            ('OAuthAccessToken', 'person'),
            ('OAuthRequestToken', 'person'),

            # Trash their codes of conduct and GPG keys
            ('SignedCodeOfConduct', 'owner'),
            ('GpgKey', 'owner'),

            # Subscriptions and notifications
            ('BranchSubscription', 'person'),
            ('BugMute', 'person'),
            ('BugNotificationRecipient', 'person'),
            ('BugSubscription', 'person'),
            ('BugSubscriptionFilterMute', 'person'),
            ('GitSubscription', 'person'),
            ('MailingListSubscription', 'person'),
            ('QuestionSubscription', 'person'),
            ('SpecificationSubscription', 'person'),
            ('StructuralSubscription', 'subscriber'),

            # Personal stuff, freeing up the namespace for others who want
            # to play or just to remove any fingerprints identifying the user.
            ('IrcId', 'person'),
            ('JabberId', 'person'),
            ('WikiName', 'person'),
            ('PersonLanguage', 'person'),
            ('PersonLocation', 'person'),
            ('SshKey', 'person'),

            # Karma
            ('Karma', 'person'),
            ('KarmaCache', 'person'),
            ('KarmaTotalCache', 'person'),

            # Team memberships
            ('TeamMembership', 'person'),
            ('TeamParticipation', 'person'),

            # Contacts
            ('AnswerContact', 'person'),

            # Pending items in queues
            ('POExportRequest', 'person'),

            # Access grants
            ('AccessArtifactGrant', 'grantee'),
            ('AccessPolicyGrant', 'grantee'),
            ('ArchivePermission', 'person'),
            ('GitRuleGrant', 'grantee'),
            ('SharingJob', 'grantee'),

            # Soyuz reporting
            ('LatestPersonSourcePackageReleaseCache', 'creator'),
            ('LatestPersonSourcePackageReleaseCache', 'maintainer'),

            # "Affects me too" information
            ('BugAffectsPerson', 'person'),
            ]
        for table, person_id_column in removals:
            table_notification(table)
            store.execute("""
                DELETE FROM %(table)s WHERE %(person_id_column)s = ?
                """ % {
                    'table': table,
                    'person_id_column': person_id_column,
                    },
                (person.id,))

        # Trash Sprint Attendance records in the future.
        table_notification('SprintAttendance')
        store.execute("""
            DELETE FROM SprintAttendance
            USING Sprint
            WHERE Sprint.id = SprintAttendance.sprint
                AND attendee = ?
                AND Sprint.time_starts > CURRENT_TIMESTAMP AT TIME ZONE 'UTC'
            """, (person.id,))
        # Any remaining past sprint attendance records can harmlessly refer to
        # the placeholder person row.
        skip.add(('sprintattendance', 'attendee'))

        # generate_ppa_htaccess currently relies on seeing active
        # ArchiveAuthToken rows so that it knows which ones to remove from
        # .htpasswd files on disk in response to the cancellation of the
        # corresponding ArchiveSubscriber rows; but even once PPA authorisation
        # is handled dynamically, we probably still want to have the per-person
        # audit trail here.
        archive_subscriber_ids = set(store.find(
            ArchiveSubscriber.id,
            ArchiveSubscriber.subscriber_id == person.id,
            ArchiveSubscriber.status == ArchiveSubscriberStatus.CURRENT))
        if archive_subscriber_ids:
            getUtility(IArchiveSubscriberSet).cancel(
                archive_subscriber_ids, janitor)
        skip.add(('archivesubscriber', 'subscriber'))
        skip.add(('archiveauthtoken', 'person'))

        # Remove hardware submissions.
        table_notification('HWSubmissionDevice')
        store.execute("""
            DELETE FROM HWSubmissionDevice
            USING HWSubmission
            WHERE HWSubmission.id = HWSubmissionDevice.submission
                AND owner = ?
            """, (person.id,))
        table_notification('HWSubmission')
        store.execute("""
            DELETE FROM HWSubmission
            WHERE HWSubmission.owner = ?
            """, (person.id,))

        # Purge deleted PPAs.  This is safe because the archive can only be in
        # the DELETED status if the publisher has removed it from disk and set
        # all its publications to DELETED.
        # XXX cjwatson 2019-08-09: This will fail if anything non-trivial has
        # been done in this person's PPAs; and it's not obvious what to do in
        # more complicated cases such as builds having been copied out
        # elsewhere.  It's good enough for some simple cases, though.
        try:
            store.find(
                Archive,
                Archive.owner == person,
                Archive.status == ArchiveStatus.DELETED).remove()
        except IntegrityError:
            log.error(
                "%s Can't delete non-trivial PPAs for user %s", self.log_name,
                username)
            raise IntegrityError(
                "Can't delete non-trivial PPAs for user %s" % username)

        has_references = False

        # Check for active related projects, and skip inactive ones.
        for col in 'bug_supervisor', 'driver', 'owner':
            # Raw SQL because otherwise using Product._owner while displaying
            # it as Product.owner is too fiddly.
            result = store.execute("""
                SELECT COUNT(*) FROM product WHERE active AND %(col)s = ?
                """ % {'col': col},
                (person.id,))
            count = result.get_one()[0]
            if count:
                log.error(
                    "User %s is still referenced by %d product.%s values" %
                    (username, count, col))
                has_references = True
            skip.add(('product', col))
        for col in 'driver', 'owner':
            count = store.find(
                ProductSeries,
                ProductSeries.product == Product.id, Product.active,
                getattr(ProductSeries, col) == person).count()
            if count:
                log.error(
                    "User %s is still referenced by %d productseries.%s values"
                    % (username, count, col))
                has_references = True
            skip.add(('productseries', col))

        # Closing the account will only work if all references have been
        # handled by this point.  If not, it's safer to bail out.  It's OK if
        # this doesn't work in all conceivable situations, since some of them
        # may require careful thought and decisions by a human administrator.
        for src_tab, src_col, ref_tab, ref_col, updact, delact in references:
            if (src_tab, src_col) in skip:
                continue
            result = store.execute("""
                SELECT COUNT(*) FROM %(src_tab)s WHERE %(src_col)s = ?
                """ % {
                    'src_tab': src_tab,
                    'src_col': src_col,
                    },
                (person.id,))
            count = result.get_one()[0]
            if count:
                log.error(
                    "User %s is still referenced by %d %s.%s values" %
                    (username, count, src_tab, src_col))
                has_references = True
        if has_references:
            log.error(
                "%s User %s is still referenced", self.log_name,
                username)
            raise LaunchpadScriptFailure(
                "User %s is still referenced" % username)

        return True


@implementer(ITeamInvitationNotificationJob)
@provider(ITeamInvitationNotificationJobSource)
class TeamInvitationNotificationJob(PersonTransferJobDerived):
    """A Job that sends a notification of an invitation to join a team."""

    class_job_type = PersonTransferJobType.TEAM_INVITATION_NOTIFICATION

    config = config.ITeamInvitationNotificationJobSource

    @classmethod
    def create(cls, member, team):
        if not ITeam.providedBy(team):
            raise TypeError('team must be ITeam: %s' % repr(team))
        return super(TeamInvitationNotificationJob, cls).create(
            minor_person=member, major_person=team, metadata={})

    @property
    def member(self):
        return self.minor_person

    @property
    def team(self):
        return self.major_person

    def run(self):
        """See `ITeamInvitationNotificationJob`."""
        TeamMembershipMailer.forInvitationToJoinTeam(
            self.member, self.team).sendAll()

    def __repr__(self):
        return (
            "<{self.__class__.__name__} for invitation of "
            "~{self.minor_person.name} to join ~{self.major_person.name}; "
            "status={self.job.status}>").format(self=self)


@implementer(ITeamJoinNotificationJob)
@provider(ITeamJoinNotificationJobSource)
class TeamJoinNotificationJob(PersonTransferJobDerived):
    """A Job that sends a notification of a new member joining a team."""

    class_job_type = PersonTransferJobType.TEAM_JOIN_NOTIFICATION

    config = config.ITeamJoinNotificationJobSource

    @classmethod
    def create(cls, member, team):
        if not ITeam.providedBy(team):
            raise TypeError('team must be ITeam: %s' % repr(team))
        return super(TeamJoinNotificationJob, cls).create(
            minor_person=member, major_person=team, metadata={})

    @property
    def member(self):
        return self.minor_person

    @property
    def team(self):
        return self.major_person

    def run(self):
        """See `ITeamJoinNotificationJob`."""
        TeamMembershipMailer.forTeamJoin(self.member, self.team).sendAll()

    def __repr__(self):
        return (
            "<{self.__class__.__name__} for "
            "~{self.minor_person.name} joining ~{self.major_person.name}; "
            "status={self.job.status}>").format(self=self)


@implementer(IExpiringMembershipNotificationJob)
@provider(IExpiringMembershipNotificationJobSource)
class ExpiringMembershipNotificationJob(PersonTransferJobDerived):
    """A Job that sends a warning about expiring membership."""

    class_job_type = PersonTransferJobType.EXPIRING_MEMBERSHIP_NOTIFICATION

    config = config.IExpiringMembershipNotificationJobSource

    @classmethod
    def create(cls, member, team, dateexpires):
        if not ITeam.providedBy(team):
            raise TypeError('team must be ITeam: %s' % repr(team))
        metadata = {
            'dateexpires': cls._serialiseDateTime(dateexpires),
            }
        return super(ExpiringMembershipNotificationJob, cls).create(
            minor_person=member, major_person=team, metadata=metadata)

    @property
    def member(self):
        return self.minor_person

    @property
    def team(self):
        return self.major_person

    @property
    def dateexpires(self):
        return self._deserialiseDateTime(self.metadata['dateexpires'])

    def run(self):
        """See `IExpiringMembershipNotificationJob`."""
        TeamMembershipMailer.forExpiringMembership(
            self.member, self.team, self.dateexpires).sendAll()

    def __repr__(self):
        return (
            "<{self.__class__.__name__} for upcoming expiry of "
            "~{self.minor_person.name} from ~{self.major_person.name}; "
            "status={self.job.status}>").format(self=self)


@implementer(ISelfRenewalNotificationJob)
@provider(ISelfRenewalNotificationJobSource)
class SelfRenewalNotificationJob(PersonTransferJobDerived):
    """A Job that sends a notification of a self-renewal."""

    class_job_type = PersonTransferJobType.SELF_RENEWAL_NOTIFICATION

    config = config.ISelfRenewalNotificationJobSource

    @classmethod
    def create(cls, member, team, dateexpires):
        if not ITeam.providedBy(team):
            raise TypeError('team must be ITeam: %s' % repr(team))
        metadata = {
            'dateexpires': cls._serialiseDateTime(dateexpires),
            }
        return super(SelfRenewalNotificationJob, cls).create(
            minor_person=member, major_person=team, metadata=metadata)

    @property
    def member(self):
        return self.minor_person

    @property
    def team(self):
        return self.major_person

    @property
    def dateexpires(self):
        return self._deserialiseDateTime(self.metadata['dateexpires'])

    def run(self):
        """See `ISelfRenewalNotificationJob`."""
        TeamMembershipMailer.forSelfRenewal(
            self.member, self.team, self.dateexpires).sendAll()

    def __repr__(self):
        return (
            "<{self.__class__.__name__} for self-renewal of "
            "~{self.minor_person.name} in ~{self.major_person.name}; "
            "status={self.job.status}>").format(self=self)
