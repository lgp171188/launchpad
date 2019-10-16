# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Model implementing `OCIProjectSeries`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIProjectSeries',
    ]

import pytz
from storm.locals import (
    DateTime,
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.registry.errors import InvalidName
from lp.registry.interfaces.ociprojectseries import (
    IOCIProjectSeries,
    IOCIProjectSeriesSet,
    )
from lp.services.database.constants import DEFAULT
from lp.services.database.interfaces import IMasterStore
from lp.services.database.stormbase import StormBase


@implementer(IOCIProjectSeries)
class OCIProjectSeries(StormBase):
    """See `IOCIProjectSeries`."""

    __storm_table__ = "OCIProjectSeries"

    id = Int(primary=True)

    ociproject_id = Int(name='ociproject', allow_none=False)
    ociproject = Reference(ociproject_id, "OCIProject.id")

    name = Unicode(name="name", allow_none=False)

    summary = Unicode(name="summary", allow_none=False)

    date_created = DateTime(
        name="date_created", tzinfo=pytz.UTC, allow_none=False)

    registrant_id = Int(name='registrant', allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    status = Int(default=2)

    def __init__(self, ociproject, name, summary,
                 registrant, status, date_created=DEFAULT):
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI project series." % name)
        self.name = name
        self.ociproject = ociproject
        self.summary = summary
        self.registrant = registrant
        self.status = status


@implementer(IOCIProjectSeriesSet)
class OCIProjectSeriesSet:
    """See `IOCIProjectSeriesSet`."""

    def new(self, ociproject, name, summary, registrant, status,
            date_created=DEFAULT):
        """See `IOCIProjectSeriesSet`."""
        store = IMasterStore(OCIProjectSeries)
        target_series = OCIProjectSeries(
            ociproject, name, summary, registrant, status,
            date_created=date_created)
        store.add(target_series)
        return target_series
