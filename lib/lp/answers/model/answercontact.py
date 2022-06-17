# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""SQLBase implementation of  IAnswerContact."""

__all__ = ["AnswerContact"]


from zope.interface import implementer

from lp.answers.interfaces.answercontact import IAnswerContact
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.sqlbase import SQLBase
from lp.services.database.sqlobject import ForeignKey


@implementer(IAnswerContact)
class AnswerContact(SQLBase):
    """An entry for an answer contact for an `IQuestionTarget`."""

    _defaultOrder = ["id"]
    _table = "AnswerContact"

    person = ForeignKey(
        dbName="person",
        notNull=True,
        foreignKey="Person",
        storm_validator=validate_public_person,
    )
    product = ForeignKey(dbName="product", notNull=False, foreignKey="Product")
    distribution = ForeignKey(
        dbName="distribution", notNull=False, foreignKey="Distribution"
    )
    sourcepackagename = ForeignKey(
        dbName="sourcepackagename",
        notNull=False,
        foreignKey="SourcePackageName",
    )
