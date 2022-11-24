# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Classes for managing the NameBlocklist table."""

__all__ = [
    "NameBlocklist",
    "NameBlocklistSet",
]


from storm.locals import Int, Reference, Unicode
from zope.interface import implementer

from lp.registry.interfaces.nameblocklist import (
    INameBlocklist,
    INameBlocklistSet,
)
from lp.registry.model.person import Person
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(INameBlocklist)
class NameBlocklist(StormBase):
    """Class for the NameBlocklist table."""

    __storm_table__ = "NameBlocklist"

    id = Int(primary=True)
    regexp = Unicode(name="regexp", allow_none=False)
    comment = Unicode(name="comment", allow_none=True)
    admin_id = Int(name="admin", allow_none=True)
    admin = Reference(admin_id, Person.id)


@implementer(INameBlocklistSet)
class NameBlocklistSet:
    """Class for creating and retrieving NameBlocklist objects."""

    def getAll(self):
        """See `INameBlocklistSet`."""
        store = IStore(NameBlocklist)
        return store.find(NameBlocklist).order_by(NameBlocklist.regexp)

    def create(self, regexp, comment=None, admin=None):
        """See `INameBlocklistSet`."""
        nameblocklist = NameBlocklist()
        nameblocklist.regexp = regexp
        nameblocklist.comment = comment
        nameblocklist.admin = admin
        store = IStore(NameBlocklist)
        store.add(nameblocklist)
        return nameblocklist

    def get(self, id):
        """See `INameBlocklistSet`."""
        try:
            id = int(id)
        except ValueError:
            return None
        store = IStore(NameBlocklist)
        return store.find(NameBlocklist, NameBlocklist.id == id).one()

    def getByRegExp(self, regexp):
        """See `INameBlocklistSet`."""
        store = IStore(NameBlocklist)
        return store.find(NameBlocklist, NameBlocklist.regexp == regexp).one()
