# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "POExportRequest",
    "POExportRequestSet",
]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Store
from zope.interface import implementer

from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import (
    IPrimaryStore,
    IStandbyStore,
    IStore,
)
from lp.services.database.sqlbase import quote
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.poexportrequest import (
    IPOExportRequest,
    IPOExportRequestSet,
)
from lp.translations.interfaces.potemplate import IPOTemplate
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat,
)


@implementer(IPOExportRequestSet)
class POExportRequestSet:
    @property
    def entry_count(self):
        """See `IPOExportRequestSet`."""
        return IStore(POExportRequest).find(POExportRequest, True).count()

    def estimateBacklog(self):
        row = (
            IStore(POExportRequest)
            .execute("SELECT now() - min(date_created) FROM POExportRequest")
            .get_one()
        )
        if row is None:
            return None
        else:
            return row[0]

    def addRequest(
        self,
        person,
        potemplates=None,
        pofiles=None,
        format=TranslationFileFormat.PO,
    ):
        """See `IPOExportRequestSet`."""
        if potemplates is None:
            potemplates = []
        elif IPOTemplate.providedBy(potemplates):
            # Allow single POTemplate as well as list of POTemplates
            potemplates = [potemplates]
        if pofiles is None:
            pofiles = []

        if not (potemplates or pofiles):
            raise AssertionError(
                "Can't add a request with no PO templates and no PO files."
            )

        potemplate_ids = ", ".join(
            [quote(template.id) for template in potemplates]
        )
        # A null pofile stands for the template itself.  We represent it in
        # SQL as -1, because that's how it's indexed in the request table.
        pofile_ids = ", ".join(
            [quote(pofile.id) for pofile in pofiles] + ["-1"]
        )

        query_params = {
            "person": quote(person),
            "format": quote(format),
            "templates": potemplate_ids,
            "pofiles": pofile_ids,
        }

        store = IPrimaryStore(POExportRequest)

        if potemplates:
            # Create requests for all these templates, insofar as the same
            # user doesn't already have requests pending for them in the same
            # format.
            store.execute(
                """
                INSERT INTO POExportRequest(person, potemplate, format)
                SELECT %(person)s, template.id, %(format)s
                FROM POTemplate AS template
                LEFT JOIN POExportRequest AS existing ON
                    existing.person = %(person)s AND
                    existing.potemplate = template.id AND
                    existing.pofile IS NULL AND
                    existing.format = %(format)s
                WHERE
                    template.id IN (%(templates)s) AND
                    existing.id IS NULL
            """
                % query_params
            )

        if pofiles:
            # Create requests for all these translations, insofar as the same
            # user doesn't already have identical requests pending.
            store.execute(
                """
                INSERT INTO POExportRequest(
                    person, potemplate, pofile, format)
                SELECT %(person)s, template.id, pofile.id, %(format)s
                FROM POFile
                JOIN POTemplate AS template ON template.id = POFile.potemplate
                LEFT JOIN POExportRequest AS existing ON
                    existing.person = %(person)s AND
                    existing.pofile = POFile.id AND
                    existing.format = %(format)s
                WHERE
                    POFile.id IN (%(pofiles)s) AND
                    existing.id IS NULL
                """
                % query_params
            )

    def _getOldestLiveRequest(self):
        """Return the oldest live request on the primary store.

        Due to replication lag, the primary store is always a little
        ahead of the standby store that exports come from.
        """
        primary_store = IPrimaryStore(POExportRequest)
        sorted_by_id = primary_store.find(POExportRequest).order_by(
            POExportRequest.id
        )
        return sorted_by_id.first()

    def _getHeadRequest(self):
        """Return oldest request on the queue."""
        # Due to replication lag, it's possible that the standby store
        # still has copies of requests that have already been completed
        # and deleted from the primary store.  So first get the oldest
        # request that is "live," i.e. still present on the primary
        # store.
        oldest_live = self._getOldestLiveRequest()
        if oldest_live is None:
            return None
        else:
            return (
                IStandbyStore(POExportRequest)
                .find(POExportRequest, POExportRequest.id == oldest_live.id)
                .one()
            )

    def getRequest(self):
        """See `IPOExportRequestSet`."""
        # Exports happen off the standby store.  To ensure that export
        # does not happen until requests have been replicated to the
        # standby, they are read primarily from the standby even though they
        # are deleted on the primary afterwards.
        head = self._getHeadRequest()
        if head is None:
            return None, None, None, None

        requests = (
            IStandbyStore(POExportRequest)
            .find(
                POExportRequest,
                POExportRequest.person == head.person,
                POExportRequest.format == head.format,
                POExportRequest.date_created == head.date_created,
            )
            .order_by(POExportRequest.potemplate_id)
        )

        summary = [
            (request.id, request.pofile or request.potemplate)
            for request in requests
        ]

        sources = [source for request_id, source in summary]
        request_ids = [request_id for request_id, source in summary]

        return head.person, sources, head.format, request_ids

    def removeRequest(self, request_ids):
        """See `IPOExportRequestSet`."""
        if request_ids:
            IPrimaryStore(POExportRequest).find(
                POExportRequest, POExportRequest.id.is_in(request_ids)
            ).remove()


@implementer(IPOExportRequest)
class POExportRequest(StormBase):
    __storm_table__ = "POExportRequest"

    id = Int(primary=True)

    person_id = Int(
        name="person", allow_none=False, validator=validate_public_person
    )
    person = Reference(person_id, "Person.id")

    date_created = DateTime(
        tzinfo=timezone.utc, name="date_created", default=DEFAULT
    )

    potemplate_id = Int(name="potemplate", allow_none=False)
    potemplate = Reference(potemplate_id, "POTemplate.id")

    pofile_id = Int(name="pofile", allow_none=True)
    pofile = Reference(pofile_id, "POFile.id")

    format = DBEnum(
        name="format",
        enum=TranslationFileFormat,
        default=TranslationFileFormat.PO,
        allow_none=False,
    )

    def destroySelf(self):
        Store.of(self).remove(self)
