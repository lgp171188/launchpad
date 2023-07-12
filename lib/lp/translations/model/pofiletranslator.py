# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "POFileTranslator",
    "POFileTranslatorSet",
]

from operator import itemgetter

import pytz
from storm.expr import And, Join, LeftJoin
from storm.locals import DateTime, Int, Reference
from storm.store import Store
from zope.interface import implementer

from lp.registry.interfaces.person import validate_public_person
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.product import Product
from lp.registry.model.productseries import ProductSeries
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.translations.interfaces.pofiletranslator import (
    IPOFileTranslator,
    IPOFileTranslatorSet,
)
from lp.translations.model.pofile import POFile
from lp.translations.model.potemplate import POTemplate


@implementer(IPOFileTranslator)
class POFileTranslator(StormBase):
    """See `IPOFileTranslator`."""

    __storm_table__ = "POFileTranslator"

    id = Int(primary=True)
    pofile_id = Int(name="pofile", allow_none=False)
    pofile = Reference(pofile_id, "POFile.id")
    person_id = Int(
        name="person", validator=validate_public_person, allow_none=False
    )
    person = Reference(person_id, "Person.id")
    date_last_touched = DateTime(
        name="date_last_touched",
        allow_none=True,
        default=None,
        tzinfo=pytz.UTC,
    )

    def __init__(self, pofile, person_id, date_last_touched=None):
        super().__init__()
        self.pofile = pofile
        # Taking `Person.ID` rather than `Person` is unusual, but it fits
        # better with how `lp.translators.scripts.scrub_pofiletranslator` is
        # designed.
        self.person_id = person_id
        self.date_last_touched = date_last_touched

    def destroySelf(self):
        IStore(self).remove(self)


@implementer(IPOFileTranslatorSet)
class POFileTranslatorSet:
    """The set of all `POFileTranslator` records."""

    def prefetchPOFileTranslatorRelations(self, pofiletranslators):
        """See `IPOFileTranslatorSet`."""
        ids = {record.id for record in pofiletranslators}
        if not ids:
            return None

        origin = [
            POFileTranslator,
            Join(POFile, POFileTranslator.pofile == POFile.id),
            Join(POTemplate, POFile.potemplate == POTemplate.id),
            LeftJoin(
                ProductSeries, POTemplate.productseries == ProductSeries.id
            ),
            LeftJoin(Product, ProductSeries.product == Product.id),
            LeftJoin(DistroSeries, POTemplate.distroseries == DistroSeries.id),
            LeftJoin(
                SourcePackageName,
                POTemplate.sourcepackagename == SourcePackageName.id,
            ),
        ]
        rows = (
            IStore(POFileTranslator)
            .using(*origin)
            .find(
                (
                    POFileTranslator,
                    POFile,
                    POTemplate,
                    ProductSeries,
                    Product,
                    DistroSeries,
                    SourcePackageName,
                ),
                POFileTranslator.id.is_in(ids),
            )
        )
        # Listify prefetch query to force its execution here.
        return list(DecoratedResultSet(rows, itemgetter(0)))

    def getForPersonPOFile(self, person, pofile):
        """See `IPOFileTranslatorSet`."""
        return (
            Store.of(pofile)
            .find(
                POFileTranslator,
                And(
                    POFileTranslator.person == person.id,
                    POFileTranslator.pofile == pofile.id,
                ),
            )
            .one()
        )

    def getForTemplate(self, potemplate):
        """See `IPOFileTranslatorSet`."""
        return Store.of(potemplate).find(
            POFileTranslator,
            POFileTranslator.pofile_id == POFile.id,
            POFile.potemplate_id == potemplate.id,
        )
