# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BinaryPackageName",
    "BinaryPackageNameSet",
]

from storm.expr import Join
from storm.properties import Int, Unicode
from storm.store import EmptyResultSet
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.interfaces.binarypackagename import (
    IBinaryPackageName,
    IBinaryPackageNameSet,
)
from lp.soyuz.interfaces.publishing import active_publishing_status


@implementer(IBinaryPackageName)
class BinaryPackageName(StormBase):
    __storm_table__ = "BinaryPackageName"

    id = Int(primary=True)
    name = Unicode(name="name", allow_none=False)

    def __init__(self, name):
        super().__init__()
        self.name = name

    def __str__(self):
        return self.name

    def __repr__(self):
        return "<BinaryPackageName at %X name=%r>" % (id(self), self.name)


@implementer(IBinaryPackageNameSet)
class BinaryPackageNameSet:
    def __getitem__(self, name):
        """See `IBinaryPackageNameSet`."""
        bpn = (
            IStore(BinaryPackageName).find(BinaryPackageName, name=name).one()
        )
        if bpn is None:
            raise NotFoundError(name)
        return bpn

    def getAll(self):
        """See `IBinaryPackageNameSet`."""
        return IStore(BinaryPackageName).find(BinaryPackageName)

    def queryByName(self, name):
        return (
            IStore(BinaryPackageName).find(BinaryPackageName, name=name).one()
        )

    def new(self, name):
        bpn = BinaryPackageName(name=name)
        store = IStore(BinaryPackageName)
        store.add(bpn)
        store.flush()
        return bpn

    def ensure(self, name):
        """Ensure that the given BinaryPackageName exists, creating it
        if necessary.

        Returns the BinaryPackageName
        """
        try:
            return self[name]
        except NotFoundError:
            return self.new(name)

    getOrCreateByName = ensure

    def getNotNewByNames(self, name_ids, distroseries, archive_ids):
        """See `IBinaryPackageNameSet`."""
        # Circular imports.
        from lp.soyuz.model.distroarchseries import DistroArchSeries
        from lp.soyuz.model.publishing import BinaryPackagePublishingHistory

        if len(name_ids) == 0:
            return EmptyResultSet()

        return (
            IStore(BinaryPackagePublishingHistory)
            .using(
                BinaryPackagePublishingHistory,
                Join(
                    BinaryPackageName,
                    BinaryPackagePublishingHistory.binarypackagename_id
                    == BinaryPackageName.id,
                ),
                Join(
                    DistroArchSeries,
                    BinaryPackagePublishingHistory.distroarchseries_id
                    == DistroArchSeries.id,
                ),
            )
            .find(
                BinaryPackageName,
                DistroArchSeries.distroseries == distroseries,
                BinaryPackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
                BinaryPackagePublishingHistory.archive_id.is_in(archive_ids),
                BinaryPackagePublishingHistory.binarypackagename_id.is_in(
                    name_ids
                ),
            )
            .config(distinct=True)
        )
