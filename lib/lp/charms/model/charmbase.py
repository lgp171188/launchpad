# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Bases for charms."""

__all__ = [
    "CharmBase",
]

from datetime import timezone

from storm.databases.postgres import JSON
from storm.locals import DateTime, Int, Reference, Store
from zope.interface import implementer

from lp.buildmaster.model.processor import Processor
from lp.charms.interfaces.charmbase import (
    DuplicateCharmBase,
    ICharmBase,
    ICharmBaseSet,
    NoSuchCharmBase,
)
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase


@implementer(ICharmBase)
class CharmBase(StormBase):
    """See `ICharmBase`."""

    __storm_table__ = "CharmBase"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    distro_series_id = Int(name="distro_series", allow_none=False)
    distro_series = Reference(distro_series_id, "DistroSeries.id")

    build_snap_channels = JSON(name="build_snap_channels", allow_none=False)

    def __init__(
        self,
        registrant,
        distro_series,
        build_snap_channels,
        date_created=DEFAULT,
    ):
        super().__init__()
        self.registrant = registrant
        self.distro_series = distro_series
        self.build_snap_channels = build_snap_channels
        self.date_created = date_created

    def _getProcessors(self):
        return list(
            Store.of(self).find(
                Processor,
                Processor.id == CharmBaseArch.processor_id,
                CharmBaseArch.charm_base == self,
            )
        )

    def setProcessors(self, processors):
        """See `ICharmBase`."""
        enablements = dict(
            Store.of(self).find(
                (Processor, CharmBaseArch),
                Processor.id == CharmBaseArch.processor_id,
                CharmBaseArch.charm_base == self,
            )
        )
        for proc in enablements:
            if proc not in processors:
                Store.of(self).remove(enablements[proc])
        for proc in processors:
            if proc not in self.processors:
                charm_base_arch = CharmBaseArch()
                charm_base_arch.charm_base = self
                charm_base_arch.processor = proc
                Store.of(self).add(charm_base_arch)

    processors = property(_getProcessors, setProcessors)

    def destroySelf(self):
        """See `ICharmBase`."""
        Store.of(self).remove(self)


class CharmBaseArch(StormBase):
    """Link table to back `CharmBase.processors`."""

    __storm_table__ = "CharmBaseArch"
    __storm_primary__ = ("charm_base_id", "processor_id")

    charm_base_id = Int(name="charm_base", allow_none=False)
    charm_base = Reference(charm_base_id, "CharmBase.id")

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")


@implementer(ICharmBaseSet)
class CharmBaseSet:
    """See `ICharmBaseSet`."""

    def new(
        self,
        registrant,
        distro_series,
        build_snap_channels,
        processors=None,
        date_created=DEFAULT,
    ):
        """See `ICharmBaseSet`."""
        try:
            self.getByDistroSeries(distro_series)
        except NoSuchCharmBase:
            pass
        else:
            raise DuplicateCharmBase(distro_series)
        store = IPrimaryStore(CharmBase)
        charm_base = CharmBase(
            registrant,
            distro_series,
            build_snap_channels,
            date_created=date_created,
        )
        store.add(charm_base)
        if processors is None:
            processors = [
                das.processor for das in distro_series.enabled_architectures
            ]
        charm_base.setProcessors(processors)
        return charm_base

    def __iter__(self):
        """See `ICharmBaseSet`."""
        return iter(self.getAll())

    def getByID(self, id):
        """See `ICharmBaseSet`."""
        return IStore(CharmBase).get(CharmBase, id)

    def getByDistroSeries(self, distro_series):
        """See `ICharmBaseSet`."""
        charm_base = (
            IStore(CharmBase)
            .find(CharmBase, distro_series=distro_series)
            .one()
        )
        if charm_base is None:
            raise NoSuchCharmBase(distro_series)
        return charm_base

    def getAll(self):
        """See `ICharmBaseSet`."""
        return (
            IStore(CharmBase)
            .find(CharmBase)
            .order_by(CharmBase.distro_series_id)
        )
