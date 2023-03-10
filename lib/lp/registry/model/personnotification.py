# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Person notifications."""

__all__ = [
    "PersonNotification",
    "PersonNotificationSet",
]

from datetime import datetime, timezone

from storm.locals import DateTime, Int, Unicode
from storm.references import Reference
from storm.store import Store
from zope.interface import implementer

from lp.registry.interfaces.personnotification import (
    IPersonNotification,
    IPersonNotificationSet,
)
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.mail.sendmail import format_address, simple_sendmail
from lp.services.propertycache import cachedproperty


@implementer(IPersonNotification)
class PersonNotification(StormBase):
    """See `IPersonNotification`."""

    __storm_table__ = "PersonNotification"
    id = Int(primary=True)
    person_id = Int("person", allow_none=False)
    person = Reference(person_id, "Person.id")

    date_created = DateTime(
        tzinfo=timezone.utc,
        name="date_created",
        allow_none=False,
        default=UTC_NOW,
    )
    date_emailed = DateTime(
        tzinfo=timezone.utc, name="date_emailed", allow_none=True
    )

    body = Unicode(name="body", allow_none=False)
    subject = Unicode(name="subject", allow_none=False)

    def __init__(self, person, subject, body):
        self.person = person
        self.subject = subject
        self.body = body

    @cachedproperty
    def to_addresses(self):
        """See `IPersonNotification`."""
        if self.person.is_team:
            return self.person.getTeamAdminsEmailAddresses()
        elif self.person.preferredemail is None:
            return []
        else:
            return [
                format_address(
                    self.person.displayname, self.person.preferredemail.email
                )
            ]

    @property
    def can_send(self):
        """See `IPersonNotification`."""
        return len(self.to_addresses) > 0

    def send(self, logger=None):
        """See `IPersonNotification`."""
        if not self.can_send:
            raise AssertionError(
                "Can't send a notification to a person without an email."
            )
        to_addresses = self.to_addresses
        if logger:
            logger.info("Sending notification to %r." % to_addresses)
        from_addr = config.canonical.bounce_address
        simple_sendmail(from_addr, to_addresses, self.subject, self.body)
        self.date_emailed = datetime.now(timezone.utc)

    def destroySelf(self):
        """See `IPersonNotification`."""
        Store.of(self).remove(self)


@implementer(IPersonNotificationSet)
class PersonNotificationSet:
    """See `IPersonNotificationSet`."""

    def getNotificationsToSend(self):
        """See `IPersonNotificationSet`."""
        store = IStore(PersonNotification)
        return store.find(
            PersonNotification, PersonNotification.date_emailed == None
        ).order_by(PersonNotification.date_created, PersonNotification.id)

    def addNotification(self, person, subject, body):
        """See `IPersonNotificationSet`."""
        return PersonNotification(person=person, subject=subject, body=body)

    def getNotificationsOlderThan(self, time_limit):
        """See `IPersonNotificationSet`."""
        store = IStore(PersonNotification)
        return store.find(
            PersonNotification, PersonNotification.date_created < time_limit
        )
