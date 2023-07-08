# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""PostgreSQL server side session storage for Zope3."""

import hashlib
import io
import pickle
from collections.abc import MutableMapping
from datetime import datetime

import six
from lazr.restful.utils import get_current_browser_request
from storm.zope.interfaces import IZStorm
from zope.authentication.interfaces import IUnauthenticatedPrincipal
from zope.component import getUtility
from zope.interface import implementer

from lp.services.webapp.interfaces import (
    IClientIdManager,
    ISessionData,
    ISessionDataContainer,
    ISessionPkgData,
)

SECONDS = 1
MINUTES = 60 * SECONDS
HOURS = 60 * MINUTES
DAYS = 24 * HOURS


class Python2FriendlyUnpickler(pickle._Unpickler):
    """An unpickler that handles Python 2 datetime objects.

    Python 3 versions before 3.6 fail to unpickle Python 2 datetime objects
    (https://bugs.python.org/issue22005); even in Python >= 3.6 they require
    passing a different encoding to pickle.loads, which may have undesirable
    effects on other objects being unpickled.  Work around this by instead
    patching in a different encoding just for the argument to
    datetime.datetime.
    """

    def find_class(self, module, name):
        if module == "datetime" and name == "datetime":
            original_encoding = self.encoding
            self.encoding = "bytes"

            def datetime_factory(pickle_data):
                self.encoding = original_encoding
                return datetime(pickle_data)

            return datetime_factory
        else:
            return super().find_class(module, name)


class PGSessionBase:
    store_name = "session"

    @property
    def store(self):
        return getUtility(IZStorm).get(self.store_name)


@implementer(ISessionDataContainer)
class PGSessionDataContainer(PGSessionBase):
    """An ISessionDataContainer that stores data in PostgreSQL

    PostgreSQL Schema:

    CREATE TABLE SessionData (
        client_id     text PRIMARY KEY,
        last_accessed timestamp with time zone
            NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
    CREATE INDEX sessiondata_last_accessed_idx ON SessionData(last_accessed);
    CREATE TABLE SessionPkgData (
        client_id  text NOT NULL
            REFERENCES SessionData(client_id) ON DELETE CASCADE,
        product_id text NOT NULL,
        key        text NOT NULL,
        pickle     bytea NOT NULL,
        CONSTRAINT sessiondata_key UNIQUE (client_id, product_id, key)
        );

    Removing expired data needs to be done out of band.
    """

    # If we have a low enough resolution, we can determine active users
    # using the session data.
    resolution = 9 * MINUTES

    session_data_table_name = "SessionData"
    session_pkg_data_table_name = "SessionPkgData"

    def __getitem__(self, client_id):
        """See `ISessionDataContainer`."""
        return PGSessionData(self, client_id)

    def __setitem__(self, client_id, session_data):
        """See `ISessionDataContainer`."""
        # The SessionData / SessionPkgData objects know how to store
        # themselves.
        pass


@implementer(ISessionData)
class PGSessionData(PGSessionBase):
    session_data_container = None

    _have_ensured_client_id = False

    def __init__(self, session_data_container, client_id):
        self.session_data_container = session_data_container
        self.client_id = six.ensure_text(client_id, "ascii")
        self.hashed_client_id = hashlib.sha256(
            self.client_id.encode()
        ).hexdigest()

        # Update the last access time in the db if it is out of date
        table_name = session_data_container.session_data_table_name
        query = """
            UPDATE %s SET last_accessed = CURRENT_TIMESTAMP
            WHERE client_id = ?
                AND last_accessed < CURRENT_TIMESTAMP - '%d seconds'::interval
            """ % (
            table_name,
            session_data_container.resolution,
        )
        self.store.execute(query, (self.hashed_client_id,), noresult=True)

    def _ensureClientId(self):
        if self._have_ensured_client_id:
            return
        # We want to make sure the browser cookie and the database both know
        # about our client id. We're doing it lazily to try and keep anonymous
        # users from having a session.
        self.store.execute(
            "SELECT ensure_session_client_id(?)",
            (self.hashed_client_id,),
            noresult=True,
        )
        request = get_current_browser_request()
        if request is not None:
            client_id_manager = getUtility(IClientIdManager)
            if IUnauthenticatedPrincipal.providedBy(request.principal):
                # it would be nice if this could be a monitored, logged
                # message instead of an instant-OOPS.
                assert (
                    client_id_manager.namespace in request.cookies
                    or request.response.getCookie(client_id_manager.namespace)
                    is not None
                ), (
                    "Session data should generally only be stored for "
                    "authenticated users, and for users who have just logged "
                    "out.  If an unauthenticated user has just logged out, "
                    "they should have a session cookie set for ten minutes. "
                    "This should be plenty of time for passing notifications "
                    "about successfully logging out.  Because this assertion "
                    "failed, it means that some code is trying to set "
                    "session data for an unauthenticated user who has been "
                    "logged out for more than ten minutes: something that "
                    "should not happen.  The code setting the session data "
                    "should be reviewed; and failing that, the cookie "
                    "timeout after logout (set in "
                    "webapp.login) should perhaps be "
                    "increased a bit, if a ten minute fudge factor is not "
                    "enough to handle the vast majority of computers with "
                    "not-very-accurate system clocks.  In an exceptional "
                    "case, the code may set the necessary cookies itself to "
                    "assert that yes, it *should* set the session for an "
                    "unauthenticated user.  See the webapp.login module for "
                    "an example of this, as well."
                )
            else:
                client_id_manager.setRequestId(request, self.client_id)
        self._have_ensured_client_id = True

    def __getitem__(self, product_id):
        """Return an `ISessionPkgData`."""
        return PGSessionPkgData(self, product_id)

    def __setitem__(self, product_id, session_pkg_data):
        """See `ISessionData`.

        This is a noop in the RDBMS implementation.
        """
        pass


@implementer(ISessionPkgData)
class PGSessionPkgData(MutableMapping, PGSessionBase):
    @property
    def store(self):
        return self.session_data.store

    def __init__(self, session_data, product_id):
        self.session_data = session_data
        self.product_id = six.ensure_text(product_id, "ascii")
        self.table_name = (
            session_data.session_data_container.session_pkg_data_table_name
        )
        self._populate()

    _data_cache = None

    def _populate(self):
        self._data_cache = {}
        query = (
            """
            SELECT key, pickle FROM %s WHERE client_id = ?
                AND product_id = ?
            """
            % self.table_name
        )
        result = self.store.execute(
            query, (self.session_data.hashed_client_id, self.product_id)
        )
        for key, pickled_value in result:
            value = Python2FriendlyUnpickler(
                io.BytesIO(bytes(pickled_value))
            ).load()
            self._data_cache[key] = value

    def __getitem__(self, key):
        return self._data_cache[key]

    def __setitem__(self, key, value):
        key = six.ensure_text(key, "ascii")
        # Use protocol 2 for Python 2 compatibility.
        pickled_value = pickle.dumps(value, protocol=2)

        self.session_data._ensureClientId()
        self.store.execute(
            "SELECT set_session_pkg_data(?, ?, ?, ?)",
            (
                self.session_data.hashed_client_id,
                self.product_id,
                key,
                pickled_value,
            ),
            noresult=True,
        )

        # Store the value in the cache too
        self._data_cache[key] = value

    def __delitem__(self, key):
        """Delete an item.

        Note that this will never fail in order to avoid
        race conditions in code using the session machinery
        """
        try:
            del self._data_cache[key]
        except KeyError:
            # Not in the cache, then it won't be in the DB. Or if it is,
            # another process has inserted it and we should keep our grubby
            # fingers out of it.
            return
        query = (
            """
            DELETE FROM %s
            WHERE client_id = ? AND product_id = ? AND key = ?
            """
            % self.table_name
        )
        self.store.execute(
            query,
            (
                self.session_data.hashed_client_id,
                self.product_id,
                six.ensure_text(key, "ascii"),
            ),
            noresult=True,
        )

    def __iter__(self):
        return iter(self._data_cache)

    def __len__(self):
        return len(self._data_cache)


data_container = PGSessionDataContainer()
