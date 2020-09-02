# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the stats number cruncher daemon."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from testtools.matchers import (
    Equals,
    MatchesListwise,
    )
from testtools.twistedsupport import AsynchronousDeferredRunTest
import transaction
from twisted.internet import task
from zope.component import getUtility

from lp.buildmaster.enums import BuilderCleanStatus
from lp.buildmaster.interactor import BuilderSlave
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.tests.mock_slaves import OkSlave
from lp.services.statsd.numbercruncher import NumberCruncher
from lp.services.statsd.tests import StatsMixin
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
        manager.builder_factory.update()
        manager.updateBuilderStats()

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
        manager.builder_factory.update()
        manager.updateBuilderStats()

        self.assertEqual(12, self.stats_client.gauge.call_count)
        i386_calls = [c for c in self.stats_client.gauge.call_args_list
                      if '386' in c[0][0]]
        amd64_calls = [c for c in self.stats_client.gauge.call_args_list
                       if 'amd64' in c[0][0]]
        self.assertEqual(8, len(i386_calls))
        self.assertEqual(4, len(amd64_calls))

    def test_correct_values_counts(self):
        builder = self.factory.makeBuilder(
            processors=[getUtility(IProcessorSet).getByName('amd64')])
        builder.setCleanStatus(BuilderCleanStatus.CLEANING)
        self.patch(BuilderSlave, 'makeBuilderSlave', FakeMethod(OkSlave()))
        transaction.commit()
        clock = task.Clock()
        manager = NumberCruncher(clock=clock)
        manager.builder_factory.update()
        manager.updateBuilderStats()

        self.assertEqual(12, self.stats_client.gauge.call_count)
        calls = [c[0] for c in self.stats_client.gauge.call_args_list
                 if 'amd64' in c[0][0]]
        self.assertThat(
            calls, MatchesListwise(
                [Equals(('builders.disabled,arch=amd64,virtualized=True', 0)),
                 Equals(('builders.building,arch=amd64,virtualized=True', 0)),
                 Equals(('builders.idle,arch=amd64,virtualized=True', 0)),
                 Equals(('builders.cleaning,arch=amd64,virtualized=True', 1))
                 ]))

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
        manager.builder_factory.update()
        manager.updateBuilderQueues()

        self.assertEqual(2, self.stats_client.gauge.call_count)
        self.assertThat(
            [x[0] for x in self.stats_client.gauge.call_args_list],
            MatchesListwise(
                [Equals(('buildqueue,virtualized=True,arch={}'.format(
                    build.processor.name), 1)),
                 Equals(('buildqueue,virtualized=False,arch=386', 1))
                 ]))
