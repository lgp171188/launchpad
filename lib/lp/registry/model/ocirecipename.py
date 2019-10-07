# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'OCIRecipeName',
    'OCIRecipeNameSet',
    ]

from storm.properties import Unicode
from storm.locals import (
    Desc,
    Int,
    )
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase
from lp.registry.errors import (
    InvalidName,
    NoSuchRecipeName,
    )
from lp.registry.interfaces.ocirecipename import (
    IOCIRecipeName,
    IOCIRecipeNameSet,
    )
from lp.services.helpers import ensure_unicode


@implementer(IOCIRecipeName)
class OCIRecipeName(StormBase):

    __storm_table__ = "OCIRecipeName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super(OCIRecipeName, self).__init__()
        self.name = name


@implementer(IOCIRecipeNameSet)
class OCIRecipeNameSet:

    def __getitem__(self, name):
        """See `IOCIRecipeNameSet`."""
        return self.getByName

    def getByName(self, name):
        """See `IOCIRecipeNameSet`."""
        recipe_name  = IStore(OCIRecipeName).find(
            OCIRecipeName, OCIRecipeName.name == name).one()
        if recipe_name is None:
            raise NoSuchRecipeName(name)
        return recipe_name

    def getAll(self):
        """See `IOCIRecipeNameSet`."""
        return IStore(OCIRecipeName).find(OCIRecipeName).order_by(
            Desc(OCIRecipeName.name))

    def new(self, name):
        """See `IOCIRecipeNameSet`."""
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI recipe." % name)
        store = IMasterStore(OCIRecipeName)
        recipe_name = OCIRecipeName(name=name)
        store.add(recipe_name)
        return recipe_name
