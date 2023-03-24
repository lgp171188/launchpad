# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""BugTrackerPerson database class."""

__all__ = [
    "BugTrackerPerson",
]

from datetime import timezone

import six
from storm.locals import DateTime, Int, Reference, Unicode
from zope.interface import implementer

from lp.bugs.interfaces.bugtrackerperson import IBugTrackerPerson
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase


@implementer(IBugTrackerPerson)
class BugTrackerPerson(StormBase):
    """See `IBugTrackerPerson`."""

    __storm_table__ = "BugTrackerPerson"
    id = Int(primary=True)

    bugtracker_id = Int(name="bugtracker", allow_none=False)
    bugtracker = Reference(bugtracker_id, "BugTracker.id")

    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")

    name = Unicode(allow_none=False)

    date_created = DateTime(
        tzinfo=timezone.utc,
        name="date_created",
        allow_none=False,
        default=UTC_NOW,
    )

    def __init__(self, name, bugtracker, person):
        self.bugtracker = bugtracker
        self.person = person
        self.name = six.ensure_text(name)
