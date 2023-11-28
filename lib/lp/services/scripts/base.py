# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "disable_oops_handler",
    "LaunchpadCronScript",
    "LaunchpadScript",
    "LaunchpadScriptFailure",
    "LOCK_PATH",
    "SilentLaunchpadScriptFailure",
]

import io
import logging
import os.path
import sys
from configparser import ConfigParser
from contextlib import contextmanager
from cProfile import Profile
from datetime import datetime, timedelta, timezone
from optparse import OptionParser
from typing import Optional
from urllib.parse import urlparse, urlunparse

import requests
import transaction
from contrib.glock import GlobalLock, LockAlreadyAcquired
from zope.component import getUtility

from lp.services import scripts
from lp.services.config import config, dbconfig
from lp.services.database.postgresql import ConnectionString
from lp.services.features import (
    get_relevant_feature_controller,
    install_feature_controller,
    make_script_feature_controller,
)
from lp.services.mail.sendmail import set_immediate_mail_delivery
from lp.services.scripts.interfaces.scriptactivity import IScriptActivitySet
from lp.services.scripts.logger import OopsHandler
from lp.services.scripts.metrics import emit_script_activity_metric
from lp.services.timeout import override_timeout, urlfetch
from lp.services.webapp.errorlog import globalErrorUtility
from lp.services.webapp.interaction import ANONYMOUS, setupInteractionByEmail

LOCK_PATH = "/var/lock/"


class LaunchpadScriptFailure(Exception):
    """Something bad happened and the script is going away.

    When you raise LaunchpadScriptFailure inside your main() method, we
    do two things:

        - log an error with the stringified exception
        - sys.exit(1)

    Releasing the lock happens as a side-effect of the exit.

    Note that the sys.exit return value of 1 is defined as
    LaunchpadScriptFailure.exit_status. If you want a different value
    subclass LaunchpadScriptFailure and redefine it.
    """

    exit_status = 1


class SilentLaunchpadScriptFailure(Exception):
    """A LaunchpadScriptFailure that doesn't log an error."""

    def __init__(self, exit_status=1):
        Exception.__init__(self, exit_status)
        self.exit_status = exit_status

    exit_status = 1


def log_unhandled_exception_and_exit(func):
    """Decorator that logs unhandled exceptions via the logging module.

    Exceptions are reraised except at the top level. ie. exceptions are
    only propagated to the outermost decorated method. At the top level,
    an exception causes the script to terminate.

    Only for methods of `LaunchpadScript` and subclasses. Not thread safe,
    which is fine as the decorated LaunchpadScript methods are only
    invoked from the main thread.
    """

    def log_unhandled_exceptions_func(self, *args, **kw):
        try:
            self._log_unhandled_exceptions_level += 1
            return func(self, *args, **kw)
        except Exception:
            if self._log_unhandled_exceptions_level == 1:
                # self.logger is setup in LaunchpadScript.__init__() so
                # we can use it.
                self.logger.exception("Unhandled exception")
                sys.exit(1)
            else:
                raise
        finally:
            self._log_unhandled_exceptions_level -= 1

    return log_unhandled_exceptions_func


class LaunchpadScript:
    """A base class for runnable scripts and cronscripts.

    Inherit from this base class to simplify the setup work that your
    script needs to do.

    What you define:
        - main()
        - add_my_options(), if you have any
        - usage and description, if you want output for --help

    What you call:
        - lock_and_run()

    If you are picky:
        - lock_or_die()
        - run()
        - unlock()
        - build_options()

    What you get:
        - self.logger
        - self.txn
        - self.parser (the OptionParser)
        - self.options (the parsed options)

    "Give me convenience or give me death."
    """

    lock = None
    txn = None
    usage: Optional[str] = None
    description: Optional[str] = None
    lockfilepath = None
    loglevel = logging.INFO

    # State for the log_unhandled_exceptions decorator.
    _log_unhandled_exceptions_level = 0

    def __init__(self, name=None, dbuser=None, test_args=None, logger=None):
        """Construct new LaunchpadScript.

        Name is a short name for this script; it will be used to
        assemble a lock filename and to identify the logger object.

        Use dbuser to specify the user to connect to the database; if
        not supplied a default will be used.

        Specify test_args when you want to override sys.argv.  This is
        useful in test scripts.

        :param logger: Use this logger, instead of initializing global
            logging.
        """
        if name is None:
            self._name = self.__class__.__name__.lower()
        else:
            self._name = name

        self._dbuser = dbuser
        self.logger = logger

        # The construction of the option parser is a bit roundabout, but
        # at least it's isolated here. First we build the parser, then
        # we add options that our logger object uses, then call our
        # option-parsing hook, and finally pull out and store the
        # supplied options and args.
        if self.description is None:
            description = self.__doc__
        else:
            description = self.description
        self.parser = OptionParser(usage=self.usage, description=description)

        if logger is None:
            scripts.logger_options(self.parser, default=self.loglevel)
        else:
            scripts.dummy_logger_options(self.parser)
        self.parser.add_option(
            "--profile",
            dest="profile",
            metavar="FILE",
            help=(
                "Run the script under the profiler and save the "
                "profiling stats in FILE."
            ),
        )

        self.add_my_options()
        self.options, self.args = self.parser.parse_args(args=test_args)

        # Enable subclasses to easily override these __init__()
        # arguments using command-line arguments.
        self.handle_options()

    def handle_options(self):
        if self.logger is None:
            self.logger = scripts.logger(self.options, self.name)

    @property
    def name(self):
        """Enable subclasses to override with command-line arguments."""
        return self._name

    @property
    def dbuser(self):
        """Enable subclasses to override with command-line arguments."""
        return self._dbuser

    #
    # Hooks that we expect users to redefine.
    #
    def main(self):
        """Define the meat of your script here. Must be defined.

        Raise LaunchpadScriptFailure if you encounter an error condition
        that makes it impossible for you to proceed; sys.exit(1) will be
        invoked in that situation.
        """
        raise NotImplementedError

    def add_my_options(self):
        """Optionally customize this hook to define your own options.

        This method should contain only a set of lines that follow the
        template:

            self.parser.add_option("-f", "--foo", dest="foo",
                default="foobar-makes-the-world-go-round",
                help="You are joking, right?")
        """

    #
    # Convenience or death
    #
    @log_unhandled_exception_and_exit
    def login(self, user=ANONYMOUS):
        """Super-convenience method that avoids the import."""
        setupInteractionByEmail(user)

    #
    # Locking and running methods. Users only call these explicitly if
    # they really want to control the run-and-locking semantics of the
    # script carefully.
    #
    @property
    def lockfilename(self):
        """Return lockfilename.

        May be overridden in targeted scripts in order to have more specific
        lockfilename.
        """
        return "launchpad-%s.lock" % self.name

    @property
    def lockfilepath(self):
        return os.path.join(LOCK_PATH, self.lockfilename)

    def setup_lock(self):
        """Create lockfile.

        Note that this will create a lockfile even if you don't actually
        use it. GlobalLock.__del__ is meant to clean it up though.
        """
        self.lock = GlobalLock(self.lockfilepath, logger=self.logger)

    @log_unhandled_exception_and_exit
    def lock_or_die(self, blocking=False):
        """Attempt to lock, and sys.exit(1) if the lock's already taken.

        Say blocking=True if you want to block on the lock being
        available.
        """
        self.setup_lock()
        try:
            self.lock.acquire(blocking=blocking)
        except LockAlreadyAcquired:
            self.logger.info("Lockfile %s in use" % self.lockfilepath)
            sys.exit(1)

    @log_unhandled_exception_and_exit
    def unlock(self, skip_delete=False):
        """Release the lock. Do this before going home.

        If you skip_delete, we won't try to delete the lock when it's
        freed. This is useful if you have moved the directory in which
        the lockfile resides.
        """
        self.lock.release(skip_delete=skip_delete)

    @log_unhandled_exception_and_exit
    def run(self, use_web_security=False, isolation=None):
        """Actually run the script, executing zcml and initZopeless."""

        if isolation is None:
            isolation = "read_committed"
        self._init_zca(use_web_security=use_web_security)
        self._init_db(isolation=isolation)

        # XXX wgrant 2011-09-24 bug=29744: initZopeless used to do this.
        # Should be called directly by scripts that actually need it.
        set_immediate_mail_delivery(True)

        date_started = datetime.now(timezone.utc)
        profiler = None
        if self.options.profile:
            profiler = Profile()

        original_feature_controller = get_relevant_feature_controller()
        install_feature_controller(make_script_feature_controller(self.name))
        try:
            if profiler:
                profiler.runcall(self.main)
            else:
                self.main()
        except LaunchpadScriptFailure as e:
            self.logger.error(str(e))
            sys.exit(e.exit_status)
        except SilentLaunchpadScriptFailure as e:
            sys.exit(e.exit_status)
        else:
            date_completed = datetime.now(timezone.utc)
            self.record_activity(date_started, date_completed)
        finally:
            install_feature_controller(original_feature_controller)
        if profiler:
            profiler.dump_stats(self.options.profile)

    def _init_zca(self, use_web_security):
        """Initialize the ZCA, this can be overridden for testing purposes."""
        scripts.execute_zcml_for_scripts(use_web_security=use_web_security)

    def _init_db(self, isolation):
        """Initialize the database transaction.

        Can be overridden for testing purposes.
        """
        dbuser = self.dbuser
        if dbuser is None:
            connstr = ConnectionString(dbconfig.main_primary)
            dbuser = connstr.user or dbconfig.dbuser
        dbconfig.override(dbuser=dbuser, isolation_level=isolation)
        self.txn = transaction

    def record_activity(self, date_started, date_completed):
        """Hook to record script activity."""

    #
    # Make things happen
    #
    @log_unhandled_exception_and_exit
    def lock_and_run(
        self,
        blocking=False,
        skip_delete=False,
        use_web_security=False,
        isolation="read_committed",
    ):
        """Call lock_or_die(), and then run() the script.

        Will die with sys.exit(1) if the locking call fails.
        """
        self.lock_or_die(blocking=blocking)
        try:
            self.run(use_web_security=use_web_security, isolation=isolation)
        finally:
            self.unlock(skip_delete=skip_delete)


class LaunchpadCronScript(LaunchpadScript):
    """Logs successful script runs in the database."""

    def __init__(
        self,
        name=None,
        dbuser=None,
        test_args=None,
        logger=None,
        ignore_cron_control=False,
    ):
        super().__init__(name, dbuser, test_args=test_args, logger=logger)

        self.ignore_cron_control = ignore_cron_control

        # Configure the IErrorReportingUtility we use with defaults.
        # Scripts can override this if they want.
        globalErrorUtility.configure()

        # WARN and higher log messages should generate OOPS reports.
        # self.name is used instead of the name argument, since it may have
        # have been overridden by command-line parameters or by
        # overriding the name property.
        oops_hdlr = OopsHandler(self.name, logger=self.logger)
        logging.getLogger().addHandler(oops_hdlr)

    def _init_db(self, isolation):
        # This runs a bit late: we initialize the whole Zope component
        # architecture before getting here, which is slow.  However, doing
        # this allows us to emit a script activity metric via the
        # IStatsdClient utility, and if cron scripts are disabled then we
        # still exit before anything important like database access happens.
        if not self.ignore_cron_control:
            enabled = cronscript_enabled(
                config.canonical.cron_control_url, self.name, self.logger
            )
            if not enabled:
                # Emit a basic script activity metric so that alerts don't
                # fire while scripts are intentionally disabled (e.g. during
                # schema updates).  We set the duration to 0 so that these
                # can be distinguished from real completions.  Avoid
                # touching the database here, since that could be
                # problematic during schema updates.
                emit_script_activity_metric(self.name, timedelta(0))
                sys.exit(0)

        super()._init_db(isolation)

    @log_unhandled_exception_and_exit
    def record_activity(self, date_started, date_completed):
        """Record the successful completion of the script."""
        self.txn.begin()
        self.login(ANONYMOUS)
        getUtility(IScriptActivitySet).recordSuccess(
            name=self.name,
            date_started=date_started,
            date_completed=date_completed,
        )
        self.txn.commit()
        # date_started is recorded *after* the lock is acquired and we've
        # initialized Zope components and the database.  Thus this time is
        # only for the script proper, rather than total execution time.
        seconds_taken = (date_completed - date_started).total_seconds()
        self.logger.debug(
            "%s ran in %ss (excl. load & lock)" % (self.name, seconds_taken)
        )


@contextmanager
def disable_oops_handler(logger):
    oops_handlers = []
    for handler in logger.handlers:
        if isinstance(handler, OopsHandler):
            oops_handlers.append(handler)
            logger.removeHandler(handler)
    yield
    for handler in oops_handlers:
        logger.addHandler(handler)


def cronscript_enabled(control_url, name, log):
    """Return True if the cronscript is enabled."""
    # In test environments, this may be a file: URL.  Adjust it to be in a
    # form that requests can cope with (i.e. using an absolute path).
    parsed_url = urlparse(control_url)
    if parsed_url.scheme == "file" and not os.path.isabs(parsed_url.path):
        assert parsed_url.path == parsed_url[2]
        parsed_url = list(parsed_url)
        parsed_url[2] = os.path.join(config.root, parsed_url[2])
    control_url = urlunparse(parsed_url)
    try:
        # Timeout of 5 seconds should be fine on the LAN. We don't want
        # the default as it is too long for scripts being run every 60
        # seconds.
        with override_timeout(5.0):
            response = urlfetch(control_url, allow_file=True)
    except requests.HTTPError as error:
        if error.response.status_code == 404:
            log.debug("Cronscript control file not found at %s", control_url)
            return True
        log.exception("Error loading %s" % control_url)
        return True
    except Exception:
        log.exception("Error loading %s" % control_url)
        return True

    cron_config = ConfigParser({"enabled": str(True)})

    # Try reading the config file. If it fails, we log the
    # traceback and continue on using the defaults.
    try:
        with response:
            cron_config.read_file(io.StringIO(response.text))
    except Exception:
        log.exception("Error parsing %s", control_url)

    if cron_config.has_option(name, "enabled"):
        section = name
    else:
        section = "DEFAULT"

    try:
        enabled = cron_config.getboolean(section, "enabled")
    except Exception:
        log.exception(
            "Failed to load value from %s section of %s", section, control_url
        )
        enabled = True

    if enabled:
        log.debug("Enabled by %s section", section)
    else:
        log.info("Disabled by %s section", section)

    return enabled
