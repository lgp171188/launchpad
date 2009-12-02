# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Module docstring goes here."""

__metaclass__ = type
__all__ = []


from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol

from lp.soyuz.interfaces.sourcepackagerecipedata import (
    ISourcePackageRecipeData)

from storm.locals import Int, Reference, Unicode


class _SourcePackageRecipeDataBranch:
    __storm_table__ = "SourcePackageRecipeDataBranch"
    id = Int(primary=True)

    branch_id = Int(name='branch', allow_none=False)
    branch = Reference(branch_id, 'Branch.id')

    sourcepackagerecipedata_id = Int(
        name='sourcepackagerecipedata', allow_none=False)
    sourcepackagerecipedata = Reference(
        sourcepackagerecipedata_id, 'SourcePackageRecipeData.id')


class SourcePackageRecipeData:
    """See `ISourcePackageRecipeData`."""

    implements(ISourcePackageRecipeData)

    __storm_table__ = "SourcePackageRecipeData"

    id = Int(primary=True)
    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    distroseries_id = Int(name='distroseries', allow_none=False)
    distroseries = Reference(distroseries_id, 'DistroSeries.id')

    sourcepackagename_id = Int(name='sourcepackagename', allow_none=False)
    sourcepackagename = Reference(
        sourcepackagename_id, 'SourcePackageName.id')

    _recipe = Unicode(name='recipe')

    def _get_recipe(self):
        # Read recipe text out, rewrite branch references.
        pass

    def _set_recipe(self):
        # Read recipe text out, rewrite branch references.
        pass

    recipe = property(_get_recipe, _set_recipe)

    @property
    def referenced_branches(self):
        # Easy...
        pass
