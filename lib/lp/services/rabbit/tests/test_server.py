# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for lp.services.rabbit.RabbitServer."""

from configparser import ConfigParser
import io

from fixtures import EnvironmentVariableFixture

from lp.services.rabbit.server import RabbitServer
from lp.testing import TestCase
from lp.testing.layers import BaseLayer


class TestRabbitServer(TestCase):

    layer = BaseLayer

    def test_service_config(self):
        # Rabbit needs to fully isolate itself: an existing per user
        # .erlang.cookie has to be ignored, and ditto bogus HOME if other
        # tests fail to cleanup.
        self.useFixture(EnvironmentVariableFixture('HOME', '/nonsense/value'))

        # The default timeout is 15 seconds, but increase this a bit to
        # allow some more leeway for slow test environments.
        fixture = self.useFixture(RabbitServer(ctltimeout=60))
        # RabbitServer pokes some .ini configuration into its config.
        service_config = ConfigParser()
        service_config.read_file(io.StringIO(fixture.config.service_config))
        self.assertEqual(["rabbitmq"], service_config.sections())
        expected = {
            "host": "localhost:%d" % fixture.config.port,
            "userid": "guest",
            "password": "guest",
            "virtual_host": "/",
            }
        observed = dict(service_config.items("rabbitmq"))
        self.assertEqual(expected, observed)
