# Copyright 2009-2017 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A person's view on a product."""

__all__ = [
    "PersonProduct",
]

from zope.interface import implementer, provider

from lp.code.model.hasbranches import HasMergeProposalsMixin
from lp.registry.interfaces.personproduct import (
    IPersonProduct,
    IPersonProductFactory,
)


@implementer(IPersonProduct)
class PersonProduct(HasMergeProposalsMixin):
    def __init__(self, person, product):
        self.person = person
        self.product = product

    @property
    def display_name(self):
        return "%s in %s" % (self.person.displayname, self.product.displayname)

    displayname = display_name

    def __eq__(self, other):
        return (
            IPersonProduct.providedBy(other)
            and self.person == other.person
            and self.product == other.product
        )

    def __ne__(self, other):
        return not self == other

    def __hash__(self):
        return hash((self.person, self.product))

    @property
    def private(self):
        return self.person.private or self.product.private


@provider(IPersonProductFactory)
class PersonProductFactory:
    @staticmethod
    def create(person, product):
        return PersonProduct(person, product)
