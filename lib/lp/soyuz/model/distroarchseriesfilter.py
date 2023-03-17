# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Distro arch series filters."""

__all__ = [
    "DistroArchSeriesFilter",
]

from datetime import timezone

from storm.locals import DateTime, Int, Reference
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.soyuz.enums import DistroArchSeriesFilterSense
from lp.soyuz.interfaces.distroarchseriesfilter import (
    IDistroArchSeriesFilter,
    IDistroArchSeriesFilterSet,
)


def distro_arch_series_filter_modified(pss, event):
    """Update date_last_modified when a `DistroArchSeriesFilter` is modified.

    This method is registered as a subscriber to `IObjectModifiedEvent`
    events on `DistroArchSeriesFilter`s.
    """
    removeSecurityProxy(pss).date_last_modified = UTC_NOW


@implementer(IDistroArchSeriesFilter)
class DistroArchSeriesFilter(StormBase):
    """See `IDistroArchSeriesFilter`."""

    __storm_table__ = "DistroArchSeriesFilter"

    id = Int(primary=True)

    distroarchseries_id = Int(name="distroarchseries", allow_none=False)
    distroarchseries = Reference(distroarchseries_id, "DistroArchSeries.id")

    packageset_id = Int(name="packageset", allow_none=False)
    packageset = Reference(packageset_id, "Packageset.id")

    sense = DBEnum(enum=DistroArchSeriesFilterSense, allow_none=False)

    creator_id = Int(name="creator", allow_none=False)
    creator = Reference(creator_id, "Person.id")

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )
    date_last_modified = DateTime(
        name="date_last_modified", tzinfo=timezone.utc, allow_none=False
    )

    def __init__(
        self,
        distroarchseries,
        packageset,
        sense,
        creator,
        date_created=DEFAULT,
    ):
        """Construct a `DistroArchSeriesFilter`."""
        super().__init__()
        self.distroarchseries = distroarchseries
        self.packageset = packageset
        self.sense = sense
        self.creator = creator
        self.date_created = date_created
        self.date_last_modified = date_created

    def __repr__(self):
        return "<DistroArchSeriesFilter for %s>" % self.distroarchseries.title

    def isSourceIncluded(self, sourcepackagename):
        """See `IDistroArchSeriesFilter`."""
        return (
            self.sense == DistroArchSeriesFilterSense.INCLUDE
        ) == self.packageset.isSourceIncluded(sourcepackagename)

    def destroySelf(self):
        """See `IDistroArchSeriesFilter`."""
        IStore(DistroArchSeriesFilter).remove(self)


@implementer(IDistroArchSeriesFilterSet)
class DistroArchSeriesFilterSet:
    """See `IDistroArchSeriesFilterSet`."""

    def new(
        self,
        distroarchseries,
        packageset,
        sense,
        creator,
        date_created=DEFAULT,
    ):
        """See `IDistroArchSeriesFilterSet`.

        The caller must check that the creator has suitable permissions on
        `distroarchseries`.
        """
        store = IPrimaryStore(DistroArchSeriesFilter)
        dasf = DistroArchSeriesFilter(
            distroarchseries,
            packageset,
            sense,
            creator,
            date_created=date_created,
        )
        store.add(dasf)
        return dasf

    def getByDistroArchSeries(self, distroarchseries):
        """See `IDistroArchSeriesFilterSet`."""
        return (
            IStore(DistroArchSeriesFilter)
            .find(
                DistroArchSeriesFilter,
                DistroArchSeriesFilter.distroarchseries == distroarchseries,
            )
            .one()
        )

    def findByPackageset(self, packageset):
        return IStore(DistroArchSeriesFilter).find(
            DistroArchSeriesFilter,
            DistroArchSeriesFilter.packageset == packageset,
        )
