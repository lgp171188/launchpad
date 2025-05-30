# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Launchpad bug-related database table classes."""

__all__ = [
    "Bug",
    "BugAffectsPerson",
    "BugBecameQuestionEvent",
    "BugMute",
    "BugSet",
    "BugTag",
    "CannotSetLockReason",
    "FileBugData",
    "generate_subscription_with",
    "get_also_notified_subscribers",
    "get_bug_tags_open_count",
]


import http.client
import operator
import re
from collections.abc import Iterable, Set
from datetime import timezone
from email.utils import make_msgid
from functools import wraps
from io import BytesIO
from itertools import chain
from typing import List

from lazr.lifecycle.event import ObjectCreatedEvent
from lazr.lifecycle.snapshot import Snapshot
from lazr.restful.declarations import error_status
from storm.expr import (
    SQL,
    Add,
    And,
    Coalesce,
    Desc,
    In,
    Join,
    LeftJoin,
    Max,
    Not,
    Or,
    Select,
    Sum,
    Union,
)
from storm.info import ClassAlias
from storm.locals import Bool, DateTime, Int, Reference, ReferenceSet
from storm.properties import Unicode
from storm.store import EmptyResultSet, Store
from zope.component import getAdapter, getUtility
from zope.contenttype import guess_content_type
from zope.event import notify
from zope.interface import implementer
from zope.security import checker
from zope.security.interfaces import Unauthorized
from zope.security.proxy import ProxyFactory, removeSecurityProxy

from lp.answers.interfaces.questiontarget import IQuestionTarget
from lp.app.enums import (
    PRIVATE_INFORMATION_TYPES,
    PROPRIETARY_INFORMATION_TYPES,
    SECURITY_INFORMATION_TYPES,
    InformationType,
    ServiceUsage,
)
from lp.app.errors import (
    NotFoundError,
    SubscriptionPrivacyViolation,
    UserCannotUnsubscribePerson,
)
from lp.app.interfaces.informationtype import IInformationType
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.security import IAuthorization
from lp.app.interfaces.services import IService
from lp.app.model.launchpad import InformationTypeMixin
from lp.app.validators import LaunchpadValidationError
from lp.bugs.adapters.bug import convert_to_information_type
from lp.bugs.adapters.bugchange import (
    BranchLinkedToBug,
    BranchUnlinkedFromBug,
    BugAttachmentChange,
    BugConvertedToQuestion,
    BugDuplicateChange,
    BugLocked,
    BugLockReasonSet,
    BugPresenceAdded,
    BugPresenceRemoved,
    BugUnlocked,
    BugWatchAdded,
    BugWatchRemoved,
    SeriesNominated,
    UnsubscribedFromBug,
)
from lp.bugs.enums import BugLockedStatus, BugLockStatus, BugNotificationLevel
from lp.bugs.errors import InvalidDuplicateValue
from lp.bugs.interfaces.bug import (
    IBug,
    IBugBecameQuestionEvent,
    IBugMute,
    IBugSet,
    IFileBugData,
)
from lp.bugs.interfaces.bugactivity import IBugActivitySet
from lp.bugs.interfaces.bugattachment import (
    BugAttachmentType,
    IBugAttachmentSet,
)
from lp.bugs.interfaces.bugmessage import IBugMessageSet
from lp.bugs.interfaces.bugnomination import (
    BugNominationStatus,
    IBugNominationSet,
    NominationError,
    NominationSeriesObsoleteError,
)
from lp.bugs.interfaces.bugnotification import IBugNotificationSet
from lp.bugs.interfaces.bugpresence import IBugPresenceSet
from lp.bugs.interfaces.bugtarget import ISeriesBugTarget
from lp.bugs.interfaces.bugtask import (
    UNRESOLVED_BUGTASK_STATUSES,
    BugTaskStatus,
    BugTaskStatusSearch,
    IBugTask,
    IBugTaskSet,
    IllegalTarget,
)
from lp.bugs.interfaces.bugtracker import BugTrackerType
from lp.bugs.interfaces.bugwatch import IBugWatchSet
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.hasbug import IHasBug
from lp.bugs.mail.bugnotificationrecipients import BugNotificationRecipients
from lp.bugs.model.bugactivity import BugActivity
from lp.bugs.model.bugattachment import BugAttachment
from lp.bugs.model.bugbranch import BugBranch
from lp.bugs.model.buglinktarget import ObjectLinkedEvent, ObjectUnlinkedEvent
from lp.bugs.model.bugmessage import BugMessage
from lp.bugs.model.bugnomination import BugNomination
from lp.bugs.model.bugnotification import BugNotification
from lp.bugs.model.bugpresence import BugPresence
from lp.bugs.model.bugsubscription import BugSubscription
from lp.bugs.model.bugtarget import OfficialBugTag
from lp.bugs.model.bugtask import BugTask, bugtask_sort_key
from lp.bugs.model.bugwatch import BugWatch
from lp.bugs.model.structuralsubscription import (
    get_structural_subscribers,
    get_structural_subscriptions,
)
from lp.code.interfaces.branchcollection import IAllBranches
from lp.code.interfaces.gitcollection import IAllGitRepositories
from lp.registry.errors import CannotChangeInformationType
from lp.registry.interfaces.accesspolicy import (
    IAccessArtifactGrantSource,
    IAccessArtifactSource,
)
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import (
    IPersonSet,
    validate_person,
    validate_public_person,
)
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.role import IPersonRoles
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sharingjob import (
    IRemoveArtifactSubscriptionsJobSource,
)
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.registry.model.accesspolicy import reconcile_access_for_artifacts
from lp.registry.model.person import Person, PersonSet, person_sort_key
from lp.registry.model.pillar import pillar_sort_key
from lp.registry.model.teammembership import TeamParticipation
from lp.services.config import config
from lp.services.database import bulk
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import WithMaterialized
from lp.services.fields import DuplicateBug
from lp.services.helpers import shortlist
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.messages.interfaces.message import IMessage, IndexedMessage
from lp.services.messages.model.message import (
    Message,
    MessageChunk,
    MessageSet,
)
from lp.services.propertycache import (
    cachedproperty,
    clear_property_cache,
    get_property_cache,
)
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import ILaunchBag
from lp.services.webapp.publisher import (
    get_raw_form_value_from_current_request,
)
from lp.services.webapp.snapshot import notify_modified
from lp.services.xref.interfaces import IXRefSet


@error_status(http.client.BAD_REQUEST)
class CannotSetLockReason(Exception):
    """Raised when someone tries to set lock_reason for an unlocked bug."""


@error_status(http.client.BAD_REQUEST)
class CannotDisableNotifications(Exception):
    """Raised when someone tries to disable notifications for adding comments
    on a bug and the person calling the API is not the bugsupervisor.
    """


@error_status(http.client.BAD_REQUEST)
class CannotLockBug(Exception):
    """
    Raised when someone tries to lock a bug already locked
    with the same reason.
    """


def snapshot_bug_params(bug_params):
    """Return a snapshot of a `CreateBugParams` object."""
    return Snapshot(
        bug_params,
        names=[
            "owner",
            "title",
            "comment",
            "description",
            "msg",
            "datecreated",
            "information_type",
            "target",
            "status",
            "subscribers",
            "tags",
            "subscribe_owner",
            "filed_by",
            "importance",
            "milestone",
            "assignee",
            "cve",
        ],
    )


class BugTag(StormBase):
    """A tag belonging to a bug."""

    __storm_table__ = "BugTag"
    id = Int(primary=True)

    bug_id = Int(name="bug", allow_none=False)
    bug = Reference(bug_id, "Bug.id")

    tag = Unicode(allow_none=False)

    def __init__(self, bug, tag):
        self.bug = bug
        self.tag = tag

    def destroySelf(self):
        Store.of(self).remove(self)


def get_bug_tags_open_count(
    context_condition, user, tag_limit=0, include_tags=None
):
    """Worker for IBugTarget.getUsedBugTagsWithOpenCounts.

    See `IBugTarget` for details.

    The only change is that this function takes a SQL expression for limiting
    the found tags.
    :param context_condition: A Storm SQL expression, limiting the
        used tags to a specific context. Only the BugSummary table may be
        used to choose the context. If False then no query will be performed
        (and {} returned).
    """
    # Circular fail.
    from lp.bugs.model.bugsummary import (
        BugSummary,
        get_bugsummary_filter_for_user,
    )

    tags = {}
    if include_tags:
        tags = {tag: 0 for tag in include_tags}
    where_conditions = [
        BugSummary.status.is_in(UNRESOLVED_BUGTASK_STATUSES),
        BugSummary.tag != None,
        context_condition,
    ]

    # Apply the privacy filter.
    store = IStore(BugSummary)
    user_with, user_where = get_bugsummary_filter_for_user(user)
    if user_with:
        store = store.with_(user_with)
    where_conditions.extend(user_where)

    sum_count = Sum(BugSummary.count)
    tag_count_columns = (BugSummary.tag, sum_count)

    # Always query for used
    def _query(*args):
        return (
            store.find(tag_count_columns, *(where_conditions + list(args)))
            .group_by(BugSummary.tag)
            .having(sum_count != 0)
            .order_by(Desc(Sum(BugSummary.count)), BugSummary.tag)
        )

    used = _query()
    if tag_limit:
        used = used[:tag_limit]
    if include_tags:
        # Union in a query for just include_tags.
        used = used.union(_query(BugSummary.tag.is_in(include_tags)))
    tags.update(dict(used))
    return tags


@implementer(IBugBecameQuestionEvent)
class BugBecameQuestionEvent:
    """See `IBugBecameQuestionEvent`."""

    def __init__(self, bug, question, user):
        self.bug = bug
        self.question = question
        self.user = user


def update_bug_heat(bug_ids):
    """Update the heat for the specified bugs."""
    # We need to flush the store first to ensure that changes are
    # reflected in the new bug heat total.
    if not bug_ids:
        return
    store = IStore(Bug)
    store.find(Bug, Bug.id.is_in(bug_ids)).set(
        heat=SQL("calculate_bug_heat(Bug.id)"), heat_last_updated=UTC_NOW
    )


@implementer(IBug, IInformationType)
class Bug(StormBase, InformationTypeMixin):
    """A bug."""

    __storm_table__ = "Bug"
    __storm_order__ = "-id"

    # db field names
    id = Int(primary=True)
    name = Unicode(default=None)
    title = Unicode(allow_none=False)
    description = Unicode(allow_none=True, default=None)
    owner_id = Int(
        name="owner", validator=validate_public_person, allow_none=False
    )
    owner = Reference(owner_id, "Person.id")
    duplicateof_id = Int(name="duplicateof", default=None)
    duplicateof = Reference(duplicateof_id, "Bug.id")
    datecreated = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )
    date_last_updated = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )
    date_made_private = DateTime(
        allow_none=True, default=None, tzinfo=timezone.utc
    )
    who_made_private_id = Int(
        name="who_made_private", validator=validate_public_person, default=None
    )
    who_made_private = Reference(who_made_private_id, "Person.id")
    information_type = DBEnum(
        enum=InformationType, allow_none=False, default=InformationType.PUBLIC
    )

    # useful Joins
    activity = ReferenceSet("id", BugActivity.bug_id, order_by=BugActivity.id)
    bug_messages = ReferenceSet(
        "id", BugMessage.bug_id, order_by=BugMessage.index
    )
    watches = ReferenceSet(
        "id",
        BugWatch.bug_id,
        order_by=(BugWatch.bugtracker_id, BugWatch.remotebug),
    )
    duplicates = ReferenceSet("id", "Bug.duplicateof_id", order_by="Bug.id")
    linked_bugbranches = ReferenceSet(
        "id", BugBranch.bug_id, order_by=BugBranch.id
    )
    date_last_message = DateTime(default=None, tzinfo=timezone.utc)
    number_of_duplicates = Int(allow_none=False, default=0)
    message_count = Int(allow_none=False, default=0)
    users_affected_count = Int(allow_none=False, default=0)
    users_unaffected_count = Int(allow_none=False, default=0)
    heat = Int(allow_none=False, default=0)
    heat_last_updated = DateTime(default=None, tzinfo=timezone.utc)
    latest_patch_uploaded = DateTime(default=None, tzinfo=timezone.utc)
    lock_status = DBEnum(
        name="lock_status",
        enum=BugLockStatus,
        allow_none=False,
        default=BugLockStatus.UNLOCKED,
    )
    lock_reason = Unicode(allow_none=True, default=None)

    def __init__(
        self,
        title,
        owner,
        description=None,
        datecreated=DEFAULT,
        date_made_private=None,
        who_made_private=None,
        information_type=InformationType.PUBLIC,
    ):
        super().__init__()
        self.title = title
        self.owner = owner
        self.description = description
        self.datecreated = datecreated
        self.date_made_private = date_made_private
        self.who_made_private = who_made_private
        self.information_type = information_type

    @property
    def locked(self):
        try:
            BugLockedStatus.items[self.lock_status.value]
            return True
        except KeyError:
            return False

    @property
    def linked_branches(self):
        return [link.branch for link in self.linked_bugbranches]

    @property
    def cves(self):
        from lp.bugs.model.cve import Cve

        xref_cve_sequences = [
            sequence
            for _, sequence in getUtility(IXRefSet).findFrom(
                ("bug", str(self.id)), types=["cve"]
            )
        ]
        if not xref_cve_sequences:
            return []
        expr = Cve.sequence.is_in(xref_cve_sequences)
        return list(
            sorted(
                IStore(Cve).find(Cve, expr),
                key=operator.attrgetter("sequence"),
            )
        )

    @property
    def vulnerabilities(self):
        from lp.bugs.model.vulnerability import Vulnerability

        ids = [
            int(vuln_id)
            for _, vuln_id in getUtility(IXRefSet).findFrom(
                ("bug", str(self.id)), types=["vulnerability"]
            )
        ]
        return list(
            sorted(
                bulk.load(Vulnerability, ids), key=operator.attrgetter("id")
            )
        )

    @property
    def questions(self):
        from lp.answers.model.question import Question

        question_ids = [
            int(id)
            for _, id in getUtility(IXRefSet).findFrom(
                ("bug", str(self.id)), types=["question"]
            )
        ]
        return list(
            sorted(
                bulk.load(Question, question_ids),
                key=operator.attrgetter("id"),
            )
        )

    @property
    def specifications(self):
        from lp.blueprints.model.specification import Specification

        spec_ids = [
            int(id)
            for _, id in getUtility(IXRefSet).findFrom(
                ("bug", str(self.id)), types=["specification"]
            )
        ]
        return list(
            sorted(
                bulk.load(Specification, spec_ids),
                key=operator.attrgetter("id"),
            )
        )

    def getSpecifications(self, user):
        """See `IBug`."""
        from lp.blueprints.model.specification import Specification
        from lp.blueprints.model.specificationsearch import (
            get_specification_privacy_filter,
        )

        specifications = self.specifications
        if not specifications:
            return EmptyResultSet()
        return IStore(Specification).find(
            Specification,
            Specification.id.is_in(spec.id for spec in specifications),
            *get_specification_privacy_filter(user),
        )

    @property
    def messages(self):
        """See `IBug`."""
        return DecoratedResultSet(
            IStore(Message)
            .find(
                (Message, Person),
                BugMessage.bug == self,
                BugMessage.message_id == Message.id,
                Message.owner_id == Person.id,
            )
            .order_by(Message.datecreated, Message.id),
            result_decorator=operator.itemgetter(0),
        )

    @property
    def security_related(self):
        return self.information_type in SECURITY_INFORMATION_TYPES

    @cachedproperty
    def _subscriber_cache(self):
        """Caches known subscribers."""
        return set()

    @cachedproperty
    def _subscriber_dups_cache(self):
        """Caches known subscribers to dupes."""
        return set()

    @cachedproperty
    def _unsubscribed_cache(self):
        """Cache known non-subscribers."""
        return set()

    @property
    def latest_patch(self):
        """See `IBug`."""
        # We want to retrieve the most recently added bug attachment
        # that is of type BugAttachmentType.PATCH. In order to find
        # this attachment, we should in theory sort by
        # BugAttachment.message.datecreated. Since we don't have
        # an index for Message.datecreated, such a query would be
        # quite slow. We search instead for the BugAttachment with
        # the largest ID for a given bug. This is "nearly" equivalent
        # to searching the record with the maximum value of
        # message.datecreated: The only exception is the rare case when
        # two BugAttachment records are simultaneuosly added to the same
        # bug, where bug_attachment_1.id < bug_attachment_2.id, while
        # the Message record for bug_attachment_2 is created before
        # the Message record for bug_attachment_1. The difference of
        # the datecreated values of the Message records is in this case
        # probably smaller than one second and the selection of the
        # "most recent" patch anyway somewhat arbitrary.
        return (
            Store.of(self)
            .find(
                BugAttachment,
                BugAttachment.id
                == Select(
                    Max(BugAttachment.id),
                    And(
                        BugAttachment.bug == self.id,
                        BugAttachment.type == BugAttachmentType.PATCH,
                    ),
                ),
            )
            .one()
        )

    @property
    def comment_count(self):
        """See `IBug`."""
        return self.message_count - 1

    @property
    def users_affected(self):
        """See `IBug`."""
        return Store.of(self).find(
            Person,
            BugAffectsPerson.person == Person.id,
            BugAffectsPerson.affected,
            BugAffectsPerson.bug == self,
        )

    @property
    def users_unaffected(self):
        """See `IBug`."""
        return Store.of(self).find(
            Person,
            BugAffectsPerson.person == Person.id,
            Not(BugAffectsPerson.affected),
            BugAffectsPerson.bug == self,
        )

    @property
    def user_ids_affected_with_dupes(self):
        """Return all IDs of Persons affected by this bug and its dupes.
        The return value is a Storm expression.  Running a query with
        this expression returns a result that may contain the same ID
        multiple times, for example if that person is affected via
        more than one duplicate."""
        return Union(
            Select(
                Person.id,
                And(
                    BugAffectsPerson.person == Person.id,
                    BugAffectsPerson.affected,
                    BugAffectsPerson.bug == self,
                ),
            ),
            Select(
                Person.id,
                And(
                    BugAffectsPerson.person == Person.id,
                    BugAffectsPerson.bug == Bug.id,
                    BugAffectsPerson.affected,
                    Bug.duplicateof == self.id,
                ),
            ),
        )

    @property
    def users_affected_with_dupes(self):
        """See `IBug`."""
        return Store.of(self).find(
            Person, Person.id.is_in(self.user_ids_affected_with_dupes)
        )

    @property
    def users_affected_count_with_dupes(self):
        """See `IBug`."""
        return self.users_affected_with_dupes.count()

    @property
    def other_users_affected_count_with_dupes(self):
        """See `IBug`."""
        current_user = getUtility(ILaunchBag).user
        if not current_user:
            return self.users_affected_count_with_dupes
        return self.users_affected_with_dupes.find(
            Person.id != current_user.id
        ).count()

    @property
    def indexed_messages(self):
        """See `IMessageTarget`."""
        # Note that this is a decorated result set, so will cache its
        # value (in the absence of slices)
        return self._indexed_messages(include_content=True)

    def _indexed_messages(self, include_content=False, include_parents=True):
        """Get the bugs messages, indexed.

        :param include_content: If True retrieve the content for the messages
            too.
        :param include_parents: If True retrieve the object for parent
            messages too. If False the parent attribute will be *forced* to
            None to reduce database lookups.
        """
        # Make all messages be 'in' the main bugtask.
        inside = self.default_bugtask
        store = Store.of(self)
        message_by_id = {}
        to_messages = lambda rows: [row[0] for row in rows]

        def eager_load_owners(messages):
            # Because we may have multiple owners, we spend less time
            # in storm with very large bugs by not joining and instead
            # querying a second time. If this starts to show high db
            # time, we can left outer join instead.
            owner_ids = {message.owner_id for message in messages}
            owner_ids.discard(None)
            if not owner_ids:
                return
            list(store.find(Person, Person.id.is_in(owner_ids)))

        def eager_load_content(messages):
            # To avoid the complexity of having multiple rows per
            # message, or joining in the database (though perhaps in
            # future we should do that), we do a single separate query
            # for the message content.
            message_ids = {message.id for message in messages}
            chunks = store.find(
                MessageChunk, MessageChunk.message_id.is_in(message_ids)
            )
            chunks.order_by(MessageChunk.id)
            chunk_map = {}
            for chunk in chunks:
                message_chunks = chunk_map.setdefault(chunk.message_id, [])
                message_chunks.append(chunk)
            for message in messages:
                if message.id not in chunk_map:
                    continue
                cache = get_property_cache(message)
                cache.text_contents = Message.chunks_text(
                    chunk_map[message.id]
                )

        def eager_load(rows):
            messages = to_messages(rows)
            eager_load_owners(messages)
            if include_content:
                eager_load_content(messages)

        def index_message(row):
            # convert row to an IndexedMessage
            if include_parents:
                message, parent, bugmessage = row
                if parent is not None:
                    # If there is an IndexedMessage available as parent, use
                    # that to reduce on-demand parent lookups.
                    parent = message_by_id.get(parent.id, parent)
            else:
                message, bugmessage = row
                parent = None  # parent attribute is not going to be accessed.
            index = bugmessage.index
            result = IndexedMessage(message, inside, index, parent)
            if include_parents:
                # This message may be the parent for another: stash it to
                # permit use.
                message_by_id[message.id] = result
            return result

        if include_parents:
            ParentMessage = ClassAlias(Message)
            ParentBugMessage = ClassAlias(BugMessage)
            tables = [
                Message,
                Join(BugMessage, BugMessage.message_id == Message.id),
                LeftJoin(
                    Join(
                        ParentMessage,
                        ParentBugMessage,
                        ParentMessage.id == ParentBugMessage.message_id,
                    ),
                    And(
                        Message.parent == ParentMessage.id,
                        ParentBugMessage.bug_id == self.id,
                    ),
                ),
            ]
            results = store.using(*tables).find(
                (Message, ParentMessage, BugMessage),
                BugMessage.bug_id == self.id,
            )
        else:
            lookup = Message, BugMessage
            results = store.find(
                lookup,
                BugMessage.bug_id == self.id,
                BugMessage.message_id == Message.id,
            )
        results.order_by(BugMessage.index)
        return DecoratedResultSet(
            results, index_message, pre_iter_hook=eager_load
        )

    @property
    def displayname(self):
        """See `IBug`."""
        dn = "Bug #%d" % self.id
        if self.name:
            dn += " (" + self.name + ")"
        return dn

    @cachedproperty
    def bugtasks(self):
        """See `IBug`."""
        # \o/ circular imports.
        from lp.registry.model.distribution import Distribution
        from lp.registry.model.distroseries import DistroSeries
        from lp.registry.model.product import Product
        from lp.registry.model.productseries import ProductSeries
        from lp.registry.model.sourcepackagename import SourcePackageName

        store = Store.of(self)
        tasks = list(store.find(BugTask, BugTask.bug_id == self.id))
        # The bugtasks attribute is iterated in the API and web
        # services, so it needs to preload all related data otherwise
        # late evaluation is triggered in both places. Separately,
        # bugtask_sort_key requires the related products, series,
        # distros, distroseries and source package names to be loaded.
        ids = set(map(operator.attrgetter("assignee_id"), tasks))
        ids.update(map(operator.attrgetter("owner_id"), tasks))
        ids.discard(None)
        if ids:
            list(
                getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                    ids, need_validity=True
                )
            )

        def load_something(attrname, klass):
            ids = set(map(operator.attrgetter(attrname), tasks))
            ids.discard(None)
            if not ids:
                return
            list(store.find(klass, klass.id.is_in(ids)))

        load_something("product_id", Product)
        load_something("productseries_id", ProductSeries)
        load_something("distribution_id", Distribution)
        load_something("distroseries_id", DistroSeries)
        load_something("sourcepackagename_id", SourcePackageName)
        list(store.find(BugWatch, BugWatch.bug == self))
        return sorted(tasks, key=bugtask_sort_key)

    @property
    def presences(self):
        """See `IBug`."""
        return Store.of(self).find(BugPresence, BugPresence.bug_id == self.id)

    @property
    def default_bugtask(self):
        """See `IBug`."""
        from lp.registry.model.product import Product

        return (
            Store.of(self)
            .using(
                BugTask, LeftJoin(Product, Product.id == BugTask.product_id)
            )
            .find(BugTask, bug=self)
            .order_by(Desc(Coalesce(Product.active, True)), BugTask.id)
            .first()
        )

    @property
    def is_complete(self):
        """See `IBug`."""
        for task in self.bugtasks:
            if not task.is_complete:
                return False
        return True

    @property
    def affected_pillars(self):
        """See `IBug`."""
        result = set()
        for task in self.bugtasks:
            result.add(task.pillar)
        return sorted(result, key=pillar_sort_key)

    @property
    def permits_expiration(self):
        """See `IBug`.

        This property checks the general state of the bug to determine if
        expiration is permitted *if* a bugtask were to qualify for expiration.
        This property does not check the bugtask preconditions to identify
        a specific bugtask that can expire.

        :See: `IBug.can_expire` or `BugTaskSet.findExpirableBugTasks` to
            check or get a list of bugs that can expire.
        """
        # Bugs cannot be expired if any bugtask is valid.
        expirable_status_list = [
            BugTaskStatus.INCOMPLETE,
            BugTaskStatus.INVALID,
            BugTaskStatus.WONTFIX,
            BugTaskStatus.DOESNOTEXIST,
        ]
        has_an_expirable_bugtask = False
        for bugtask in self.bugtasks:
            if bugtask.status not in expirable_status_list:
                # We found an unexpirable bugtask; the bug cannot expire.
                return False
            if (
                bugtask.status == BugTaskStatus.INCOMPLETE
                and bugtask.pillar.enable_bug_expiration
            ):
                # This bugtasks meets the basic conditions to expire.
                has_an_expirable_bugtask = True

        return has_an_expirable_bugtask

    @property
    def can_expire(self):
        """See `IBug`.

        Only Incomplete bug reports that affect a single pillar with
        enabled_bug_expiration set to True can be expired. To qualify for
        expiration, the bug and its bugtasks meet the follow conditions:

        1. The bug is inactive; the last update of the bug is older than
            Launchpad expiration age.
        2. The bug is not a duplicate.
        3. The bug has at least one message (a request for more information).
        4. The bug does not have any other valid bugtasks.
        5. The bugtask belongs to a project with enable_bug_expiration set
           to True.
        6. The bugtask has the status Incomplete.
        7. The bugtask is not assigned to anyone.
        8. The bugtask does not have a milestone.
        """
        # IBugTaskSet.findExpirableBugTasks() is the authoritative determiner
        # if a bug can expire, but it is expensive. We do a general check
        # to verify the bug permits expiration before using IBugTaskSet to
        # determine if a bugtask can cause expiration.
        if not self.permits_expiration:
            return False

        days_old = config.malone.days_before_expiration
        # Do the search as the Janitor, to ensure that this bug can be
        # found, even if it's private. We don't have access to the user
        # calling this property. If the user has access to view this
        # property, they have permission to see the bug, so we're not
        # exposing something we shouldn't. The Janitor has access to
        # view all bugs.
        bugtasks = getUtility(IBugTaskSet).findExpirableBugTasks(
            days_old, getUtility(ILaunchpadCelebrities).janitor, bug=self
        )
        return not bugtasks.is_empty()

    def isExpirable(self, days_old=None):
        """See `IBug`."""

        # If days_old is None read it from the Launchpad configuration
        # and use that value
        if days_old is None:
            days_old = config.malone.days_before_expiration

        # IBugTaskSet.findExpirableBugTasks() is the authoritative determiner
        # if a bug can expire, but it is expensive. We do a general check
        # to verify the bug permits expiration before using IBugTaskSet to
        # determine if a bugtask can cause expiration.
        if not self.permits_expiration:
            return False

        # Do the search as the Janitor, to ensure that this bug can be
        # found, even if it's private. We don't have access to the user
        # calling this property. If the user has access to view this
        # property, they have permission to see the bug, so we're not
        # exposing something we shouldn't. The Janitor has access to
        # view all bugs.
        bugtasks = getUtility(IBugTaskSet).findExpirableBugTasks(
            days_old, getUtility(ILaunchpadCelebrities).janitor, bug=self
        )
        return not bugtasks.is_empty()

    @cachedproperty
    def initial_message(self):
        """See `IBug`."""
        return (
            Store.of(self)
            .find(
                Message,
                BugMessage.bug == self,
                BugMessage.message == Message.id,
            )
            .order_by("id")
            .first()
        )

    @cachedproperty
    def official_tags(self):
        """See `IBug`."""
        # Da circle of imports forces the locals.
        from lp.registry.model.distribution import Distribution
        from lp.registry.model.product import Product

        table = OfficialBugTag
        table = LeftJoin(
            table,
            Distribution,
            OfficialBugTag.distribution_id == Distribution.id,
        )
        table = LeftJoin(
            table, Product, OfficialBugTag.product_id == Product.id
        )
        # When this method is typically called it already has the necessary
        # info in memory, so rather than rejoin with Product etc, we do this
        # bit in Python. If reviewing performance here feel free to change.
        clauses = []
        for task in self.bugtasks:
            clauses.append(
                # Storm cannot compile proxied objects.
                removeSecurityProxy(task.target._getOfficialTagClause())
            )
        clause = Or(*clauses)
        return list(
            Store.of(self)
            .using(table)
            .find(OfficialBugTag.tag, clause)
            .order_by(OfficialBugTag.tag)
            .config(distinct=True)
        )

    def followup_subject(self):
        """See `IBug`."""
        return "Re: " + self.title

    @property
    def has_patches(self):
        """See `IBug`."""
        return self.latest_patch_uploaded is not None

    def subscribe(
        self, person, subscribed_by, suppress_notify=True, level=None
    ):
        """See `IBug`."""
        if person.is_team and self.private and person.anyone_can_join():
            error_msg = (
                "Open and delegated teams cannot be subscribed "
                "to private bugs."
            )
            raise SubscriptionPrivacyViolation(error_msg)
        # first look for an existing subscription
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                if level is not None:
                    sub.bug_notification_level = level
                    # Should subscribed_by be changed in this case?  Until
                    # proven otherwise, we will answer with "no."
                return sub

        if level is None:
            level = BugNotificationLevel.COMMENTS

        sub = BugSubscription(
            bug=self,
            person=person,
            subscribed_by=subscribed_by,
            bug_notification_level=level,
        )

        # Ensure that the subscription has been flushed.
        Store.of(sub).flush()

        # Grant the subscriber access if they can't see the bug but only if
        # there is at least one bugtask for which access can be checked.
        if self.default_bugtask:
            service = getUtility(IService, "sharing")
            bugs = service.getVisibleArtifacts(
                person, bugs=[self], ignore_permissions=True
            )["bugs"]
            if not bugs:
                service.ensureAccessGrants(
                    [person],
                    subscribed_by,
                    bugs=[self],
                    ignore_permissions=True,
                )

        # In some cases, a subscription should be created without
        # email notifications.  suppress_notify determines if
        # notifications are sent.
        if suppress_notify is False:
            notify(ObjectCreatedEvent(sub, user=subscribed_by))

        update_bug_heat([self.id])
        return sub

    def unsubscribe(self, person, unsubscribed_by, **kwargs):
        """See `IBug`."""
        # Drop cached subscription info.
        clear_property_cache(self)
        # Ensure the unsubscriber is in the _known_viewer cache for the bug so
        # that the permissions are such that the operation can succeed.
        get_property_cache(self)._known_viewers = {unsubscribed_by.id}
        if person is None:
            person = unsubscribed_by

        ignore_permissions = kwargs.get("ignore_permissions", False)
        recipients = kwargs.get("recipients")
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                if not ignore_permissions and not sub.canBeUnsubscribedByUser(
                    unsubscribed_by
                ):
                    raise UserCannotUnsubscribePerson(
                        "%s does not have permission to unsubscribe %s."
                        % (unsubscribed_by.displayname, person.displayname)
                    )

                self.addChange(
                    UnsubscribedFromBug(
                        when=UTC_NOW,
                        person=unsubscribed_by,
                        unsubscribed_user=person,
                        **kwargs,
                    ),
                    recipients=recipients,
                )
                store = Store.of(sub)
                store.remove(sub)
                # Make sure that the subscription removal has been
                # flushed so that code running with implicit flushes
                # disabled see the change.
                store.flush()
                update_bug_heat([self.id])
                del get_property_cache(self)._known_viewers

                # Revoke access to bug
                artifacts_to_delete = getUtility(IAccessArtifactSource).find(
                    [self]
                )
                getUtility(IAccessArtifactGrantSource).revokeByArtifact(
                    artifacts_to_delete, [person]
                )
                return

    def unsubscribeFromDupes(self, person, unsubscribed_by):
        """See `IBug`."""
        if person is None:
            person = unsubscribed_by

        bugs_unsubscribed = []
        for dupe in self.duplicates:
            if dupe.isSubscribed(person):
                dupe.unsubscribe(person, unsubscribed_by)
                bugs_unsubscribed.append(dupe)

        return bugs_unsubscribed

    def isSubscribed(self, person):
        """See `IBug`."""
        return self.personIsDirectSubscriber(person)

    def isSubscribedToDupes(self, person):
        """See `IBug`."""
        return self.personIsSubscribedToDuplicate(person)

    def _getMutes(self, person):
        return Store.of(self).find(
            BugMute, BugMute.bug == self, BugMute.person == person
        )

    def isMuted(self, person):
        """See `IBug`."""
        return not self._getMutes(person).is_empty()

    def mute(self, person, muted_by):
        """See `IBug`."""
        if person is None:
            # This may be a webservice request.
            person = muted_by
        assert (
            not person.is_team
        ), "Muting a subscription for entire team is not allowed."

        # If it's already muted, ignore the request.
        mutes = self._getMutes(person)
        if mutes.is_empty():
            mute = BugMute(person, self)
            Store.of(mute).flush()

    def unmute(self, person, unmuted_by):
        """See `IBug`."""
        if person is None:
            # This may be a webservice request.
            person = unmuted_by
        mutes = self._getMutes(person)
        if not mutes.is_empty():
            Store.of(self).remove(mutes.one())
        return self.getSubscriptionForPerson(person)

    @property
    def subscriptions(self):
        """The set of `BugSubscriptions` for this bug."""
        # XXX: kiko 2006-09-23: Why is subscriptions ordered by ID?
        results = (
            Store.of(self)
            .find(
                (Person, BugSubscription),
                BugSubscription.person_id == Person.id,
                BugSubscription.bug_id == self.id,
            )
            .order_by(BugSubscription.id)
        )
        return DecoratedResultSet(results, operator.itemgetter(1))

    def getSubscriptionInfo(self, level=None):
        """See `IBug`."""
        if level is None:
            level = BugNotificationLevel.LIFECYCLE
        return BugSubscriptionInfo(self, level)

    def getDirectSubscriptions(self):
        """See `IBug`."""
        return self.getSubscriptionInfo().direct_subscriptions

    def getDirectSubscribers(
        self, recipients=None, level=None, filter_visible=False
    ):
        """See `IBug`.

        The recipients argument is private and not exposed in the
        interface. If a BugNotificationRecipients instance is supplied,
        the relevant subscribers and rationales will be registered on
        it.
        """
        if level is None:
            level = BugNotificationLevel.LIFECYCLE
        direct_subscribers = self.getSubscriptionInfo(level).direct_subscribers
        if filter_visible:
            filtered_subscribers = IStore(Person).find(
                Person,
                Person.id.is_in([s.id for s in direct_subscribers]),
                self.getSubscriptionInfo().visible_recipients_filter(
                    Person.id
                ),
            )
            direct_subscribers = BugSubscriberSet(
                direct_subscribers.intersection(filtered_subscribers)
            )
        if recipients is not None:
            for subscriber in direct_subscribers:
                recipients.addDirectSubscriber(subscriber)
        return direct_subscribers.sorted

    def getDirectSubscribersWithDetails(self):
        """See `IBug`."""
        SubscribedBy = ClassAlias(Person, name="subscribed_by")
        results = (
            Store.of(self)
            .find(
                (Person, SubscribedBy, BugSubscription),
                BugSubscription.person_id == Person.id,
                BugSubscription.bug_id == self.id,
                BugSubscription.subscribed_by_id == SubscribedBy.id,
                Not(
                    In(
                        BugSubscription.person_id,
                        Select(BugMute.person_id, BugMute.bug_id == self.id),
                    )
                ),
            )
            .order_by(Person.display_name)
        )
        return results

    def getIndirectSubscribers(self, recipients=None, level=None):
        """See `IBug`.

        See the comment in getDirectSubscribers for a description of the
        recipients argument.
        """
        # "Also notified" and duplicate subscribers are mutually
        # exclusive, so return both lists.
        indirect_subscribers = chain(
            self.getAlsoNotifiedSubscribers(recipients, level),
            self.getSubscribersFromDuplicates(recipients, level),
        )

        # Remove security proxy for the sort key, but return
        # the regular proxied object.
        return sorted(
            indirect_subscribers,
            # XXX: GavinPanella 2011-12-12 bug=911752: Use person_sort_key.
            key=lambda x: removeSecurityProxy(x).displayname,
        )

    def getSubscriptionsFromDuplicates(self, recipients=None):
        """See `IBug`."""
        if self.private:
            return []
        # For each subscription to each duplicate of this bug, find the
        # earliest subscription for each subscriber. Eager load the
        # subscribers.
        return DecoratedResultSet(
            IStore(BugSubscription)
            .find(
                (Person, BugSubscription),
                Bug.duplicateof == self,
                BugSubscription.bug_id == Bug.id,
                BugSubscription.person_id == Person.id,
            )
            .order_by(
                BugSubscription.person_id,
                BugSubscription.date_created,
                BugSubscription.id,
            )
            .config(distinct=(BugSubscription.person_id,)),
            operator.itemgetter(1),
        )

    def getSubscribersFromDuplicates(self, recipients=None, level=None):
        """See `IBug`.

        See the comment in getDirectSubscribers for a description of the
        recipients argument.
        """
        if level is None:
            level = BugNotificationLevel.LIFECYCLE
        info = self.getSubscriptionInfo(level)
        if recipients is not None:
            list(self.duplicates)  # Pre-load duplicate bugs.
            info.duplicate_only_subscribers  # Pre-load subscribers.
            for subscription in info.duplicate_only_subscriptions:
                recipients.addDupeSubscriber(
                    subscription.person, subscription.bug
                )
        return info.duplicate_only_subscribers.sorted

    def getSubscribersForPerson(self, person):
        """See `IBug."""

        assert person is not None

        def cache_unsubscribed(rows):
            if not rows:
                self._unsubscribed_cache.add(person)

        def cache_subscriber(row):
            subscriber, subscription = row
            if subscription.bug_id == self.id:
                self._subscriber_cache.add(subscriber)
            else:
                self._subscriber_dups_cache.add(subscriber)
            return subscriber

        with_statement = generate_subscription_with(self, person)
        store = Store.of(self).with_(with_statement)
        return DecoratedResultSet(
            store.find(
                # Return people and subscriptions
                (Person, BugSubscription),
                BugSubscription.id.is_in(
                    SQL("SELECT bugsubscriptions.id FROM bugsubscriptions")
                ),
                Person.id == BugSubscription.person_id,
            )
            .order_by(Person.name)
            .config(distinct=(Person.name, BugSubscription.person_id)),
            cache_subscriber,
            pre_iter_hook=cache_unsubscribed,
        )

    def getSubscriptionForPerson(self, person):
        """See `IBug`."""
        return (
            Store.of(self)
            .find(
                BugSubscription,
                BugSubscription.person == person,
                BugSubscription.bug == self,
            )
            .one()
        )

    def getAlsoNotifiedSubscribers(self, recipients=None, level=None):
        """See `IBug`.

        See the comment in getDirectSubscribers for a description of the
        recipients argument.
        """
        return get_also_notified_subscribers(self, recipients, level)

    def _getBugNotificationRecipients(self, level):
        """Get the recipients for the BugNotificationLevel."""
        recipients = BugNotificationRecipients()
        self.getDirectSubscribers(recipients, level=level, filter_visible=True)
        self.getIndirectSubscribers(recipients, level=level)
        return recipients

    @cachedproperty
    def _notification_recipients_for_lifecycle(self):
        """The cached BugNotificationRecipients for LIFECYCLE events."""
        return self._getBugNotificationRecipients(
            BugNotificationLevel.LIFECYCLE
        )

    @cachedproperty
    def _notification_recipients_for_metadata(self):
        """The cached BugNotificationRecipients for METADATA events."""
        return self._getBugNotificationRecipients(
            BugNotificationLevel.METADATA
        )

    @cachedproperty
    def _notification_recipients_for_comments(self):
        """The cached BugNotificationRecipients for COMMENT events."""
        return self._getBugNotificationRecipients(
            BugNotificationLevel.COMMENTS
        )

    def getBugNotificationRecipients(
        self, level=BugNotificationLevel.LIFECYCLE
    ):
        """See `IBug`."""
        recipients = BugNotificationRecipients()
        if level == BugNotificationLevel.LIFECYCLE:
            recipients.update(self._notification_recipients_for_lifecycle)
        elif level == BugNotificationLevel.METADATA:
            recipients.update(self._notification_recipients_for_metadata)
        else:
            recipients.update(self._notification_recipients_for_comments)
        return recipients

    def clearBugNotificationRecipientsCache(self):
        cache = get_property_cache(self)
        if getattr(cache, "_notification_recipients_for_lifecycle", False):
            del cache._notification_recipients_for_lifecycle
        if getattr(cache, "_notification_recipients_for_metadata", False):
            del cache._notification_recipients_for_metadata
        if getattr(cache, "_notification_recipients_for_comments", False):
            del cache._notification_recipients_for_comments

    def addCommentNotification(
        self,
        message,
        recipients=None,
        activity=None,
        level=BugNotificationLevel.COMMENTS,
    ):
        """See `IBug`."""
        if recipients is None:
            recipients = self.getBugNotificationRecipients(level=level)
        getUtility(IBugNotificationSet).addNotification(
            bug=self,
            is_comment=True,
            message=message,
            recipients=recipients,
            activity=activity,
        )

    def addChange(
        self, change, recipients=None, deferred=False, update_heat=True
    ):
        """See `IBug`."""
        when = change.when
        if when is None:
            when = UTC_NOW

        activity_data = change.getBugActivity()
        if activity_data is not None:
            activity = getUtility(IBugActivitySet).new(
                self,
                when,
                change.person,
                activity_data["whatchanged"],
                activity_data.get("oldvalue"),
                activity_data.get("newvalue"),
                activity_data.get("message"),
            )
        else:
            activity = None

        notification_data = change.getBugNotification()
        if notification_data is not None:
            assert (
                notification_data.get("text") is not None
            ), "notification_data must include a `text` value."
            message = MessageSet().fromText(
                self.followup_subject(),
                notification_data["text"],
                owner=change.person,
                datecreated=when,
            )
            if recipients is None:
                recipients = self.getBugNotificationRecipients(
                    level=change.change_level
                )
            getUtility(IBugNotificationSet).addNotification(
                bug=self,
                is_comment=False,
                message=message,
                recipients=recipients,
                activity=activity,
                deferred=deferred,
            )

        if update_heat:
            update_bug_heat([self.id])

    def expireNotifications(self):
        """See `IBug`."""
        store = IStore(BugNotification)
        notifications = store.find(
            BugNotification, bug=self, date_emailed=None
        )
        notifications.set(date_emailed=UTC_NOW)
        store.flush()

    def newMessage(
        self,
        owner=None,
        subject=None,
        content=None,
        parent=None,
        bugwatch=None,
        remote_comment_id=None,
        send_notifications=True,
    ):
        # Admins, commercial admins, registry experts, pillar owners,
        # pillar drivers, and pillar bug supervisors should be able
        # to disable email notifications
        if not send_notifications:
            authz = getAdapter(self, IAuthorization, "launchpad.Moderate")
            if not authz.checkAuthenticated(IPersonRoles(owner)):
                raise CannotDisableNotifications(
                    "Email notifications can only "
                    "be disabled by admins, commercial admins, "
                    "registry experts, or bug supervisors."
                )
        return self.newMessage_internal(
            owner=owner,
            subject=subject,
            content=content,
            parent=parent,
            bugwatch=bugwatch,
            remote_comment_id=remote_comment_id,
            send_notifications=send_notifications,
        )

    def newMessage_internal(
        self,
        owner=None,
        subject=None,
        content=None,
        parent=None,
        bugwatch=None,
        remote_comment_id=None,
        send_notifications=True,
    ):
        """Create a new Message and link it to this bug."""
        if subject is None:
            subject = self.followup_subject()
        msg = Message(
            parent=parent,
            owner=owner,
            subject=subject,
            rfc822msgid=make_msgid("malone"),
        )
        MessageChunk(message=msg, content=content, sequence=1)

        bugmsg = self.linkMessage(
            msg, bugwatch, remote_comment_id=remote_comment_id
        )
        if not bugmsg:
            return

        if send_notifications:
            notify(ObjectCreatedEvent(bugmsg, user=owner))

        return bugmsg.message

    def linkMessage(
        self, message, bugwatch=None, user=None, remote_comment_id=None
    ):
        """See `IBug`."""
        if IStore(self).find(BugMessage, bug=self, message=message).is_empty():
            if user is None:
                user = message.owner
            result = BugMessage(
                bug=self,
                message=message,
                bugwatch=bugwatch,
                remote_comment_id=remote_comment_id,
                index=self.bug_messages.count(),
            )
            getUtility(IBugWatchSet).fromText(
                message.text_contents, self, user
            )
            self.findCvesInText(message.text_contents, user)
            for bugtask in self.bugtasks:
                # Check the stored value so we don't write to unaltered tasks.
                if bugtask._status in (
                    BugTaskStatus.INCOMPLETE,
                    BugTaskStatusSearch.INCOMPLETE_WITHOUT_RESPONSE,
                ):
                    # This is not a semantic change, so we don't update date
                    # records or send email.
                    bugtask._status = (
                        BugTaskStatusSearch.INCOMPLETE_WITH_RESPONSE
                    )
            # XXX 2008-05-27 jamesh:
            # Ensure that BugMessages get flushed in same order as
            # they are created.
            Store.of(result).flush()
            return result

    def addTask(self, owner, target, validate_target=True):
        """See `IBug`."""
        return getUtility(IBugTaskSet).createTask(
            self, owner, target, validate_target
        )

    def addWatch(self, bugtracker, remotebug, owner):
        """See `IBug`."""
        # We shouldn't add duplicate bug watches.
        bug_watch = self.getBugWatch(bugtracker, remotebug)
        if bug_watch is None:
            bug_watch = BugWatch(
                bug=self,
                bugtracker=bugtracker,
                remotebug=remotebug,
                owner=owner,
            )
            Store.of(bug_watch).flush()
        self.addChange(BugWatchAdded(UTC_NOW, owner, bug_watch))
        notify(ObjectCreatedEvent(bug_watch, user=owner))
        return bug_watch

    def removeWatch(self, bug_watch, user):
        """See `IBug`."""
        self.addChange(BugWatchRemoved(UTC_NOW, user, bug_watch))
        bug_watch.destroySelf()

    def removeAttachment(self, bug_attachment, user):
        """See `IBug`."""
        self.addChange(
            BugAttachmentChange(
                UTC_NOW,
                user,
                "attachment",
                bug_attachment,
                None,
            )
        )
        bug_attachment.destroySelf()

    def addAttachment(
        self,
        owner,
        data,
        comment,
        filename,
        url,
        is_patch=False,
        content_type=None,
        description=None,
        from_api=False,
        vulnerability_patches: List[dict] = None,
    ):
        """See `IBug`."""
        # XXX: StevenK 2013-02-06 bug=1116954: We should not need to refetch
        # the file content from the request, since the passed in one has been
        # wrongly encoded.
        if from_api:
            data = get_raw_form_value_from_current_request(data, "data")

        if data:
            if isinstance(data, bytes):
                filecontent = data
            else:
                filecontent = data.read()

            if is_patch:
                content_type = "text/plain"
            else:
                if content_type is None:
                    content_type, encoding = guess_content_type(
                        name=filename, body=filecontent
                    )

            file_alias = getUtility(ILibraryFileAliasSet).create(
                name=filename,
                size=len(filecontent),
                file=BytesIO(filecontent),
                contentType=content_type,
                restricted=self.private,
            )
        else:
            file_alias = None

        return self.linkAttachment(
            owner=owner,
            file_alias=file_alias,
            url=url,
            comment=comment,
            is_patch=is_patch,
            description=description,
            vulnerability_patches=vulnerability_patches,
        )

    def linkAttachment(
        self,
        owner,
        file_alias,
        url,
        comment,
        is_patch=False,
        description=None,
        send_notifications=True,
        vulnerability_patches: List[dict] = None,
    ):
        """See `IBug`.

        This method should only be called by addAttachment() and
        FileBugViewBase.submit_bug_action, otherwise
        we may get inconsistent settings of bug.private and
        file_alias.restricted.

        :param send_notifications: Control sending of notifications for this
            attachment. This is disabled when adding attachments from 'extra
            data' in the filebug form, because that triggered hundreds of DB
            inserts and thus timeouts. Defaults to sending notifications.
        """
        if is_patch:
            attach_type = BugAttachmentType.PATCH
        else:
            attach_type = BugAttachmentType.UNSPECIFIED

        if IMessage.providedBy(comment):
            message = comment
        else:
            message = self.newMessage(
                owner=owner, subject=description, content=comment
            )

        return getUtility(IBugAttachmentSet).create(
            bug=self,
            filealias=file_alias,
            url=url,
            attach_type=attach_type,
            title=description,
            message=message,
            send_notifications=send_notifications,
            vulnerability_patches=vulnerability_patches,
        )

    def addPresence(
        self,
        product,
        distribution,
        source_package_name,
        git_repository,
        break_fix_data,
        user,
    ):
        """See `IBug`."""

        # TODO: we are not doing any validation here. See `IBug`.
        bug_presence = getUtility(IBugPresenceSet).create(
            bug=self,
            product=product,
            distribution=distribution,
            source_package_name=source_package_name,
            git_repository=git_repository,
            break_fix_data=break_fix_data,
        )
        self.addChange(BugPresenceAdded(UTC_NOW, user, bug_presence))
        return bug_presence

    def removePresence(self, bug_presence, user):
        """See `IBug`."""
        self.addChange(BugPresenceRemoved(UTC_NOW, user, bug_presence))
        bug_presence.destroySelf()

    def linkBranch(self, branch, registrant):
        """See `IBug`."""
        if branch in self.linked_branches:
            return

        BugBranch(branch=branch, bug=self, registrant=registrant)
        branch.date_last_modified = UTC_NOW

        self.addChange(BranchLinkedToBug(UTC_NOW, registrant, branch, self))
        notify(ObjectLinkedEvent(branch, self, user=registrant))
        notify(ObjectLinkedEvent(self, branch, user=registrant))

    def unlinkBranch(self, branch, user):
        """See `IBug`."""
        bug_branch = (
            Store.of(self)
            .find(BugBranch, BugBranch.bug == self, BugBranch.branch == branch)
            .one()
        )
        if bug_branch is not None:
            self.addChange(BranchUnlinkedFromBug(UTC_NOW, user, branch, self))
            notify(ObjectUnlinkedEvent(branch, self, user=user))
            notify(ObjectUnlinkedEvent(self, branch, user=user))
            Store.of(bug_branch).remove(bug_branch)

    def getVisibleLinkedBranches(self, user, eager_load=False):
        """See `IBug`."""
        linked_branches = list(
            getUtility(IAllBranches)
            .visibleByUser(user)
            .linkedToBugs([self])
            .getBranches(eager_load=eager_load)
        )
        if len(linked_branches) == 0:
            return EmptyResultSet()
        else:
            branch_ids = [branch.id for branch in linked_branches]
            results = Store.of(self).find(
                BugBranch,
                BugBranch.bug == self,
                In(BugBranch.branch_id, branch_ids),
            )
            return results.order_by(BugBranch.id)

    def linkMergeProposal(self, merge_proposal, user, check_permissions=True):
        """See `IBug`."""
        merge_proposal.linkBug(
            self, user=user, check_permissions=check_permissions
        )

    def unlinkMergeProposal(
        self, merge_proposal, user, check_permissions=True
    ):
        """See `IBug`."""
        merge_proposal.unlinkBug(
            self, user=user, check_permissions=check_permissions
        )

    @property
    def linked_merge_proposals(self):
        from lp.code.model.branchmergeproposal import BranchMergeProposal

        merge_proposal_ids = [
            int(id)
            for _, id in getUtility(IXRefSet).findFrom(
                ("bug", str(self.id)), types=["merge_proposal"]
            )
        ]
        return list(
            sorted(
                bulk.load(BranchMergeProposal, merge_proposal_ids),
                key=operator.attrgetter("id"),
            )
        )

    def getVisibleLinkedMergeProposals(self, user, eager_load=False):
        """See `IBug`."""
        linked_merge_proposal_ids = {
            bmp.id for bmp in self.linked_merge_proposals
        }
        if not linked_merge_proposal_ids:
            return EmptyResultSet()
        else:
            # XXX cjwatson 2016-06-24: This will also need to look at
            # IAllBranches in the event that we start linking bugs directly
            # to Bazaar-based merge proposals rather than to their source
            # branches.
            collection = getUtility(IAllGitRepositories).visibleByUser(user)
            return collection.getMergeProposals(
                merge_proposal_ids=linked_merge_proposal_ids,
                eager_load=eager_load,
            )

    @cachedproperty
    def has_cves(self):
        """See `IBug`."""
        return bool(self.cves)

    def linkCVE(self, cve, user, check_permissions=True):
        """See `IBug`."""
        cve.linkBug(self, user=user, check_permissions=check_permissions)

    def unlinkCVE(self, cve, user, check_permissions=True):
        """See `IBug`."""
        cve.unlinkBug(self, user=user, check_permissions=check_permissions)

    def findCvesInText(self, text, user):
        """See `IBug`."""
        cves = getUtility(ICveSet).inText(text)
        for cve in cves:
            self.linkCVE(cve, user, check_permissions=False)

    # Several other classes need to generate lists of bugs, and
    # one thing they often have to filter for is completeness. We maintain
    # this single canonical query string here so that it does not have to be
    # cargo culted into Product, Distribution, ProductSeries etc
    completeness_clause = (
        """
        BugTask.bug = Bug.id AND """
        + BugTask.completeness_clause
    )

    def canBeAQuestion(self):
        """See `IBug`."""
        return (
            self._getQuestionTargetableBugTask() is not None
            and self.getQuestionCreatedFromBug() is None
        )

    def _getQuestionTargetableBugTask(self):
        """Return the only bugtask that can be a QuestionTarget, or None.

        Bugs that are also in external bug trackers cannot be converted
        to questions. This is also true for bugs that are being developed.
        None is returned when either of these conditions are true.

        The bugtask is selected by these rules:
        1. It's status is not Invalid or Does Not Exist.
        2. It is not a conjoined replica.
        Only one bugtask must meet both conditions to be return. When
        zero or many bugtasks match, None is returned.
        """
        # We may want to removed the bugtask.conjoined_primary check
        # below. It is used to simplify the task of converting
        # conjoined bugtasks to question--since replicas cannot be
        # directly updated anyway.
        non_invalid_bugtasks = [
            bugtask
            for bugtask in self.bugtasks
            if (
                bugtask.status != BugTaskStatus.INVALID
                and bugtask.status != BugTaskStatus.DOESNOTEXIST
                and bugtask.conjoined_primary is None
            )
        ]
        if len(non_invalid_bugtasks) != 1:
            return None
        [valid_bugtask] = non_invalid_bugtasks
        pillar = valid_bugtask.pillar
        if (
            pillar.bug_tracking_usage == ServiceUsage.LAUNCHPAD
            and pillar.answers_usage == ServiceUsage.LAUNCHPAD
        ):
            return valid_bugtask
        else:
            return None

    def convertToQuestion(self, person, comment=None):
        """See `IBug`."""
        question = self.getQuestionCreatedFromBug()
        assert question is None, (
            "This bug was already converted to question #%s." % question.id
        )
        bugtask = self._getQuestionTargetableBugTask()
        assert bugtask is not None, (
            "A question cannot be created from this bug without a "
            "valid bugtask."
        )

        with notify_modified(bugtask, ["status"], user=person):
            bugtask.transitionToStatus(BugTaskStatus.INVALID, person)
            if comment is not None:
                self.newMessage(
                    owner=person,
                    subject=self.followup_subject(),
                    content=comment,
                )

        question_target = IQuestionTarget(bugtask.target)
        question = question_target.createQuestionFromBug(self)
        self.addChange(BugConvertedToQuestion(UTC_NOW, person, question))
        get_property_cache(self)._question_from_bug = question
        notify(BugBecameQuestionEvent(self, question, person))
        return question

    @cachedproperty
    def _question_from_bug(self):
        for question in self.questions:
            if (
                question.owner_id == self.owner_id
                and question.datecreated == self.datecreated
            ):
                return question
        return None

    def getQuestionCreatedFromBug(self):
        """See `IBug`."""
        return self._question_from_bug

    def getMessagesForView(self, slice_info):
        """See `IBug`."""
        # Note that this function and indexed_messages have significant
        # overlap and could stand to be refactored.
        slices = []
        if slice_info is not None:
            # NB: This isn't a full implementation of the slice protocol,
            # merely the bits needed by BugTask:+index.
            for slice in slice_info:
                if not slice.start:
                    assert slice.stop > 0, slice.stop
                    slices.append(BugMessage.index < slice.stop)
                elif not slice.stop:
                    if slice.start < 0:
                        # If the high index is N, a slice of -1: should
                        # return index N - so we need to add one to the
                        # range.
                        slices.append(
                            BugMessage.index
                            >= Add(
                                Select(
                                    Max(BugMessage.index),
                                    where=(BugMessage.bug == self),
                                ),
                                slice.start + 1,
                            )
                        )
                    else:
                        slices.append(BugMessage.index >= slice.start)
                else:
                    slices.append(
                        And(
                            BugMessage.index >= slice.start,
                            BugMessage.index < slice.stop,
                        )
                    )
        if slices:
            ranges = [Or(*slices)]
        else:
            ranges = []
        # We expect:
        # 1 bugmessage -> 1 message -> small N chunks. For now, using a wide
        # query seems fine as we have to join out from bugmessage anyway.
        # Since "soft-deleted" messages will have 0 chunks, we should use
        # left join here.
        message_join = LeftJoin(
            Message, MessageChunk, Message.id == MessageChunk.message_id
        )
        query = Store.of(self).using(BugMessage, message_join)
        result = query.find(
            (BugMessage, Message, MessageChunk),
            BugMessage.message_id == Message.id,
            BugMessage.bug == self.id,
            *ranges,
        )
        result.order_by(BugMessage.index, MessageChunk.sequence)

        def eager_load_owners(rows):
            owners = set()
            for row in rows:
                owners.add(row[1].owner_id)
            owners.discard(None)
            if not owners:
                return
            list(
                PersonSet().getPrecachedPersonsFromIDs(
                    owners, need_validity=True
                )
            )

        return DecoratedResultSet(result, pre_iter_hook=eager_load_owners)

    def addNomination(self, owner, target):
        """See `IBug`."""
        if not self.canBeNominatedFor(target):
            raise NominationError(
                "This bug cannot be nominated for %s."
                % target.bugtargetdisplayname
            )

        distroseries = None
        productseries = None
        if IDistroSeries.providedBy(target):
            distroseries = target
            if target.status == SeriesStatus.OBSOLETE:
                raise NominationSeriesObsoleteError(
                    "%s is an obsolete series." % target.bugtargetdisplayname
                )
        else:
            assert IProductSeries.providedBy(target)
            productseries = target

        if not (
            check_permission("launchpad.BugSupervisor", target)
            or check_permission("launchpad.Driver", target)
        ):
            raise NominationError(
                "Only bug supervisors or owners can nominate bugs."
            )

        # There may be an existing DECLINED nomination. If so, we set the
        # status back to PROPOSED. We do not alter the original date_created.
        nomination = None
        try:
            nomination = self.getNominationFor(target)
        except NotFoundError:
            pass
        if nomination:
            nomination.status = BugNominationStatus.PROPOSED
            nomination.decider = None
            nomination.date_decided = None
        else:
            nomination = BugNomination(
                owner=owner,
                bug=self,
                distroseries=distroseries,
                productseries=productseries,
            )
        self.addChange(SeriesNominated(UTC_NOW, owner, target))
        return nomination

    def canBeNominatedFor(self, target):
        """See `IBug`."""
        try:
            nomination = self.getNominationFor(target)
        except NotFoundError:
            # No nomination exists. Let's see if the bug is already
            # directly targeted to this nomination target.
            if IDistroSeries.providedBy(target):
                series_getter = operator.attrgetter("distroseries")
                pillar_getter = operator.attrgetter("distribution")
            elif IProductSeries.providedBy(target):
                series_getter = operator.attrgetter("productseries")
                pillar_getter = operator.attrgetter("product")
            else:
                return False

            for task in self.bugtasks:
                if series_getter(task) == target:
                    # The bug is already targeted at this
                    # nomination target.
                    return False

            # No nomination or tasks are targeted at this
            # nomination target. But we also don't want to nominate for a
            # series of a product or distro for which we don't have a
            # plain pillar task.
            for task in self.bugtasks:
                if pillar_getter(task) == pillar_getter(target):
                    return True

            # No tasks match the candidate's pillar. We must refuse.
            return False
        else:
            # The bug may be already nominated for this nomination target.
            # If the status is declined, the bug can be renominated, else
            # return False
            if nomination:
                return nomination.status == BugNominationStatus.DECLINED
            return False

    def getNominationFor(self, target):
        """See `IBug`."""
        nomination = getUtility(IBugNominationSet).getByBugTarget(self, target)

        if nomination is None:
            raise NotFoundError(
                "Bug #%d is not nominated for %s."
                % (self.id, target.displayname)
            )

        return nomination

    def getNominations(self, target=None, nominations=None):
        """See `IBug`."""

        # Define the function used as a sort key.
        def by_bugtargetdisplayname(nomination):
            """Return the friendly sort key version of displayname."""
            return nomination.target.bugtargetdisplayname.lower()

        if nominations is None:
            nominations = getUtility(IBugNominationSet).findByBug(self)
        if IProduct.providedBy(target):
            filtered_nominations = []
            for nomination in shortlist(nominations):
                if (
                    nomination.productseries
                    and nomination.productseries.product == target
                ):
                    filtered_nominations.append(nomination)
            nominations = filtered_nominations
        elif IDistribution.providedBy(target):
            filtered_nominations = []
            for nomination in shortlist(nominations):
                if (
                    nomination.distroseries
                    and nomination.distroseries.distribution == target
                ):
                    filtered_nominations.append(nomination)
            nominations = filtered_nominations

        return sorted(nominations, key=by_bugtargetdisplayname)

    def getBugWatch(self, bugtracker, remote_bug):
        """See `IBug`."""
        # If the bug tracker is of BugTrackerType.EMAILADDRESS we can
        # never tell if a bug is already being watched upstream, since
        # the remotebug field for such bug watches contains either '' or
        # an RFC822 message ID. In these cases, then, we always return
        # None for the sake of sanity.
        if bugtracker.bugtrackertype == BugTrackerType.EMAILADDRESS:
            return None

        # XXX: BjornT 2006-10-11:
        # This matching is a bit fragile, since bugwatch.remotebug
        # is a user editable text string. We should improve the
        # matching so that for example '#42' matches '42' and so on.
        return (
            IStore(BugWatch)
            .find(
                BugWatch,
                bug=self,
                bugtracker=bugtracker,
                remotebug=str(remote_bug),
            )
            .order_by("id")
            .first()
        )

    def setStatus(self, target, status, user):
        """See `IBug`."""
        bugtask = self.getBugTask(target)
        if bugtask is None:
            if IProductSeries.providedBy(target):
                bugtask = self.getBugTask(target.product)
            elif ISourcePackage.providedBy(target):
                current_distro_series = target.distribution.currentseries
                current_package = current_distro_series.getSourcePackage(
                    target.sourcepackagename.name
                )
                if self.getBugTask(current_package) is not None:
                    # The bug is targeted to the current series, don't
                    # fall back on the general distribution task.
                    return None
                distro_package = target.distribution.getSourcePackage(
                    target.sourcepackagename.name
                )
                bugtask = self.getBugTask(distro_package)
            else:
                return None

        if bugtask is None:
            return None

        if bugtask.conjoined_primary is not None:
            bugtask = bugtask.conjoined_primary

        if bugtask.status == status:
            return None

        with notify_modified(bugtask, ["status"], user=user):
            bugtask.transitionToStatus(status, user)

        return bugtask

    def setPrivate(self, private, who):
        """See `IBug`.

        We also record who made the change and when the change took
        place.
        """
        return self.transitionToInformationType(
            convert_to_information_type(private, self.security_related), who
        )

    def setSecurityRelated(self, security_related, who):
        """Setter for the `security_related` property."""
        return self.transitionToInformationType(
            convert_to_information_type(self.private, security_related), who
        )

    def getAllowedInformationTypes(self, who):
        """See `IBug`."""
        types = set(InformationType.items)
        for pillar in self.affected_pillars:
            types.intersection_update(
                set(pillar.getAllowedBugInformationTypes())
            )
        types.add(self.information_type)
        return types

    def transitionToInformationType(self, information_type, who):
        """See `IBug`."""
        if self.information_type == information_type:
            return False
        if information_type not in self.getAllowedInformationTypes(who):
            raise CannotChangeInformationType("Forbidden by project policy.")
        if (
            information_type in PROPRIETARY_INFORMATION_TYPES
            and len(self.affected_pillars) > 1
        ):
            raise CannotChangeInformationType(
                "Proprietary bugs can only affect one project."
            )
        if information_type in PRIVATE_INFORMATION_TYPES:
            self.who_made_private = who
            self.date_made_private = UTC_NOW
        else:
            self.who_made_private = None
            self.date_made_private = None
        # XXX: This should be a bulk update. RBC 20100827
        # bug=https://bugs.launchpad.net/storm/+bug/625071
        for attachment in self.attachments_unpopulated:
            if attachment.libraryfile:
                attachment.libraryfile.restricted = (
                    information_type in PRIVATE_INFORMATION_TYPES
                )

        self.information_type = information_type
        self._reconcileAccess()

        # If the new type is private, some people may no longer have
        # access to the bug. We ensure that the bug reporter and the
        # person changing the privacy can see the bug, and then remove
        # subscriptions for anyone who can't see it any more.
        if information_type in PRIVATE_INFORMATION_TYPES:
            service = getUtility(IService, "sharing")
            for person in (who, self.owner):
                bugs = service.getVisibleArtifacts(
                    person, bugs=[self], ignore_permissions=True
                )["bugs"]
                if not bugs:
                    # subscribe() isn't sufficient if a subscription
                    # already exists, as it will do nothing even if
                    # there is no corresponding access grant. We
                    # explicitly ensureAccessGrants() to ensure that the
                    # subscription is retained.
                    service.ensureAccessGrants(
                        [person], who, bugs=[self], ignore_permissions=True
                    )
                    self.subscribe(person, who)

            # And now fire off a job to remove any subscribers that can
            # no longer see the bug.
            getUtility(IRemoveArtifactSubscriptionsJobSource).create(
                who, [self]
            )

        update_bug_heat([self.id])
        return True

    def getBugTask(self, target):
        """See `IBug`."""
        for bugtask in self.bugtasks:
            if bugtask.target == target:
                return bugtask

        return None

    def _getTags(self):
        """Get the tags as a sorted list of strings."""
        return self._cached_tags

    @cachedproperty
    def _cached_tags(self):
        return list(
            Store.of(self)
            .find(BugTag.tag, BugTag.bug_id == self.id)
            .order_by(BugTag.tag)
        )

    def _setTags(self, tags):
        """Set the tags from a list of strings."""
        # Sets provide an easy way to get the difference between the old and
        # new tags.
        new_tags = {tag.lower() for tag in tags}
        old_tags = set(self.tags)
        # The cache will be stale after we add/remove tags, clear it.
        del get_property_cache(self)._cached_tags
        # Find the set of tags that are to be removed and remove them.
        removed_tags = old_tags.difference(new_tags)
        for removed_tag in removed_tags:
            tag = IStore(BugTag).find(BugTag, bug=self, tag=removed_tag).one()
            tag.destroySelf()
        # Find the set of tags that are to be added and add them.
        added_tags = new_tags.difference(old_tags)
        for added_tag in added_tags:
            BugTag(bug=self, tag=added_tag)
        # Write all pending changes to the DB, including any pending non-tag
        # changes.
        Store.of(self).flush()

    tags = property(_getTags, _setTags)

    @staticmethod
    def getBugTasksByPackageName(bugtasks):
        """See IBugTask."""
        bugtasks_by_package = {}
        for bugtask in bugtasks:
            bugtasks_by_package.setdefault(bugtask.sourcepackagename, [])
            bugtasks_by_package[bugtask.sourcepackagename].append(bugtask)
        return bugtasks_by_package

    def _getAffectedUser(self, user):
        """Return the `IBugAffectsPerson` for a user, or None

        :param user: An `IPerson` that may be affected by the bug.
        :return: An `IBugAffectsPerson` or None.
        """
        if user is None:
            return None
        else:
            return Store.of(self).get(BugAffectsPerson, (self.id, user.id))

    def isUserAffected(self, user):
        """See `IBug`."""
        bap = self._getAffectedUser(user)
        if bap is not None:
            return bap.affected
        else:
            return None

    def _flushAndInvalidate(self):
        """Flush all changes to the store and re-read `self` from the DB."""
        store = Store.of(self)
        store.flush()
        store.invalidate(self)

    def shouldConfirmBugtasks(self):
        """See `IBug`."""
        # == 2 would probably be sufficient once we have all legacy bug tasks
        # confirmed.  For now, this is a compromise: we don't need a migration
        # step, but we will make some unnecessary comparisons.
        return self.users_affected_count_with_dupes > 1

    def maybeConfirmBugtasks(self):
        """See `IBug`."""
        if self.shouldConfirmBugtasks():
            for bugtask in self.bugtasks:
                bugtask.maybeConfirm()

    def markUserAffected(self, user, affected=True):
        """See `IBug`."""
        bap = self._getAffectedUser(user)
        if bap is None:
            BugAffectsPerson(bug=self, person=user, affected=affected)
        else:
            if bap.affected != affected:
                bap.affected = affected

        dupe_bug_ids = [dupe.id for dupe in self.duplicates]
        # Where BugAffectsPerson records already exist for each duplicate,
        # update the affected status.
        if dupe_bug_ids:
            Store.of(self).find(
                BugAffectsPerson,
                BugAffectsPerson.person == user,
                BugAffectsPerson.bug_id.is_in(dupe_bug_ids),
            ).set(affected=affected)
            for dupe in self.duplicates:
                dupe._flushAndInvalidate()
        self._flushAndInvalidate()

        if affected:
            self.maybeConfirmBugtasks()

        update_bug_heat(dupe_bug_ids + [self.id])

    def _markAsDuplicate(self, duplicate_of, affected_bug_ids):
        """Mark this bug as a duplicate of another.

        Marking a bug as a duplicate requires a recalculation of the
        heat of this bug and of the master bug. None of this is done
        here in order to avoid unnecessary repetitions in recursive
        calls for duplicates of this bug, which also become duplicates
        of the new master bug.
        """
        field = DuplicateBug()
        field.context = self
        current_duplicateof = self.duplicateof
        try:
            if duplicate_of is not None:
                field._validate(duplicate_of)
            if not self.duplicates.is_empty():
                user = getUtility(ILaunchBag).user
                for duplicate in self.duplicates:
                    old_value = duplicate.duplicateof
                    duplicate._markAsDuplicate(duplicate_of, affected_bug_ids)
                    # Put an entry into the BugNotification table for
                    # later processing.
                    change = BugDuplicateChange(
                        when=None,
                        person=user,
                        what_changed="duplicateof",
                        old_value=old_value,
                        new_value=duplicate_of,
                    )
                    empty_recipients = BugNotificationRecipients()
                    duplicate.addChange(
                        change,
                        empty_recipients,
                        deferred=True,
                        update_heat=False,
                    )
                    affected_bug_ids.add(duplicate.id)

            self.duplicateof = duplicate_of
        except LaunchpadValidationError as validation_error:
            raise InvalidDuplicateValue(validation_error, already_escaped=True)
        if duplicate_of is not None:
            affected_bug_ids.add(duplicate_of.id)
            # Maybe confirm bug tasks, now that more people might be affected
            # by this bug from the duplicates.
            duplicate_of.maybeConfirmBugtasks()

        # Update the former duplicateof's heat, as it will have been
        # reduced by the unduping.
        if current_duplicateof is not None:
            affected_bug_ids.add(current_duplicateof.id)

    def markAsDuplicate(self, duplicate_of):
        """See `IBug`."""
        affected_bug_ids = set()
        self._markAsDuplicate(duplicate_of, affected_bug_ids)
        update_bug_heat(affected_bug_ids)

    def setCommentVisibility(self, user, comment_number, visible):
        """See `IBug`."""
        bug_message_set = getUtility(IBugMessageSet)
        bug_message = bug_message_set.getByBugAndMessage(
            self, self.messages[comment_number]
        )

        user_owns_comment = bug_message.owner == user
        if (
            not self.userCanSetCommentVisibility(user)
            and not user_owns_comment
        ):
            raise Unauthorized(
                "User %s cannot hide or show bug comments" % user.name
            )
        bug_message.message.setVisible(visible)

    @cachedproperty
    def _known_viewers(self):
        """A set of known persons able to view this bug.

        This method must return an empty set or bug searches will trigger late
        evaluation. Any 'should be set on load' properties must be done by the
        bug search.

        If you are tempted to change this method, don't. Instead see
        userCanView which defines the just-in-time policy for bug visibility,
        and BugTask._search which honours visibility rules.
        """
        return set()

    def userCanView(self, user):
        """See `IBug`.

        This method is called by security adapters but only in the case for
        authenticated users.  It is also called in other contexts where the
        user may be anonymous.

        Most logic is delegated to the query provided by
        get_bug_privacy_filter, but some short-circuits and caching are
        reimplemented here.

        If bug privacy rights are changed here, corresponding changes need
        to be made to the queries which screen for privacy.  See
        bugtasksearch's get_bug_privacy_filter.
        """
        from lp.bugs.interfaces.bugtasksearch import BugTaskSearchParams

        if not self.private:
            # This is a public bug.
            return True
        # This method may be called for anonymous users.  For private bugs
        # always return false for anonymous.
        if user is None:
            return False
        if user.id in self._known_viewers:
            return True

        params = BugTaskSearchParams(user=user, bug=self)
        if not getUtility(IBugTaskSet).search(params).is_empty():
            self._known_viewers.add(user.id)
            return True
        return False

    def userCanSetCommentVisibility(self, user):
        """See `IBug`"""
        if user is None:
            return False
        # Admins and registry experts always have permission.
        roles = IPersonRoles(user)
        if roles.in_admin or roles.in_registry_experts:
            return True
        return getUtility(IService, "sharing").checkPillarAccess(
            self.affected_pillars, InformationType.USERDATA, user
        )

    def personIsDirectSubscriber(self, person):
        """See `IBug`."""
        if person in self._subscriber_cache:
            return True
        if person in self._unsubscribed_cache:
            return False
        if person is None:
            return False
        store = Store.of(self)
        subscriptions = store.find(
            BugSubscription,
            BugSubscription.bug == self,
            BugSubscription.person == person,
        )
        return not subscriptions.is_empty()

    def personIsAlsoNotifiedSubscriber(self, person):
        """See `IBug`."""
        # We have to use getAlsoNotifiedSubscribers() here and iterate
        # over what it returns because "also notified subscribers" is
        # actually a composite of bug structural subscribers and assignees.
        # As such, it's not possible to get them all with one query.
        also_notified_subscribers = self.getAlsoNotifiedSubscribers()
        if person in also_notified_subscribers:
            return True
        # Otherwise check to see if the person is a member of any of the
        # subscribed teams.
        for subscriber in also_notified_subscribers:
            if subscriber.is_team and person.inTeam(subscriber):
                return True
        return False

    def personIsSubscribedToDuplicate(self, person):
        """See `IBug`."""
        if person in self._subscriber_dups_cache:
            return True
        if person in self._unsubscribed_cache:
            return False
        if person is None:
            return False
        return (
            not Store.of(self)
            .find(
                BugSubscription,
                Bug.duplicateof == self,
                BugSubscription.bug_id == Bug.id,
                BugSubscription.person == person,
            )
            .is_empty()
        )

    def _reconcileAccess(self):
        # reconcile_access_for_artifacts will only use the pillar list if
        # the information type is private. But affected_pillars iterates
        # over the tasks immediately, which is needless expense for
        # public bugs.
        if self.information_type in PRIVATE_INFORMATION_TYPES:
            pillars = self.affected_pillars
        else:
            pillars = []
        reconcile_access_for_artifacts([self], self.information_type, pillars)

    def _attachments_query(self):
        """Helper for the attachments* properties."""
        # get bug attachments that have either a URL,
        # or associated LibraryFileContent
        # bug attachments with LibraryFileAlias and no LibraryFileContent have
        # been deleted - the garbo_daily run will remove the LibraryFileAlias
        # asynchronously. See bug 542274 for more details.
        store = Store.of(self)
        return (
            store.using(
                BugAttachment,
                LeftJoin(
                    LibraryFileAlias,
                    BugAttachment.libraryfile == LibraryFileAlias.id,
                ),
                LeftJoin(
                    LibraryFileContent,
                    LibraryFileContent.id == LibraryFileAlias.content_id,
                ),
            )
            .find(
                (BugAttachment, LibraryFileAlias, LibraryFileContent),
                BugAttachment.bug == self,
                Or(
                    BugAttachment.url != None,
                    BugAttachment.vulnerability_patches != None,
                    LibraryFileAlias.content_id != None,
                ),
            )
            .order_by(BugAttachment.id)
        )

    @property
    def attachments(self):
        """See `IBug`.

        This property does eager loading of the index_messages so that
        the API which wants the message_link for the attachment can
        answer that without O(N^2) overhead. As such it is moderately
        expensive to call (it currently retrieves all messages before
        any attachments, and does this when attachments is evaluated,
        not when the resultset is processed).
        """
        message_to_indexed = {}
        for message in self._indexed_messages(include_parents=False):
            message_to_indexed[message.id] = message

        def set_indexed_message(row):
            attachment = row[0]
            # row[1] - the LibraryFileAlias is now in the storm cache and
            # will be found without a query when dereferenced.
            indexed_message = message_to_indexed.get(attachment._message_id)
            if indexed_message is not None:
                get_property_cache(attachment).message = indexed_message
            return attachment

        rawresults = self._attachments_query()
        return DecoratedResultSet(rawresults, set_indexed_message)

    @property
    def attachments_unpopulated(self):
        """See `IBug`.

        This version does not pre-lookup messages and LibraryFileAliases.

        The regular 'attachments' property does prepopulation because it is
        exposed in the API.
        """
        # Grab the attachment only; the LibraryFileAlias will be eager loaded.
        return DecoratedResultSet(
            self._attachments_query(), operator.itemgetter(0)
        )

    def getActivityForDateRange(self, start_date, end_date):
        """See `IBug`."""
        store = Store.of(self)
        activity_in_range = store.find(
            BugActivity,
            BugActivity.bug == self,
            BugActivity.datechanged >= start_date,
            BugActivity.datechanged <= end_date,
        )
        return activity_in_range

    def lock(self, who, status, reason=None):
        """See `IBug`."""
        if status == self.lock_status:
            raise CannotLockBug(
                "This bug is already locked "
                "with the lock status '{}'.".format(status)
            )
        else:
            old_lock_status = self.lock_status
            self.lock_status = BugLockStatus.items[status.value]
            if reason:
                self.lock_reason = reason

            self.addChange(
                BugLocked(
                    when=UTC_NOW,
                    person=who,
                    old_status=old_lock_status,
                    new_status=self.lock_status,
                    reason=reason,
                )
            )

    def unlock(self, who):
        """See `IBug`."""
        if self.lock_status != BugLockStatus.UNLOCKED:
            old_lock_status = self.lock_status
            self.lock_reason = None
            self.lock_status = BugLockStatus.UNLOCKED

            self.addChange(
                BugUnlocked(
                    when=UTC_NOW, person=who, old_status=old_lock_status
                )
            )

    def setLockReason(self, reason, who):
        """See `IBug`."""
        if self.lock_status == BugLockStatus.UNLOCKED:
            raise CannotSetLockReason(
                "Lock reason cannot be set for an unlocked bug."
            )
        if self.lock_reason != reason:
            old_reason = self.lock_reason
            self.lock_reason = reason
            self.addChange(
                BugLockReasonSet(
                    when=UTC_NOW,
                    person=who,
                    old_reason=old_reason,
                    new_reason=reason,
                )
            )


@ProxyFactory
def get_also_notified_subscribers(bug_or_bugtask, recipients=None, level=None):
    """Return the indirect subscribers for a bug or bug task.

    Return the list of people who should get notifications about changes
    to the bug or task because of having an indirect subscription
    relationship with it (by subscribing to a target, being an assignee
    or owner, etc...)

    If `recipients` is present, add the subscribers to the set of
    bug notification recipients.
    """
    if IBug.providedBy(bug_or_bugtask):
        bug = bug_or_bugtask
        bugtasks = bug.bugtasks
        info = bug.getSubscriptionInfo(level)
    elif IBugTask.providedBy(bug_or_bugtask):
        bug = bug_or_bugtask.bug
        bugtasks = [bug_or_bugtask]
        info = bug.getSubscriptionInfo(level).forTask(bug_or_bugtask)
    else:
        raise ValueError("First argument must be bug or bugtask")

    # Subscribers to exclude.
    exclude_subscribers = frozenset().union(
        info.direct_subscribers_at_all_levels, info.muted_subscribers
    )
    # Get also-notified subscribers at the given level for the given tasks.
    also_notified_subscribers = info.also_notified_subscribers

    if recipients is not None:
        for bugtask in bugtasks:
            assignee = bugtask.assignee
            if assignee in also_notified_subscribers:
                # We have an assignee that is not a direct subscriber.
                recipients.addAssignee(bugtask.assignee)

    # This structural subscribers code omits direct subscribers itself.
    # TODO: Pass the info object into get_structural_subscribers for
    # efficiency... or do the recipients stuff here.
    structural_subscribers = get_structural_subscribers(
        bug_or_bugtask, recipients, level, exclude_subscribers
    )
    assert also_notified_subscribers.issuperset(structural_subscribers)

    return also_notified_subscribers.sorted


def load_people(*where):
    """Get subscribers from subscriptions.

    Also preloads `ValidPersonCache` records if they exist.

    :param people: An iterable sequence of `Person` IDs.
    :return: A `DecoratedResultSet` of `Person` objects. The corresponding
        `ValidPersonCache` records are loaded simultaneously.
    """
    return PersonSet()._getPrecachedPersons(
        origin=[Person],
        conditions=where,
        need_validity=True,
        need_preferred_email=True,
    )


class FrozenSetBasedSet(Set):
    """A subclassable immutable set.

    On Python 3, we can't simply subclass `frozenset`: set operations such
    as union will create a new set, but it will be a plain `frozenset` and
    will lack the appropriate custom properties.  However, the `Set` ABC
    (which is in fact an immutable set; `MutableSet` is a separate ABC)
    knows to create new sets using the same class.  Take advantage of this
    with a trivial implementation of `Set` that backs straight onto a
    `frozenset`.

    The ABC doesn't implement the non-operator versions of set methods such
    as `union`, so do that here, at least for those methods we actually use.
    """

    def __init__(self, iterable=None):
        self._frozenset = (
            frozenset() if iterable is None else frozenset(iterable)
        )

    def __iter__(self):
        return iter(self._frozenset)

    def __contains__(self, value):
        return value in self._frozenset

    def __len__(self):
        return len(self._frozenset)

    def issubset(self, other):
        return self <= self._from_iterable(other)

    def issuperset(self, other):
        return self >= self._from_iterable(other)

    def union(self, *others):
        for other in others:
            if not isinstance(other, Iterable):
                raise NotImplementedError
        return self._from_iterable(value for value in chain(self, *others))

    def intersection(self, *others):
        for other in others:
            if not isinstance(other, Iterable):
                raise NotImplementedError
        return self._from_iterable(
            value for value in chain(*others) if value in self
        )

    def difference(self, *others):
        other = self._from_iterable([]).union(*others)
        return self._from_iterable(
            value for value in self if value not in other
        )


class BugSubscriberSet(FrozenSetBasedSet):
    """An immutable set of bug subscribers.

    Every member should provide `IPerson`.
    """

    @cachedproperty
    def sorted(self):
        """A sorted tuple of this set's members.

        Sorted with `person_sort_key`, the default sort key for `Person`.
        """
        return tuple(sorted(self, key=person_sort_key))


class BugSubscriptionSet(FrozenSetBasedSet):
    """An immutable set of bug subscriptions."""

    @cachedproperty
    def sorted(self):
        """A sorted tuple of this set's members.

        Sorted with `person_sort_key` of the subscription owner.
        """
        self.subscribers  # Pre-load subscribers.
        sort_key = lambda sub: person_sort_key(sub.person)
        return tuple(sorted(self, key=sort_key))

    @cachedproperty
    def subscribers(self):
        """A `BugSubscriberSet` of the owners of this set's members."""
        if len(self) == 0:
            return BugSubscriberSet()
        else:
            condition = Person.id.is_in(
                removeSecurityProxy(subscription).person_id
                for subscription in self
            )
            return BugSubscriberSet(load_people(condition))


class StructuralSubscriptionSet(FrozenSetBasedSet):
    """A set of structural subscriptions."""

    @cachedproperty
    def sorted(self):
        """A sorted tuple of this set's members.

        Sorted with `person_sort_key` of the subscription owner.
        """
        self.subscribers  # Pre-load subscribers.
        sort_key = lambda sub: person_sort_key(sub.subscriber)
        return tuple(sorted(self, key=sort_key))

    @cachedproperty
    def subscribers(self):
        """A `BugSubscriberSet` of the owners of this set's members."""
        if len(self) == 0:
            return BugSubscriberSet()
        else:
            condition = Person.id.is_in(
                removeSecurityProxy(subscription).subscriberID
                for subscription in self
            )
            return BugSubscriberSet(load_people(condition))


# XXX: GavinPanella 2010-12-08 bug=694057: Subclasses of frozenset don't
# appear to be granted those permissions given to frozenset. This would make
# writing ZCML tedious, so I've opted for registering custom checkers (see
# lp_sitecustomize for some other jiggery pokery in the same vein) while I
# seek a better solution.
checker_for_frozen_set = checker.getCheckerForInstancesOf(frozenset)
checker_for_subscriber_set = checker.NamesChecker(["sorted"])
checker_for_subscription_set = checker.NamesChecker(["sorted", "subscribers"])
checker.BasicTypes[BugSubscriberSet] = checker.MultiChecker(
    (
        checker_for_frozen_set.get_permissions,
        checker_for_subscriber_set.get_permissions,
    )
)
checker.BasicTypes[BugSubscriptionSet] = checker.MultiChecker(
    (
        checker_for_frozen_set.get_permissions,
        checker_for_subscription_set.get_permissions,
    )
)
checker.BasicTypes[StructuralSubscriptionSet] = checker.MultiChecker(
    (
        checker_for_frozen_set.get_permissions,
        checker_for_subscription_set.get_permissions,
    )
)


def freeze(factory):
    """Return a decorator that wraps returned values with `factory`."""

    def decorate(func):
        """Decorator that wraps returned values."""

        @wraps(func)
        def wrapper(*args, **kwargs):
            return factory(func(*args, **kwargs))

        return wrapper

    return decorate


@implementer(IHasBug)
class BugSubscriptionInfo:
    """Represents bug subscription sets.

    The intention for this class is to encapsulate all calculations of
    subscriptions and subscribers for a bug. Some design considerations:

    * Immutable.

    * Set-based.

    * Sets are cached.

    * Usable with a *snapshot* of a bug. This is interesting for two reasons:

      - Event subscribers commonly deal with snapshots. An instance of this
        class could be added to a custom snapshot so that multiple subscribers
        can share the information it contains.

      - Use outside of the web request. A serialized snapshot could be used to
        calculate subscribers for a particular bug state. This could help us
        to move even more bug mail processing out of the web request.

    """

    def __init__(self, bug, level):
        self.bug = bug
        self.bugtask = None  # Implies all.
        assert level is not None
        self.level = level
        # This cache holds related `BugSubscriptionInfo` instances relating to
        # the same bug but with different levels and/or choice of bugtask.
        self.cache = {self.cache_key: self}
        # This is often used in event handlers, many of which block implicit
        # flushes. However, the data needs to be in the database for the
        # queries herein to give correct answers.
        Store.of(bug).flush()

    @property
    def cache_key(self):
        """A (bug ID, bugtask ID, level) tuple for use as a hash key.

        This helps `forTask()` and `forLevel()` to be more efficient,
        returning previously populated instances to avoid running the same
        queries against the database again and again.
        """
        bugtask_id = None if self.bugtask is None else self.bugtask.id
        return self.bug.id, bugtask_id, self.level

    def forTask(self, bugtask):
        """Create a new `BugSubscriptionInfo` limited to `bugtask`.

        The given task must refer to this object's bug. If `None` is passed a
        new `BugSubscriptionInfo` instance is returned with no limit.
        """
        info = self.__class__(self.bug, self.level)
        info.bugtask, info.cache = bugtask, self.cache
        return self.cache.setdefault(info.cache_key, info)

    def forLevel(self, level):
        """Create a new `BugSubscriptionInfo` limited to `level`."""
        info = self.__class__(self.bug, level)
        info.bugtask, info.cache = self.bugtask, self.cache
        return self.cache.setdefault(info.cache_key, info)

    @cachedproperty
    @freeze(BugSubscriberSet)
    def muted_subscribers(self):
        muted_people = Select(BugMute.person_id, BugMute.bug == self.bug)
        return load_people(Person.id.is_in(muted_people))

    def visible_recipients_filter(self, column):
        # Circular fail :(
        from lp.bugs.model.bugtasksearch import (
            get_bug_bulk_privacy_filter_terms,
        )

        if self.bug.private:
            return get_bug_bulk_privacy_filter_terms(column, self.bug.id)
        else:
            return True

    @cachedproperty
    @freeze(BugSubscriptionSet)
    def direct_subscriptions(self):
        """The bug's direct subscriptions.

        Excludes muted subscriptions.
        """
        return IStore(BugSubscription).find(
            BugSubscription,
            BugSubscription.bug_notification_level >= self.level,
            BugSubscription.bug == self.bug,
            Not(
                In(
                    BugSubscription.person_id,
                    Select(BugMute.person_id, BugMute.bug_id == self.bug.id),
                )
            ),
        )

    @property
    def direct_subscribers(self):
        """The bug's direct subscriptions.

        Excludes muted subscribers.
        """
        return self.direct_subscriptions.subscribers

    @property
    def direct_subscriptions_at_all_levels(self):
        """The bug's direct subscriptions at all levels.

        Excludes muted subscriptions.
        """
        return self.forLevel(
            BugNotificationLevel.LIFECYCLE
        ).direct_subscriptions

    @property
    def direct_subscribers_at_all_levels(self):
        """The bug's direct subscribers at all levels.

        Excludes muted subscribers.
        """
        return self.direct_subscriptions_at_all_levels.subscribers

    @cachedproperty
    @freeze(BugSubscriptionSet)
    def duplicate_subscriptions(self):
        """Subscriptions to duplicates of the bug.

        Excludes muted subscriptions, and subscribers who can not see the
        master bug.
        """
        return IStore(BugSubscription).find(
            BugSubscription,
            BugSubscription.bug_notification_level >= self.level,
            BugSubscription.bug_id == Bug.id,
            Bug.duplicateof == self.bug,
            Not(
                In(
                    BugSubscription.person_id,
                    Select(
                        BugMute.person_id,
                        BugMute.bug_id == Bug.id,
                        tables=[BugMute],
                    ),
                )
            ),
            self.visible_recipients_filter(BugSubscription.person_id),
        )

    @property
    def duplicate_subscribers(self):
        """Subscribers to duplicates of the bug.

        Excludes muted subscribers.
        """
        return self.duplicate_subscriptions.subscribers

    @cachedproperty
    @freeze(BugSubscriptionSet)
    def duplicate_only_subscriptions(self):
        """Subscriptions to duplicates of the bug only.

        Excludes muted subscriptions, subscriptions for people who have a
        direct subscription, or who are also notified for another reason.
        """
        self.duplicate_subscribers  # Pre-load subscribers.
        higher_precedence = self.direct_subscribers.union(
            self.also_notified_subscribers
        )
        return (
            subscription
            for subscription in self.duplicate_subscriptions
            if subscription.person not in higher_precedence
        )

    @property
    def duplicate_only_subscribers(self):
        """Subscribers to duplicates of the bug only.

        Excludes muted subscribers, subscribers who have a direct
        subscription, or who are also notified for another reason.
        """
        return self.duplicate_only_subscriptions.subscribers

    @cachedproperty
    @freeze(StructuralSubscriptionSet)
    def structural_subscriptions(self):
        """Structural subscriptions to the bug's targets.

        Excludes direct subscriptions.
        """
        subject = self.bug if self.bugtask is None else self.bugtask
        return get_structural_subscriptions(subject, self.level)

    @property
    def structural_subscribers(self):
        """Structural subscribers to the bug's targets.

        Excludes direct subscribers.
        """
        return self.structural_subscriptions.subscribers

    @cachedproperty
    @freeze(BugSubscriberSet)
    def all_assignees(self):
        """Assignees of the bug's tasks.

        *Does not* exclude muted subscribers.
        """
        if self.bugtask is None:
            assignees = load_people(
                Person.id.is_in(
                    Select(BugTask.assignee_id, BugTask.bug == self.bug)
                )
            )
        else:
            assignees = load_people(Person.id == self.bugtask.assignee_id)
        if self.bug.private:
            return IStore(Person).find(
                Person,
                Person.id.is_in([a.id for a in assignees]),
                self.visible_recipients_filter(Person.id),
            )
        else:
            return assignees

    @cachedproperty
    def also_notified_subscribers(self):
        """All subscribers except direct, dupe, and muted subscribers."""
        subscribers = BugSubscriberSet().union(
            self.structural_subscribers, self.all_assignees
        )
        return subscribers.difference(
            self.direct_subscribers_at_all_levels, self.muted_subscribers
        )

    @cachedproperty
    def indirect_subscribers(self):
        """All subscribers except direct subscribers.

        Excludes muted subscribers.
        """
        return self.also_notified_subscribers.union(self.duplicate_subscribers)


@implementer(IBugSet)
class BugSet:
    """See BugSet."""

    valid_bug_name_re = re.compile(r"""^[a-z][a-z0-9\\+\\.\\-]+$""")

    def get(self, bugid):
        """See `IBugSet`."""
        bug = IStore(Bug).get(Bug, int(bugid))
        if bug is None:
            raise NotFoundError(
                "Unable to locate bug with ID %s." % str(bugid)
            )
        return bug

    def getByNameOrID(self, bugid):
        """See `IBugSet`."""
        if self.valid_bug_name_re.match(bugid):
            bug = IStore(Bug).find(Bug, name=bugid).one()
            if bug is None:
                raise NotFoundError("Unable to locate bug with ID %s." % bugid)
        else:
            try:
                bug = self.get(bugid)
            except ValueError:
                raise NotFoundError(
                    "Unable to locate bug with nickname %s." % bugid
                )
        return bug

    def createBug(self, bug_params, notify_event=True):
        """See `IBugSet`."""
        # Make a copy of the parameter object, because we might modify some
        # of its attribute values below.
        params = snapshot_bug_params(bug_params)

        if ISeriesBugTarget.providedBy(params.target):
            raise IllegalTarget(
                "Can't create a bug on a series. Create it with a non-series "
                "task instead, and target it to the series afterwards."
            )

        if params.information_type is None:
            params.information_type = (
                params.target.pillar.getDefaultBugInformationType()
            )

        bug, event = self._makeBug(params)

        # Create the initial task on the specified target.  This also
        # reconciles access policies for this bug based on that target.
        getUtility(IBugTaskSet).createTask(
            bug, params.owner, params.target, status=params.status
        )

        if params.subscribe_owner:
            bug.subscribe(params.owner, params.owner)
        # Subscribe other users.
        for subscriber in params.subscribers:
            bug.subscribe(subscriber, params.owner)

        bug_task = bug.default_bugtask
        if params.assignee:
            bug_task.transitionToAssignee(params.assignee)
        if params.importance:
            bug_task.transitionToImportance(params.importance, params.owner)
        if params.milestone:
            bug_task.transitionToMilestone(params.milestone, params.owner)

        # Tell everyone.
        if notify_event:
            notify(event)

        # Calculate the bug's initial heat.
        update_bug_heat([bug.id])

        if not notify_event:
            return bug, event
        return bug

    def _makeBug(self, bug_params):
        """Construct a bew bug object using the specified parameters."""

        # Make a copy of the parameter object, because we might modify some
        # of its attribute values below.
        params = snapshot_bug_params(bug_params)

        if not (params.comment or params.description or params.msg):
            raise AssertionError(
                "Either comment, msg, or description should be specified."
            )

        if not params.datecreated:
            params.datecreated = UTC_NOW

        # make sure we did not get TOO MUCH information
        assert (
            params.comment is None or params.msg is None
        ), "Expected either a comment or a msg, but got both."

        # Create the bug comment if one was given.
        if params.comment:
            rfc822msgid = make_msgid("malonedeb")
            params.msg = Message(
                subject=params.title,
                rfc822msgid=rfc822msgid,
                owner=params.owner,
                datecreated=params.datecreated,
            )
            MessageChunk(
                message=params.msg, sequence=1, content=params.comment
            )

        # Extract the details needed to create the bug and optional msg.
        if not params.description:
            params.description = params.msg.text_contents

        extra_params = {}
        if params.information_type in PRIVATE_INFORMATION_TYPES:
            # We add some auditing information. After bug creation
            # time these attributes are updated by Bug.setPrivate().
            extra_params.update(
                date_made_private=params.datecreated,
                who_made_private=params.owner,
            )

        bug = Bug(
            title=params.title,
            description=params.description,
            owner=params.owner,
            datecreated=params.datecreated,
            information_type=params.information_type,
            **extra_params,
        )

        if params.tags:
            bug.tags = params.tags

        Store.of(bug).flush()

        # Link the bug to the message.
        BugMessage(bug=bug, message=params.msg, index=0)

        # Mark the bug reporter as affected by that bug.
        bug.markUserAffected(bug.owner)

        if params.cve is not None:
            bug.linkCVE(params.cve, params.owner)

        # Populate the creation event.
        if params.filed_by is None:
            event = ObjectCreatedEvent(bug, user=params.owner)
        else:
            event = ObjectCreatedEvent(bug, user=params.filed_by)

        return (bug, event)

    def getDistinctBugsForBugTasks(self, bug_tasks, user, limit=10):
        """See `IBugSet`."""
        # XXX: Graham Binns 2009-05-28 bug=75764
        #      We slice bug_tasks here to prevent this method from
        #      causing timeouts, since if we try to iterate over it
        #      Transaction.iterSelect() will try to listify the results.
        #      This can be fixed by selecting from Bugs directly, but
        #      that's non-trivial.
        # ---: Robert Collins 2010-08-18: if bug_tasks implements IResultSet
        #      then it should be very possible to improve on it, though
        #      DecoratedResultSets would need careful handling (e.g. type
        #      driven callbacks on columns)
        # We select more than :limit: since if a bug affects more than
        # one source package, it will be returned more than one time. 4
        # is an arbitrary number that should be large enough.
        bugs = []
        for bug_task in bug_tasks[: 4 * limit]:
            bug = bug_task.bug
            duplicateof = bug.duplicateof
            if duplicateof is not None:
                bug = duplicateof

            if not bug.userCanView(user):
                continue

            if bug not in bugs:
                bugs.append(bug)
                if len(bugs) >= limit:
                    break

        return bugs

    def getByNumbers(self, bug_numbers):
        """See `IBugSet`."""
        if bug_numbers is None or len(bug_numbers) < 1:
            return EmptyResultSet()
        store = IStore(Bug)
        result_set = store.find(Bug, Bug.id.is_in(bug_numbers))
        return result_set.order_by("id")

    def getBugsWithOutdatedHeat(self, cutoff):
        """See `IBugSet`."""
        store = IStore(Bug)
        last_updated_clause = Or(
            Bug.heat_last_updated < cutoff, Bug.heat_last_updated == None
        )

        return store.find(Bug, last_updated_clause).order_by(
            Bug.heat_last_updated
        )


class BugAffectsPerson(StormBase):
    """A bug is marked as affecting a user."""

    __storm_table__ = "BugAffectsPerson"
    __storm_primary__ = "bug_id", "person_id"

    bug_id = Int(name="bug", allow_none=False)
    bug = Reference(bug_id, "Bug.id")

    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")

    affected = Bool(allow_none=False, default=True)

    def __init__(self, bug, person, affected=True):
        super().__init__()
        self.bug = bug
        self.person = person
        self.affected = affected


@implementer(IFileBugData)
class FileBugData:
    """Extra data to be added to the bug."""

    def __init__(
        self,
        initial_summary=None,
        initial_tags=None,
        private=None,
        subscribers=None,
        extra_description=None,
        comments=None,
        attachments=None,
    ):
        if initial_tags is None:
            initial_tags = []
        if subscribers is None:
            subscribers = []
        if comments is None:
            comments = []
        if attachments is None:
            attachments = []

        self.initial_summary = initial_summary
        self.private = private
        self.extra_description = extra_description
        self.initial_tags = initial_tags
        self.subscribers = subscribers
        self.comments = comments
        self.attachments = attachments

    def asDict(self):
        """Return the FileBugData instance as a dict."""
        return self.__dict__.copy()


@implementer(IBugMute)
class BugMute(StormBase):
    """Contains bugs a person has decided to block notifications from."""

    __storm_table__ = "BugMute"

    def __init__(self, person=None, bug=None):
        if person is not None:
            self.person = person
        if bug is not None:
            self.bug_id = bug.id

    person_id = Int("person", allow_none=False, validator=validate_person)
    person = Reference(person_id, "Person.id")

    bug_id = Int("bug", allow_none=False)
    bug = Reference(bug_id, "Bug.id")

    __storm_primary__ = "person_id", "bug_id"

    date_created = DateTime(
        "date_created", allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )


def generate_subscription_with(bug, person):
    store = IStore(bug)
    return [
        WithMaterialized(
            "all_bugsubscriptions",
            store,
            Select(
                (BugSubscription.id, BugSubscription.person_id),
                tables=[
                    BugSubscription,
                    Join(Bug, Bug.id == BugSubscription.bug_id),
                ],
                where=Or(Bug.id == bug.id, Bug.duplicateof_id == bug.id),
            ),
        ),
        WithMaterialized(
            "bugsubscriptions",
            store,
            Select(
                SQL("all_bugsubscriptions.id"),
                tables=[
                    SQL("all_bugsubscriptions"),
                    Join(
                        TeamParticipation,
                        TeamParticipation.team_id
                        == SQL("all_bugsubscriptions.person"),
                    ),
                ],
                where=[TeamParticipation.person == person],
            ),
        ),
    ]
