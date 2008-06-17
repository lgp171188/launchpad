# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

"""Person notifications."""

__metaclass__ = type
__all__ = [
    'IPersonNotification',
    'IPersonNotificationSet',
    ]

from zope.interface import Interface
from zope.schema import Datetime, Object, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.interfaces.person import IPerson


class IPersonNotification(Interface):
    """A textual message about a change in our records about a person."""

    person = Object(
        title=_("The person who will receive this notification."),
        schema=IPerson)
    date_emailed = Datetime(
        title=_("Date emailed"),
        description=_("When was the notification sent? None, if it hasn't"
                      " been sent yet."),
        required=False)
    date_created = Datetime(title=_("Date created"))
    body = Text(title=_("Notification body."))
    subject = TextLine(title=_("Notification subject."))

    def destroySelf():
        """Delete this notification."""

    def send():
        """Send the notification by email."""


class IPersonNotificationSet(Interface):
    """The set of person notifications."""

    def getNotificationsToSend():
        """Return the notifications that haven't been sent yet."""

    def addNotification(person, subject, body):
        """Create a new `IPersonNotification`."""

    def getNotificationsOlderThan(time_limit):
        """Return notifications that are older than the time_limit."""
