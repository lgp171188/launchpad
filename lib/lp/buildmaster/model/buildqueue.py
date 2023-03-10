# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BuildQueue",
    "BuildQueueSet",
]

import json
import logging
from datetime import datetime, timezone
from itertools import groupby
from operator import attrgetter

from storm.expr import SQL, Cast, Coalesce, Desc, Exists, Or
from storm.properties import Bool, DateTime, Int, TimeDelta, Unicode
from storm.references import Reference
from storm.store import Store
from zope.component import getSiteManager, getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.buildmaster.enums import (
    BuildFarmJobType,
    BuildQueueStatus,
    BuildStatus,
)
from lp.buildmaster.interfaces.buildfarmjob import ISpecificBuildFarmJobSource
from lp.buildmaster.interfaces.buildqueue import IBuildQueue, IBuildQueueSet
from lp.services.database.bulk import load_referencing, load_related
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import ImmutablePgJSON, JSONContains
from lp.services.features import getFeatureFlag
from lp.services.propertycache import cachedproperty, get_property_cache


def specific_build_farm_job_sources():
    """Sources for specific jobs that may run on the build farm."""
    job_sources = dict()
    # Get all components that implement the `ISpecificBuildFarmJobSource`
    # interface.
    components = getSiteManager()
    implementations = sorted(
        components.getUtilitiesFor(ISpecificBuildFarmJobSource)
    )
    # The above yields a collection of 2-tuples where the first element
    # is the name of the `BuildFarmJobType` enum and the second element
    # is the implementing class respectively.
    for job_enum_name, job_source in implementations:
        if not job_enum_name:
            continue
        job_enum = getattr(BuildFarmJobType, job_enum_name)
        job_sources[job_enum] = job_source

    return job_sources


@implementer(IBuildQueue)
class BuildQueue(StormBase):
    __storm_table__ = "BuildQueue"
    __storm_order__ = "id"

    def __init__(
        self,
        build_farm_job,
        estimated_duration=DEFAULT,
        virtualized=DEFAULT,
        processor=DEFAULT,
        builder_constraints=None,
        lastscore=None,
    ):
        super().__init__()
        self._build_farm_job = build_farm_job
        self.estimated_duration = estimated_duration
        self.virtualized = virtualized
        self.processor = processor
        self.builder_constraints = builder_constraints
        self.lastscore = lastscore
        if lastscore is None and self.specific_build is not None:
            self.score()

    id = Int(primary=True)

    _build_farm_job_id = Int(name="build_farm_job")
    _build_farm_job = Reference(_build_farm_job_id, "BuildFarmJob.id")
    status = DBEnum(enum=BuildQueueStatus, default=BuildQueueStatus.WAITING)
    date_started = DateTime(tzinfo=timezone.utc)

    builder_id = Int(name="builder", default=None)
    builder = Reference(builder_id, "Builder.id")
    logtail = Unicode(name="logtail", default=None)
    lastscore = Int(name="lastscore", default=0)
    manual = Bool(name="manual", default=False)
    estimated_duration = TimeDelta()
    processor_id = Int(name="processor")
    processor = Reference(processor_id, "Processor.id")
    virtualized = Bool(name="virtualized")
    builder_constraints = ImmutablePgJSON(
        name="builder_constraints", allow_none=True
    )

    @property
    def specific_source(self):
        """See `IBuildQueue`."""
        return specific_build_farm_job_sources()[self._build_farm_job.job_type]

    @cachedproperty
    def specific_build(self):
        """See `IBuildQueue`."""
        return self.specific_source.getByBuildFarmJob(self._build_farm_job)

    @property
    def build_cookie(self):
        """See `IBuildQueue`."""
        return self.specific_build.build_cookie

    def _clear_specific_build_cache(self):
        del get_property_cache(self).specific_build

    @staticmethod
    def preloadSpecificBuild(queues):
        from lp.buildmaster.model.buildfarmjob import BuildFarmJob

        queues = [removeSecurityProxy(bq) for bq in queues]
        load_related(BuildFarmJob, queues, ["_build_farm_job_id"])
        bfj_to_bq = {bq._build_farm_job: bq for bq in queues}
        key = attrgetter("_build_farm_job.job_type")
        for job_type, group in groupby(sorted(queues, key=key), key=key):
            source = getUtility(ISpecificBuildFarmJobSource, job_type.name)
            builds = source.getByBuildFarmJobs(
                [bq._build_farm_job for bq in group]
            )
            for build in builds:
                bq = bfj_to_bq[removeSecurityProxy(build).build_farm_job]
                get_property_cache(bq).specific_build = build

    @property
    def current_build_duration(self):
        """See `IBuildQueue`."""
        date_started = self.date_started
        if date_started is None:
            return None
        else:
            return self._now() - date_started

    def destroySelf(self):
        """Remove this record."""
        builder = self.builder
        specific_build = self.specific_build
        Store.of(self).remove(self)
        Store.of(self).flush()
        if builder is not None:
            del get_property_cache(builder).currentjob
        del get_property_cache(specific_build).buildqueue_record
        self._clear_specific_build_cache()

    def manualScore(self, value):
        """See `IBuildQueue`."""
        self.lastscore = value
        self.manual = True

    def score(self):
        """See `IBuildQueue`."""
        if self.manual:
            return
        # Allow the `IBuildFarmJob` instance with the data/logic specific to
        # the job at hand to calculate the score as appropriate.
        self.lastscore = self.specific_build.calculateScore()

    def markAsBuilding(self, builder):
        """See `IBuildQueue`."""
        self.builder = builder
        self.status = BuildQueueStatus.RUNNING
        self.date_started = UTC_NOW
        self.specific_build.updateStatus(BuildStatus.BUILDING, builder=builder)
        if builder is not None:
            del get_property_cache(builder).currentjob

    def suspend(self):
        """See `IBuildQueue`."""
        if self.status != BuildQueueStatus.WAITING:
            raise AssertionError("Only waiting jobs can be suspended.")
        self.status = BuildQueueStatus.SUSPENDED

    def resume(self):
        """See `IBuildQueue`."""
        if self.status != BuildQueueStatus.SUSPENDED:
            raise AssertionError("Only suspended jobs can be resumed.")
        self.status = BuildQueueStatus.WAITING

    def reset(self):
        """See `IBuildQueue`."""
        self.specific_build.emitMetric("reset")
        builder = self.builder
        self.builder = None
        self.status = BuildQueueStatus.WAITING
        self.date_started = None
        self.logtail = None
        self.specific_build.clearBuilder()
        self.specific_build.updateStatus(BuildStatus.NEEDSBUILD)
        if builder is not None:
            del get_property_cache(builder).currentjob

    def cancel(self):
        """See `IBuildQueue`."""
        if self.status == BuildQueueStatus.WAITING:
            # If the job's not yet on a worker then we can just
            # short-circuit to completed cancellation.
            self.markAsCancelled()
        elif self.status == BuildQueueStatus.RUNNING:
            # Otherwise set the statuses to CANCELLING so buildd-manager
            # can kill the worker, grab the log, and call
            # markAsCancelled() when it's done.
            self.status = BuildQueueStatus.CANCELLING
            self.specific_build.updateStatus(BuildStatus.CANCELLING)
        else:
            raise AssertionError(
                "Tried to cancel %r from %s" % (self, self.status.name)
            )

    def markAsCancelled(self):
        """See `IBuildQueue`."""
        self.specific_build.updateStatus(BuildStatus.CANCELLED)
        self.destroySelf()

    def getEstimatedJobStartTime(self, now=None):
        """See `IBuildQueue`."""
        from lp.buildmaster.queuedepth import estimate_job_start_time

        return estimate_job_start_time(self, now or self._now())

    @staticmethod
    def _now():
        """Return current time (UTC).  Overridable for test purposes."""
        return datetime.now(timezone.utc)


@implementer(IBuildQueueSet)
class BuildQueueSet:
    """Utility to deal with BuildQueue content class."""

    def get(self, buildqueue_id):
        """See `IBuildQueueSet`."""
        bq = IStore(BuildQueue).get(BuildQueue, buildqueue_id)
        if bq is None:
            raise NotFoundError(buildqueue_id)
        return bq

    def getByBuilder(self, builder):
        """See `IBuildQueueSet`."""
        return IStore(BuildQueue).find(BuildQueue, builder=builder).one()

    def preloadForBuilders(self, builders):
        # Populate builders' currentjob cachedproperty.
        queues = load_referencing(BuildQueue, builders, ["builder_id"])
        queue_builders = {queue.builder_id: queue for queue in queues}
        for builder in builders:
            cache = get_property_cache(builder)
            cache.currentjob = queue_builders.get(builder.id, None)
        return queues

    def preloadForBuildFarmJobs(self, builds):
        """See `IBuildQueueSet`."""
        from lp.buildmaster.model.builder import Builder

        bqs = list(
            IStore(BuildQueue).find(
                BuildQueue,
                BuildQueue._build_farm_job_id.is_in(
                    [removeSecurityProxy(b).build_farm_job_id for b in builds]
                ),
            )
        )
        load_related(Builder, bqs, ["builder_id"])
        prefetched_data = {
            removeSecurityProxy(buildqueue)._build_farm_job_id: buildqueue
            for buildqueue in bqs
        }
        for build in builds:
            bq = prefetched_data.get(
                removeSecurityProxy(build).build_farm_job_id
            )
            get_property_cache(build).buildqueue_record = bq
        return bqs

    def _getWorkerScannerLogger(self):
        """Return the logger instance from lp.buildmaster.manager."""
        # XXX cprov 20071120: Ideally the Launchpad logging system
        # should be able to configure the root-logger instead of creating
        # a new object, then the logger lookups won't require the specific
        # name argument anymore. See bug 164203.
        logger = logging.getLogger("worker-scanner")
        return logger

    def findBuildCandidates(
        self,
        processor,
        virtualized,
        limit,
        open_resources=None,
        restricted_resources=None,
    ):
        """See `IBuildQueueSet`."""
        # Circular import.
        from lp.buildmaster.model.buildfarmjob import BuildFarmJob

        logger = self._getWorkerScannerLogger()

        job_type_conditions = []
        job_sources = specific_build_farm_job_sources()
        for job_type, job_source in job_sources.items():
            query = job_source.addCandidateSelectionCriteria()
            if query:
                job_type_conditions.append(
                    Or(BuildFarmJob.job_type != job_type, Exists(SQL(query)))
                )

        def get_int_feature_flag(flag):
            value_str = getFeatureFlag(flag)
            if value_str is not None:
                try:
                    return int(value_str)
                except ValueError:
                    logger.error("invalid %s: %s", flag, value_str)

        score_conditions = []
        minimum_scores = set()
        if processor is not None:
            minimum_scores.add(
                get_int_feature_flag(
                    "buildmaster.minimum_score.%s" % processor.name
                )
            )
        minimum_scores.add(get_int_feature_flag("buildmaster.minimum_score"))
        minimum_scores.discard(None)
        # If there are minimum scores set for any of the processors
        # supported by this builder, use the highest of them.  This is a bit
        # weird and not completely ideal, but it's a safe conservative
        # option and avoids substantially complicating the candidate query.
        if minimum_scores:
            score_conditions.append(
                BuildQueue.lastscore >= max(minimum_scores)
            )

        builder_constraints = Coalesce(
            BuildQueue.builder_constraints, Cast("[]", "jsonb")
        )
        # All constraints on the build queue entry must be satisfied by the
        # builder's resources.
        resource_conditions = [
            JSONContains(
                Cast(
                    json.dumps(
                        (open_resources or ()) + (restricted_resources or ())
                    ),
                    "jsonb",
                ),
                builder_constraints,
            )
        ]
        # If the builder has any restricted resources, then the build queue
        # entry must specify all of them.
        if restricted_resources:
            resource_conditions.append(
                JSONContains(
                    builder_constraints,
                    Cast(json.dumps(restricted_resources), "jsonb"),
                )
            )

        store = IStore(BuildQueue)
        return list(
            store.using(BuildQueue, BuildFarmJob).find(
                BuildQueue,
                BuildFarmJob.id == BuildQueue._build_farm_job_id,
                BuildQueue.status == BuildQueueStatus.WAITING,
                BuildQueue.processor == processor,
                BuildQueue.virtualized == virtualized,
                BuildQueue.builder == None,
                *job_type_conditions,
                *score_conditions,
                *resource_conditions,
            )
            # This must match the ordering used in
            # PrefetchedBuildCandidates._getSortKey.
            .order_by(Desc(BuildQueue.lastscore), BuildQueue.id)[:limit]
        )
