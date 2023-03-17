# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Model implementing `IOCIProjectSeries`."""

__all__ = [
    "OCIProjectSeries",
]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Unicode
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.registry.errors import InvalidName
from lp.registry.interfaces.ociprojectseries import IOCIProjectSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.services.database.constants import DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IOCIProjectSeries)
class OCIProjectSeries(StormBase):
    """See `IOCIProjectSeries`."""

    __storm_table__ = "OCIProjectSeries"

    id = Int(primary=True)

    oci_project_id = Int(name="ociproject", allow_none=False)
    oci_project = Reference(oci_project_id, "OCIProject.id")

    name = Unicode(name="name", allow_none=False)

    summary = Unicode(name="summary", allow_none=False)

    date_created = DateTime(
        name="date_created", tzinfo=timezone.utc, allow_none=False
    )

    registrant_id = Int(name="registrant", allow_none=False)
    registrant = Reference(registrant_id, "Person.id")

    status = DBEnum(name="status", allow_none=False, enum=SeriesStatus)

    def __init__(
        self,
        oci_project,
        name,
        summary,
        registrant,
        status,
        date_created=DEFAULT,
    ):
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI project series." % name
            )
        self.name = name
        self.oci_project = oci_project
        self.summary = summary
        self.registrant = registrant
        self.status = status
        self.date_created = date_created

    def destroySelf(self):
        IStore(self).remove(self)
