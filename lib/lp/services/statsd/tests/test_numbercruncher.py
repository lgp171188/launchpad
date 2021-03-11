# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the stats number cruncher daemon."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import datetime

import pytz
from storm.store import Store
from testtools.matchers import (
    Equals,
    MatchesListwise,
    MatchesSetwise,
    Not,
    )
from testtools.twistedsupport import AsynchronousDeferredRunTest
import transaction
from twisted.internet import task
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import (
    BuilderCleanStatus,
    BuildStatus,
    )
from lp.buildmaster.interactor import BuilderSlave
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.tests.mock_slaves import OkSlave
from lp.code.enums import CodeImportJobState
from lp.services.database.isolation import is_transaction_in_progress
from lp.services.database.policy import DatabaseBlockedPolicy
from lp.services.log.logger import BufferLogger
from lp.services.statsd.numbercruncher import NumberCruncher
from lp.services.statsd.tests import StatsMixin
from lp.soyuz.enums import PackagePublishingStatus
from lp.testing import TestCaseWithFactory
from lp.testing.fakemethod import FakeMethod
from lp.testing.layers import ZopelessDatabaseLayer


class TestNumberCruncher(StatsMixin, TestCaseWithFactory):

    layer = ZopelessDatabaseLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=20)

    def setUp(self):
        super(TestNumberCruncher, self).setUp()
        self.setUpStats()

    def test_single_processor_counts(self):
        builder = self.factory.makeBuilder()
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(8, self.stats_client.gauge.call_count)
        for call in self.stats_client.mock.gauge.call_args_list:
            self.assertIn('386', call[0][0])

    def test_multiple_processor_counts(self):
        builder = self.factory.makeBuilder(
            processors=[getUtility(IProcessorSet).getByName('amd64')])
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(12, self.stats_client.gauge.call_count)
        i386_calls = [c for c in self.stats_client.gauge.call_args_list
                      if '386' in c[0][0]]
        amd64_calls = [c for c in self.stats_client.gauge.call_args_list
                       if 'amd64' in c[0][0]]
        self.assertEqual(8, len(i386_calls))
        self.assertEqual(4, len(amd64_calls))

    def test_correct_values_counts(self):
        for _ in range(3):
            cleaning_builder = self.factory.makeBuilder(
                processors=[getUtility(IProcessorSet).getByName('amd64')])
            cleaning_builder.setCleanStatus(BuilderCleanStatus.CLEANING)
        for _ in range(4):
            idle_builder = self.factory.makeBuilder(
                processors=[getUtility(IProcessorSet).getByName('amd64')])
            idle_builder.setCleanStatus(BuilderCleanStatus.CLEAN)
            old_build = self.factory.makeSnapBuild()
            old_build.queueBuild()
            old_build.buildqueue_record.markAsBuilding(builder=idle_builder)
            old_build.buildqueue_record.destroySelf()
        builds = []
        for _ in range(2):
            building_builder = self.factory.makeBuilder(
                processors=[getUtility(IProcessorSet).getByName('amd64')])
            building_builder.setCleanStatus(BuilderCleanStatus.CLEAN)
            build = self.factory.makeSnapBuild()
            build.queueBuild()
            build.buildqueue_record.markAsBuilding(builder=building_builder)
            builds.append(build)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager.builder_factory.update()
        # Simulate one of the builds having finished between the builder
        # factory being updated and _updateBuilderCounts being called.  (In
        # this case we count the builder as building anyway, since
        # everything is prefetched.)  We do this in an unusual way so that
        # Storm doesn't know that the object has been deleted until it tries
        # to reload it.
        Store.of(builds[1].buildqueue_record).find(
            BuildQueue, id=builds[1].buildqueue_record.id).remove()
        transaction.commit()
        manager.builder_factory.update = FakeMethod()
        manager.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(12, self.stats_client.gauge.call_count)
        calls = [c[0] for c in self.stats_client.gauge.call_args_list
                 if 'amd64' in c[0][0]]
        self.assertThat(
            calls, MatchesSetwise(
                Equals((
                    'builders,arch=amd64,env=test,status=disabled,'
                    'virtualized=True', 0)),
                Equals((
                    'builders,arch=amd64,env=test,status=building,'
                    'virtualized=True', 2)),
                Equals((
                    'builders,arch=amd64,env=test,status=idle,'
                    'virtualized=True', 4)),
                Equals((
                    'builders,arch=amd64,env=test,status=cleaning,'
                    'virtualized=True', 3))
                ))

    def test_updateBuilderStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating builder stats:",
            cruncher.logger.getLogBuffer())

    def test_updateBuilderQueues(self):
        builder = self.factory.makeBuilder(
            processors=[getUtility(IProcessorSet).getByName('amd64')])
        builder.setCleanStatus(BuilderCleanStatus.CLEANING)
        build = self.factory.makeSnapBuild()
        build.queueBuild()
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager._updateBuilderCounts = FakeMethod()
        manager.updateBuilderQueues()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesSetwise(
                Equals(('buildqueue,arch={},env=test,virtualized=True'.format(
                    build.processor.name), 1)),
                Equals(('buildqueue,arch=386,env=test,virtualized=False', 1))
                ))

    def test_updateBuilderQueues_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateBuilderQueues()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating build queue stats:",
            cruncher.logger.getLogBuffer())

    def test_updateLibrarianStats(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.updateLibrarianStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise([
                MatchesListwise([
                    Equals('librarian.total_files,env=test'),
                    Not(Equals(0)),
                    ]),
                MatchesListwise([
                    Equals('librarian.total_filesize,env=test'),
                    Not(Equals(0)),
                    ]),
                ]))
        total_files = self.stats_client.gauge.call_args_list[0][0][1]
        total_filesize = self.stats_client.gauge.call_args_list[1][0][1]

        self.factory.makeLibraryFileAlias(content=b'x' * 1000, db_only=True)
        self.factory.makeLibraryFileAlias(content=b'x' * 2000, db_only=True)
        self.stats_client.gauge.reset_mock()
        cruncher.updateLibrarianStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise([
                Equals(('librarian.total_files,env=test', total_files + 2)),
                Equals((
                    'librarian.total_filesize,env=test',
                    total_filesize + 3000,
                    )),
                ]))

    def test_updateLibrarianStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateLibrarianStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating librarian stats:",
            cruncher.logger.getLogBuffer())

    def test_updateCodeImportStats(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.updateCodeImportStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise([
                MatchesListwise([
                    Equals('codeimport.pending,env=test'),
                    Equals(1),
                    ]),
                MatchesListwise([
                    Equals('codeimport.overdue,env=test'),
                    Equals(1),
                    ]),
                ]))

        job = removeSecurityProxy(self.factory.makeCodeImportJob())
        job.state = CodeImportJobState.PENDING
        self.stats_client.gauge.reset_mock()
        cruncher.updateCodeImportStats()

        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise([
                MatchesListwise([
                    Equals('codeimport.pending,env=test'),
                    Equals(2),
                    ]),
                MatchesListwise([
                    Equals('codeimport.overdue,env=test'),
                    Equals(2),
                    ]),
                ]))

    def test_updateCodeImportStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateCodeImportStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating code import stats.",
            cruncher.logger.getLogBuffer())
        self.assertFalse(is_transaction_in_progress())

    def test_updatePPABuildLatencyStats(self):
        archive = self.factory.makeArchive()
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, status=PackagePublishingStatus.PUBLISHED)
        bpph.binarypackagerelease.build.updateStatus(
            BuildStatus.BUILDING, date_started=datetime.now(pytz.UTC))
        bpph.binarypackagerelease.build.updateStatus(BuildStatus.FULLYBUILT)
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.updatePPABuildLatencyStats()
        self.assertEqual(4, self.stats_client.gauge.call_count)
        # The raw values here are non-deterministic and affected
        # by the test data, so just check that the gauges exist
        keys = [x[0][0] for x in self.stats_client.gauge.call_args_list]
        gauges = [
            "ppa.startdelay,env=test",
            "ppa.uploaddelay,env=test",
            "ppa.processaccepted,env=test",
            "ppa.publishdistro,env=test"]
        for gauge in gauges:
            self.assertIn(gauge, keys)

    def test_updatePPABuildLatencyStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updatePPABuildLatencyStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while update PPA build latency stats.",
            cruncher.logger.getLogBuffer())
        self.assertFalse(is_transaction_in_progress())

    def test_startService_starts_update_queues_loop(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)

        cruncher.updateBuilderQueues = FakeMethod()

        cruncher.startService()
        advance = NumberCruncher.QUEUE_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, cruncher.updateBuilderQueues.call_count)

    def test_startService_starts_update_builders_loop(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)

        cruncher.updateBuilderStats = FakeMethod()

        cruncher.startService()
        advance = NumberCruncher.BUILDER_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, cruncher.updateBuilderStats.call_count)

    def test_startService_starts_update_librarian_loop(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)

        cruncher.updateLibrarianStats = FakeMethod()

        cruncher.startService()
        advance = NumberCruncher.LIBRARIAN_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, cruncher.updateLibrarianStats.call_count)

    def test_startService_starts_update_code_import_loop(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)

        cruncher.updateCodeImportStats = FakeMethod()

        cruncher.startService()
        advance = NumberCruncher.CODE_IMPORT_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, cruncher.updateCodeImportStats.call_count)

    def test_startService_starts_update_ppa_build_latency_loop(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)

        cruncher.updatePPABuildLatencyStats = FakeMethod()

        cruncher.startService()
        advance = NumberCruncher.PPA_LATENCY_INTERVAL + 1
        clock.advance(advance)
        self.assertNotEqual(0, cruncher.updatePPABuildLatencyStats.call_count)
