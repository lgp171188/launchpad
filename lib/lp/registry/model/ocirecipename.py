# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Recipe Name implementation."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeName',
    'OCIRecipeNameSet',
    ]

from storm.properties import Unicode
from storm.locals import Int
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase
from lp.registry.errors import (
    InvalidName,
    NoSuchOCIRecipeName,
    )
from lp.registry.interfaces.ocirecipename import (
    IOCIRecipeName,
    IOCIRecipeNameSet,
    )


@implementer(IOCIRecipeName)
class OCIRecipeName(StormBase):
    """See `IOCIRecipeName`."""

    __storm_table__ = "OCIRecipeName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super(OCIRecipeName, self).__init__()
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI recipe." % name)
        self.name = name


@implementer(IOCIRecipeNameSet)
class OCIRecipeNameSet:
    """See `IOCIRecipeNameSet`."""

    def __getitem__(self, name):
        """See `IOCIRecipeNameSet`."""
        return self.getByName(name)

    def getByName(self, name):
        """See `IOCIRecipeNameSet`."""
        recipe_name = IStore(OCIRecipeName).find(
            OCIRecipeName, OCIRecipeName.name == name).one()
        if recipe_name is None:
            raise NoSuchOCIRecipeName(name)
        return recipe_name

    def new(self, name):
        """See `IOCIRecipeNameSet`."""
        store = IMasterStore(OCIRecipeName)
        recipe_name = OCIRecipeName(name=name)
        store.add(recipe_name)
        return recipe_name
