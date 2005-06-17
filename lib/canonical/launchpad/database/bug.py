# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
"""Launchpad bug-related database table classes."""

__metaclass__ = type
__all__ = ['Bug', 'BugDelta', 'BugFactory', 'BugSet']

from sets import Set
from datetime import datetime
from email.Utils import make_msgid

from zope.interface import implements
from zope.exceptions import NotFoundError
from zope.component import getUtility

from sqlobject import ForeignKey, IntCol, StringCol, BoolCol
from sqlobject import MultipleJoin, RelatedJoin
from sqlobject import SQLObjectNotFound

from canonical.launchpad.interfaces import (
    IBug, IBugAddForm, IBugSet, IBugDelta)
from canonical.launchpad.helpers import contactEmailAddresses
from canonical.database.sqlbase import SQLBase
from canonical.database.constants import UTC_NOW, DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.lp import dbschema
from canonical.launchpad.database.bugset import BugSetBase
from canonical.launchpad.database.message import (
    Message, MessageSet, MessageChunk)
from canonical.launchpad.database.bugmessage import BugMessage
from canonical.launchpad.database.bugtask import BugTask
from canonical.launchpad.database.bugsubscription import BugSubscription
from canonical.launchpad.database.maintainership import Maintainership

from zope.i18n import MessageIDFactory
_ = MessageIDFactory("launchpad")


class Bug(SQLBase):
    """A bug."""

    implements(IBug)

    _defaultOrder = '-id'

    # db field names
    name = StringCol(unique=True, default=None)
    title = StringCol(notNull=True)
    summary = StringCol(notNull=False, default=None)
    description = StringCol(notNull=False,
                            default=None)
    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    duplicateof = ForeignKey(
        dbName='duplicateof', foreignKey='Bug', default=None)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    communityscore = IntCol(dbName='communityscore', notNull=True, default=0)
    communitytimestamp = UtcDateTimeCol(dbName='communitytimestamp',
                                        notNull=True, default=DEFAULT)
    hits = IntCol(dbName='hits', notNull=True, default=0)
    hitstimestamp = UtcDateTimeCol(dbName='hitstimestamp', notNull=True,
                                   default=DEFAULT)
    activityscore = IntCol(dbName='activityscore', notNull=True, default=0)
    activitytimestamp = UtcDateTimeCol(dbName='activitytimestamp',
                                       notNull=True, default=DEFAULT)
    private = BoolCol(notNull=True, default=False)

    # useful Joins
    activity = MultipleJoin('BugActivity', joinColumn='bug', orderBy='id')
    messages = RelatedJoin('Message', joinColumn='bug',
                           otherColumn='message',
                           intermediateTable='BugMessage')
    bugtasks = MultipleJoin('BugTask', joinColumn='bug', orderBy='id')
    productinfestations = MultipleJoin(
            'BugProductInfestation', joinColumn='bug', orderBy='id')
    packageinfestations = MultipleJoin(
            'BugPackageInfestation', joinColumn='bug', orderBy='id')
    watches = MultipleJoin('BugWatch', joinColumn='bug')
    externalrefs = MultipleJoin(
            'BugExternalRef', joinColumn='bug', orderBy='id')
    cverefs = MultipleJoin('CVERef', joinColumn='bug', orderBy='cveref')
    subscriptions = MultipleJoin(
            'BugSubscription', joinColumn='bug', orderBy='id')
    duplicates = MultipleJoin('Bug', joinColumn='duplicateof', orderBy='id')

    def followup_title(self):
        return 'Re: '+ self.title

    def subscribe(self, person, subscription):
        """See canonical.launchpad.interfaces.IBug."""
        if self.isSubscribed(person):
            raise ValueError(
                _("Person with ID %d is already subscribed to this bug") %
                person.id)

        return BugSubscription(
            bug = self.id, person = person.id, subscription = subscription)

    def unsubscribe(self, person):
        """See canonical.launchpad.interfaces.IBug."""
        pass

    def isSubscribed(self, person):
        """See canonical.launchpad.interfaces.IBug."""
        bs = BugSubscription.selectBy(bugID = self.id, personID = person.id)
        return bool(bs.count())

    def notificationRecipientAddresses(self):
        """See canonical.launchpad.interfaces.IBug."""
        emails = Set()
        for subscription in self.subscriptions:
            if subscription.subscription == dbschema.BugSubscription.CC:
                emails.update(contactEmailAddresses(subscription.person))

        if not self.private:
            # Collect implicit subscriptions. This only happens on
            # public bugs.
            for task in self.bugtasks:
                if task.assignee is not None:
                    emails.update(contactEmailAddresses(task.assignee))

                if task.product is not None:
                    owner = task.product.owner
                    emails.update(contactEmailAddresses(owner))
                else:
                    if task.sourcepackagename is not None:
                        if task.distribution is not None:
                            distribution = task.distribution
                        else:
                            distribution = task.distrorelease.distribution

                        maintainership = Maintainership.selectOneBy(
                            sourcepackagenameID = task.sourcepackagename.id,
                            distributionID = distribution.id)

                        if maintainership is not None:
                            maintainer = maintainership.maintainer
                            emails.update(contactEmailAddresses(maintainer))

        emails.update(contactEmailAddresses(self.owner))
        emails = list(emails)
        emails.sort()
        return emails


class BugDelta:
    """See canonical.launchpad.interfaces.IBugDelta."""
    implements(IBugDelta)
    def __init__(self, bug, bugurl, user, title=None, summary=None,
                 description=None, name=None, private=None, duplicateof=None,
                 external_reference=None, bugwatch=None, cveref=None,
                 bugtask_deltas=None):
        self.bug = bug
        self.bugurl = bugurl
        self.user = user
        self.title = title
        self.summary = summary
        self.description = description
        self.name = name
        self.private = private
        self.duplicateof = duplicateof
        self.external_reference = external_reference
        self.bugwatch = bugwatch
        self.cveref = cveref
        self.bugtask_deltas = bugtask_deltas

def BugFactory(addview=None, distribution=None, sourcepackagename=None,
               binarypackagename=None, product=None, comment=None,
               description=None, rfc822msgid=None, summary=None,
               datecreated=None, title=None, private=False,
               owner=None):
    """Create a bug and return it.

    Things to note when using this factory:

      * addview is not used for anything in this factory

      * if no description is passed, the comment will be used as the
        description

      * if summary is not passed then the summary will be the
        first sentence of the description

      * the submitter will be subscribed to the bug

      * if either product or distribution is specified, an appropiate
        bug task will be created
    """
    # make sure that the factory has been passed enough information
    if not (comment or description or rfc822msgid):
        raise ValueError(
            'BugFactory requires a comment, rfc822msgid or description')

    # create the bug comment if one was given
    if comment:
        if not rfc822msgid:
            rfc822msgid = make_msgid('malonedeb')

    # retrieve or create the message in the db
    msg_set = MessageSet()
    try:
        msg = msg_set.get(rfc822msgid=rfc822msgid)
    except NotFoundError:
        msg = Message(
            title=title, distribution=distribution,
            rfc822msgid=rfc822msgid, owner=owner)
        chunk = MessageChunk(
                messageID=msg.id, sequence=1, content=comment, blobID=None)

    # extract the details needed to create the bug and optional msg
    if not description:
        description = msg.contents

    # if we have been passed only a description, then we set the summary to
    # be the first paragraph of it, up to 320 characters long
    if description and not summary:
        summary = description.split('. ')[0]
        if len(summary) > 320:
            summary = summary[:320] + '...'

    if not datecreated:
        datecreated = UTC_NOW

    bug = Bug(
        title=title, summary=summary,
        description=description, private=private,
        owner=owner.id, datecreated=datecreated)

    BugSubscription(
        person=owner.id, bug=bug.id, subscription=dbschema.BugSubscription.CC)

    # link the bug to the message
    bugmsg = BugMessage(bugID=bug.id, messageID=msg.id)

    # create the task on a product if one was passed
    if product:
        BugTask(bug=bug, product=product, owner=owner)

    # create the task on a source package name if one was passed
    if distribution:
        BugTask(
            bug=bug,
            distribution=distribution,
            sourcepackagename=sourcepackagename,
            binarypackagename=binarypackagename,
            owner=owner)

    return bug


class BugSet(BugSetBase):
    implements(IBugSet)

    def __iter__(self):
        """See canonical.launchpad.interfaces.bug.IBugSet."""
        for row in Bug.select():
            yield row

    def get(self, bugid):
        """See canonical.launchpad.interfaces.bug.IBugSet."""
        return Bug.get(bugid)

    def search(self, duplicateof=None):
        """See canonical.launchpad.interfaces.bug.IBugSet."""
        return Bug.selectBy(duplicateofID=duplicateof.id)
