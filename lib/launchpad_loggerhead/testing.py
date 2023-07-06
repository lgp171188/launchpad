# Copyright 2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "LoggerheadFixture",
]

import os.path
import time
import warnings

from fixtures import Fixture

from lp.services.config import config
from lp.services.osutils import (
    get_pid_from_file,
    kill_by_pidfile,
    remove_if_exists,
)
from lp.services.pidfile import pidfile_path
from lp.testing.layers import BaseLayer, LayerProcessController
from lp.testing.script import run_script


class LoggerheadFixtureException(Exception):
    pass


class LoggerheadFixture(Fixture):
    """Start loggerhead as a fixture."""

    def _setUp(self):
        pidfile = pidfile_path(
            "codebrowse", use_config=LayerProcessController.appserver_config
        )
        pid = get_pid_from_file(pidfile)
        if pid is not None:
            warnings.warn(
                "Attempt to start LoggerheadFixture with an existing "
                "instance (%d) running in %s." % (pid, pidfile)
            )
            kill_by_pidfile(pidfile)
        self.logfile = os.path.join(config.codebrowse.log_folder, "debug.log")
        remove_if_exists(self.logfile)
        self.addCleanup(kill_by_pidfile, pidfile)
        exit_code, out, err = run_script(
            os.path.join(config.root, "scripts", "start-loggerhead.py"),
            args=["--daemon"],
            # The testrunner-appserver config provides the correct
            # openid_provider_root URL.
            extra_env={"LPCONFIG": BaseLayer.appserver_config_name},
            universal_newlines=False,
        )
        if exit_code != 0:
            raise AssertionError(
                "Starting loggerhead failed with exit code %d:\n%s\n%s"
                % (exit_code, out, err)
            )
        self._waitForStartup()

    def _hasStarted(self):
        if os.path.exists(self.logfile):
            with open(self.logfile) as logfile:
                return "Listening at:" in logfile.read()
        else:
            return False

    def _waitForStartup(self):
        now = time.time()
        deadline = now + 20
        while now < deadline and not self._hasStarted():
            time.sleep(0.1)
            now = time.time()

        if now >= deadline:
            raise LoggerheadFixtureException("Unable to start loggerhead.")
