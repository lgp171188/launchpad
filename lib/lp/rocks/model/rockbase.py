# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Bases for rocks."""

__all__ = [
    "RockBase",
]
from datetime import timezone

from storm.locals import JSON, DateTime, Int, Reference, Store, Storm
from zope.interface import implementer

from lp.buildmaster.model.processor import Processor
from lp.rocks.interfaces.rockbase import (
    DuplicateRockBase,
    IRockBase,
    IRockBaseSet,
    NoSuchRockBase,
)
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IPrimaryStore, IStore


@implementer(IRockBase)
class RockBase(Storm):
    """See `IRockBase`."""

    __storm_table__ = "RockBase"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    distro_series_id = Int(name="distro_series", allow_none=False)
    distro_series = Reference(distro_series_id, "DistroSeries.id")

    build_channels = JSON(name="build_channels", allow_none=False)

    def __init__(
        self, registrant, distro_series, build_channels, date_created=DEFAULT
    ):
        super().__init__()
        self.registrant = registrant
        self.distro_series = distro_series
        self.build_channels = build_channels
        self.date_created = date_created

    def _getProcessors(self):
        return list(
            Store.of(self).find(
                Processor,
                Processor.id == RockBaseArch.processor_id,
                RockBaseArch.rock_base == self,
            )
        )

    def setProcessors(self, processors):
        """See `IRockBase`."""
        enablements = dict(
            Store.of(self).find(
                (Processor, RockBaseArch),
                Processor.id == RockBaseArch.processor_id,
                RockBaseArch.rock_base == self,
            )
        )
        for proc in enablements:
            if proc not in processors:
                Store.of(self).remove(enablements[proc])
        for proc in processors:
            if proc not in self.processors:
                rock_base_arch = RockBaseArch()
                rock_base_arch.rock_base = self
                rock_base_arch.processor = proc
                Store.of(self).add(rock_base_arch)

    processors = property(_getProcessors, setProcessors)

    def destroySelf(self):
        """See `IRockBase`."""
        Store.of(self).remove(self)


class RockBaseArch(Storm):
    """Link table to back `RockBase.processors`."""

    __storm_table__ = "RockBaseArch"
    __storm_primary__ = ("rock_base_id", "processor_id")

    rock_base_id = Int(name="rock_base", allow_none=False)
    rock_base = Reference(rock_base_id, "RockBase.id")

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")


@implementer(IRockBaseSet)
class RockBaseSet:
    """See `IRockBaseSet`."""

    def new(
        self,
        registrant,
        distro_series,
        build_channels,
        processors=None,
        date_created=DEFAULT,
    ):
        """See `IRockBaseSet`."""
        try:
            self.getByDistroSeries(distro_series)
        except NoSuchRockBase:
            pass
        else:
            raise DuplicateRockBase(distro_series)
        store = IPrimaryStore(RockBase)
        rock_base = RockBase(
            registrant,
            distro_series,
            build_channels,
            date_created=date_created,
        )
        store.add(rock_base)
        if processors is None:
            processors = [
                das.processor for das in distro_series.enabled_architectures
            ]
        rock_base.setProcessors(processors)
        return rock_base

    def __iter__(self):
        """See `IRockBaseSet`."""
        return iter(self.getAll())

    def getByID(self, id):
        """See `IRockBaseSet`."""
        return IStore(RockBase).get(RockBase, id)

    def getByDistroSeries(self, distro_series):
        """See `IRockBaseSet`."""
        rock_base = (
            IStore(RockBase).find(RockBase, distro_series=distro_series).one()
        )
        if rock_base is None:
            raise NoSuchRockBase(distro_series)
        return rock_base

    def getAll(self):
        """See `IRockBaseSet`."""
        return (
            IStore(RockBase).find(RockBase).order_by(RockBase.distro_series_id)
        )
