# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'SpecificationMessage',
    'SpecificationMessageSet'
    ]

from email.Utils import make_msgid

from zope.interface import implements

from sqlobject import BoolCol, ForeignKey, StringCol
from storm.store import Store

from canonical.database.sqlbase import SQLBase, sqlvalues
from lp.blueprints.interfaces.specificationmessage import (
    ISpecificationMessage, ISpecificationMessageSet)
from canonical.launchpad.database.message import Message, MessageChunk


class SpecificationMessage(SQLBase):
    """A table linking specifictions and messages."""

    implements(ISpecificationMessage)

    _table = 'SpecificationMessage'

    specification = ForeignKey(
        dbName='specification', foreignKey='Specification', notNull=True)
    message = ForeignKey(dbName='message', foreignKey='Message', notNull=True)
    visible = BoolCol(notNull=True, default=True)


class SpecificationMessageSet:
    """See ISpecificationMessageSet."""

    implements(ISpecificationMessageSet)

    def createMessage(self, subject, spec, owner, content=None):
        """See ISpecificationMessageSet."""
        msg = Message(
            parent=spec.initial_message, owner=owner,
            rfc822msgid=make_msgid('blueprint'), subject=subject)
        chunk = MessageChunk(message=msg, content=content, sequence=1)
        specmsg = SpecificationMessage(specification=spec, message=msg)

        Store.of(specmsg).flush()
        return specmsg

    def get(self, specmessageid):
        """See ISpecificationMessageSet."""
        return SpecificationMessage.get(specmessageid)

    def getBySpecificationAndMessage(self, spec, message):
        """See ISpecificationMessageSet."""
        return SpecificationMessage.selectOneBy(
            specification=spec, message=message)
