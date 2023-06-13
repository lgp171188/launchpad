# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "Builder",
    "BuilderProcessor",
    "BuilderSet",
]

import re
from datetime import timezone

from storm.expr import Coalesce, Count, Sum
from storm.properties import Bool, DateTime, Int, Unicode
from storm.references import Reference
from storm.store import Store
from zope.component import getUtility
from zope.interface import implementer

from lp.app.errors import IncompatibleArguments, NotFoundError
from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuilderResetProtocol,
    BuildQueueStatus,
)
from lp.buildmaster.interfaces.builder import IBuilder, IBuilderSet
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSet
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.model.processor import Processor
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.bulk import load, load_related
from lp.services.database.constants import UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStandbyStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import ImmutablePgJSON
from lp.services.propertycache import cachedproperty, get_property_cache

# XXX Michael Nelson 2010-01-13 bug=491330
# These dependencies on soyuz will be removed when getBuildRecords()
# is moved.
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords

region_re = re.compile(r"(^[a-z0-9][a-z0-9+.-]+)-\d+$")


@implementer(IBuilder, IHasBuildRecords)
class Builder(StormBase):
    __storm_table__ = "Builder"
    __storm_order__ = ["id"]

    id = Int(primary=True)
    url = Unicode(name="url", allow_none=False)
    name = Unicode(name="name", allow_none=False)
    title = Unicode(name="title", allow_none=False)
    owner_id = Int(
        name="owner", validator=validate_public_person, allow_none=False
    )
    owner = Reference(owner_id, "Person.id")
    _builderok = Bool(name="builderok", allow_none=False)
    failnotes = Unicode(name="failnotes")
    virtualized = Bool(name="virtualized", default=True, allow_none=False)
    manual = Bool(name="manual", default=False)
    vm_host = Unicode(name="vm_host")
    open_resources = ImmutablePgJSON(name="open_resources", allow_none=True)
    restricted_resources = ImmutablePgJSON(
        name="restricted_resources", allow_none=True
    )
    active = Bool(name="active", allow_none=False, default=True)
    failure_count = Int(name="failure_count", default=0, allow_none=False)
    version = Unicode(name="version")
    clean_status = DBEnum(
        enum=BuilderCleanStatus, default=BuilderCleanStatus.DIRTY
    )
    vm_reset_protocol = DBEnum(enum=BuilderResetProtocol)
    date_clean_status_changed = DateTime(tzinfo=timezone.utc)

    def __init__(
        self,
        processors,
        url,
        name,
        title,
        owner,
        active=True,
        virtualized=True,
        vm_host=None,
        vm_reset_protocol=None,
        open_resources=None,
        restricted_resources=None,
        builderok=True,
        manual=False,
    ):
        super().__init__()
        # The processors cache starts out empty so that the processors
        # property setter doesn't issue an additional query.
        get_property_cache(self)._processors_cache = []
        self.url = url
        self.name = name
        self.title = title
        self.owner = owner
        self.active = active
        self.virtualized = virtualized
        self.vm_host = vm_host
        self.vm_reset_protocol = vm_reset_protocol
        self.open_resources = open_resources
        self.restricted_resources = restricted_resources
        self._builderok = builderok
        self.manual = manual
        # We have to add the new object to the store here (it might more
        # normally be done in BuilderSet.new), because the processors
        # property setter needs to link other objects to it.
        IStore(Builder).add(self)
        self.processors = processors

    @property
    def builderok(self):
        return self._builderok

    @builderok.setter
    def builderok(self, value):
        self._builderok = value
        if value is True:
            self.resetFailureCount()
            self.setCleanStatus(BuilderCleanStatus.DIRTY)

    def gotFailure(self):
        """See `IBuilder`."""
        self.failure_count += 1

    def resetFailureCount(self):
        """See `IBuilder`."""
        self.failure_count = 0

    @cachedproperty
    def _processors_cache(self):
        """See `IBuilder`."""
        # This _cache method is a quick hack to get a settable
        # cachedproperty, mostly for the webservice's benefit.
        return list(
            Store.of(self)
            .find(
                Processor,
                BuilderProcessor.processor_id == Processor.id,
                BuilderProcessor.builder == self,
            )
            .order_by(Processor.name)
        )

    @property
    def processors(self):
        return self._processors_cache

    @processors.setter
    def processors(self, processors):
        existing = set(self.processors)
        wanted = set(processors)
        # Enable the wanted but missing.
        for processor in wanted - existing:
            bp = BuilderProcessor()
            bp.builder = self
            bp.processor = processor
            Store.of(self).add(bp)
        # Disable the unwanted but present.
        Store.of(self).find(
            BuilderProcessor,
            BuilderProcessor.builder == self,
            BuilderProcessor.processor_id.is_in(
                processor.id for processor in existing - wanted
            ),
        ).remove()
        del get_property_cache(self)._processors_cache

    @property
    def processor(self):
        """See `IBuilder`."""
        try:
            return self.processors[0]
        except IndexError:
            return None

    @processor.setter
    def processor(self, processor):
        self.processors = [processor]

    @cachedproperty
    def currentjob(self):
        """See IBuilder"""
        return getUtility(IBuildQueueSet).getByBuilder(self)

    @property
    def current_build(self):
        if self.currentjob is None:
            return None
        return self.currentjob.specific_build

    def setCleanStatus(self, status):
        """See `IBuilder`."""
        if status != self.clean_status:
            self.clean_status = status
            self.date_clean_status_changed = UTC_NOW

    def failBuilder(self, reason):
        """See IBuilder"""
        # XXX cprov 2007-04-17: ideally we should be able to notify the
        # the buildd-admins about FAILED builders. One alternative is to
        # make the buildd_cronscript (worker-scanner, in this case) to exit
        # with error, for those cases buildd-sequencer automatically sends
        # an email to admins with the script output.
        self.builderok = False
        self.failnotes = reason

    def getBuildRecords(
        self,
        build_state=None,
        name=None,
        pocket=None,
        arch_tag=None,
        user=None,
        binary_only=True,
    ):
        """See IHasBuildRecords."""
        if binary_only:
            return getUtility(IBinaryPackageBuildSet).getBuildsForBuilder(
                self.id, build_state, name, pocket, arch_tag, user
            )
        else:
            if arch_tag is not None or name is not None or pocket is not None:
                raise IncompatibleArguments(
                    "The 'arch_tag', 'name', and 'pocket' parameters can be "
                    "used only with binary_only=True."
                )
            return getUtility(IBuildFarmJobSet).getBuildsForBuilder(
                self, status=build_state, user=user
            )

    @property
    def region(self):
        region_match = region_re.match(self.name)
        return region_match.group(1) if region_match is not None else ""


class BuilderProcessor(StormBase):
    __storm_table__ = "BuilderProcessor"
    __storm_primary__ = ("builder_id", "processor_id")

    builder_id = Int(name="builder", allow_none=False)
    builder = Reference(builder_id, Builder.id)
    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, Processor.id)


@implementer(IBuilderSet)
class BuilderSet:
    """See IBuilderSet"""

    def __init__(self):
        self.title = "The Launchpad build farm"

    def __iter__(self):
        return iter(IStore(Builder).find(Builder))

    def getByName(self, name):
        """See IBuilderSet."""
        return IStore(Builder).find(Builder, name=name).one()

    def __getitem__(self, name):
        return self.getByName(name)

    def new(
        self,
        processors,
        url,
        name,
        title,
        owner,
        active=True,
        virtualized=False,
        vm_host=None,
        vm_reset_protocol=None,
        open_resources=None,
        restricted_resources=None,
        manual=True,
    ):
        """See IBuilderSet."""
        return Builder(
            processors=processors,
            url=url,
            name=name,
            title=title,
            owner=owner,
            active=active,
            virtualized=virtualized,
            vm_host=vm_host,
            vm_reset_protocol=vm_reset_protocol,
            open_resources=open_resources,
            restricted_resources=restricted_resources,
            builderok=True,
            manual=manual,
        )

    def get(self, builder_id):
        """See IBuilderSet."""
        builder = IStore(Builder).get(Builder, builder_id)
        if builder is None:
            raise NotFoundError(builder_id)
        return builder

    def count(self):
        """See IBuilderSet."""
        return IStore(Builder).find(Builder).count()

    def preloadProcessors(self, builders):
        """See `IBuilderSet`."""
        # Grab (Builder.id, Processor.id) pairs and stuff them into the
        # Builders' processor caches.
        store = IStore(BuilderProcessor)
        builders_by_id = {b.id: b for b in builders}
        pairs = list(
            store.using(BuilderProcessor, Processor)
            .find(
                (BuilderProcessor.builder_id, BuilderProcessor.processor_id),
                BuilderProcessor.processor_id == Processor.id,
                BuilderProcessor.builder_id.is_in(builders_by_id),
            )
            .order_by(BuilderProcessor.builder_id, Processor.name)
        )
        load(Processor, [pid for bid, pid in pairs])
        for builder in builders:
            get_property_cache(builder)._processors_cache = []
        for bid, pid in pairs:
            cache = get_property_cache(builders_by_id[bid])
            cache._processors_cache.append(store.get(Processor, pid))

    def getBuilders(self):
        """See IBuilderSet."""
        from lp.registry.model.person import Person

        rs = (
            IStore(Builder)
            .find(Builder, Builder.active == True)
            .order_by(Builder.virtualized, Builder.name)
        )

        def preload(rows):
            self.preloadProcessors(rows)
            load_related(Person, rows, ["owner_id"])
            bqs = getUtility(IBuildQueueSet).preloadForBuilders(rows)
            BuildQueue.preloadSpecificBuild(bqs)

        return DecoratedResultSet(rs, pre_iter_hook=preload)

    def getBuildQueueSizes(self):
        """See `IBuilderSet`."""
        # XXX cjwatson 2022-11-18: We should probably also expose
        # resource-dependent queue sizes, but we need to work out how best
        # to represent that.
        results = (
            IStandbyStore(BuildQueue)
            .find(
                (
                    Count(),
                    Sum(BuildQueue.estimated_duration),
                    Processor,
                    Coalesce(BuildQueue.virtualized, True),
                ),
                Processor.id == BuildQueue.processor_id,
                BuildQueue.status == BuildQueueStatus.WAITING,
            )
            .group_by(Processor, Coalesce(BuildQueue.virtualized, True))
        )

        result_dict = {"virt": {}, "nonvirt": {}}
        for size, duration, processor, virtualized in results:
            if virtualized is False:
                virt_str = "nonvirt"
            else:
                virt_str = "virt"
            result_dict[virt_str][processor.name] = (size, duration)

        return result_dict

    def getBuildersForQueue(self, processor, virtualized):
        """See `IBuilderSet`."""
        return IStore(Builder).find(
            Builder,
            Builder._builderok == True,
            Builder.virtualized == virtualized,
            BuilderProcessor.builder_id == Builder.id,
            BuilderProcessor.processor == processor,
        )
