# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BinaryAndSourcePackageName",
    "BinaryAndSourcePackageNameVocabulary",
]

from storm.locals import Unicode
from zope.interface import implementer
from zope.schema.vocabulary import SimpleTerm

from lp.services.database.stormbase import StormBase
from lp.services.webapp.vocabulary import (
    BatchedCountableIterator,
    NamedStormHugeVocabulary,
)
from lp.soyuz.interfaces.binarypackagename import IBinaryAndSourcePackageName


@implementer(IBinaryAndSourcePackageName)
class BinaryAndSourcePackageName(StormBase):
    """See IBinaryAndSourcePackageName"""

    __storm_table__ = "BinaryAndSourcePackageNameView"
    __storm_order__ = "name"

    name = Unicode("name", primary=True)


class BinaryAndSourcePackageNameIterator(BatchedCountableIterator):
    """Iterator for BinaryAndSourcePackageNameVocabulary.

    Builds descriptions from source and binary descriptions it can
    identify based on the names returned when queried.
    """

    def getTermsWithDescriptions(self, results):
        return [SimpleTerm(obj, obj.name, obj.name) for obj in results]


class BinaryAndSourcePackageNameVocabulary(NamedStormHugeVocabulary):
    """A vocabulary for searching for binary and sourcepackage names.

    This is useful for, e.g., reporting a bug on a 'package' when a reporter
    often has no idea about whether they mean a 'binary package' or a 'source
    package'.

    The value returned by a widget using this vocabulary will be either an
    ISourcePackageName or an IBinaryPackageName.
    """

    _table = BinaryAndSourcePackageName
    displayname = "Select a Package"
    _order_by = "name"
    iterator = BinaryAndSourcePackageNameIterator

    def getTermByToken(self, token):
        """See `IVocabularyTokenized`."""
        # package names are always lowercase.
        return super().getTermByToken(token.lower())
