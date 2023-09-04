# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "Processor",
    "ProcessorSet",
]

from storm.locals import Bool, Int, Unicode
from zope.interface import implementer

from lp.buildmaster.interfaces.processor import (
    IProcessor,
    IProcessorSet,
    ProcessorNotFound,
)
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IProcessor)
class Processor(StormBase):
    __storm_table__ = "Processor"

    id = Int(primary=True)

    name = Unicode(name="name", allow_none=False)
    title = Unicode(name="title", allow_none=False)
    description = Unicode(name="description", allow_none=False)
    restricted = Bool(allow_none=False, default=False)

    # When setting this to true you may want to add missing
    # ArchiveArches.
    build_by_default = Bool(allow_none=False, default=False)

    # This controls build creation, so you may want to create or cancel
    # some builds after changing it on an existing processor.
    supports_virtualized = Bool(allow_none=False, default=False)

    # Queued and failed builds' BuildQueue.virtualized and
    # BinaryPackageBuild.virtualized may need tweaking if this is
    # changed on an existing processor.
    supports_nonvirtualized = Bool(allow_none=False, default=True)

    def __init__(
        self,
        name,
        title,
        description,
        restricted=DEFAULT,
        build_by_default=DEFAULT,
        supports_virtualized=DEFAULT,
        supports_nonvirtualized=DEFAULT,
    ):
        super().__init__()
        self.name = name
        self.title = title
        self.description = description
        self.restricted = restricted
        self.build_by_default = build_by_default
        self.supports_virtualized = supports_virtualized
        self.supports_nonvirtualized = supports_nonvirtualized

    def __repr__(self):
        return "<Processor %r>" % self.title


@implementer(IProcessorSet)
class ProcessorSet:
    """See `IProcessorSet`."""

    def getByName(self, name):
        """See `IProcessorSet`."""
        processor = (
            IStore(Processor).find(Processor, Processor.name == name).one()
        )
        if processor is None:
            raise ProcessorNotFound(name)
        return processor

    def getAll(self):
        """See `IProcessorSet`."""
        return IStore(Processor).find(Processor)

    def new(
        self,
        name,
        title,
        description,
        restricted=False,
        build_by_default=False,
        supports_virtualized=False,
        supports_nonvirtualized=True,
    ):
        """See `IProcessorSet`."""
        processor = Processor(
            name=name,
            title=title,
            description=description,
            restricted=restricted,
            build_by_default=build_by_default,
            supports_virtualized=supports_virtualized,
            supports_nonvirtualized=supports_nonvirtualized,
        )
        return IStore(Processor).add(processor)
