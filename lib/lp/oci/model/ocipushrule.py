# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Registry credentials for use by an `OCIPushRule`."""

__all__ = [
    "OCIDistributionPushRule",
    "OCIPushRule",
    "OCIPushRuleSet",
]

from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.oci.interfaces.ocipushrule import (
    IOCIPushRule,
    IOCIPushRuleSet,
    OCIPushRuleAlreadyExists,
)
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IOCIPushRule)
class OCIPushRule(StormBase):
    __storm_table__ = "OCIPushRule"

    id = Int(primary=True)

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "OCIRecipe.id")

    registry_credentials_id = Int(
        name="registry_credentials", allow_none=False
    )
    registry_credentials = Reference(
        registry_credentials_id, "OCIRegistryCredentials.id"
    )

    image_name = Unicode(name="image_name", allow_none=False)

    @property
    def registry_url(self):
        return self.registry_credentials.url

    @property
    def username(self):
        return self.registry_credentials.username

    def setNewImageName(self, new_image_name):
        result = (
            IStore(OCIPushRule)
            .find(
                OCIPushRule,
                OCIPushRule.registry_credentials == self.registry_credentials,
                OCIPushRule.image_name == new_image_name,
            )
            .one()
        )
        if result:
            raise OCIPushRuleAlreadyExists()
        self.image_name = new_image_name

    def __init__(self, recipe, registry_credentials, image_name):
        self.recipe = recipe
        self.registry_credentials = registry_credentials
        self.image_name = image_name

    def destroySelf(self):
        """See `IOCIPushRule`."""
        IStore(OCIPushRule).remove(self)


@implementer(IOCIPushRule)
class OCIDistributionPushRule:
    """A non-database instance that is synthesised from data elsewhere."""

    registry_credentials = None

    def __init__(self, recipe, registry_credentials, image_name):
        self.id = None  # This is not a database instance
        self.recipe = recipe
        self.registry_credentials = registry_credentials
        self.image_name = image_name

    @property
    def registry_url(self):
        return self.registry_credentials.url

    @property
    def username(self):
        return self.registry_credentials.username


@implementer(IOCIPushRuleSet)
class OCIPushRuleSet:
    def new(self, recipe, registry_credentials, image_name):
        """See `IOCIPushRuleSet`."""
        for existing in recipe.push_rules:
            credentials_match = (
                existing.registry_credentials == registry_credentials
            )
            image_match = existing.image_name == image_name
            if credentials_match and image_match:
                raise OCIPushRuleAlreadyExists()
        push_rule = OCIPushRule(recipe, registry_credentials, image_name)
        IStore(OCIPushRule).add(push_rule)
        return push_rule

    def getByID(self, id):
        """See `IOCIPushRuleSet`."""
        return IStore(OCIPushRule).get(OCIPushRule, id)

    def findByRecipe(self, recipe):
        store = IStore(OCIPushRule)
        return store.find(OCIPushRule, OCIPushRule.recipe == recipe)

    def findByRegistryCredentials(self, credentials):
        store = IStore(OCIPushRule)
        return store.find(
            OCIPushRule, OCIPushRule.registry_credentials == credentials
        )
