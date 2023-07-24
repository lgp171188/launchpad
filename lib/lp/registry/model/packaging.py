# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["Packaging", "PackagingUtil"]

from datetime import timezone

from lazr.lifecycle.event import ObjectCreatedEvent, ObjectDeletedEvent
from storm.locals import DateTime, Int, Reference
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
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(IPackaging)
class Packaging(StormBase):
    """A Packaging relating a SourcePackage and a Product."""

    __storm_table__ = "Packaging"

    id = Int(primary=True)
    productseries_id = Int(name="productseries", allow_none=False)
    productseries = Reference(productseries_id, "ProductSeries.id")
    sourcepackagename_id = Int(name="sourcepackagename", allow_none=False)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")
    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")
    packaging = DBEnum(name="packaging", allow_none=False, enum=PackagingType)
    datecreated = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )
    owner_id = Int(
        name="owner",
        validator=validate_public_person,
        allow_none=True,
        default=None,
    )
    owner = Reference(owner_id, "Person.id")

    @property
    def sourcepackage(self):
        from lp.registry.model.sourcepackage import SourcePackage

        return SourcePackage(
            distroseries=self.distroseries,
            sourcepackagename=self.sourcepackagename,
        )

    def __init__(
        self,
        productseries,
        sourcepackagename,
        distroseries,
        packaging,
        owner=None,
    ):
        super().__init__()
        self.productseries = productseries
        self.sourcepackagename = sourcepackagename
        self.distroseries = distroseries
        self.packaging = packaging
        self.owner = owner
        notify(ObjectCreatedEvent(self))

    def destroySelf(self):
        notify(ObjectDeletedEvent(self))
        IStore(self).remove(self)


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
        packaging = Packaging(
            productseries=productseries,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
            packaging=packaging,
            owner=owner,
        )
        IStore(packaging).flush()
        return packaging

    def get(self, productseries, sourcepackagename, distroseries):
        criteria = {
            "sourcepackagename": sourcepackagename,
            "distroseries": distroseries,
        }
        if productseries is not None:
            criteria["productseries"] = productseries
        return IStore(Packaging).find(Packaging, **criteria).one()

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
