# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe subscription model."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeSubscription'
]

import pytz
from storm.properties import (
    DateTime,
    Int,
    )
from storm.references import Reference
from zope.interface import implementer

from lp.registry.interfaces.person import validate_person
from lp.registry.interfaces.role import IPersonRoles
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase
from lp.oci.interfaces.ocirecipesubscription import IOCIRecipeSubscription


@implementer(IOCIRecipeSubscription)
class OCIRecipeSubscription(StormBase):
    """A relationship between a person and an OCI recipe."""

    __storm_table__ = 'OCIRecipeSubscription'

    id = Int(primary=True)

    person_id = Int(
        "person", allow_none=False, validator=validate_person)
    person = Reference(person_id, "Person.id")

    ocirecipe_id = Int("ocirecipe", allow_none=False)
    ocirecipe = Reference(ocirecipe_id, "OCIRecipe.id")

    date_created = DateTime(allow_none=False, default=UTC_NOW, tzinfo=pytz.UTC)

    subscribed_by_id = Int(
        "subscribed_by", allow_none=False, validator=validate_person)
    subscribed_by = Reference(subscribed_by_id, "Person.id")

    def __init__(self, ocirecipe, person, subscribed_by):
        super(OCIRecipeSubscription, self).__init__()
        self.ocirecipe = ocirecipe
        self.person = person
        self.subscribed_by = subscribed_by

    def canBeUnsubscribedByUser(self, user):
        """See `IOCIRecipeSubscription`."""
        if user is None:
            return False
        return (user.inTeam(self.ocirecipe.owner) or
                user.inTeam(self.person) or
                user.inTeam(self.subscribed_by) or
                IPersonRoles(user).in_admin)
