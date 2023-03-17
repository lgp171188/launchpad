# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Out of process statsd reporting."""

__all__ = ["NumberCruncher"]

import logging
from datetime import datetime, timezone

import transaction
from storm.expr import Count, Sum
from twisted.application import service
from twisted.internet import defer, reactor
from twisted.internet.task import LoopingCall
from twisted.python import log
from zope.component import getUtility

from lp.buildmaster.enums import BuilderCleanStatus
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.manager import PrefetchedBuilderFactory
from lp.code.enums import CodeImportJobState
from lp.code.model.codeimportjob import CodeImportJob
from lp.services.database.interfaces import IStore
from lp.services.librarian.model import LibraryFileContent
from lp.services.statsd.interfaces.statsd_client import IStatsdClient
from lp.soyuz.model.archive import Archive

NUMBER_CRUNCHER_LOG_NAME = "number-cruncher"


class NumberCruncher(service.Service):
    """Export statistics to statsd."""

    QUEUE_INTERVAL = 60
    BUILDER_INTERVAL = 60
    LIBRARIAN_INTERVAL = 3600
    CODE_IMPORT_INTERVAL = 60
    PPA_LATENCY_INTERVAL = 3600

    def __init__(self, clock=None, builder_factory=None):
        if clock is None:
            clock = reactor
        self._clock = clock
        self.logger = self._setupLogger()
        self.builder_factory = builder_factory or PrefetchedBuilderFactory()
        self.statsd_client = getUtility(IStatsdClient)

    def _setupLogger(self):
        """Set up a 'number-cruncher' logger that redirects to twisted."""
        level = logging.DEBUG
        logger = logging.getLogger(NUMBER_CRUNCHER_LOG_NAME)
        logger.propagate = False

        # Redirect the output to the twisted log module.
        channel = logging.StreamHandler(log.StdioOnnaStick())
        channel.setLevel(level)
        channel.setFormatter(logging.Formatter("%(message)s"))

        logger.addHandler(channel)
        logger.setLevel(level)
        return logger

    def _startLoop(self, interval, callback):
        """Schedule `callback` to run every `interval` seconds."""
        loop = LoopingCall(callback)
        loop.clock = self._clock
        stopping_deferred = loop.start(interval)
        return loop, stopping_deferred

    def _sendGauge(self, gauge_name, value, labels=None):
        if value is None:
            return
        self.logger.debug(
            "{}: {}".format(
                self.statsd_client.composeMetric(gauge_name, labels), value
            )
        )
        self.statsd_client.gauge(gauge_name, value, labels=labels)

    def updateBuilderQueues(self):
        """Update statsd with the build queue lengths.

        This aborts the current transaction before returning.
        """
        self.logger.debug("Updating build queue stats.")
        try:
            queue_details = getUtility(IBuilderSet).getBuildQueueSizes()
            for queue_type, contents in queue_details.items():
                virt = queue_type == "virt"
                for arch, value in contents.items():
                    self._sendGauge(
                        "buildqueue",
                        value[0],
                        labels={"virtualized": virt, "arch": arch},
                    )
            self.logger.debug("Build queue stats update complete.")
        except Exception:
            self.logger.exception("Failure while updating build queue stats:")
        transaction.abort()

    def _updateBuilderCounts(self):
        """Update statsd with the builder statuses.

        Requires the builder_factory to be updated.
        """
        self.logger.debug("Updating builder stats.")
        counts_by_processor = {}
        for builder in self.builder_factory.iterVitals():
            if not builder.active:
                continue
            for processor_name in builder.processor_names:
                counts = counts_by_processor.setdefault(
                    (processor_name, builder.virtualized),
                    {"cleaning": 0, "idle": 0, "disabled": 0, "building": 0},
                )
                if not builder.builderok:
                    counts["disabled"] += 1
                elif builder.clean_status == BuilderCleanStatus.CLEANING:
                    counts["cleaning"] += 1
                elif builder.build_queue:
                    counts["building"] += 1
                elif builder.clean_status == BuilderCleanStatus.CLEAN:
                    counts["idle"] += 1
            self._sendGauge(
                "builders.failure_count",
                builder.failure_count,
                labels={"builder_name": builder.name},
            )
        for (processor, virtualized), counts in counts_by_processor.items():
            for count_name, count_value in counts.items():
                self._sendGauge(
                    "builders",
                    count_value,
                    labels={
                        "status": count_name,
                        "arch": processor,
                        "virtualized": virtualized,
                    },
                )
        self.logger.debug("Builder stats update complete.")

    def updateBuilderStats(self):
        """Statistics that require builder knowledge to be updated.

        This aborts the current transaction before returning.
        """
        try:
            self.builder_factory.update()
            self._updateBuilderCounts()
        except Exception:
            self.logger.exception("Failure while updating builder stats:")
        transaction.abort()

    def updateLibrarianStats(self):
        """Update librarian statistics.

        This aborts the current transaction before returning.
        """
        try:
            self.logger.debug("Updating librarian stats.")
            store = IStore(LibraryFileContent)
            total_files, total_filesize = store.find(
                (Count(), Sum(LibraryFileContent.filesize))
            ).one()
            self._sendGauge("librarian.total_files", total_files)
            self._sendGauge("librarian.total_filesize", total_filesize)
            self.logger.debug("Librarian stats update complete.")
        except Exception:
            self.logger.exception("Failure while updating librarian stats:")
        transaction.abort()

    def updateCodeImportStats(self):
        """Update stats about code imports.

        This aborts the current transaction before returning.
        """
        try:
            self.logger.debug("Update code import stats.")
            store = IStore(CodeImportJob)
            pending = store.find(
                CodeImportJob,
                CodeImportJob.state == CodeImportJobState.PENDING,
            ).count()
            overdue = store.find(
                CodeImportJob,
                CodeImportJob.date_due < datetime.now(timezone.utc),
            ).count()
            self._sendGauge("codeimport.pending", pending)
            self._sendGauge("codeimport.overdue", overdue)
            self.logger.debug("Code import stats update complete")
        except Exception:
            self.logger.exception("Failure while updating code import stats.")
        transaction.abort()

    def updatePPABuildLatencyStats(self):
        """Update stats about build latencies.

        This aborts the current transaction before returning.
        """

        try:
            self.logger.debug("Update PPA build latency stats.")
            query = (
                """
            SELECT
                avg(extract(
                    epoch FROM bpb.date_first_dispatched - bpb.date_created)
                    )/60,
                avg(extract(
                    epoch FROM bpr.datecreated - bpb.date_finished))/60,
                avg(extract(
                    epoch FROM bpph.datecreated - bpr.datecreated))/60,
                avg(extract(
                    epoch FROM bpph.datepublished - bpph.datecreated))/60
            FROM
                archive,
                binarypackagebuild bpb,
                binarypackagepublishinghistory bpph,
                binarypackagerelease bpr
            WHERE
                archive.purpose = 2
                AND bpph.archive = archive.id
                AND bpph.archive = bpb.archive
                AND bpr.id = bpph.binarypackagerelease
                AND bpr.build = bpb.id
                AND bpb.distro_arch_series = bpph.distroarchseries
                AND bpph.datepublished >= %s
            """
                % "(NOW() at time zone 'UTC' - interval '1 hour')"
            )
            results = IStore(Archive).execute(query).get_one()
            self._sendGauge("ppa.startdelay", results[0])
            self._sendGauge("ppa.uploaddelay", results[1])
            self._sendGauge("ppa.processaccepted", results[2])
            self._sendGauge("ppa.publishdistro", results[3])
            self.logger.debug("PPA build latency stats update complete.")
        except Exception:
            self.logger.exception(
                "Failure while update PPA build latency stats."
            )
        transaction.abort()

    def startService(self):
        self.logger.info("Starting number-cruncher service.")
        self.loops = []
        self.stopping_deferreds = []
        for interval, callback in (
            (self.QUEUE_INTERVAL, self.updateBuilderQueues),
            (self.BUILDER_INTERVAL, self.updateBuilderStats),
            (self.LIBRARIAN_INTERVAL, self.updateLibrarianStats),
            (self.CODE_IMPORT_INTERVAL, self.updateCodeImportStats),
            (self.PPA_LATENCY_INTERVAL, self.updatePPABuildLatencyStats),
        ):
            loop, stopping_deferred = self._startLoop(interval, callback)
            self.loops.append(loop)
            self.stopping_deferreds.append(stopping_deferred)

    def stopService(self):
        for loop in self.loops:
            loop.stop()
        return defer.DeferredList(self.stopping_deferreds, consumeErrors=True)
