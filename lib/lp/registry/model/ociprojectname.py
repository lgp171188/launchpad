# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Recipe Name implementation."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIProjectName',
    'OCIProjectNameSet',
    ]

from storm.locals import Int
from storm.properties import Unicode
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.registry.errors import (
    InvalidName,
    NoSuchOCIProjectName,
    )
from lp.registry.interfaces.ociprojectname import (
    IOCIProjectName,
    IOCIProjectNameSet,
    )
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase


@implementer(IOCIProjectName)
class OCIProjectName(StormBase):
    """See `IOCIProjectName`."""

    __storm_table__ = "OCIProjectName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super(OCIProjectName, self).__init__()
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI recipe." % name)
        self.name = name


@implementer(IOCIProjectNameSet)
class OCIProjectNameSet:
    """See `IOCIProjectNameSet`."""

    def __getitem__(self, name):
        """See `IOCIProjectNameSet`."""
        return self.getByName(name)

    def getByName(self, name):
        """See `IOCIProjectNameSet`."""
        recipe_name = IStore(OCIProjectName).find(
            OCIProjectName, OCIProjectName.name == name).one()
        if recipe_name is None:
            raise NoSuchOCIProjectName(name)
        return recipe_name

    def new(self, name):
        """See `IOCIProjectNameSet`."""
        store = IMasterStore(OCIProjectName)
        recipe_name = OCIProjectName(name=name)
        store.add(recipe_name)
        return recipe_name
