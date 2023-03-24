# Copyright 2020-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the stats number cruncher daemon."""

from datetime import datetime, timezone

import transaction
from storm.store import Store
from testtools.matchers import Equals, MatchesListwise, MatchesSetwise, Not
from testtools.twistedsupport import AsynchronousDeferredRunTest
from twisted.internet import task
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuilderCleanStatus, BuildStatus
from lp.buildmaster.interactor import BuilderWorker
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.tests.mock_workers import OkWorker
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
        super().setUp()
        self.setUpStats()
        # Deactivate sampledata builders; we only want statistics for the
        # builders explicitly created in these tests.
        for builder in getUtility(IBuilderSet):
            builder.active = False

    def test_single_processor_counts(self):
        builder = self.factory.makeBuilder()
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        expected_gauges = [
            "builders.failure_count,builder_name=%s,env=test" % builder.name,
        ]
        expected_gauges.extend(
            [
                "builders,arch=386,env=test,status=%s,virtualized=True"
                % status
                for status in ("building", "cleaning", "disabled", "idle")
            ]
        )
        self.assertThat(
            [call[0][0] for call in self.stats_client.gauge.call_args_list],
            MatchesSetwise(
                *(Equals(gauge_name) for gauge_name in expected_gauges)
            ),
        )

    def test_multiple_processor_counts(self):
        builders = [
            self.factory.makeBuilder(
                processors=[
                    getUtility(IProcessorSet).getByName(processor_name)
                ],
                virtualized=virtualized,
            )
            for processor_name, virtualized in (
                ("386", True),
                ("386", False),
                ("amd64", True),
                ("amd64", False),
            )
        ]
        for builder in builders:
            builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        expected_gauges = [
            "builders.failure_count,builder_name=%s,env=test" % builder.name
            for builder in builders
        ]
        expected_gauges.extend(
            [
                "builders,arch=%s,env=test,status=%s,virtualized=%s"
                % (arch, status, virtualized)
                for arch in ("386", "amd64")
                for virtualized in (True, False)
                for status in ("building", "cleaning", "disabled", "idle")
            ]
        )
        self.assertThat(
            [call[0][0] for call in self.stats_client.gauge.call_args_list],
            MatchesSetwise(
                *(Equals(gauge_name) for gauge_name in expected_gauges)
            ),
        )

    def test_correct_values_counts(self):
        cleaning_builders = [
            self.factory.makeBuilder(
                processors=[getUtility(IProcessorSet).getByName("amd64")]
            )
            for _ in range(3)
        ]
        for cleaning_builder in cleaning_builders:
            cleaning_builder.gotFailure()
            cleaning_builder.setCleanStatus(BuilderCleanStatus.CLEANING)
        idle_builders = [
            self.factory.makeBuilder(
                processors=[getUtility(IProcessorSet).getByName("amd64")]
            )
            for _ in range(4)
        ]
        for idle_builder in idle_builders:
            idle_builder.setCleanStatus(BuilderCleanStatus.CLEAN)
            old_build = self.factory.makeSnapBuild()
            old_build.queueBuild()
            old_build.buildqueue_record.markAsBuilding(builder=idle_builder)
            old_build.buildqueue_record.destroySelf()
        building_builders = [
            self.factory.makeBuilder(
                processors=[getUtility(IProcessorSet).getByName("amd64")]
            )
            for _ in range(2)
        ]
        builds = []
        for building_builder in building_builders:
            building_builder.setCleanStatus(BuilderCleanStatus.CLEAN)
            build = self.factory.makeSnapBuild()
            build.queueBuild()
            build.buildqueue_record.markAsBuilding(builder=building_builder)
            builds.append(build)
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
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
            BuildQueue, id=builds[1].buildqueue_record.id
        ).remove()
        transaction.commit()
        manager.builder_factory.update = FakeMethod()
        manager.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        expected_gauges = {
            "builders.failure_count,builder_name=%s,env=test" % builder.name: 1
            for builder in cleaning_builders
        }
        expected_gauges.update(
            {
                "builders.failure_count,builder_name=%s,env=test"
                % builder.name: 0
                for builder in idle_builders + building_builders
            }
        )
        expected_gauges.update(
            {
                "builders,arch=amd64,env=test,status=%s,"
                "virtualized=True" % status: count
                for status, count in (
                    ("building", 2),
                    ("cleaning", 3),
                    ("disabled", 0),
                    ("idle", 4),
                )
            }
        )
        self.assertThat(
            [call[0] for call in self.stats_client.gauge.call_args_list],
            MatchesSetwise(
                *(
                    Equals((gauge_name, count))
                    for gauge_name, count in expected_gauges.items()
                )
            ),
        )

    def test_updateBuilderStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateBuilderStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating builder stats:",
            cruncher.logger.getLogBuffer(),
        )

    def test_updateBuilderQueues(self):
        builder = self.factory.makeBuilder(
            processors=[getUtility(IProcessorSet).getByName("amd64")]
        )
        builder.setCleanStatus(BuilderCleanStatus.CLEANING)
        build = self.factory.makeSnapBuild()
        build.queueBuild()
        self.patch(BuilderWorker, "makeBuilderWorker", FakeMethod(OkWorker()))
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
                Equals(
                    (
                        "buildqueue,arch={},env=test,virtualized=True".format(
                            build.processor.name
                        ),
                        1,
                    )
                ),
                Equals(("buildqueue,arch=386,env=test,virtualized=False", 1)),
            ),
        )

    def test_updateBuilderQueues_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateBuilderQueues()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating build queue stats:",
            cruncher.logger.getLogBuffer(),
        )

    def test_updateLibrarianStats(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.updateLibrarianStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise(
                [
                    MatchesListwise(
                        [
                            Equals("librarian.total_files,env=test"),
                            Not(Equals(0)),
                        ]
                    ),
                    MatchesListwise(
                        [
                            Equals("librarian.total_filesize,env=test"),
                            Not(Equals(0)),
                        ]
                    ),
                ]
            ),
        )
        total_files = self.stats_client.gauge.call_args_list[0][0][1]
        total_filesize = self.stats_client.gauge.call_args_list[1][0][1]

        self.factory.makeLibraryFileAlias(content=b"x" * 1000, db_only=True)
        self.factory.makeLibraryFileAlias(content=b"x" * 2000, db_only=True)
        self.stats_client.gauge.reset_mock()
        cruncher.updateLibrarianStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise(
                [
                    Equals(
                        ("librarian.total_files,env=test", total_files + 2)
                    ),
                    Equals(
                        (
                            "librarian.total_filesize,env=test",
                            total_filesize + 3000,
                        )
                    ),
                ]
            ),
        )

    def test_updateLibrarianStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateLibrarianStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating librarian stats:",
            cruncher.logger.getLogBuffer(),
        )

    def test_updateCodeImportStats(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.updateCodeImportStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise(
                [
                    MatchesListwise(
                        [
                            Equals("codeimport.pending,env=test"),
                            Equals(1),
                        ]
                    ),
                    MatchesListwise(
                        [
                            Equals("codeimport.overdue,env=test"),
                            Equals(1),
                        ]
                    ),
                ]
            ),
        )

        job = removeSecurityProxy(self.factory.makeCodeImportJob())
        job.state = CodeImportJobState.PENDING
        self.stats_client.gauge.reset_mock()
        cruncher.updateCodeImportStats()

        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise(
                [
                    MatchesListwise(
                        [
                            Equals("codeimport.pending,env=test"),
                            Equals(2),
                        ]
                    ),
                    MatchesListwise(
                        [
                            Equals("codeimport.overdue,env=test"),
                            Equals(2),
                        ]
                    ),
                ]
            ),
        )

    def test_updateCodeImportStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updateCodeImportStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while updating code import stats.",
            cruncher.logger.getLogBuffer(),
        )
        self.assertFalse(is_transaction_in_progress())

    def test_updatePPABuildLatencyStats(self):
        archive = self.factory.makeArchive()
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, status=PackagePublishingStatus.PUBLISHED
        )
        bpph.binarypackagerelease.build.updateStatus(
            BuildStatus.BUILDING, date_started=datetime.now(timezone.utc)
        )
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
            "ppa.publishdistro,env=test",
        ]
        for gauge in gauges:
            self.assertIn(gauge, keys)

    def test_updatePPABuildLatencyStats_no_data(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.updatePPABuildLatencyStats()
        self.assertEqual(0, self.stats_client.gauge.call_count)

    def test_updatePPABuildLatencyStats_error(self):
        clock = task.Clock()
        cruncher = NumberCruncher(clock=clock)
        cruncher.logger = BufferLogger()
        with DatabaseBlockedPolicy():
            cruncher.updatePPABuildLatencyStats()

        self.assertFalse(is_transaction_in_progress())
        self.assertIn(
            "Failure while update PPA build latency stats.",
            cruncher.logger.getLogBuffer(),
        )
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
