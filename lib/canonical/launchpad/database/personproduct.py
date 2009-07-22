# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A person's view on a product."""

__metaclass__ = type
__all__ = [
    'PersonProduct',
    ]

from zope.interface import classProvides, implements

from canonical.launchpad.interfaces.personproduct import (
    IPersonProduct, IPersonProductFactory)


class PersonProduct:

    implements(IPersonProduct)

    classProvides(IPersonProductFactory)

    def __init__(self, person, product):
        self.person = person
        self.product = product

    @staticmethod
    def create(person, product):
        return PersonProduct(person, product)
