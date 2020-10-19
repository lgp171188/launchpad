# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for ArchiveDependency."""

__metaclass__ = type

__all__ = ['ArchiveDependency']

import pytz
from storm.locals import (
    DateTime,
    Int,
    Reference,
    Store,
    )
from zope.interface import implementer

from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.soyuz.adapters.archivedependencies import get_components_for_context
from lp.soyuz.interfaces.archivedependency import IArchiveDependency


@implementer(IArchiveDependency)
class ArchiveDependency(StormBase):
    """See `IArchiveDependency`."""

    __storm_table__ = 'ArchiveDependency'
    __storm_order__ = 'id'

    id = Int(primary=True)

    date_created = DateTime(
        name='date_created', tzinfo=pytz.UTC, allow_none=False,
        default=UTC_NOW)

    archive_id = Int(name='archive', allow_none=False)
    archive = Reference(archive_id, 'Archive.id')

    dependency_id = Int(name='dependency', allow_none=False)
    dependency = Reference(dependency_id, 'Archive.id')

    pocket = DBEnum(
        name='pocket', allow_none=False, enum=PackagePublishingPocket)

    component_id = Int(name='component', allow_none=True)
    component = Reference(component_id, 'Component.id')

    def __init__(self, archive, dependency, pocket, component=None):
        super(ArchiveDependency, self).__init__()
        self.archive = archive
        self.dependency = dependency
        self.pocket = pocket
        self.component = component

    @property
    def component_name(self):
        """See `IArchiveDependency`"""
        if self.component:
            return self.component.name
        else:
            return None

    @property
    def title(self):
        """See `IArchiveDependency`."""
        if self.dependency.is_ppa:
            return self.dependency.displayname

        pocket_title = "%s - %s" % (
            self.dependency.displayname, self.pocket.name)

        if self.component is None:
            return pocket_title

        # XXX cjwatson 2016-03-31: This may be inaccurate, but we can't do
        # much better since this ArchiveDependency applies to multiple
        # series which may each resolve component dependencies in different
        # ways.
        distroseries = self.archive.distribution.currentseries

        component_part = ", ".join(get_components_for_context(
            self.component, distroseries, self.pocket))

        return "%s (%s)" % (pocket_title, component_part)

    def destroySelf(self):
        Store.of(self).remove(self)
