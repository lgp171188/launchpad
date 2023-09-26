# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Session Storm database classes"""

__all__ = ["SessionData", "SessionPkgData"]

from datetime import timezone

from storm.locals import DateTime, Pickle, Unicode
from zope.interface import implementer, provider

from lp.services.database.stormbase import StormBase
from lp.services.session.interfaces import IUseSessionStore


@implementer(IUseSessionStore)
@provider(IUseSessionStore)
class SessionData(StormBase):
    """A user's Session."""

    __storm_table__ = "SessionData"
    client_id = Unicode(primary=True)
    created = DateTime(tzinfo=timezone.utc)
    last_accessed = DateTime(tzinfo=timezone.utc)


@implementer(IUseSessionStore)
@provider(IUseSessionStore)
class SessionPkgData(StormBase):
    """Data storage for a Session."""

    __storm_table__ = "SessionPkgData"
    __storm_primary__ = "client_id", "product_id", "key"

    client_id = Unicode()
    product_id = Unicode()
    key = Unicode()
    pickle = Pickle()
