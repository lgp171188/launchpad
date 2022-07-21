# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCI Project Name implementation."""

__all__ = [
    "OCIProjectName",
    "OCIProjectNameSet",
]

from storm.locals import Int
from storm.properties import Unicode
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.registry.errors import InvalidName, NoSuchOCIProjectName
from lp.registry.interfaces.ociprojectname import (
    IOCIProjectName,
    IOCIProjectNameSet,
)
from lp.services.database.interfaces import IMasterStore, IStore
from lp.services.database.stormbase import StormBase


@implementer(IOCIProjectName)
class OCIProjectName(StormBase):
    """See `IOCIProjectName`."""

    __storm_table__ = "OCIProjectName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super().__init__()
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI project." % name
            )
        self.name = name


@implementer(IOCIProjectNameSet)
class OCIProjectNameSet:
    """See `IOCIProjectNameSet`."""

    def __getitem__(self, name):
        """See `IOCIProjectNameSet`."""
        return self.getByName(name)

    def getByName(self, name):
        """See `IOCIProjectNameSet`."""
        project_name = (
            IStore(OCIProjectName)
            .find(OCIProjectName, OCIProjectName.name == name)
            .one()
        )
        if project_name is None:
            raise NoSuchOCIProjectName(name)
        return project_name

    def new(self, name):
        """See `IOCIProjectNameSet`."""
        store = IMasterStore(OCIProjectName)
        project_name = OCIProjectName(name=name)
        store.add(project_name)
        return project_name

    def getOrCreateByName(self, name):
        """See `IOCIProjectNameSet`."""
        try:
            return self.getByName(name)
        except NoSuchOCIProjectName:
            return self.new(name)
