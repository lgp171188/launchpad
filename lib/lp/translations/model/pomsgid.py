# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = ['POMsgID']

import six
from storm.expr import Func
from storm.locals import (
    Int,
    Unicode,
    )
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.pomsgid import IPOMsgID


@implementer(IPOMsgID)
class POMsgID(StormBase):

    __storm_table__ = 'POMsgID'

    id = Int(primary=True)
    msgid = Unicode(name='msgid', allow_none=False)

    def __init__(self, msgid):
        super(POMsgID, self).__init__()
        self.msgid = msgid

    @classmethod
    def new(cls, msgid):
        """Return a new POMsgID object for the given msgid."""
        pomsgid = cls(msgid)
        IStore(cls).add(pomsgid)
        return pomsgid

    @classmethod
    def getByMsgid(cls, key):
        """Return a POMsgID object for the given msgid.

        :raises NotFoundError: if the msgid is not found.
        """
        # We can't search directly on msgid, because this database column
        # contains values too large to index. Instead we search on its
        # hash, which *is* indexed.
        r = IStore(POMsgID).find(
            POMsgID,
            Func('sha1', POMsgID.msgid) ==
                Func('sha1', six.ensure_text(key))).one()
        if r is None:
            raise NotFoundError(six.ensure_str(key, errors='replace'))
        return r
