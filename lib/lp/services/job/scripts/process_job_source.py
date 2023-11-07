# Copyright 2009, 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Handle jobs for a specified job source class."""

import logging
import sys
from collections import defaultdict

from twisted.python import log
from zope.component import getUtility

from lp.services.config import config
from lp.services.database.sqlbase import disconnect_stores
from lp.services.job import runner
from lp.services.scripts.base import (
    LaunchpadCronScript,
    LaunchpadScript,
    SilentLaunchpadScriptFailure,
)
from lp.services.scripts.logger import OopsHandler
from lp.services.webapp import errorlog


class ProcessSingleJobSource(LaunchpadCronScript):
    """Run jobs for a single specified job source class.

    This is for internal use by the L{ProcessJobSource} wrapper.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The fromlist argument is necessary so that __import__()
        # returns the bottom submodule instead of the top one.
        module = __import__(
            self.config_section.module, fromlist=[self.job_source_name]
        )
        self.source_interface = getattr(module, self.job_source_name)

    @property
    def config_name(self):
        return self.job_source_name

    @property
    def config_section(self):
        cfg = getattr(config, self.config_name)

        # If the config section is just a link to another section,
        # use the linked one
        if hasattr(cfg, "link"):
            return getattr(config, cfg.link)
        return cfg

    @property
    def dbuser(self):
        return self.config_section.dbuser

    @property
    def name(self):
        return "process-job-source-%s" % self.job_source_name

    @property
    def runner_class(self):
        runner_class_name = getattr(
            self.config_section, "runner_class", "JobRunner"
        )
        # Override attributes that are normally set in __init__().
        return getattr(runner, runner_class_name)

    # Keep this in sync with ProcessJobSource.add_my_options.
    def add_my_options(self):
        self.parser.add_option(
            "--log-twisted",
            action="store_true",
            default=False,
            help="Enable extra Twisted logging.",
        )

    def handle_options(self):
        if len(self.args) != 1:
            self.parser.print_help()
            sys.exit(1)
        self.job_source_name = self.args[0]
        super().handle_options()

    def job_counts(self, jobs):
        """Return a list of tuples containing the job name and counts."""
        counts = defaultdict(int)
        for job in jobs:
            counts[job.__class__.__name__] += 1
        return sorted(counts.items())

    def _init_zca(self, use_web_security):
        """Do nothing; already done by ProcessJobSource."""
        pass

    def _init_db(self, isolation):
        """Switch to the appropriate database user.

        We may be running jobs from multiple different job sources
        consecutively, so we need to disconnect existing Storm stores which
        may be using a connection with a different user.  Any existing Storm
        objects will be broken, but this script never holds object
        references across calls to this method.
        """
        disconnect_stores()
        super()._init_db(isolation)

    def main(self):
        errorlog.globalErrorUtility.configure(self.config_name)
        job_source = getUtility(self.source_interface)
        kwargs = {}
        if getattr(self.options, "log_twisted", False):
            kwargs["_log_twisted"] = True
        runner = self.runner_class.runFromSource(
            job_source, self.dbuser, self.logger, **kwargs
        )
        for name, count in self.job_counts(runner.completed_jobs):
            self.logger.info("Ran %d %s jobs.", count, name)
        for name, count in self.job_counts(runner.incomplete_jobs):
            self.logger.info("%d %s jobs did not complete.", count, name)


class ProcessJobSource(LaunchpadScript):
    """Run jobs for specified job source classes."""

    usage = (
        "Usage: %prog [options] JOB_SOURCE [JOB_SOURCE ...]\n\n"
        "For more help, run:\n"
        "    cronscripts/process-job-source.py --help"
    )

    description = (
        "Takes pending jobs of the given type(s) off the queue and runs them."
    )

    name = "process-job-source"

    # Keep this in sync with ProcessSingleJobSource.add_my_options.
    def add_my_options(self):
        self.parser.add_option(
            "--log-twisted",
            action="store_true",
            default=False,
            help="Enable extra Twisted logging.",
        )

    def handle_options(self):
        if len(self.args) < 1:
            self.parser.print_help()
            sys.exit(1)
        self.job_source_names = self.args
        super().handle_options()

    def main(self):
        if self.options.verbose:
            log.startLogging(sys.stdout)
        failure_count = 0
        for job_source_name in self.job_source_names:
            script = ProcessSingleJobSource(
                test_args=[job_source_name], logger=self.logger
            )
            # This is easier than unparsing all the possible options.
            script.options = self.options
            try:
                script.lock_and_run()
            except SystemExit:
                # We're acting somewhat as though each job source were being
                # handled by a separate process.  If the lock file for a
                # given job source is locked, or if one of them raises
                # LaunchpadScriptFailure and so causes LaunchpadScript to
                # call sys.exit, carry on to the next job source.  Other
                # ordinarily-fatal exceptions are left alone.
                failure_count += 1
            # Disable the OOPS handler added by this script, as otherwise
            # we'll get duplicate OOPSes if anything goes wrong in second or
            # subsequent job sources.
            root_logger = logging.getLogger()
            for handler in list(root_logger.handlers):
                if isinstance(handler, OopsHandler):
                    root_logger.removeHandler(handler)
        if failure_count:
            self.logger.info("%d job sources failed." % failure_count)
            raise SilentLaunchpadScriptFailure(failure_count)
