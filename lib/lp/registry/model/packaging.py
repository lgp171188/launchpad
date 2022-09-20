# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["Packaging", "PackagingUtil"]

from lazr.lifecycle.event import ObjectCreatedEvent, ObjectDeletedEvent
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer

from lp.app.enums import InformationType
from lp.registry.errors import CannotPackageProprietaryProduct
from lp.registry.interfaces.packaging import (
    IPackaging,
    IPackagingUtil,
    PackagingType,
)
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.datetimecol import UtcDateTimeCol
from lp.services.database.enumcol import DBEnum
from lp.services.database.sqlbase import SQLBase
from lp.services.database.sqlobject import ForeignKey


@implementer(IPackaging)
class Packaging(SQLBase):
    """A Packaging relating a SourcePackage and a Product."""

    _table = "Packaging"

    productseries = ForeignKey(
        foreignKey="ProductSeries", dbName="productseries", notNull=True
    )
    sourcepackagename = ForeignKey(
        foreignKey="SourcePackageName",
        dbName="sourcepackagename",
        notNull=True,
    )
    distroseries = ForeignKey(
        foreignKey="DistroSeries", dbName="distroseries", notNull=True
    )
    packaging = DBEnum(name="packaging", allow_none=False, enum=PackagingType)
    datecreated = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    owner = ForeignKey(
        dbName="owner",
        foreignKey="Person",
        storm_validator=validate_public_person,
        notNull=False,
        default=DEFAULT,
    )

    @property
    def sourcepackage(self):
        from lp.registry.model.sourcepackage import SourcePackage

        return SourcePackage(
            distroseries=self.distroseries,
            sourcepackagename=self.sourcepackagename,
        )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        notify(ObjectCreatedEvent(self))

    def destroySelf(self):
        notify(ObjectDeletedEvent(self))
        super().destroySelf()


@implementer(IPackagingUtil)
class PackagingUtil:
    """Utilities for Packaging."""

    def createPackaging(
        self, productseries, sourcepackagename, distroseries, packaging, owner
    ):
        """See `IPackaging`.

        Raises an assertion error if there is already packaging for
        the sourcepackagename in the distroseries.
        """
        if self.packagingEntryExists(sourcepackagename, distroseries):
            raise AssertionError(
                "A packaging entry for %s in %s already exists."
                % (sourcepackagename.name, distroseries.name)
            )
        # XXX: AaronBentley: 2012-08-12 bug=1066063 Cannot adapt ProductSeries
        # to IInformationType.
        # The line below causes a failure of
        # lp.registry.tests.test_distroseries.TestDistroSeriesPackaging.
        # test_getPrioritizedPackagings_bug_tracker because
        # productseries.product loses all set permissions.
        # info_type = IInformationType(productseries).information_type
        info_type = productseries.product.information_type
        if info_type != InformationType.PUBLIC:
            raise CannotPackageProprietaryProduct(
                "Only Public project series can be packaged, not %s."
                % info_type.title
            )
        return Packaging(
            productseries=productseries,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
            packaging=packaging,
            owner=owner,
        )

    def get(self, productseries, sourcepackagename, distroseries):
        criteria = {
            "sourcepackagename": sourcepackagename,
            "distroseries": distroseries,
        }
        if productseries is not None:
            criteria["productseries"] = productseries
        return Packaging.selectOneBy(**criteria)

    def deletePackaging(self, productseries, sourcepackagename, distroseries):
        """See `IPackaging`."""
        packaging = getUtility(IPackagingUtil).get(
            productseries=productseries,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
        )
        assert packaging is not None, (
            "Tried to delete non-existent Packaging: "
            "productseries=%s/%s, sourcepackagename=%s, distroseries=%s/%s"
            % (
                productseries.name,
                productseries.product.name,
                sourcepackagename.name,
                distroseries.parent.name,
                distroseries.name,
            )
        )
        packaging.destroySelf()

    def packagingEntryExists(
        self, sourcepackagename, distroseries, productseries=None
    ):
        """See `IPackaging`."""
        packaging = self.get(
            productseries=productseries,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
        )
        return packaging is not None
