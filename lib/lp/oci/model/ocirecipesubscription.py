# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe subscription model."""

__all__ = ["OCIRecipeSubscription"]

from datetime import timezone

from storm.properties import DateTime, Int
from storm.references import Reference
from zope.interface import implementer

from lp.oci.interfaces.ocirecipesubscription import IOCIRecipeSubscription
from lp.registry.interfaces.person import validate_person
from lp.registry.interfaces.role import IPersonRoles
from lp.services.database.constants import UTC_NOW
from lp.services.database.stormbase import StormBase


@implementer(IOCIRecipeSubscription)
class OCIRecipeSubscription(StormBase):
    """A relationship between a person and an OCI recipe."""

    __storm_table__ = "OCIRecipeSubscription"

    id = Int(primary=True)

    person_id = Int("person", allow_none=False, validator=validate_person)
    person = Reference(person_id, "Person.id")

    recipe_id = Int("recipe", allow_none=False)
    recipe = Reference(recipe_id, "OCIRecipe.id")

    date_created = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )

    subscribed_by_id = Int(
        "subscribed_by", allow_none=False, validator=validate_person
    )
    subscribed_by = Reference(subscribed_by_id, "Person.id")

    def __init__(self, recipe, person, subscribed_by):
        super().__init__()
        self.recipe = recipe
        self.person = person
        self.subscribed_by = subscribed_by

    def canBeUnsubscribedByUser(self, user):
        """See `IOCIRecipeSubscription`."""
        if user is None:
            return False
        return (
            user.inTeam(self.recipe.owner)
            or user.inTeam(self.person)
            or user.inTeam(self.subscribed_by)
            or IPersonRoles(user).in_admin
        )
