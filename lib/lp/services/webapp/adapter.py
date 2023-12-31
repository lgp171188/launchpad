# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import logging
import os
import re
import sys
import threading
import traceback
import warnings
from functools import partial
from textwrap import dedent
from time import time

import transaction
from lazr.restful.utils import get_current_browser_request
from psycopg2.extensions import (
    ISOLATION_LEVEL_AUTOCOMMIT,
    ISOLATION_LEVEL_READ_COMMITTED,
    ISOLATION_LEVEL_REPEATABLE_READ,
    ISOLATION_LEVEL_SERIALIZABLE,
    QueryCanceledError,
    make_dsn,
    parse_dsn,
)
from storm.database import register_scheme
from storm.databases.postgres import Postgres, PostgresTimeoutTracer
from storm.exceptions import TimeoutError
from storm.store import Store
from storm.tracer import install_tracer
from talisker.logs import logging_context
from zope.component import getUtility
from zope.interface import alsoProvides, classImplements, implementer, provider
from zope.security.proxy import removeSecurityProxy

from lp.services import features
from lp.services.config import config, dbconfig
from lp.services.database.interfaces import (
    DEFAULT_FLAVOR,
    MAIN_STORE,
    PRIMARY_FLAVOR,
    STANDBY_FLAVOR,
    IPrimaryObject,
    IPrimaryStore,
    IRequestExpired,
    IStoreSelector,
)
from lp.services.database.policy import PrimaryDatabasePolicy
from lp.services.database.postgresql import ConnectionString
from lp.services.log.loglevels import DEBUG2
from lp.services.stacktrace import extract_stack, extract_tb, print_list
from lp.services.timeline.requesttimeline import (
    get_request_timeline,
    make_timeline,
    set_request_timeline,
)
from lp.services.timeout import set_default_timeout_function
from lp.services.webapp import LaunchpadView
from lp.services.webapp.interaction import get_interaction_extras

__all__ = [
    "RequestExpired",
    "set_request_started",
    "clear_request_started",
    "get_request_remaining_seconds",
    "get_request_statements",
    "get_request_start_time",
    "get_request_duration",
    "print_queries",
    "soft_timeout_expired",
    "start_sql_logging",
    "stop_sql_logging",
    "StoreSelector",
]


classImplements(TimeoutError, IRequestExpired)


class LaunchpadTimeoutError(TimeoutError):
    """A variant of TimeoutError that reports the original PostgreSQL error."""

    def __init__(self, statement, params, original_error):
        super().__init__(statement, params)
        self.original_error = original_error

    def __str__(self):
        return "Statement: %r\nParameters:%r\nOriginal error: %r" % (
            self.statement,
            self.params,
            self.original_error,
        )


@implementer(IRequestExpired)
class RequestExpired(RuntimeError):
    """Request has timed out."""


def _get_dirty_commit_flags():
    """Return the current dirty commit status"""
    from lp.testing.pgsql import ConnectionWrapper

    return (ConnectionWrapper.committed, ConnectionWrapper.dirty)


def _reset_dirty_commit_flags(previous_committed, previous_dirty):
    """Set the dirty commit status to False unless previous is True"""
    from lp.testing.pgsql import ConnectionWrapper

    if not previous_committed:
        ConnectionWrapper.committed = False
    if not previous_dirty:
        ConnectionWrapper.dirty = False


_local = threading.local()


class CommitLogger:
    def __init__(self, txn):
        self.txn = txn

    def newTransaction(self, txn):
        pass

    def beforeCompletion(self, txn):
        pass

    def afterCompletion(self, txn):
        action = get_request_timeline(get_current_browser_request()).start(
            "SQL-nostore", "Transaction completed, status: %s" % txn.status
        )
        action.finish()


def set_request_started(
    starttime=None,
    request_statements=None,
    txn=None,
    enable_timeout=True,
    detail_filter=None,
):
    """Set the start time for the request being served by the current
    thread.

    :param start_time: The start time of the request. If given, it is used as
        the start time for the request, as returned by time().  If it is not
        given, the current time is used.
    :param request_statements; The sequence used to store the logged SQL
        statements.
    :type request_statements: mutable sequence.
    :param txn: The current transaction manager. If given, txn.commit() and
        txn.abort() calls are logged too.
    :param enable_timeout: If True, a timeout error is raised if the request
        runs for a longer time than the configured timeout.
    :param detail_filter: An optional (category, detail) -> detail callable
        that filters action details.  This may be used when some details are
        expected to be very large.
    """
    if getattr(_local, "request_start_time", None) is not None:
        warnings.warn(
            "set_request_started() called before previous request " "finished",
            stacklevel=1,
        )

    if starttime is None:
        starttime = time()
    _local.request_start_time = starttime
    request = get_current_browser_request()
    # Ensure a timeline is created, so that time offset for actions is
    # reasonable.
    set_request_timeline(
        request,
        make_timeline(actions=request_statements, detail_filter=detail_filter),
    )
    _local.current_statement_timeout = None
    _local.enable_timeout = enable_timeout
    _local.commit_logger = CommitLogger(transaction)
    transaction.manager.registerSynch(_local.commit_logger)


def clear_request_started():
    """Clear the request timer.  This function should be called when
    the request completes.
    """
    if getattr(_local, "request_start_time", None) is None:
        warnings.warn(
            "clear_request_started() called outside of a request", stacklevel=2
        )
    _local.request_start_time = None
    _local.sql_logging = None
    _local.sql_logging_start = None
    _local.sql_logging_tracebacks_if = None
    request = get_current_browser_request()
    set_request_timeline(request, make_timeline())
    if getattr(_local, "commit_logger", None) is not None:
        transaction.manager.unregisterSynch(_local.commit_logger)
        del _local.commit_logger


def summarize_requests():
    """Produce human-readable summary of requests issued so far."""
    secs = get_request_duration()
    request = get_current_browser_request()
    timeline = get_request_timeline(request)
    from lp.services.webapp.errorlog import maybe_record_user_requested_oops

    maybe_record_user_requested_oops()
    if request.oopsid is None:
        oops_str = ""
    else:
        oops_str = " %s" % request.oopsid
    log = "%s queries/external actions issued in %.2f seconds%s" % (
        len(timeline.actions),
        secs,
        oops_str,
    )
    return log


# Truncate the in-page timeline after this many actions.
IN_PAGE_TIMELINE_CAP = 200


def get_timeline_actions():
    """Return an iterable of timeline actions."""
    timeline = get_request_timeline(get_current_browser_request())
    return timeline.actions[:IN_PAGE_TIMELINE_CAP]


def store_sql_statements(event):
    actions = get_request_timeline(get_current_browser_request()).actions
    logging_context.push(nonpython_actions=len(actions))


def get_request_statements():
    """Get the list of executed statements in the request.

    The list is composed of (starttime, endtime, db_id, statement) tuples.
    Times are given in milliseconds since the start of the request.
    """
    result = []
    request = get_current_browser_request()
    for action in get_request_timeline(request).actions:
        if not action.category.startswith("SQL-"):
            continue
        # Can't show incomplete requests in this API
        if action.duration is None:
            continue
        result.append(action.logTuple())
    return result


def get_request_start_time():
    """Get the time at which the request started."""
    return getattr(_local, "request_start_time", None)


def get_request_duration(now=None):
    """Get the duration of the current request in seconds."""
    starttime = getattr(_local, "request_start_time", None)
    if starttime is None:
        return -1

    if now is None:
        now = time()
    return now - starttime


def set_permit_timeout_from_features(enabled):
    """Control request timeouts being obtained from the 'hard_timeout' flag.

    Until we've fully setup a page to render - routed the request to the
    right object, setup a participation etc, feature flags cannot be
    completely used; and because doing feature flag lookups will trigger
    DB access, attempting to do a DB lookup will cause a nested DB
    lookup (the one being done, and the flags lookup). To resolve all of
    this, timeouts start as a config file only setting, and are then
    overridden once the request is ready to execute.

    :param enabled: If True permit looking up request timeouts in
        feature flags.
    """
    get_interaction_extras().permit_timeout_from_features = enabled


def _get_request_timeout(timeout=None):
    """Get the timeout value in ms for the current request.

    :param timeout: A custom timeout in ms.
    :return None or a time in ms representing the budget to grant the request.
    """
    if not getattr(_local, "enable_timeout", True):
        return None
    if timeout is None:
        timeout = config.database.db_statement_timeout
        interaction_extras = get_interaction_extras()
        if (
            interaction_extras is not None
            and interaction_extras.permit_timeout_from_features
        ):
            set_permit_timeout_from_features(False)
            try:
                timeout_str = features.getFeatureFlag("hard_timeout")
            finally:
                set_permit_timeout_from_features(True)
            if timeout_str:
                try:
                    timeout = float(timeout_str)
                except ValueError:
                    logging.error("invalid hard timeout flag %r", timeout_str)
    return timeout


def get_request_remaining_seconds(no_exception=False, now=None, timeout=None):
    """Return how many seconds are remaining in the current request budget.

    If timeouts are disabled, None is returned.

    :param no_exception: If True, do not raise an error if the request
        is out of time. Instead return a float e.g. -2.0 for 2 seconds over
        budget.
    :param now: Override the result of time.time()
    :param timeout: A custom timeout in ms.
    :return: None or a float representing the remaining time budget.
    """
    timeout = _get_request_timeout(timeout=timeout)
    if not timeout:
        return None
    duration = get_request_duration(now)
    if duration == -1:
        return None
    remaining = timeout / 1000.0 - duration
    if remaining <= 0:
        if no_exception:
            return remaining
        raise RequestExpired("request expired.")
    return remaining


def set_launchpad_default_timeout(event):
    """Set the LAZR default timeout function on IProcessStartingEvent."""
    set_default_timeout_function(get_request_remaining_seconds)


def soft_timeout_expired():
    """Returns True if the soft request timeout been reached."""
    try:
        get_request_remaining_seconds(
            timeout=config.database.soft_request_timeout
        )
        return False
    except RequestExpired:
        return True


def start_sql_logging(tracebacks_if=False):
    """Turn the sql data logging on."""
    if getattr(_local, "sql_logging", None) is not None:
        warnings.warn("SQL logging already started")
        return
    _local.sql_logging_tracebacks_if = tracebacks_if
    result = []
    _local.sql_logging = result
    _local.sql_logging_start = int(time() * 1000)
    return result


def stop_sql_logging():
    """Turn off the sql data logging and return the result."""
    result = getattr(_local, "sql_logging", None)
    _local.sql_logging_tracebacks_if = None
    _local.sql_logging = None
    _local.sql_logging_start = None
    if result is None:
        warnings.warn("SQL logging not started")
    return result


def print_queries(queries, file=None):
    if file is None:
        file = sys.stdout
    for query in queries:
        # Note: this could use the sql tb if it exists.
        stack = query["stack"]
        if stack is not None:
            exception = query["exception"]
            if exception is not None:
                file.write(
                    "Error when determining whether to generate a "
                    "stacktrace.\n"
                )
                file.write("Traceback (most recent call last):\n")
            print_list(stack, file)
            if exception is not None:
                lines = traceback.format_exception_only(*exception)
                file.write(" ".join(lines))
            file.write("." * 70 + "\n")
        sql = query["sql"]
        if sql is not None:
            file.write("%d-%d@%s %s\n" % sql[:4])
        else:
            file.write("(no SQL recorded)\n")
        file.write("-" * 70 + "\n")


# ---- Storm database classes

isolation_level_map = {
    "autocommit": ISOLATION_LEVEL_AUTOCOMMIT,
    "read_committed": ISOLATION_LEVEL_READ_COMMITTED,
    "repeatable_read": ISOLATION_LEVEL_REPEATABLE_READ,
    "serializable": ISOLATION_LEVEL_SERIALIZABLE,
}


class LaunchpadDatabase(Postgres):
    def __init__(self, uri):
        super().__init__(uri)
        # A unique name for this database connection.
        self.name = uri.database

    def raw_connect(self):
        # XXX cjwatson 2023-03-28: Can we rework this on top of
        # lp.services.database.sqlbase.connect somehow so that we only need
        # one implementation of the set_role_after_connecting logic?
        try:
            realm, flavor = self._uri.database.split("-")
        except ValueError:
            raise AssertionError(
                "Connection uri %s does not match realm-flavor format"
                % repr(self._uri.database)
            )

        assert realm == "main", "Unknown realm %s" % realm
        assert flavor in ("primary", "standby"), "Unknown flavor %s" % flavor

        # We set self._dsn here rather than in __init__ so when the Store
        # is reconnected it pays attention to any config changes.
        config_entry = "%s_%s" % (realm, flavor)
        connection_string = getattr(dbconfig, config_entry)

        # Try to lookup dbuser using the $realm_dbuser key. If this fails,
        # fallback to the dbuser key.
        dbuser = getattr(dbconfig, "%s_dbuser" % realm, dbconfig.dbuser)
        parsed_dsn = parse_dsn(connection_string)

        if dbconfig.set_role_after_connecting:
            assert "user" in parsed_dsn, (
                "With set_role_after_connecting, database username must be "
                "specified in connection string (%s)." % connection_string
            )
            self._dsn = make_dsn(connection_string)
        else:
            assert "user" not in parsed_dsn, (
                "Database username must not be specified in "
                "connection string (%s)." % connection_string
            )
            self._dsn = make_dsn(connection_string, user=dbuser)

        flags = _get_dirty_commit_flags()

        if dbconfig.isolation_level is None:
            self._isolation = ISOLATION_LEVEL_REPEATABLE_READ
        else:
            self._isolation = isolation_level_map[dbconfig.isolation_level]

        raw_connection = super().raw_connect()

        if dbconfig.set_role_after_connecting and dbuser != parsed_dsn["user"]:
            raw_connection.cursor().execute("SET ROLE %s", (dbuser,))
            raw_connection.commit()

        # Set read only mode for the session.
        # An alternative would be to use the _ro users generated by
        # security.py, but this would needlessly double the number
        # of database users we need to maintain ACLs for on production.
        if flavor == STANDBY_FLAVOR:
            raw_connection.cursor().execute(
                "SET DEFAULT_TRANSACTION_READ_ONLY TO TRUE"
            )
            # Make the altered session setting stick.
            raw_connection.commit()
        elif not config_entry.endswith(("_master", "_primary")):
            raise AssertionError(
                "DB connection URL %s does not meet naming convention."
            )

        _reset_dirty_commit_flags(*flags)

        logging.log(
            DEBUG2,
            "Connected to %s backend %d, as user %s, at isolation level %s.",
            flavor,
            raw_connection.get_backend_pid(),
            dbuser,
            self._isolation,
        )
        return raw_connection


class LaunchpadSessionDatabase(Postgres):
    # A unique name for this database connection.
    name = "session"

    def raw_connect(self):
        dsn = ConnectionString(config.launchpad_session.database)
        if config.launchpad_session.dbuser is not None:
            dsn.user = config.launchpad_session.dbuser
        self._dsn = str(dsn)
        flags = _get_dirty_commit_flags()
        raw_connection = super().raw_connect()
        if hasattr(raw_connection, "auto_close"):
            raw_connection.auto_close = False
        raw_connection.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        _reset_dirty_commit_flags(*flags)
        return raw_connection


register_scheme("launchpad", LaunchpadDatabase)
register_scheme("launchpad-session", LaunchpadSessionDatabase)


class LaunchpadTimeoutTracer(PostgresTimeoutTracer):
    """Storm tracer class to keep statement execution time bounded."""

    def __init__(self):
        # The parent class __init__ just sets the granularity
        # attribute, which we are handling with a property.
        pass

    @property
    def granularity(self):
        return config.database.db_statement_timeout_precision / 1000.0

    def connection_raw_execute(
        self, connection, raw_cursor, statement, params
    ):
        """See `TimeoutTracer`"""
        # Only perform timeout handling on LaunchpadDatabase
        # connections.
        if not isinstance(connection._database, LaunchpadDatabase):
            return
        # If we are outside of a request, don't do timeout adjustment.
        try:
            if self.get_remaining_time() is None:
                return
            super().connection_raw_execute(
                connection, raw_cursor, statement, params
            )
        except (RequestExpired, TimeoutError):
            # XXX bug=636801 Robert Colins 20100914 This is duplicated
            # from the statement tracer, because the tracers are not
            # arranged in a stack rather a queue: the done-code in the
            # statement tracer never runs.
            action = getattr(connection, "_lp_statement_action", None)
            if action is not None:
                # action may be None if the tracer was installed after
                # the statement was submitted.
                action.finish()
                connection._lp_statement_action = None
            info = sys.exc_info()
            transaction.doom()
            try:
                raise info[1].with_traceback(None)
            finally:
                # Avoid traceback reference cycles.
                del info

    def connection_raw_execute_error(
        self, connection, raw_cursor, statement, params, error
    ):
        """See `TimeoutTracer`"""
        # Only perform timeout handling on LaunchpadDatabase
        # connections.
        if not isinstance(connection._database, LaunchpadDatabase):
            return
        if isinstance(error, QueryCanceledError):
            raise LaunchpadTimeoutError(statement, params, error)

    def get_remaining_time(self):
        """See `TimeoutTracer`"""
        return get_request_remaining_seconds()


class LaunchpadStatementTracer:
    """Storm tracer class to log executed statements."""

    _normalize_whitespace = partial(re.compile(r"\s+").sub, " ")

    def __init__(self):
        self._debug_sql = bool(os.environ.get("LP_DEBUG_SQL"))
        self._debug_sql_extra = bool(os.environ.get("LP_DEBUG_SQL_EXTRA"))

    def connection_raw_execute(
        self, connection, raw_cursor, statement, params
    ):
        statement_to_log = statement
        if params:
            statement_to_log = raw_cursor.mogrify(
                statement, tuple(connection.to_database(params))
            )
        if isinstance(statement_to_log, bytes):
            statement_to_log = statement_to_log.decode(
                "UTF-8", errors="replace"
            )
        # Record traceback to log, if requested.
        print_traceback = self._debug_sql_extra
        log_sql = getattr(_local, "sql_logging", None)
        log_traceback = False
        if log_sql is not None:
            log_sql.append(dict(stack=None, sql=None, exception=None))
            conditional = getattr(_local, "sql_logging_tracebacks_if", None)
            if callable(conditional):
                try:
                    log_traceback = conditional(
                        self._normalize_whitespace(
                            statement_to_log.strip()
                        ).upper()
                    )
                except MemoryError:
                    raise
                except (GeneratorExit, Exception):
                    exc_type, exc_value, tb = sys.exc_info()
                    log_sql[-1]["exception"] = (exc_type, exc_value)
                    log_sql[-1]["stack"] = extract_tb(tb)
            else:
                log_traceback = bool(conditional)
        if print_traceback or log_traceback:
            stack = extract_stack()
            if log_traceback:
                log_sql[-1]["stack"] = stack
            if print_traceback:
                print_list(stack)
                sys.stderr.write("." * 70 + "\n")
        request_starttime = getattr(_local, "request_start_time", None)
        if request_starttime is None:
            if print_traceback or self._debug_sql or log_sql is not None:
                # Stash some information for logging at the end of the
                # SQL execution.
                connection._lp_statement_info = (
                    int(time() * 1000),
                    "SQL-%s" % connection._database.name,
                    statement_to_log,
                )
                connection._lp_statement_action = None
            return
        action = get_request_timeline(get_current_browser_request()).start(
            "SQL-%s" % connection._database.name, statement_to_log
        )
        connection._lp_statement_action = action

    def connection_raw_execute_success(
        self, connection, raw_cursor, statement, params
    ):
        action = getattr(connection, "_lp_statement_action", None)
        if action is not None:
            # action may be None if the tracer was installed after the
            # statement was submitted or if the timeline tracer is not
            # installed.
            action.finish()
            connection._lp_statement_action = None
        log_sql = getattr(_local, "sql_logging", None)
        if log_sql is not None or self._debug_sql or self._debug_sql_extra:
            data = None
            if action is not None:
                data = action.logTuple()
            else:
                info = getattr(connection, "_lp_statement_info", None)
                if info is not None:
                    stop = int(time() * 1000)
                    start, dbname, statement = info
                    logging_start = (
                        getattr(_local, "sql_logging_start", None) or start
                    )
                    # Times are in milliseconds, to mirror actions.
                    start = start - logging_start
                    stop = stop - logging_start
                    data = (start, stop, dbname, statement, None)
                    connection._lp_statement_info = None
            if data is not None:
                if log_sql and log_sql[-1]["sql"] is None:
                    log_sql[-1]["sql"] = data
                if self._debug_sql or self._debug_sql_extra:
                    # Don't print the backtrace from the data to stderr - too
                    # messy given that LP_DEBUG_SQL_EXTRA logs that
                    # separately anyhow.
                    sys.stderr.write("%d-%d@%s %s\n" % data[:4])
                    sys.stderr.write("-" * 70 + "\n")

    def connection_raw_execute_error(
        self, connection, raw_cursor, statement, params, error
    ):
        # Since we are just logging durations, we execute the same
        # hook code for errors as successes.
        self.connection_raw_execute_success(
            connection, raw_cursor, statement, params
        )


# The LaunchpadTimeoutTracer needs to be installed last, as it raises
# TimeoutError exceptions. When this happens, tracers installed later
# are not invoked.
install_tracer(LaunchpadStatementTracer())
install_tracer(LaunchpadTimeoutTracer())


@provider(IStoreSelector)
class StoreSelector:
    """See `lp.services.database.interfaces.IStoreSelector`."""

    @staticmethod
    def push(db_policy):
        """See `IStoreSelector`."""
        if not hasattr(_local, "db_policies"):
            _local.db_policies = []
        db_policy.install()
        _local.db_policies.append(db_policy)

    @staticmethod
    def pop():
        """See `IStoreSelector`."""
        db_policy = _local.db_policies.pop()
        db_policy.uninstall()
        return db_policy

    @staticmethod
    def get_current():
        """See `IStoreSelector`."""
        try:
            return _local.db_policies[-1]
        except (AttributeError, IndexError):
            return None

    @staticmethod
    def get(name, flavor):
        """See `IStoreSelector`."""
        db_policy = StoreSelector.get_current()
        if db_policy is None:
            db_policy = PrimaryDatabasePolicy(None)
        return db_policy.getStore(name, flavor)


# We want to be able to adapt a Storm class to an IStore, IPrimaryStore or
# IStandbyStore. Unfortunately, the component architecture provides no
# way for us to declare that a class, and all its subclasses, provides
# a given interface. This means we need to use an global adapter.


def get_store(storm_class, flavor=DEFAULT_FLAVOR):
    """Return a flavored Store for the given database class."""
    table = getattr(removeSecurityProxy(storm_class), "__storm_table__", None)
    if table is not None:
        return getUtility(IStoreSelector).get(MAIN_STORE, flavor)
    else:
        return None


def get_primary_store(storm_class):
    """Return the primary Store for the given database class."""
    return get_store(storm_class, PRIMARY_FLAVOR)


def get_standby_store(storm_class):
    """Return the standby Store for the given database class."""
    return get_store(storm_class, STANDBY_FLAVOR)


def get_object_from_primary_store(obj):
    """Return a copy of the given object retrieved from its primary Store.

    Returns the object if it already comes from the relevant primary Store.

    Registered as a trusted adapter, so if the input is security wrapped,
    so is the result. Otherwise an unwrapped object is returned.
    """
    primary_store = IPrimaryStore(obj)
    if primary_store is not Store.of(obj):
        obj = primary_store.get(obj.__class__, obj.id)
        if obj is None:
            return None
    alsoProvides(obj, IPrimaryObject)
    return obj


class WhichDbView(LaunchpadView):
    "A page that reports which database is being used by default."

    def render(self):
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        dbname = store.execute("SELECT current_database()").get_one()[0]
        return dedent(
            """
                <html>
                <body>
                <span id="dbname">
                %s
                </span>
                <form method="post">
                <input type="submit" value="Do Post" />
                </form>
                </body>
                </html>
                """
            % dbname
        ).strip()
