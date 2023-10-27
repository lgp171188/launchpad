# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Soyuz buildd worker manager logic."""

__all__ = [
    "BuilddManager",
    "BUILDD_MANAGER_LOG_NAME",
    "PrefetchedBuilderFactory",
    "WorkerScanner",
]

import datetime
import logging
import os.path
import shutil
from collections import defaultdict

import six
import transaction
from storm.expr import Column, LeftJoin, Table
from twisted.application import service
from twisted.internet import defer, reactor
from twisted.internet.task import LoopingCall
from twisted.python import log
from zope.component import getUtility

from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuildQueueStatus,
    BuildStatus,
)
from lp.buildmaster.interactor import BuilderInteractor, extract_vitals_from_db
from lp.buildmaster.interfaces.builder import (
    BuildDaemonError,
    BuildDaemonIsolationError,
    BuildWorkerFailure,
    CannotBuild,
    CannotFetchFile,
    CannotResumeHost,
    IBuilderSet,
)
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.builder import Builder
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.services.config import config
from lp.services.database.bulk import dbify_value
from lp.services.database.interfaces import IStore
from lp.services.database.stormexpr import BulkUpdate, Values
from lp.services.propertycache import get_property_cache
from lp.services.statsd.interfaces.statsd_client import IStatsdClient

BUILDD_MANAGER_LOG_NAME = "worker-scanner"


# The number of times the scan of a builder can fail before we start
# attributing it to the builder and job.
SCAN_FAILURE_THRESHOLD = 5

# The number of times a builder can consecutively fail before we
# reset its current job.
JOB_RESET_THRESHOLD = 3

# The number of times a builder can consecutively fail before we
# mark it builderok=False.
BUILDER_FAILURE_THRESHOLD = 5


class PrefetchedBuildCandidates:
    """A set of build candidates updated using efficient bulk queries.

    `pop` doesn't touch the DB directly.  It works from cached data updated
    by `prefetchForBuilder`.
    """

    def __init__(self, all_vitals):
        self.builder_groups = defaultdict(list)
        for vitals in all_vitals:
            for builder_group_key in self._getBuilderGroupKeys(vitals):
                self.builder_groups[builder_group_key].append(vitals)
        self.candidates = defaultdict(list)
        self.sort_keys = {}

    @staticmethod
    def _getBuilderGroupKeys(vitals):
        return [
            (
                processor_name,
                vitals.virtualized,
                vitals.restricted_resources,
                vitals.open_resources,
            )
            for processor_name in vitals.processor_names + [None]
        ]

    @staticmethod
    def _getSortKey(candidate):
        # Sort key for build candidates.  This must match the ordering used in
        # BuildQueueSet.findBuildCandidates.
        return -candidate.lastscore, candidate.id

    def _addCandidates(self, builder_group_key, candidates):
        for candidate in candidates:
            self.candidates[builder_group_key].append(candidate.id)
            self.sort_keys[candidate.id] = self._getSortKey(candidate)

    def prefetchForBuilder(self, vitals):
        """Ensure that the prefetched cache is populated for this builder."""
        missing_builder_group_keys = set(
            self._getBuilderGroupKeys(vitals)
        ) - set(self.candidates)
        if not missing_builder_group_keys:
            return
        processor_set = getUtility(IProcessorSet)
        processors_by_name = {
            processor_name: (
                processor_set.getByName(processor_name)
                if processor_name is not None
                else None
            )
            for processor_name, _, _, _ in missing_builder_group_keys
        }
        bq_set = getUtility(IBuildQueueSet)
        for builder_group_key in missing_builder_group_keys:
            (
                processor_name,
                virtualized,
                restricted_resources,
                open_resources,
            ) = builder_group_key
            self._addCandidates(
                builder_group_key,
                bq_set.findBuildCandidates(
                    processor=processors_by_name[processor_name],
                    virtualized=virtualized,
                    limit=len(self.builder_groups[builder_group_key]),
                    open_resources=open_resources,
                    restricted_resources=restricted_resources,
                ),
            )

    def pop(self, vitals):
        """Return a suitable build candidate for this builder.

        The candidate is removed from the cache, but the caller must ensure
        that it is marked as building, otherwise it will come back the next
        time the cache is updated (typically on the next scan cycle).
        """
        builder_group_keys = self._getBuilderGroupKeys(vitals)
        # Take the first entry from the pre-sorted list of candidates for
        # each builder group, and then re-sort the combined list in exactly
        # the same way.
        grouped_candidates = sorted(
            (
                (builder_group_key, self.candidates[builder_group_key][0])
                for builder_group_key in builder_group_keys
                if self.candidates[builder_group_key]
            ),
            key=lambda key_candidate: self.sort_keys[key_candidate[1]],
        )
        if grouped_candidates:
            builder_group_key, candidate_id = grouped_candidates[0]
            self.candidates[builder_group_key].pop(0)
            del self.sort_keys[candidate_id]
            return getUtility(IBuildQueueSet).get(candidate_id)
        else:
            return None


class BaseBuilderFactory:
    date_updated = None

    def update(self):
        """Update the factory's view of the world."""
        raise NotImplementedError

    def prescanUpdate(self):
        """Update the factory's view of the world before each scan."""
        raise NotImplementedError

    def __getitem__(self, name):
        """Get the named `Builder` Storm object."""
        return getUtility(IBuilderSet).getByName(name)

    def getVitals(self, name):
        """Get the named `BuilderVitals` object."""
        raise NotImplementedError

    def iterVitals(self):
        """Iterate over all `BuilderVitals` objects."""
        raise NotImplementedError

    def findBuildCandidate(self, vitals):
        """Find the next build candidate for this `BuilderVitals`, or None."""
        raise NotImplementedError

    def acquireBuildCandidate(self, vitals, builder):
        """Acquire and return a build candidate in an atomic fashion.

        If we succeed, mark it as building immediately so that it is not
        dispatched to another builder by the build manager.

        We can consider this to be atomic, because although the build
        manager is a Twisted app and gives the appearance of doing lots of
        things at once, it's still single-threaded so no more than one
        builder scan can be in this code at the same time (as long as we
        don't yield).

        If there's ever more than one build manager running at once, then
        this code will need some sort of mutex.
        """
        candidate = self.findBuildCandidate(vitals)
        if candidate is not None:
            candidate.markAsBuilding(builder)
            transaction.commit()
        return candidate


class BuilderFactory(BaseBuilderFactory):
    """A dumb builder factory that just talks to the DB."""

    def update(self):
        """See `BaseBuilderFactory`.

        For the basic BuilderFactory this is a no-op, but others might do
        something.
        """
        return

    def prescanUpdate(self):
        """See `BaseBuilderFactory`.

        For the basic BuilderFactory this means ending the transaction
        to ensure that data retrieved is up to date.
        """
        transaction.abort()

    @property
    def date_updated(self):
        return datetime.datetime.utcnow()

    def getVitals(self, name):
        """See `BaseBuilderFactory`."""
        return extract_vitals_from_db(self[name])

    def iterVitals(self):
        """See `BaseBuilderFactory`."""
        return (
            extract_vitals_from_db(b)
            for b in getUtility(IBuilderSet).__iter__()
        )

    def findBuildCandidate(self, vitals):
        """See `BaseBuilderFactory`."""
        candidates = PrefetchedBuildCandidates([vitals])
        candidates.prefetchForBuilder(vitals)
        return candidates.pop(vitals)


class PrefetchedBuilderFactory(BaseBuilderFactory):
    """A smart builder factory that does efficient bulk queries.

    `getVitals` and `iterVitals` don't touch the DB directly. They work
    from cached data updated by `update`.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # This needs to exist to avoid race conditions between
        # `updateStats` and `update`.
        self.vitals_map = {}

    def update(self):
        """See `BaseBuilderFactory`."""
        transaction.abort()
        builders_and_current_bqs = list(
            IStore(Builder)
            .using(
                Builder, LeftJoin(BuildQueue, BuildQueue.builder == Builder.id)
            )
            .find((Builder, BuildQueue))
        )
        getUtility(IBuilderSet).preloadProcessors(
            [b for b, _ in builders_and_current_bqs]
        )
        self.vitals_map = {
            b.name: extract_vitals_from_db(b, bq)
            for b, bq in builders_and_current_bqs
        }
        self.candidates = PrefetchedBuildCandidates(
            list(self.vitals_map.values())
        )
        transaction.abort()
        self.date_updated = datetime.datetime.utcnow()

    def prescanUpdate(self):
        """See `BaseBuilderFactory`.

        This is a no-op, as the data was already brought sufficiently up
        to date by update().
        """
        return

    def getVitals(self, name):
        """See `BaseBuilderFactory`."""
        return self.vitals_map[name]

    def iterVitals(self):
        """See `BaseBuilderFactory`."""
        return (b for n, b in sorted(self.vitals_map.items()))

    def findBuildCandidate(self, vitals):
        """See `BaseBuilderFactory`."""
        self.candidates.prefetchForBuilder(vitals)
        return self.candidates.pop(vitals)


def get_statsd_labels(builder, build):
    labels = {
        "builder_name": builder.name,
        "region": builder.region,
        "virtualized": str(builder.virtualized),
    }
    if build is not None:
        labels.update(
            {
                "build": True,
                "arch": build.processor.name,
                "job_type": build.job_type.name,
            }
        )
    return labels


def judge_failure(builder_count, job_count, exc, retry=True):
    """Judge how to recover from a scan failure.

    Assesses the failure counts of a builder and its current job, and
    determines the best course of action for recovery.

    :param: builder_count: Count of consecutive failures of the builder.
    :param: job_count: Count of consecutive failures of the job.
    :param: exc: Exception that caused the failure, if any.
    :param: retry: Whether to retry a few times without taking action.
    :return: A tuple of (builder action, job action). True means reset,
        False means fail, None means take no action.
    """
    if isinstance(exc, BuildDaemonIsolationError):
        # We have a potential security issue. Insta-kill both regardless
        # of any failure counts.
        return (False, False)

    if builder_count == job_count:
        # We can't tell which is to blame. Retry a few times, and then
        # reset the job so it can be retried elsewhere. If the job is at
        # fault, it'll error on the next builder and fail out. If the
        # builder is at fault, the job will work fine next time, and the
        # builder will error on the next job and fail out.
        if not retry or builder_count >= JOB_RESET_THRESHOLD:
            return (None, True)
    elif builder_count > job_count:
        # The builder has failed more than the job, so the builder is at
        # fault. We reset the job and attempt to recover the builder.
        if builder_count < BUILDER_FAILURE_THRESHOLD:
            # Let's dirty the builder and give it a few cycles to
            # recover. Since it's dirty and idle, this will
            # automatically attempt a reset if virtual.
            return (True, True)
        else:
            # We've retried too many times, so fail the builder.
            return (False, True)
    else:
        # The job has failed more than the builder. Fail it.
        return (None, False)

    # Just retry.
    return (None, None)


def recover_failure(logger, vitals, builder, retry, exception):
    """Recover from a scan failure by slapping the builder or job."""
    del get_property_cache(builder).currentjob
    job = builder.currentjob

    # If a job is being cancelled we won't bother retrying a failure.
    # Just mark it as cancelled and clear the builder for normal cleanup.
    cancelling = job is not None and job.status == BuildQueueStatus.CANCELLING

    # judge_failure decides who is guilty and their sentences. We're
    # just the executioner.
    builder_action, job_action = judge_failure(
        builder.failure_count,
        job.specific_build.failure_count if job else 0,
        exception,
        retry=retry and not cancelling,
    )
    if job is not None:
        logger.info(
            "Judged builder %s (%d failures) with job %s (%d failures): "
            "%r, %r",
            builder.name,
            builder.failure_count,
            job.build_cookie,
            job.specific_build.failure_count,
            builder_action,
            job_action,
        )
    else:
        logger.info(
            "Judged builder %s (%d failures) with no job: %r, %r",
            builder.name,
            builder.failure_count,
            builder_action,
            job_action,
        )

    statsd_client = getUtility(IStatsdClient)
    labels = get_statsd_labels(builder, job.specific_build if job else None)

    if job is not None and job_action is not None:
        if cancelling:
            # We've previously been asked to cancel the job, so just set
            # it to cancelled rather than retrying or failing.
            logger.info("Cancelling job %s.", job.build_cookie)
            statsd_client.incr("builders.failure.job_cancelled", labels=labels)
            job.markAsCancelled()
        elif job_action == False:
            # Fail and dequeue the job.
            logger.info("Failing job %s.", job.build_cookie)
            if job.specific_build.status == BuildStatus.FULLYBUILT:
                # A FULLYBUILT build should be out of our hands, and
                # probably has artifacts like binaries attached. It's
                # impossible to enter the state twice, so don't revert
                # the status. Something's wrong, so log an OOPS and get
                # it out of the queue to avoid further corruption.
                logger.warning(
                    "Build is already successful! Dequeuing but leaving build "
                    "status alone. Something is very wrong."
                )
            else:
                # Whatever it was before, we want it failed. We're an
                # error handler, so let's not risk more errors.
                job.specific_build.updateStatus(
                    BuildStatus.FAILEDTOBUILD, force_invalid_transition=True
                )
            statsd_client.incr("builders.failure.job_failed", labels=labels)
            job.destroySelf()
        elif job_action == True:
            # Reset the job so it will be retried elsewhere.
            logger.info("Requeueing job %s.", job.build_cookie)
            statsd_client.incr("builders.failure.job_reset", labels=labels)
            job.reset()

        if job_action == False:
            # We've decided the job is bad, so unblame the builder.
            logger.info("Resetting failure count of builder %s.", builder.name)
            builder.resetFailureCount()

    if builder_action == False:
        # We've already tried resetting it enough times, so we have
        # little choice but to give up.
        logger.info("Failing builder %s.", builder.name)
        statsd_client.incr("builders.failure.builder_failed", labels=labels)
        builder.failBuilder(str(exception))
    elif builder_action == True:
        # Dirty the builder to attempt recovery. In the virtual case,
        # the dirty idleness will cause a reset, giving us a good chance
        # of recovery.
        logger.info("Dirtying builder %s to attempt recovery.", builder.name)
        statsd_client.incr("builders.failure.builder_reset", labels=labels)
        builder.setCleanStatus(BuilderCleanStatus.DIRTY)


class WorkerScanner:
    """A manager for a single builder."""

    # The interval between each poll cycle, in seconds.  We'd ideally
    # like this to be lower but 15 seems a reasonable compromise between
    # responsivity and load on the database server, since in each cycle
    # we can run quite a few queries.
    #
    # NB. This used to be as low as 5 but as more builders are added to
    # the farm this rapidly increases the query count, PG load and this
    # process's load.  It's backed off until we come up with a better
    # algorithm for polling.
    SCAN_INTERVAL = 15

    # The time before deciding that a cancelling builder has failed, in
    # seconds.  This should normally be a multiple of SCAN_INTERVAL, and
    # greater than abort_timeout in launchpad-buildd's worker BuildManager.
    CANCEL_TIMEOUT = 180

    def __init__(
        self,
        builder_name,
        builder_factory,
        manager,
        logger,
        clock=None,
        interactor_factory=BuilderInteractor,
        worker_factory=BuilderInteractor.makeWorkerFromVitals,
        behaviour_factory=BuilderInteractor.getBuildBehaviour,
    ):
        self.builder_name = builder_name
        self.builder_factory = builder_factory
        self.manager = manager
        self.logger = logger
        self.interactor_factory = interactor_factory
        self.worker_factory = worker_factory
        self.behaviour_factory = behaviour_factory
        # Use the clock if provided, so that tests can advance it.  Use the
        # reactor by default.
        if clock is None:
            clock = reactor
        self._clock = clock
        self.date_cancel = None
        self.date_scanned = None

        self.can_retry = True

        # The build and job failure counts are persisted, but we only really
        # care about the consecutive scan failure count over the space of a
        # couple of minutes, so it's okay if it resets on buildd-manager
        # restart.
        self.scan_failure_count = 0

        # We cache the build cookie, keyed on the BuildQueue, to avoid
        # hitting the DB on every scan.
        self._cached_build_cookie = None
        self._cached_build_queue = None

        self.statsd_client = getUtility(IStatsdClient)

    def startCycle(self):
        """Scan the builder and dispatch to it or deal with failures."""
        self.loop = LoopingCall(self.singleCycle)
        self.loop.clock = self._clock
        self.stopping_deferred = self.loop.start(self.SCAN_INTERVAL)
        return self.stopping_deferred

    def stopCycle(self):
        """Terminate the LoopingCall."""
        self.loop.stop()

    @defer.inlineCallbacks
    def singleCycle(self):
        # Inhibit scanning if the BuilderFactory hasn't updated since
        # the last run. This doesn't matter for the base BuilderFactory,
        # as it's always up to date, but PrefetchedBuilderFactory caches
        # heavily, and we don't want to eg. forget that we dispatched a
        # build in the previous cycle.
        if (
            self.date_scanned is not None
            and self.date_scanned > self.builder_factory.date_updated
        ):
            self.logger.debug(
                "Skipping builder %s (cache out of date)" % self.builder_name
            )
            return

        self.logger.debug("Scanning builder %s" % self.builder_name)

        try:
            yield self.scan()

            # We got through a scan without error, so reset the consecutive
            # failure count. We don't reset the persistent builder or job
            # failure counts, since the build might consistently break the
            # builder later in the build.
            self.scan_failure_count = 0
        except Exception as e:
            self._scanFailed(self.can_retry, e)

        self.logger.debug("Scan finished for builder %s" % self.builder_name)
        self.date_scanned = datetime.datetime.utcnow()

    def _scanFailed(self, retry, exc):
        """Deal with failures encountered during the scan cycle.

        1. Print the error in the log
        2. Increment and assess failure counts on the builder and job.
           If asked to retry, a single failure may not be considered fatal.
        """
        # Make sure that pending database updates are removed as it
        # could leave the database in an inconsistent state (e.g. The
        # job says it's running but the buildqueue has no builder set).
        transaction.abort()

        # If we don't recognise the exception include a stack trace with
        # the error.
        if isinstance(
            exc,
            (
                BuildWorkerFailure,
                CannotBuild,
                CannotResumeHost,
                BuildDaemonError,
                CannotFetchFile,
            ),
        ):
            self.logger.info(
                "Scanning %s failed with: %r" % (self.builder_name, exc)
            )
        else:
            self.logger.info(
                "Scanning %s failed" % self.builder_name, exc_info=exc
            )

        # Certain errors can't possibly be a glitch, and they can insta-fail
        # even if the scan phase would normally allow a retry.
        if isinstance(exc, (BuildDaemonIsolationError, CannotResumeHost)):
            retry = False

        # Decide if we need to terminate the job or reset/fail the builder.
        vitals = self.builder_factory.getVitals(self.builder_name)
        builder = self.builder_factory[self.builder_name]
        try:
            labels = get_statsd_labels(builder, builder.current_build)
            self.statsd_client.incr(
                "builders.failure.scan_failed", labels=labels
            )
            self.scan_failure_count += 1

            # To avoid counting network glitches or similar against innocent
            # builds and jobs, we allow a scan to fail a few times in a row
            # without consequence, and just retry. If we exceed the threshold,
            # we then persistently record a single failure against the build
            # and job.
            if retry and self.scan_failure_count < SCAN_FAILURE_THRESHOLD:
                self.statsd_client.incr(
                    "builders.failure.scan_retried",
                    labels={
                        "failures": str(self.scan_failure_count),
                        **labels,
                    },
                )
                return

            self.scan_failure_count = 0

            builder.gotFailure()
            if builder.current_build is not None:
                builder.current_build.gotFailure()

            recover_failure(self.logger, vitals, builder, retry, exc)
            transaction.commit()
        except Exception:
            # Catastrophic code failure! Not much we can do.
            self.logger.error(
                "Miserable failure when trying to handle failure:\n",
                exc_info=True,
            )
        finally:
            transaction.abort()

    @defer.inlineCallbacks
    def checkCancellation(self, vitals, worker):
        """See if there is a pending cancellation request.

        If the current build is in status CANCELLING then terminate it
        immediately.

        :return: A deferred which fires when this cancellation cycle is done.
        """
        if vitals.build_queue.status != BuildQueueStatus.CANCELLING:
            self.date_cancel = None
        elif self.date_cancel is None:
            self.logger.info(
                "Cancelling BuildQueue %d (%s) on %s",
                vitals.build_queue.id,
                self.getExpectedCookie(vitals),
                vitals.name,
            )
            yield worker.abort()
            self.date_cancel = self._clock.seconds() + self.CANCEL_TIMEOUT
        else:
            # The BuildFarmJob will normally set the build's status to
            # something other than CANCELLING once the builder responds to
            # the cancel request.  This timeout is in case it doesn't.
            if self._clock.seconds() < self.date_cancel:
                self.logger.info(
                    "Waiting for BuildQueue %d (%s) on %s to cancel",
                    vitals.build_queue.id,
                    self.getExpectedCookie(vitals),
                    vitals.name,
                )
            else:
                raise BuildWorkerFailure(
                    "Timeout waiting for BuildQueue %d (%s) on %s to "
                    "cancel"
                    % (
                        vitals.build_queue.id,
                        self.getExpectedCookie(vitals),
                        vitals.name,
                    )
                )

    def getExpectedCookie(self, vitals):
        """Return the build cookie expected to be held by the worker.

        Calculating this requires hitting the DB, so it's cached based
        on the current BuildQueue.
        """
        if vitals.build_queue != self._cached_build_queue:
            if vitals.build_queue is not None:
                self._cached_build_cookie = vitals.build_queue.build_cookie
            else:
                self._cached_build_cookie = None
            self._cached_build_queue = vitals.build_queue
        return self._cached_build_cookie

    def updateVersion(self, vitals, worker_status):
        """Update the DB's record of the worker version if necessary."""
        version = worker_status.get("builder_version")
        if version is not None:
            version = six.ensure_text(version)
        if version != vitals.version:
            self.builder_factory[self.builder_name].version = version
            transaction.commit()

    @defer.inlineCallbacks
    def scan(self):
        """Probe the builder and update/dispatch/collect as appropriate.

        :return: A Deferred that fires when the scan is complete.
        """
        self.builder_factory.prescanUpdate()
        vitals = self.builder_factory.getVitals(self.builder_name)
        interactor = self.interactor_factory()
        worker = self.worker_factory(vitals)
        self.can_retry = True

        if vitals.build_queue is not None:
            if vitals.clean_status != BuilderCleanStatus.DIRTY:
                # This is probably a grave bug with security implications,
                # as a worker that has a job must be cleaned afterwards.
                raise BuildDaemonIsolationError(
                    "Non-dirty builder allegedly building."
                )

            lost_reason = None
            if not vitals.builderok:
                lost_reason = "%s is disabled" % vitals.name
            else:
                worker_status = yield worker.status()
                # Ensure that the worker has the job that we think it
                # should.
                worker_cookie = worker_status.get("build_id")
                expected_cookie = self.getExpectedCookie(vitals)
                if worker_cookie != expected_cookie:
                    lost_reason = "%s is lost (expected %r, got %r)" % (
                        vitals.name,
                        expected_cookie,
                        worker_cookie,
                    )

            if lost_reason is not None:
                # The worker is either confused or disabled, so reset and
                # requeue the job. The next scan cycle will clean up the
                # worker if appropriate.
                self.logger.warning(
                    "%s. Resetting job %s.",
                    lost_reason,
                    vitals.build_queue.build_cookie,
                )
                vitals.build_queue.reset()
                transaction.commit()
                return

            yield self.checkCancellation(vitals, worker)

            # The worker and DB agree on the builder's state.  Scan the
            # worker and get the logtail, or collect the build if it's
            # ready.  Yes, "updateBuild" is a bad name.
            assert worker_status is not None
            yield interactor.updateBuild(
                vitals,
                worker,
                worker_status,
                self.builder_factory,
                self.behaviour_factory,
                self.manager,
            )
        else:
            if not vitals.builderok:
                return
            # We think the builder is idle. If it's clean, dispatch. If
            # it's dirty, clean.
            if vitals.clean_status == BuilderCleanStatus.CLEAN:
                worker_status = yield worker.status()
                if worker_status.get("builder_status") != "BuilderStatus.IDLE":
                    raise BuildDaemonIsolationError(
                        "Allegedly clean worker not idle (%r instead)"
                        % worker_status.get("builder_status")
                    )
                self.updateVersion(vitals, worker_status)
                if vitals.manual:
                    # If the builder is in manual mode, don't dispatch
                    # anything.
                    self.logger.debug(
                        "%s is in manual mode, not dispatching.", vitals.name
                    )
                    return
                # Try to find and dispatch a job. If it fails, don't attempt to
                # just retry the scan; we need to reset the job so the dispatch
                # will be reattempted.
                builder = self.builder_factory[self.builder_name]
                self.can_retry = False
                yield interactor.findAndStartJob(
                    vitals, builder, worker, self.builder_factory
                )
                if builder.currentjob is not None:
                    # After a successful dispatch we can reset the
                    # failure_count.
                    builder.resetFailureCount()
                    transaction.commit()
            else:
                # Ask the BuilderInteractor to clean the worker. It might
                # be immediately cleaned on return, in which case we go
                # straight back to CLEAN, or we might have to spin
                # through another few cycles.
                done = yield interactor.cleanWorker(
                    vitals, worker, self.builder_factory
                )
                if done:
                    builder = self.builder_factory[self.builder_name]
                    builder.setCleanStatus(BuilderCleanStatus.CLEAN)
                    self.logger.debug("%s has been cleaned.", vitals.name)
                    transaction.commit()


class BuilddManager(service.Service):
    """Main Buildd Manager service class."""

    # How often to check for new builders, in seconds.
    SCAN_BUILDERS_INTERVAL = 15

    # How often to flush logtail updates, in seconds.
    FLUSH_LOGTAILS_INTERVAL = 15

    def __init__(self, clock=None, builder_factory=None):
        # Use the clock if provided, it's so that tests can
        # advance it.  Use the reactor by default.
        if clock is None:
            clock = reactor
        self._clock = clock
        self.workers = []
        self.builder_factory = builder_factory or PrefetchedBuilderFactory()
        self.logger = self._setupLogger()
        self.current_builders = []
        self.pending_logtails = {}
        self.statsd_client = getUtility(IStatsdClient)

    def _setupLogger(self):
        """Set up a 'worker-scanner' logger that redirects to twisted.

        Make it less verbose to avoid messing too much with the old code.
        """
        level = logging.INFO
        logger = logging.getLogger(BUILDD_MANAGER_LOG_NAME)
        logger.propagate = False

        # Redirect the output to the twisted log module.
        channel = logging.StreamHandler(log.StdioOnnaStick())
        channel.setLevel(level)
        channel.setFormatter(logging.Formatter("%(message)s"))

        logger.addHandler(channel)
        logger.setLevel(level)
        return logger

    def checkForNewBuilders(self):
        """Add and return any new builders."""
        new_builders = {
            vitals.name for vitals in self.builder_factory.iterVitals()
        }
        old_builders = set(self.current_builders)
        extra_builders = new_builders.difference(old_builders)
        self.current_builders.extend(extra_builders)
        return list(extra_builders)

    def scanBuilders(self):
        """Update builders from the database and start new polling loops."""
        self.logger.debug("Refreshing builders from the database.")
        try:
            self.builder_factory.update()
            new_builders = self.checkForNewBuilders()
            self.addScanForBuilders(new_builders)
        except Exception:
            self.logger.error(
                "Failure while updating builders:\n", exc_info=True
            )
            transaction.abort()
        self.logger.debug("Builder refresh complete.")

    def addLogTail(self, build_queue_id, logtail):
        self.pending_logtails[build_queue_id] = logtail

    def flushLogTails(self):
        """Flush any pending log tail updates to the database."""
        self.logger.debug("Flushing log tail updates.")
        try:
            pending_logtails = self.pending_logtails
            self.pending_logtails = {}
            if pending_logtails:
                new_logtails = Table("new_logtails")
                new_logtails_expr = Values(
                    new_logtails.name,
                    [("buildqueue", "integer"), ("logtail", "text")],
                    [
                        [
                            dbify_value(BuildQueue.id, buildqueue_id),
                            dbify_value(BuildQueue.logtail, logtail),
                        ]
                        for buildqueue_id, logtail in pending_logtails.items()
                    ],
                )
                store = IStore(BuildQueue)
                store.execute(
                    BulkUpdate(
                        {BuildQueue.logtail: Column("logtail", new_logtails)},
                        table=BuildQueue,
                        values=new_logtails_expr,
                        where=(
                            BuildQueue.id == Column("buildqueue", new_logtails)
                        ),
                    )
                )
                transaction.commit()
        except Exception:
            self.logger.exception("Failure while flushing log tail updates:\n")
            transaction.abort()
        self.logger.debug("Flushing log tail updates complete.")

    def _startLoop(self, interval, callback):
        """Schedule `callback` to run every `interval` seconds."""
        loop = LoopingCall(callback)
        loop.clock = self._clock
        stopping_deferred = loop.start(interval)
        return loop, stopping_deferred

    def startService(self):
        """Service entry point, called when the application starts."""
        # Clear "grabbing" directory, used by
        # BuildFarmJobBehaviourBase.handleSuccess as temporary storage for
        # results of builds.  They're moved to "incoming" once they've been
        # gathered completely, so any files still here when buildd-manager
        # starts are useless, and we can easily end up with quite large
        # leftovers here if buildd-manager was restarted while gathering
        # builds.  The behaviour will recreate this directory as needed.
        try:
            shutil.rmtree(os.path.join(config.builddmaster.root, "grabbing"))
        except FileNotFoundError:
            pass
        # Add and start WorkerScanners for each current builder, and any
        # added in the future.
        self.scan_builders_loop, self.scan_builders_deferred = self._startLoop(
            self.SCAN_BUILDERS_INTERVAL, self.scanBuilders
        )
        # Schedule bulk flushes for build queue logtail updates.
        (
            self.flush_logtails_loop,
            self.flush_logtails_deferred,
        ) = self._startLoop(self.FLUSH_LOGTAILS_INTERVAL, self.flushLogTails)

    def stopService(self):
        """Callback for when we need to shut down."""
        # XXX: lacks unit tests
        # All the WorkerScanner objects need to be halted gracefully.
        deferreds = [worker.stopping_deferred for worker in self.workers]
        deferreds.append(self.scan_builders_deferred)
        deferreds.append(self.flush_logtails_deferred)

        self.flush_logtails_loop.stop()
        self.scan_builders_loop.stop()
        for worker in self.workers:
            worker.stopCycle()

        # The 'stopping_deferred's are called back when the loops are
        # stopped, so we can wait on them all at once here before
        # exiting.
        d = defer.DeferredList(deferreds, consumeErrors=True)
        return d

    def addScanForBuilders(self, builders):
        """Set up scanner objects for the builders specified."""
        for builder in builders:
            worker_scanner = WorkerScanner(
                builder, self.builder_factory, self, self.logger
            )
            self.workers.append(worker_scanner)
            worker_scanner.startCycle()

        # Return the worker list for the benefit of tests.
        return self.workers
