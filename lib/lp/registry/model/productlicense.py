# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes including and related to ProductLicense."""

__all__ = [
    "ProductLicense",
]

from storm.locals import Int, Reference, Store
from zope.interface import implementer

from lp.registry.interfaces.product import License
from lp.registry.interfaces.productlicense import IProductLicense
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase


@implementer(IProductLicense)
class ProductLicense(StormBase):
    """A product's licence."""

    __storm_table__ = "ProductLicense"

    id = Int(primary=True)
    product_id = Int(name="product", allow_none=False)
    product = Reference(product_id, "Product.id")
    license = DBEnum(name="license", allow_none=False, enum=License)

    def __init__(self, product, license):
        super().__init__()
        self.product = product
        self.license = license

    def destroySelf(self):
        Store.of(self).remove(self)
