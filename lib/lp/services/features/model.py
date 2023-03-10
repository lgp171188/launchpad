# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "FeatureFlag",
    "FeatureFlagChangelogEntry",
    "getFeatureStore",
]

from datetime import datetime, timezone

import six
from storm.locals import DateTime, Int, Reference, Unicode
from zope.interface import implementer

from lp.services.database.datetimecol import UtcDateTimeCol
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.features.interfaces import IFeatureRules


@implementer(IFeatureRules)
class FeatureRules:
    """
    See `IFeatureRules`
    """

    pass


class FeatureFlag(StormBase):
    """Database setting of a particular flag in a scope"""

    __storm_table__ = "FeatureFlag"
    __storm_primary__ = "scope", "flag"

    scope = Unicode(allow_none=False)
    flag = Unicode(allow_none=False)
    priority = Int(allow_none=False)
    value = Unicode(allow_none=False)
    date_modified = DateTime()

    def __init__(self, scope, priority, flag, value):
        super().__init__()
        self.scope = scope
        self.priority = priority
        self.flag = flag
        self.value = value


class FeatureFlagChangelogEntry(StormBase):
    """A record of a change to the whole set of feature flags."""

    __storm_table__ = "FeatureFlagChangelogEntry"

    id = Int(primary=True)
    date_changed = UtcDateTimeCol(notNull=True)
    diff = Unicode(allow_none=False)
    comment = Unicode(allow_none=False)
    person_id = Int(name="person", allow_none=False)
    person = Reference(person_id, "Person.id")

    def __init__(self, diff, comment, person):
        super().__init__()
        self.diff = six.ensure_text(diff)
        self.date_changed = datetime.now(timezone.utc)
        self.comment = six.ensure_text(comment)
        self.person = person


def getFeatureStore():
    """Get Storm store to access feature definitions."""
    # TODO: This is copied so many times in Launchpad; maybe it should be more
    # general?
    return IStore(FeatureFlag)
