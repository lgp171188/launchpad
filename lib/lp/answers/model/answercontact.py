# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ORM implementation of IAnswerContact."""

__all__ = ["AnswerContact"]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.answers.interfaces.answercontact import IAnswerContact
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.stormbase import StormBase


@implementer(IAnswerContact)
class AnswerContact(StormBase):
    """An entry for an answer contact for an `IQuestionTarget`."""

    __storm_table__ = "AnswerContact"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    person_id = Int(
        name="person", allow_none=False, validator=validate_public_person
    )
    person = Reference(person_id, "Person.id")
    product_id = Int(name="product", allow_none=True)
    product = Reference(product_id, "Product.id")
    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")
    sourcepackagename_id = Int(name="sourcepackagename", allow_none=True)
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")

    def __init__(
        self, person, product=None, distribution=None, sourcepackagename=None
    ):
        super().__init__()
        self.person = person
        self.product = product
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
