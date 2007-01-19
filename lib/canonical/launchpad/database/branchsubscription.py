# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['BranchSubscription']

from zope.interface import implements

from sqlobject import ForeignKey, IntCol

from canonical.database.constants import DEFAULT
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import IBranchSubscription

from canonical.lp.dbschema import (
    EnumCol,
    BranchSubscriptionNotificationLevel,
    BranchSubscriptionDiffSize)

class BranchSubscription(SQLBase):
    """A relationship between a person and a branch."""

    implements(IBranchSubscription)

    _table = 'BranchSubscription'

    person = ForeignKey(dbName='person', foreignKey='Person', notNull=True)
    branch = ForeignKey(dbName='branch', foreignKey='Branch', notNull=True)
    notification_level = EnumCol(schema=BranchSubscriptionNotificationLevel,
                                 notNull=True, default=DEFAULT)
    max_diff_lines = EnumCol(schema=BranchSubscriptionDiffSize,
                             notNull=True)
