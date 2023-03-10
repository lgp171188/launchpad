# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["SprintSpecification"]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Store, Unicode
from zope.interface import implementer

from lp.blueprints.enums import SprintSpecificationStatus
from lp.blueprints.interfaces.sprintspecification import ISprintSpecification
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase


@implementer(ISprintSpecification)
class SprintSpecification(StormBase):
    """A link between a sprint and a specification."""

    __storm_table__ = "SprintSpecification"

    id = Int(primary=True)

    sprint_id = Int(name="sprint", allow_none=False)
    sprint = Reference(sprint_id, "Sprint.id")
    specification_id = Int(name="specification", allow_none=False)
    specification = Reference(specification_id, "Specification.id")
    status = DBEnum(
        enum=SprintSpecificationStatus,
        allow_none=False,
        default=SprintSpecificationStatus.PROPOSED,
    )
    whiteboard = Unicode(allow_none=True, default=None)
    registrant_id = Int(
        name="registrant", validator=validate_public_person, allow_none=False
    )
    registrant = Reference(registrant_id, "Person.id")
    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=DEFAULT
    )
    decider_id = Int(
        name="decider",
        validator=validate_public_person,
        allow_none=True,
        default=None,
    )
    decider = Reference(decider_id, "Person.id")
    date_decided = DateTime(tzinfo=timezone.utc, allow_none=True, default=None)

    def __init__(self, sprint, specification, registrant):
        super().__init__()
        self.sprint = sprint
        self.specification = specification
        self.registrant = registrant

    @property
    def is_confirmed(self):
        """See ISprintSpecification."""
        return self.status == SprintSpecificationStatus.ACCEPTED

    @property
    def is_decided(self):
        """See ISprintSpecification."""
        return self.status != SprintSpecificationStatus.PROPOSED

    def acceptBy(self, decider):
        """See ISprintSpecification."""
        self.status = SprintSpecificationStatus.ACCEPTED
        self.decider = decider
        self.date_decided = UTC_NOW

    def declineBy(self, decider):
        """See ISprintSpecification."""
        self.status = SprintSpecificationStatus.DECLINED
        self.decider = decider
        self.date_decided = UTC_NOW

    def destroySelf(self):
        Store.of(self).remove(self)
