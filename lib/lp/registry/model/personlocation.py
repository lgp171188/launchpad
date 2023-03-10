# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for Person Location.

The location of the person includes their geographic coordinates (latitude
and longitude) and their time zone. We only store this information for
people who have provided it, so we put it in a separate table which
decorates Person.
"""

__all__ = [
    "PersonLocation",
]

from datetime import timezone

import six
from storm.locals import Bool, DateTime, Float, Int, Reference, Unicode
from zope.interface import implementer

from lp.registry.interfaces.location import IPersonLocation
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase


@implementer(IPersonLocation)
class PersonLocation(StormBase):
    """A person's location."""

    __storm_table__ = "PersonLocation"

    __storm_order__ = "id"
    id = Int(primary=True)

    date_created = DateTime(
        tzinfo=timezone.utc,
        name="date_created",
        allow_none=False,
        default=UTC_NOW,
    )

    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")

    latitude = Float(allow_none=True)
    longitude = Float(allow_none=True)
    time_zone = Unicode(allow_none=False)

    last_modified_by_id = Int(
        name="last_modified_by",
        validator=validate_public_person,
        allow_none=False,
    )
    last_modified_by = Reference(last_modified_by_id, "Person.id")

    date_last_modified = DateTime(
        tzinfo=timezone.utc,
        name="date_last_modified",
        allow_none=False,
        default=UTC_NOW,
    )

    visible = Bool(name="visible", allow_none=False, default=True)

    def __init__(
        self, person, time_zone, latitude, longitude, last_modified_by
    ):
        self.person = person
        self.time_zone = six.ensure_text(time_zone)
        self.latitude = latitude
        self.longitude = longitude
        self.last_modified_by = last_modified_by
