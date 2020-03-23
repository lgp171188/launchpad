# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Registry credentials for use by an `OCIPushRule`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIPushRule',
    'OCIPushRuleSet',
    ]

from storm.locals import (
    Int,
    Reference,
    Storm,
    Unicode,
    )
from zope.interface import implementer

from lp.oci.interfaces.ocipushrule import (
    IOCIPushRule,
    IOCIPushRuleSet,
    )
from lp.services.database.interfaces import IStore


@implementer(IOCIPushRule)
class OCIPushRule(Storm):

    __storm_table__ = 'OCIPushRule'

    id = Int(primary=True)

    recipe_id = Int(name='recipe', allow_none=False)
    recipe = Reference(recipe_id, 'OCIRecipe.id')

    registry_credentials_id = Int(
        name='registry_credentials', allow_none=False)
    registry_credentials = Reference(
        registry_credentials_id, 'OCIRegistryCredentials.id')

    image_name = Unicode(name="image_name", allow_none=False)

    def __init__(self, recipe, registry_credentials, image_name):
        self.recipe = recipe
        self.registry_credentials = registry_credentials
        self.image_name = image_name

    def destroySelf(self):
        """See `IOCIPushRule`."""
<<<<<<< 16ae97a6453c1c6d4e298ff58b1cc50a78f4b326
        IStore(OCIPushRule).get(self.id).remove()
=======
        store = IStore(OCIPushRule)
        store.find(
            OCIPushRule, OCIPushRule.id == self).remove()
>>>>>>> Add OCIPushRule model


@implementer(IOCIPushRuleSet)
class OCIPushRuleSet:

    def new(self, recipe, registry_credentials, image_name):
        """See `IOCIPushRuleSet`."""
        return OCIPushRule(recipe, registry_credentials, image_name)
