# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap subscription model."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'SnapSubscription'
]

import pytz
from lp.registry.interfaces.person import validate_person
from lp.registry.interfaces.role import IPersonRoles
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase
from lp.snappy.interfaces.snapsubscription import ISnapSubscription
from storm.properties import Int, DateTime
from storm.references import Reference
from zope.interface import implementer


@implementer(ISnapSubscription)
class SnapSubscription(StormBase):
    """A relationship between a person and a snap recipe."""

    __storm_table__ = 'SnapSubscription'

    id = Int(primary=True)

    person_id = Int(
        "person", allow_none=False, validator=validate_person)
    person = Reference(person_id, "Person.id")

    snap_id = Int("snap", allow_none=False)
    snap = Reference(snap_id, "Snap.id")

    date_created = DateTime(allow_none=False, default=UTC_NOW, tzinfo=pytz.UTC)

    subscribed_by_id = Int(
        "subscribed_by", allow_none=False, validator=validate_person)
    subscribed_by = Reference(subscribed_by_id, "Person.id")

    def __init__(self, snap=None, person=None, subscribed_by=None):
        super(SnapSubscription, self).__init__()
        self.snap = snap
        self.person = person
        self.subscribed_by = subscribed_by

    def canBeUnsubscribedByUser(self, user):
        """See `ISnapSubscription`."""
        if user is None:
            return False
        return (user.inTeam(self.person) or
                user.inTeam(self.subscribed_by) or
                IPersonRoles(user).in_admin)
