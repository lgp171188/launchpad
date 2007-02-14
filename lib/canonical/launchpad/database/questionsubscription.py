# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = ['TicketSubscription']

from zope.interface import implements

from sqlobject import ForeignKey

from canonical.launchpad.interfaces import IQuestionSubscription

from canonical.database.sqlbase import SQLBase


class TicketSubscription(SQLBase):
    """A subscription for person to a question."""

    implements(IQuestionSubscription)

    _table='TicketSubscription'

    ticket = ForeignKey(dbName='ticket', foreignKey='Ticket', notNull=True)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)


