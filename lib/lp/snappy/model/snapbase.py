# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Bases for snaps."""

__all__ = [
    "SnapBase",
]

from datetime import timezone
from typing import Dict, Optional

from lazr.enum import Item
from storm.databases.postgres import JSON as PgJSON
from storm.locals import JSON, Bool, DateTime, Int, Reference, Store, Unicode
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.buildmaster.model.processor import Processor
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.person import Person
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.snappy.interfaces.snapbase import (
    CannotDeleteSnapBase,
    ISnapBase,
    ISnapBaseSet,
    NoSuchSnapBase,
    SnapBaseFeature,
)
from lp.soyuz.interfaces.archive import (
    ArchiveDependencyError,
    ComponentNotFound,
)
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.model.archive import Archive
from lp.soyuz.model.archivedependency import ArchiveDependency


@implementer(ISnapBase)
class SnapBase(StormBase):
    """See `ISnapBase`."""

    __storm_table__ = "SnapBase"

    id = Int(primary=True)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    name = Unicode(name="name", allow_none=False)

    display_name = Unicode(name="display_name", allow_none=False)

    distro_series_id = Int(name="distro_series", allow_none=False)
    distro_series = Reference(distro_series_id, "DistroSeries.id")

    build_channels = JSON(name="build_channels", allow_none=False)

    is_default = Bool(name="is_default", allow_none=False)

    _features = PgJSON(name="features", allow_none=True)

    def __init__(
        self,
        registrant,
        name,
        display_name,
        distro_series,
        build_channels,
        features: Optional[Dict[Item, bool]],
        date_created=DEFAULT,
    ):
        super().__init__()
        self.registrant = registrant
        self.name = name
        self.display_name = display_name
        self.distro_series = distro_series
        self.build_channels = build_channels
        self.date_created = date_created
        self.features = features
        self.is_default = False

    @property
    def features(self) -> Dict[Item, bool]:
        if self._features is None:
            return {}
        features = {}
        for token, is_enabled in self._features.items():
            try:
                term = SnapBaseFeature.getTermByToken(token)
            except LookupError:
                continue
            features[term.value] = is_enabled
        return features

    @features.setter
    def features(self, value: Optional[Dict[Item, bool]]) -> None:
        features = {}
        for item, is_enabled in (value or {}).items():
            features[item.title] = is_enabled
        self._features = features

    def _getProcessors(self):
        return list(
            Store.of(self).find(
                Processor,
                Processor.id == SnapBaseArch.processor_id,
                SnapBaseArch.snap_base == self,
            )
        )

    def setProcessors(self, processors):
        """See `ISnapBase`."""
        enablements = dict(
            Store.of(self).find(
                (Processor, SnapBaseArch),
                Processor.id == SnapBaseArch.processor_id,
                SnapBaseArch.snap_base == self,
            )
        )
        for proc in enablements:
            if proc not in processors:
                Store.of(self).remove(enablements[proc])
        for proc in processors:
            if proc not in self.processors:
                snap_base_arch = SnapBaseArch()
                snap_base_arch.snap_base = self
                snap_base_arch.processor = proc
                Store.of(self).add(snap_base_arch)

    processors = property(_getProcessors, setProcessors)

    @property
    def dependencies(self):
        """See `ISnapBase`."""
        return (
            IStore(ArchiveDependency)
            .find(
                ArchiveDependency,
                ArchiveDependency.dependency == Archive.id,
                Archive.owner == Person.id,
                ArchiveDependency.snap_base == self,
            )
            .order_by(Person.display_name)
        )

    def getArchiveDependency(self, dependency):
        """See `ISnapBase`."""
        return (
            IStore(ArchiveDependency)
            .find(ArchiveDependency, snap_base=self, dependency=dependency)
            .one()
        )

    def addArchiveDependency(self, dependency, pocket, component=None):
        """See `ISnapBase`."""
        archive_dependency = self.getArchiveDependency(dependency)
        if archive_dependency is not None:
            raise ArchiveDependencyError(
                "This dependency is already registered."
            )
        if not dependency.enabled:
            raise ArchiveDependencyError("Dependencies must not be disabled.")

        if dependency.is_ppa:
            if pocket is not PackagePublishingPocket.RELEASE:
                raise ArchiveDependencyError(
                    "Non-primary archives only support the RELEASE pocket."
                )
            if (
                component is not None
                and component != dependency.default_component
            ):
                raise ArchiveDependencyError(
                    "Non-primary archives only support the '%s' component."
                    % dependency.default_component.name
                )
        return ArchiveDependency(
            parent=self,
            dependency=dependency,
            pocket=pocket,
            component=component,
        )

    def _addArchiveDependency(self, dependency, pocket, component=None):
        """See `ISnapBase`."""
        if isinstance(component, str):
            try:
                component = getUtility(IComponentSet)[component]
            except NotFoundError as e:
                raise ComponentNotFound(e)
        return self.addArchiveDependency(dependency, pocket, component)

    def removeArchiveDependency(self, dependency):
        """See `ISnapBase`."""
        archive_dependency = self.getArchiveDependency(dependency)
        if archive_dependency is None:
            raise ArchiveDependencyError("This dependency does not exist.")
        archive_dependency.destroySelf()

    def destroySelf(self):
        """See `ISnapBase`."""
        # Guard against unfortunate accidents.
        if self.is_default:
            raise CannotDeleteSnapBase("Cannot delete the default base.")
        Store.of(self).remove(self)


class SnapBaseArch(StormBase):
    """Link table to back `SnapArch.processors`."""

    __storm_table__ = "SnapBaseArch"
    __storm_primary__ = ("snap_base_id", "processor_id")

    snap_base_id = Int(name="snap_base", allow_none=False)
    snap_base = Reference(snap_base_id, "SnapBase.id")

    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, "Processor.id")


@implementer(ISnapBaseSet)
class SnapBaseSet:
    """See `ISnapBaseSet`."""

    def new(
        self,
        registrant,
        name,
        display_name,
        distro_series,
        build_channels,
        features,
        processors=None,
        date_created=DEFAULT,
    ):
        """See `ISnapBaseSet`."""
        store = IPrimaryStore(SnapBase)
        snap_base = SnapBase(
            registrant,
            name,
            display_name,
            distro_series,
            build_channels,
            features,
            date_created=date_created,
        )
        store.add(snap_base)
        if processors is None:
            processors = [
                das.processor for das in distro_series.enabled_architectures
            ]
        snap_base.setProcessors(processors)
        return snap_base

    def __iter__(self):
        """See `ISnapBaseSet`."""
        return iter(self.getAll())

    def __getitem__(self, name):
        """See `ISnapBaseSet`."""
        return self.getByName(name)

    def getByName(self, name):
        """See `ISnapBaseSet`."""
        snap_base = (
            IStore(SnapBase).find(SnapBase, SnapBase.name == name).one()
        )
        if snap_base is None:
            raise NoSuchSnapBase(name)
        return snap_base

    def getDefault(self):
        """See `ISnapBaseSet`."""
        return IStore(SnapBase).find(SnapBase, SnapBase.is_default).one()

    def setDefault(self, snap_base):
        """See `ISnapBaseSet`."""
        previous = self.getDefault()
        if previous != snap_base:
            # We can safely remove the security proxy here, because the
            # default base is logically a property of the set even though it
            # is stored on the base.
            if previous is not None:
                removeSecurityProxy(previous).is_default = False
            if snap_base is not None:
                removeSecurityProxy(snap_base).is_default = True

    def getAll(self):
        """See `ISnapBaseSet`."""
        return IStore(SnapBase).find(SnapBase).order_by(SnapBase.name)
