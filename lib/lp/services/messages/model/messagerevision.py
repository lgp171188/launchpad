# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Message revision history."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'MessageRevision',
    'MessageRevisionChunk',
    ]

import pytz
from storm.locals import (
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.services.database.constants import UTC_NOW
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.messages.interfaces.messagerevision import (
    IMessageRevision,
    IMessageRevisionChunk,
    )
from lp.services.propertycache import (
    cachedproperty,
    get_property_cache,
    )


@implementer(IMessageRevision)
class MessageRevision(StormBase):
    """A historical revision of a IMessage."""

    __storm_table__ = 'MessageRevision'

    id = Int(primary=True)

    message_id = Int(name='message', allow_none=False)
    message = Reference(message_id, 'Message.id')

    revision = Int(name='revision', allow_none=False)

    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)
    date_deleted = DateTime(
        name="date_deleted", tzinfo=pytz.UTC, allow_none=True)

    def __init__(self, message, revision, date_created, date_deleted=None):
        self.message = message
        self.revision = revision
        self.date_created = date_created
        self.date_deleted = date_deleted

    @cachedproperty
    def chunks(self):
        return list(IStore(self).find(
            MessageRevisionChunk, message_revision=self))

    @property
    def content(self):
        return '\n\n'.join(i.content for i in self.chunks)

    def deleteContent(self):
        store = IStore(self)
        store.find(MessageRevisionChunk, message_revision=self).remove()
        self.date_deleted = UTC_NOW
        del get_property_cache(self).chunks


@implementer(IMessageRevisionChunk)
class MessageRevisionChunk(StormBase):
    __storm_table__ = 'MessageRevisionChunk'

    id = Int(primary=True)

    message_revision_id = Int(name='messagerevision', allow_none=False)
    message_revision = Reference(message_revision_id, 'MessageRevision.id')

    sequence = Int(name='sequence', allow_none=False)

    content = Unicode(name="content", allow_none=False)

    def __init__(self, message_revision, sequence, content):
        self.message_revision = message_revision
        self.sequence = sequence
        self.content = content
