# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OpenIDStore implementation for the SSO server's OpenID provider."""

__all__ = [
    "BaseStormOpenIDStore",
    "BaseStormOpenIDAssociation",
    "BaseStormOpenIDNonce",
]

import time
from operator import attrgetter

import six
from openid.association import Association
from openid.store import nonce
from openid.store.interface import OpenIDStore
from storm.properties import Bytes, Int, Unicode

from lp.services.database.interfaces import IPrimaryStore


class BaseStormOpenIDAssociation:
    """Database representation of a stored OpenID association."""

    __storm_primary__ = ("server_url", "handle")

    server_url = Unicode()
    handle = Unicode()
    secret = Bytes()
    issued = Int()
    lifetime = Int()
    assoc_type = Unicode()

    def __init__(self, server_url, association):
        super().__init__()
        self.server_url = six.ensure_text(server_url)
        self.handle = six.ensure_text(association.handle, "ASCII")
        self.update(association)

    def update(self, association):
        assert self.handle == six.ensure_text(
            association.handle, "ASCII"
        ), "Association handle does not match (expected %r, got %r" % (
            self.handle,
            association.handle,
        )
        self.secret = association.secret
        self.issued = association.issued
        self.lifetime = association.lifetime
        self.assoc_type = six.ensure_text(association.assoc_type, "ASCII")

    def as_association(self):
        """Return an equivalent openid-python `Association` object."""
        return Association(
            str(self.handle),
            self.secret,
            self.issued,
            self.lifetime,
            str(self.assoc_type),
        )


class BaseStormOpenIDNonce:
    """Database representation of a stored OpenID nonce."""

    __storm_primary__ = ("server_url", "timestamp", "salt")

    server_url = Unicode()
    timestamp = Int()
    salt = Unicode()

    def __init__(self, server_url, timestamp, salt):
        super().__init__()
        self.server_url = server_url
        self.timestamp = timestamp
        self.salt = salt


class BaseStormOpenIDStore(OpenIDStore):
    """An association store for the OpenID Provider."""

    OpenIDAssociation = BaseStormOpenIDAssociation
    OpenIDNonce = BaseStormOpenIDNonce

    def storeAssociation(self, server_url, association):
        """See `OpenIDStore`."""
        store = IPrimaryStore(self.Association)
        db_assoc = store.get(
            self.Association,
            (
                six.ensure_text(server_url),
                six.ensure_text(association.handle, "ASCII"),
            ),
        )
        if db_assoc is None:
            db_assoc = self.Association(server_url, association)
            store.add(db_assoc)
        else:
            db_assoc.update(association)

    def getAssociation(self, server_url, handle=None):
        """See `OpenIDStore`."""
        store = IPrimaryStore(self.Association)
        server_url = str(server_url)
        if handle is None:
            result = store.find(self.Association, server_url=server_url)
        else:
            handle = str(handle)
            result = store.find(
                self.Association, server_url=server_url, handle=handle
            )

        db_associations = list(result)
        associations = []
        for db_assoc in db_associations:
            assoc = db_assoc.as_association()
            if assoc.expiresIn == 0:
                store.remove(db_assoc)
            else:
                associations.append(assoc)

        if len(associations) == 0:
            return None
        associations.sort(key=attrgetter("issued"))
        return associations[-1]

    def removeAssociation(self, server_url, handle):
        """See `OpenIDStore`."""
        store = IPrimaryStore(self.Association)
        assoc = store.get(
            self.Association,
            (six.ensure_text(server_url), six.ensure_text(handle, "ASCII")),
        )
        if assoc is None:
            return False
        store.remove(assoc)
        return True

    def useNonce(self, server_url, timestamp, salt):
        """See `OpenIDStore`."""
        # If the nonce is too far from the present time, it is not valid.
        if abs(timestamp - time.time()) > nonce.SKEW:
            return False

        server_url = six.ensure_text(server_url)
        salt = six.ensure_text(salt, "ASCII")

        store = IPrimaryStore(self.Nonce)
        old_nonce = store.get(self.Nonce, (server_url, timestamp, salt))
        if old_nonce is not None:
            # The nonce has already been seen, so reject it.
            return False
        # Record the nonce so it can't be used again.
        store.add(self.Nonce(server_url, timestamp, salt))
        return True

    def cleanupAssociations(self):
        """See `OpenIDStore`."""
        store = IPrimaryStore(self.Association)
        now = int(time.time())
        expired = store.find(
            self.Association,
            self.Association.issued + self.Association.lifetime < now,
        )
        count = expired.count()
        if count > 0:
            expired.remove()
        return count
