# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    'POFileTranslator',
    'POFileTranslatorSet',
    ]

from operator import itemgetter

from storm.expr import (
    And,
    Join,
    LeftJoin,
    )
from storm.store import Store
from zope.interface import implementer

from lp.registry.interfaces.person import validate_public_person
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.product import Product
from lp.registry.model.productseries import ProductSeries
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.database.datetimecol import UtcDateTimeCol
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import SQLBase
from lp.services.database.sqlobject import ForeignKey
from lp.translations.interfaces.pofiletranslator import (
    IPOFileTranslator,
    IPOFileTranslatorSet,
    )
from lp.translations.model.pofile import POFile
from lp.translations.model.potemplate import POTemplate


@implementer(IPOFileTranslator)
class POFileTranslator(SQLBase):
    """See `IPOFileTranslator`."""
    pofile = ForeignKey(foreignKey='POFile', dbName='pofile', notNull=True)
    person = ForeignKey(
        dbName='person', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    date_last_touched = UtcDateTimeCol(
        dbName='date_last_touched', notNull=False, default=None)


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
                ProductSeries, POTemplate.productseries == ProductSeries.id),
            LeftJoin(Product, ProductSeries.product == Product.id),
            LeftJoin(DistroSeries, POTemplate.distroseries == DistroSeries.id),
            LeftJoin(
                SourcePackageName,
                POTemplate.sourcepackagename == SourcePackageName.id),
            ]
        rows = IStore(POFileTranslator).using(*origin).find(
            (POFileTranslator, POFile, POTemplate,
             ProductSeries, Product, DistroSeries, SourcePackageName),
            POFileTranslator.id.is_in(ids))
        # Listify prefetch query to force its execution here.
        return list(DecoratedResultSet(rows, itemgetter(0)))

    def getForPersonPOFile(self, person, pofile):
        """See `IPOFileTranslatorSet`."""
        return Store.of(pofile).find(POFileTranslator, And(
            POFileTranslator.person == person.id,
            POFileTranslator.pofile == pofile.id)).one()

    def getForTemplate(self, potemplate):
        """See `IPOFileTranslatorSet`."""
        return Store.of(potemplate).find(
            POFileTranslator,
            POFileTranslator.pofileID == POFile.id,
            POFile.potemplateID == potemplate.id)
