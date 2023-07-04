# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Launchpad database policies."""

__all__ = [
    "BaseDatabasePolicy",
    "DatabaseBlockedPolicy",
    "LaunchpadDatabasePolicy",
    "PrimaryDatabasePolicy",
    "StandbyDatabasePolicy",
    "StandbyOnlyDatabasePolicy",
]

from datetime import datetime, timedelta

import psycopg2
from storm.cache import Cache, GenerationalCache
from storm.exceptions import DisconnectionError
from storm.zope.interfaces import IZStorm
from zope.authentication.interfaces import IUnauthenticatedPrincipal
from zope.component import getUtility
from zope.interface import alsoProvides, implementer

from lp.services.config import config, dbconfig
from lp.services.database.interfaces import (
    DEFAULT_FLAVOR,
    MAIN_STORE,
    PRIMARY_FLAVOR,
    STANDBY_FLAVOR,
    DisallowedStore,
    IDatabasePolicy,
    IPrimaryStore,
    IStandbyStore,
    IStoreSelector,
)
from lp.services.database.sqlbase import StupidCache
from lp.services.webapp.interfaces import IClientIdManager, ISession


def _now():
    """Return current utc time as a datetime with no timezone info.

    This is a global method to allow the test suite to override.
    """
    return datetime.utcnow()


# Can be tweaked by the test suite to simulate replication lag.
_test_lag = None


def storm_cache_factory():
    """Return a Storm Cache of the type and size specified in dbconfig."""
    if dbconfig.storm_cache == "generational":
        return GenerationalCache(int(dbconfig.storm_cache_size))
    elif dbconfig.storm_cache == "stupid":
        return StupidCache(int(dbconfig.storm_cache_size))
    elif dbconfig.storm_cache == "default":
        return Cache(int(dbconfig.storm_cache_size))
    else:
        assert False, "Unknown storm_cache %s." % dbconfig.storm_cache


def get_connected_store(name, flavor):
    """Retrieve a store from the IZStorm Utility and ensure it is connected.

    :raises storm.exceptions.DisconnectionError: On failures.
    """
    store_name = "%s-%s" % (name, flavor)
    try:
        store = getUtility(IZStorm).get(
            store_name, "launchpad:%s" % store_name
        )
        store._connection._ensure_connected()
        return store
    except DisconnectionError:
        # If the Store is in a disconnected state, ensure it is
        # registered with the transaction manager. Otherwise, if
        # _ensure_connected() caused the disconnected state it may not
        # be put into reconnect state at the end of the transaction.
        store._connection._event.emit("register-transaction")
        raise
    except psycopg2.OperationalError as exc:
        # Per Bug #1025264, Storm emits psycopg2 errors when we
        # want DisconnonnectionErrors, eg. attempting to open a
        # new connection to a non-existent database.
        raise DisconnectionError(str(exc))


@implementer(IDatabasePolicy)
class BaseDatabasePolicy:
    """Base class for database policies."""

    # The default flavor to use.
    default_flavor = PRIMARY_FLAVOR

    def __init__(self, request=None):
        pass

    def getStore(self, name, flavor):
        """See `IDatabasePolicy`."""
        if flavor == DEFAULT_FLAVOR:
            flavor = self.default_flavor

        try:
            store = get_connected_store(name, flavor)
        except DisconnectionError:
            # A request for a primary database connection was made
            # and failed. Nothing we can do so reraise the exception.
            if flavor != STANDBY_FLAVOR:
                raise

            # A request for a standby database connection was made
            # and failed. Try to return a primary connection, this
            # will be good enough. Note we don't call self.getStore()
            # recursively because we want to make this attempt even if
            # the DatabasePolicy normally disallows primary database
            # connections. All this behaviour allows read-only requests
            # to keep working when standby databases are being rebuilt or
            # updated.
            try:
                flavor = PRIMARY_FLAVOR
                store = get_connected_store(name, flavor)
            except DisconnectionError:
                store = None

            # If we still haven't connected to a suitable database,
            # reraise the original attempt's exception.
            if store is None:
                raise

        if not getattr(store, "_lp_store_initialized", False):
            # No existing Store. Create a new one and tweak its defaults.

            # XXX stub 2009-06-25 bug=391996: The default Storm
            # Cache is useless to a project like Launchpad. Because we
            # are using ZStorm to manage our Stores there is no API
            # available to change the default. Instead, we monkey patch.
            store._cache = storm_cache_factory()

            # Attach our marker interfaces so our adapters don't lie.
            if flavor == PRIMARY_FLAVOR:
                alsoProvides(store, IPrimaryStore)
            else:
                alsoProvides(store, IStandbyStore)

            store._lp_store_initialized = True

        return store

    def install(self, request=None):
        """See `IDatabasePolicy`."""
        pass

    def uninstall(self):
        """See `IDatabasePolicy`."""
        pass

    def __enter__(self):
        """See `IDatabasePolicy`."""
        getUtility(IStoreSelector).push(self)

    def __exit__(self, exc_type, exc_value, traceback):
        """See `IDatabasePolicy`."""
        policy = getUtility(IStoreSelector).pop()
        assert (
            policy is self
        ), "Unexpected database policy %s returned by store selector" % repr(
            policy
        )


class DatabaseBlockedPolicy(BaseDatabasePolicy):
    """`IDatabasePolicy` that blocks all access to the database."""

    def getStore(self, name, flavor):
        """Raises `DisallowedStore`. No Database access is allowed."""
        raise DisallowedStore(name, flavor)


class PrimaryDatabasePolicy(BaseDatabasePolicy):
    """`IDatabasePolicy` that selects the PRIMARY_FLAVOR by default.

    Standby databases can still be accessed if requested explicitly.

    This policy is used for XMLRPC and WebService requests which don't
    support session cookies. It is also used when no policy has been
    installed.
    """

    default_flavor = PRIMARY_FLAVOR


class StandbyDatabasePolicy(BaseDatabasePolicy):
    """`IDatabasePolicy` that selects the STANDBY_FLAVOR by default.

    Access to the primary can still be made if requested explicitly.
    """

    default_flavor = STANDBY_FLAVOR


class StandbyOnlyDatabasePolicy(BaseDatabasePolicy):
    """`IDatabasePolicy` that only allows access to STANDBY_FLAVOR stores.

    This policy is used for Feeds requests and other always-read only request.
    """

    default_flavor = STANDBY_FLAVOR

    def getStore(self, name, flavor):
        """See `IDatabasePolicy`."""
        if flavor == PRIMARY_FLAVOR:
            raise DisallowedStore(flavor)
        return super().getStore(name, STANDBY_FLAVOR)


def LaunchpadDatabasePolicyFactory(request):
    """Return the Launchpad IDatabasePolicy for the current appserver state."""
    # We need to select a non-load balancing DB policy for some status URLs so
    # it doesn't query the DB for lag information (this page should not
    # hit the database at all). We haven't traversed yet, so we have
    # to sniff the request this way.  Even though PATH_INFO is always
    # present in real requests, we need to tread carefully (``get``) because
    # of test requests in our automated tests.
    if request.get("PATH_INFO") == "/+opstats":
        return DatabaseBlockedPolicy(request)
    else:
        return LaunchpadDatabasePolicy(request)


class LaunchpadDatabasePolicy(BaseDatabasePolicy):
    """Default database policy for web requests.

    Selects the DEFAULT_FLAVOR based on the request.
    """

    def __init__(self, request):
        self.request = request
        # Detect if this is a read only request or not.
        self.read_only = self.request.method in ["GET", "HEAD"]

    def _hasSession(self):
        "Is there is already a session cookie hanging around?"
        cookie_name = getUtility(IClientIdManager).namespace
        return (
            cookie_name in self.request.cookies
            or self.request.response.getCookie(cookie_name) is not None
        )

    def install(self):
        """See `IDatabasePolicy`."""
        default_flavor = None

        # If this is a Retry attempt, force use of the primary database.
        if getattr(self.request, "_retry_count", 0) > 0:
            default_flavor = PRIMARY_FLAVOR

        # Select if the DEFAULT_FLAVOR Store will be the primary or a
        # standby. We select standby if this is a readonly request, and
        # only readonly requests have been made by this user recently.
        # This ensures that a user will see any changes they just made
        # on the primary, despite the fact it might take a while for
        # those changes to propagate to the standby databases.
        elif self.read_only:
            lag = self.getReplicationLag()
            if lag is not None and lag > timedelta(
                seconds=config.database.max_usable_lag
            ):
                # Don't use the standby at all if lag is greater than the
                # configured threshold. This reduces replication oddities
                # noticed by users, as well as reducing load on the
                # standby allowing it to catch up quicker.
                default_flavor = PRIMARY_FLAVOR
            else:
                # We don't want to even make a DB query to read the session
                # if we can tell that it is not around.  This can be
                # important for fast and reliable performance for pages like
                # +opstats.
                if self._hasSession():
                    session_data = ISession(self.request)["lp.dbpolicy"]
                    last_write = session_data.get("last_write", None)
                else:
                    last_write = None
                now = _now()
                # 'recently' is  2 minutes plus the replication lag.
                recently = timedelta(minutes=2)
                if lag is None:
                    recently = timedelta(minutes=2)
                else:
                    recently = timedelta(minutes=2) + lag
                if last_write is None or last_write < now - recently:
                    default_flavor = STANDBY_FLAVOR
                else:
                    default_flavor = PRIMARY_FLAVOR
        else:
            default_flavor = PRIMARY_FLAVOR

        assert default_flavor is not None, "default_flavor not set!"

        self.default_flavor = default_flavor

    def uninstall(self):
        """See `IDatabasePolicy`.

        If the request just handled was not read_only, we need to store
        this fact and the timestamp in the session. Subsequent requests
        can then keep using the primary until they are sure any changes
        made have been propagated.
        """
        if not self.read_only:
            # We need to further distinguish whether it's safe to write
            # to the session. This will be true if the principal is
            # authenticated or if there is already a session cookie
            # hanging around.
            if (
                not IUnauthenticatedPrincipal.providedBy(
                    self.request.principal
                )
                or self._hasSession()
            ):
                # A non-readonly request has been made. Store this fact
                # in the session. Precision is hard coded at 1 minute
                # (so we don't update the timestamp if it is no more
                # than 1 minute out of date to avoid unnecessary and
                # expensive write operations). Feeds are always read
                # only, and since they run over http, browsers won't
                # send their session key that was set over https, so we
                # don't want to access the session which will overwrite
                # the cookie and log the user out.
                session_data = ISession(self.request)["lp.dbpolicy"]
                last_write = session_data.get("last_write", None)
                now = _now()
                if last_write is None or last_write < now - timedelta(
                    minutes=1
                ):
                    # set value
                    session_data["last_write"] = now

    def getReplicationLag(self):
        """Return the replication lag between the primary and our hot standby.

        :returns: timedelta, or None if this isn't a replicated environment,
        """
        # Support the test suite hook.
        if _test_lag is not None:
            return _test_lag

        # Attempt to retrieve PostgreSQL streaming replication lag
        # from the standby.
        standby_store = self.getStore(MAIN_STORE, STANDBY_FLAVOR)
        hot_standby, streaming_lag = standby_store.execute(
            """
            SELECT
                pg_is_in_recovery(),
                now() - pg_last_xact_replay_timestamp()
            """
        ).get_one()
        if hot_standby and streaming_lag is not None:
            # standby is a PG 9.1 streaming replication hot standby.
            # Return the lag.
            return streaming_lag

        # Unreplicated. This might be a dev system, or a production
        # system running on a single database for some reason.
        return None


def WebServiceDatabasePolicyFactory(request):
    """Return the Launchpad IDatabasePolicy for the current appserver state."""
    # If a session cookie was sent with the request, use the
    # standard Launchpad database policy for load balancing to
    # the standby databases. The javascript web service libraries
    # send the session cookie for authenticated users.
    cookie_name = getUtility(IClientIdManager).namespace
    if cookie_name in request.cookies:
        return LaunchpadDatabasePolicy(request)
    # Otherwise, use the primary only web service database policy.
    return PrimaryDatabasePolicy(request)
