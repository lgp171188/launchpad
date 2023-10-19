# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "block_implicit_flushes",
    "connect",
    "convert_storm_clause_to_string",
    "cursor",
    "disconnect_stores",
    "flush_database_caches",
    "flush_database_updates",
    "get_transaction_timestamp",
    "ISOLATION_LEVEL_AUTOCOMMIT",
    "ISOLATION_LEVEL_DEFAULT",
    "ISOLATION_LEVEL_READ_COMMITTED",
    "ISOLATION_LEVEL_REPEATABLE_READ",
    "ISOLATION_LEVEL_SERIALIZABLE",
    "quote",
    "quote_identifier",
    "reset_store",
    "session_store",
    "sqlvalues",
    "StupidCache",
]

from datetime import datetime, timezone

import psycopg2
import transaction
from psycopg2.extensions import (
    ISOLATION_LEVEL_AUTOCOMMIT,
    ISOLATION_LEVEL_READ_COMMITTED,
    ISOLATION_LEVEL_REPEATABLE_READ,
    ISOLATION_LEVEL_SERIALIZABLE,
    make_dsn,
    parse_dsn,
)
from storm.databases.postgres import compile as postgres_compile
from storm.expr import State
from storm.expr import compile as storm_compile
from storm.zope.interfaces import IZStorm
from twisted.python.util import mergeFunctionMetadata
from zope.component import getUtility

from lp.services.config import dbconfig
from lp.services.database.interfaces import (
    DEFAULT_FLAVOR,
    MAIN_STORE,
    DisallowedStore,
    IStoreSelector,
)
from lp.services.database.sqlobject import sqlrepr

# Default we want for scripts, and the PostgreSQL default. Note psycopg1 will
# use SERIALIZABLE unless we override, but psycopg2 will not.
ISOLATION_LEVEL_DEFAULT = ISOLATION_LEVEL_READ_COMMITTED


# XXX 20080313 jamesh:
# When quoting names in SQL statements, PostgreSQL treats them as case
# sensitive.  Storm includes a list of reserved words that it
# automatically quotes, which includes a few of our table names.  We
# remove them here due to case mismatches between the DB and Launchpad
# code.
postgres_compile.remove_reserved_words(["language", "section"])


class StupidCache:
    """A Storm cache that never evicts objects except on clear().

    This class is basically equivalent to Storm's standard Cache class
    with a very large size but without the overhead of maintaining the
    LRU list.
    """

    def __init__(self, size):
        self._cache = {}

    def clear(self):
        self._cache.clear()

    def add(self, obj_info):
        if obj_info not in self._cache:
            self._cache[obj_info] = obj_info.get_obj()

    def remove(self, obj_info):
        if obj_info in self._cache:
            del self._cache[obj_info]
            return True
        return False

    def set_size(self, size):
        pass

    def get_cached(self):
        return self._cache.keys()


def _get_main_default_store():
    """Return the main store using the default flavor.

    For web requests, the default flavor uses a primary or standby database
    depending on the type of request (see
    `lp.services.database.policy.LaunchpadDatabasePolicy`); in all other
    situations, it uses the primary database.
    """
    return getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)


def get_transaction_timestamp(store):
    """Get the timestamp for the current transaction on `store`."""
    timestamp = store.execute(
        "SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC'"
    ).get_one()[0]
    return timestamp.replace(tzinfo=timezone.utc)


def quote(x):
    r"""Quote a variable ready for inclusion into an SQL statement.

    >>> import six
    >>> from lp.services.helpers import backslashreplace

    Basic SQL quoting works

    >>> quote(1)
    '1'
    >>> quote(1.0)
    '1.0'
    >>> quote("hello")
    "E'hello'"
    >>> quote("'hello'")
    "E'''hello'''"
    >>> quote(r"\'hello")
    "E'\\\\''hello'"

    Note that we need to receive a Unicode string back, because our
    query will be a Unicode string (the entire query will be encoded
    before sending across the wire to the database).

    >>> quoted = quote("\N{TRADE MARK SIGN}")
    >>> isinstance(quoted, str)
    True
    >>> print(backslashreplace(quoted))
    E'\u2122'

    Timezone handling is not implemented, since all timestamps should
    be UTC anyway.

    >>> from datetime import datetime, date, time
    >>> quote(datetime(2003, 12, 4, 13, 45, 50))
    "'2003-12-04 13:45:50'"
    >>> quote(datetime(2003, 12, 4, 13, 45, 50, 123456))
    "'2003-12-04 13:45:50.123456'"
    >>> quote(date(2003, 12, 4))
    "'2003-12-04'"
    >>> quote(time(13, 45, 50))
    "'13:45:50'"

    sqlrepr() also special-cases set objects.

    >>> quote(set([1, 2, 3]))
    '(1, 2, 3)'

    >>> quote(frozenset([1, 2, 3]))
    '(1, 2, 3)'
    """
    if isinstance(x, datetime):
        return "'%s'" % x
    return sqlrepr(x, "postgres")


def sqlvalues(*values, **kwvalues):
    """Return a tuple of converted sql values for each value in some_tuple.

    This safely quotes strings (except for '%'!), or gives representations
    of dbschema items, for example.

    Use it when constructing a string for use in a SELECT.  Always use
    %s as the replacement marker.

      ('SELECT foo from Foo where bar = %s and baz = %s'
       % sqlvalues(BugTaskSeverity.CRITICAL, 'foo'))

    This is DEPRECATED in favour of passing parameters to SQL statements
    using the second parameter to `cursor.execute` (normally via the Storm
    query compiler), because it does not deal with escaping '%' characters
    in strings.

    >>> sqlvalues()
    Traceback (most recent call last):
    ...
    TypeError: Use either positional or keyword values with sqlvalue.
    >>> sqlvalues(1)
    ('1',)
    >>> sqlvalues(1, "bad ' string")
    ('1', "E'bad '' string'")

    You can also use it when using dict-style substitution.

    >>> sqlvalues(foo=23)
    {'foo': '23'}

    However, you cannot mix the styles.

    >>> sqlvalues(14, foo=23)
    Traceback (most recent call last):
    ...
    TypeError: Use either positional or keyword values with sqlvalue.

    """
    if (values and kwvalues) or (not values and not kwvalues):
        raise TypeError(
            "Use either positional or keyword values with sqlvalue."
        )
    if values:
        return tuple(quote(item) for item in values)
    elif kwvalues:
        return {key: quote(value) for key, value in kwvalues.items()}


def quote_identifier(identifier):
    r'''Quote an identifier, such as a table name.

    In SQL, identifiers are quoted using " rather than ' which is reserved
    for strings.

    >>> print(quote_identifier("hello"))
    "hello"
    >>> print(quote_identifier("'"))
    "'"
    >>> print(quote_identifier('"'))
    """"
    >>> print(quote_identifier("\\"))
    "\"
    >>> print(quote_identifier('\\"'))
    "\"""
    '''
    return '"%s"' % identifier.replace('"', '""')


def convert_storm_clause_to_string(storm_clause):
    """Convert a Storm expression into a plain string.

    :param storm_clause: A Storm expression

    A helper function allowing to use a Storm expressions in old-style
    code which builds for example WHERE expressions as plain strings.

    >>> from lp.bugs.model.bug import Bug
    >>> from lp.bugs.model.bugtask import BugTask
    >>> from lp.bugs.interfaces.bugtask import BugTaskImportance
    >>> from storm.expr import And, Or

    >>> print(convert_storm_clause_to_string(BugTask))
    BugTask

    >>> print(convert_storm_clause_to_string(BugTask.id == 16))
    BugTask.id = 16

    >>> print(
    ...     convert_storm_clause_to_string(
    ...         BugTask.importance == BugTaskImportance.UNKNOWN
    ...     )
    ... )
    BugTask.importance = 999

    >>> print(convert_storm_clause_to_string(Bug.title == "foo'bar'"))
    Bug.title = E'foo''bar'''

    >>> print(
    ...     convert_storm_clause_to_string(
    ...         Or(
    ...             BugTask.importance == BugTaskImportance.UNKNOWN,
    ...             BugTask.importance == BugTaskImportance.HIGH,
    ...         )
    ...     )
    ... )
    BugTask.importance = 999 OR BugTask.importance = 40

    >>> print(
    ...     convert_storm_clause_to_string(
    ...         And(
    ...             Bug.title == "foo",
    ...             BugTask.bug == Bug.id,
    ...             Or(
    ...                 BugTask.importance == BugTaskImportance.UNKNOWN,
    ...                 BugTask.importance == BugTaskImportance.HIGH,
    ...             ),
    ...         )
    ...     )
    ... )
    Bug.title = E'foo' AND BugTask.bug = Bug.id AND
    (BugTask.importance = 999 OR BugTask.importance = 40)
    """
    state = State()
    clause = storm_compile(storm_clause, state)
    if len(state.parameters):
        parameters = [param.get(to_db=True) for param in state.parameters]
        clause = clause.replace("?", "%s") % sqlvalues(*parameters)
    return clause


def flush_database_updates():
    """Flushes all pending database updates.

    Storm normally flushes changes to objects before it needs to issue the
    next query, but there are situations where it doesn't realize that it
    needs to do so.  One common case is when creating an object and
    immediately fetching its ID, which is typically assigned by the database
    based on a sequence when the row is inserted::

        store = IStore(Beer)
        beer = Beer(name="Victoria Bitter")
        store.add(beer)
        assert beer.id is not None  # This will fail

    To avoid this problem, use this function::

        store = IStore(Beer)
        beer = Beer(name="Victoria Bitter")
        store.add(beer)
        flush_database_updates()
        assert beer.id is not None  # This will pass

    (You can also flush individual stores using `store.flush()`, which is
    normally sufficient, but sometimes this function is a convenient
    shorthand if you don't already have a store object handy.)
    """
    zstorm = getUtility(IZStorm)
    for _, store in zstorm.iterstores():
        store.flush()


def flush_database_caches():
    """Flush all database caches.

    Storm caches field values from the database in Storm instances.  If SQL
    statements are issued that change the state of the database behind
    Storm's back, these cached values will be invalid.

    This function iterates through all the objects in the Storm connection's
    cache, and synchronises them with the database.  This ensures that they
    all reflect the values in the database.
    """
    zstorm = getUtility(IZStorm)
    for _, store in zstorm.iterstores():
        store.flush()
        store.invalidate()


def block_implicit_flushes(func):
    """A decorator that blocks implicit flushes on the main store."""

    def block_implicit_flushes_decorator(*args, **kwargs):
        try:
            store = _get_main_default_store()
        except DisallowedStore:
            return func(*args, **kwargs)
        store.block_implicit_flushes()
        try:
            return func(*args, **kwargs)
        finally:
            store.unblock_implicit_flushes()

    return mergeFunctionMetadata(func, block_implicit_flushes_decorator)


def reset_store(func):
    """Function decorator that resets the main store."""

    def reset_store_decorator(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        finally:
            _get_main_default_store().reset()

    return mergeFunctionMetadata(func, reset_store_decorator)


def connect(user=None, dbname=None, isolation=ISOLATION_LEVEL_DEFAULT):
    """Return a fresh DB-API connection to the MAIN PRIMARY database.

    Can be used without first setting up the Component Architecture,
    unlike the usual stores.

    Default database name is the one specified in the main configuration file.
    """
    # We must connect to the read-write DB here, so we use rw_main_primary
    # directly.
    parsed_dsn = parse_dsn(dbconfig.rw_main_primary)
    dsn_kwargs = {}
    if dbname is not None:
        dsn_kwargs["dbname"] = dbname
    if dbconfig.set_role_after_connecting:
        assert "user" in parsed_dsn, (
            "With set_role_after_connecting, database username must be "
            "specified in connection string (%s)." % dbconfig.rw_main_primary
        )
    else:
        assert "user" not in parsed_dsn, (
            "Database username must not be specified in connection string "
            "(%s)." % dbconfig.rw_main_primary
        )
        dsn_kwargs["user"] = user
    dsn = make_dsn(dbconfig.rw_main_primary, **dsn_kwargs)

    con = psycopg2.connect(dsn)
    con.set_isolation_level(isolation)
    if (
        dbconfig.set_role_after_connecting
        and user is not None
        and user != parsed_dsn["user"]
    ):
        con.cursor().execute("SET ROLE %s", (user,))
        con.commit()
    return con


class cursor:
    """A DB-API cursor-like object for the Storm connection.

    DEPRECATED - use of this class is deprecated in favour of using
    Store.execute().
    """

    def __init__(self):
        self._connection = _get_main_default_store()._connection
        self._result = None

    def execute(self, query, params=None):
        self.close()
        if isinstance(params, dict):
            query = query % sqlvalues(**params)
        elif params is not None:
            query = query % sqlvalues(*params)
        self._result = self._connection.execute(query)

    @property
    def rowcount(self):
        return self._result._raw_cursor.rowcount

    @property
    def description(self):
        return self._result._raw_cursor.description

    def fetchone(self):
        assert self._result is not None, "No results to fetch"
        return self._result.get_one()

    def fetchall(self):
        assert self._result is not None, "No results to fetch"
        return self._result.get_all()

    def close(self):
        if self._result is not None:
            self._result.close()
            self._result = None


def session_store():
    """Return a store connected to the session DB."""
    return getUtility(IZStorm).get("session", "launchpad-session:")


def disconnect_stores():
    """Disconnect Storm stores.

    Note that any existing Storm objects will be broken, so this should only
    be used in situations where we can guarantee that we have no such object
    references in hand (other than in Storm caches, which will be dropped as
    a process of removing stores anyway).
    """
    zstorm = getUtility(IZStorm)
    stores = [
        store for name, store in zstorm.iterstores() if name != "session"
    ]

    # If we have any stores, abort the transaction and close them.
    if stores:
        for store in stores:
            zstorm.remove(store)
        transaction.abort()
        for store in stores:
            store.close()
