# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for lp.services.scripts.base."""

import os.path
import socket
from unittest import mock

from testtools.matchers import MatchesStructure
from testtools.testcase import ExpectedException
from zope.component import getUtility

from lp.services.log.logger import DevNullLogger
from lp.services.scripts.base import LaunchpadCronScript
from lp.services.scripts.interfaces.scriptactivity import IScriptActivitySet
from lp.services.statsd.tests import StatsMixin
from lp.testing import TestCase
from lp.testing.layers import ZopelessDatabaseLayer


class TestScript(LaunchpadCronScript):
    def _init_zca(self, use_web_security):
        # Already done by test layer.
        pass

    def main(self):
        # Fail if we are told to do so.
        if self.args[0] == "fail":
            raise RuntimeError("Some failure")


class TestLaunchpadCronScript(StatsMixin, TestCase):
    """Test cron script integration.

    `LaunchpadCronScript` is a `LaunchpadScript` subclass that automatically
    logs the result of successful runs.  This is intended for use by cron
    scripts and others where it is useful to monitor the result.
    """

    layer = ZopelessDatabaseLayer

    def setCronControlConfig(self, body):
        tempdir = self.makeTemporaryDirectory()
        config_path = os.path.join(tempdir, "cron-control.ini")
        with open(config_path, "w") as config_file:
            config_file.write(body)
        self.pushConfig(
            "canonical", cron_control_url="file://%s" % config_path
        )

    def test_cronscript_disabled(self):
        # If scripts are centrally disabled, there is no activity record in
        # the database but there is an activity metric in statsd.
        self.setCronControlConfig("[DEFAULT]\nenabled: False\n")
        self.setUpStats()
        script = TestScript(
            "script-name", test_args=["fail"], logger=DevNullLogger()
        )
        with ExpectedException(
            SystemExit, MatchesStructure.byEquality(code=0)
        ):
            script.run()
        self.assertIsNone(
            getUtility(IScriptActivitySet).getLastActivity("script-name")
        )
        self.stats_client.timing.assert_called_once_with(
            "script_activity,env=test,name=script-name", 0.0
        )

    def test_script_fails(self):
        # If the script fails, there is no activity record in the database
        # and no activity metric in statsd.
        self.setUpStats()
        script = TestScript(
            "script-name", test_args=["fail"], logger=DevNullLogger()
        )
        with ExpectedException(
            SystemExit, MatchesStructure.byEquality(code=1)
        ):
            script.run()
        self.assertIsNone(
            getUtility(IScriptActivitySet).getLastActivity("script-name")
        )
        self.stats_client.timing.assert_not_called()

    def test_script_succeeds(self):
        # If the script succeeds, there is an activity record in the
        # database and an activity metric in statsd.
        self.setUpStats()
        script = TestScript(
            "script-name", test_args=["pass"], logger=DevNullLogger()
        )
        script.run()
        self.assertThat(
            getUtility(IScriptActivitySet).getLastActivity("script-name"),
            MatchesStructure.byEquality(
                name="script-name", hostname=socket.gethostname()
            ),
        )
        self.stats_client.timing.assert_called_once_with(
            "script_activity,env=test,name=script-name", mock.ANY
        )
