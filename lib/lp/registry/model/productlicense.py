# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes including and related to ProductLicense."""

__all__ = [
    "ProductLicense",
]


from zope.interface import implementer

from lp.registry.interfaces.product import License
from lp.registry.interfaces.productlicense import IProductLicense
from lp.services.database.enumcol import DBEnum
from lp.services.database.sqlbase import SQLBase
from lp.services.database.sqlobject import ForeignKey


@implementer(IProductLicense)
class ProductLicense(SQLBase):
    """A product's licence."""

    product = ForeignKey(dbName="product", foreignKey="Product", notNull=True)
    license = DBEnum(name="license", allow_none=False, enum=License)
