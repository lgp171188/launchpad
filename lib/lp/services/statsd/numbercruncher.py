# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Out of process statsd reporting."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = ['NumberCruncher']

import logging

import transaction
from twisted.application import service
from twisted.internet import (
    defer,
    reactor,
    )
from twisted.internet.task import LoopingCall
from twisted.python import log
from zope.component import getUtility

from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuildQueueStatus,
    )
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.manager import PrefetchedBuilderFactory
from lp.services.statsd.interfaces.statsd_client import IStatsdClient

NUMBER_CRUNCHER_LOG_NAME = "number-cruncher"


class NumberCruncher(service.Service):
    """Export statistics to statsd."""

    QUEUE_INTERVAL = 60
    BUILDER_INTERVAL = 60

    def __init__(self, clock=None, builder_factory=None):
        if clock is None:
            clock = reactor
        self._clock = clock
        self.logger = self._setupLogger()
        self.builder_factory = builder_factory or PrefetchedBuilderFactory()
        self.statsd_client = getUtility(IStatsdClient)

    def _setupLogger(self):
        """Set up a 'number-cruncher' logger that redirects to twisted.
        """
        level = logging.DEBUG
        logger = logging.getLogger(NUMBER_CRUNCHER_LOG_NAME)
        logger.propagate = False

        # Redirect the output to the twisted log module.
        channel = logging.StreamHandler(log.StdioOnnaStick())
        channel.setLevel(level)
        channel.setFormatter(logging.Formatter('%(message)s'))

        logger.addHandler(channel)
        logger.setLevel(level)
        return logger

    def _startLoop(self, interval, callback):
        """Schedule `callback` to run every `interval` seconds."""
        loop = LoopingCall(callback)
        loop.clock = self._clock
        stopping_deferred = loop.start(interval)
        return loop, stopping_deferred

    def updateBuilderQueues(self):
        """Update statsd with the build queue lengths."""
        self.logger.debug("Updating build queue stats.")
        queue_details = getUtility(IBuilderSet).getBuildQueueSizes()
        for queue_type, contents in queue_details.items():
            virt = queue_type == 'virt'
            for arch, value in contents.items():
                gauge_name = "buildqueue,virtualized={},arch={},env={}".format(
                    virt, arch, self.statsd_client.lp_environment)
                self.logger.debug("{}: {}".format(gauge_name, value[0]))
                self.statsd_client.gauge(gauge_name, value[0])
        self.logger.debug("Build queue stats update complete.")
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
                    "{},virtualized={}".format(
                        processor_name,
                        builder.virtualized),
                    {'cleaning': 0, 'idle': 0, 'disabled': 0, 'building': 0})
                if not builder.builderok:
                    counts['disabled'] += 1
                elif builder.clean_status == BuilderCleanStatus.CLEANING:
                    counts['cleaning'] += 1
                elif (builder.build_queue and
                      builder.build_queue.status == BuildQueueStatus.RUNNING):
                    counts['building'] += 1
                elif builder.clean_status == BuilderCleanStatus.CLEAN:
                    counts['idle'] += 1
        for processor, counts in counts_by_processor.items():
            for count_name, count_value in counts.items():
                gauge_name = "builders,status={},arch={},env={}".format(
                    count_name, processor, self.statsd_client.lp_environment)
                self.logger.debug("{}: {}".format(gauge_name, count_value))
                self.statsd_client.gauge(gauge_name, count_value)
        self.logger.debug("Builder stats update complete.")

    def updateBuilderStats(self):
        """Statistics that require builder knowledge to be updated."""
        self.builder_factory.update()
        self._updateBuilderCounts()
        transaction.abort()

    def startService(self):
        self.logger.info("Starting number-cruncher service.")
        self.update_queues_loop, self.update_queues_deferred = (
            self._startLoop(self.QUEUE_INTERVAL, self.updateBuilderQueues))
        self.update_builder_loop, self.update_builder_deferred = (
            self._startLoop(self.BUILDER_INTERVAL, self.updateBuilderStats))

    def stopService(self):
        deferreds = []
        deferreds.append(self.update_queues_deferred)
        deferreds.append(self.update_builder_deferred)

        self.update_queues_loop.stop()
        self.update_builder_loop.stop()

        d = defer.DeferredList(deferreds, consumeErrors=True)
        return d
