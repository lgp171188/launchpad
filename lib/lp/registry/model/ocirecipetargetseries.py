# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Model implementing `OCIRecipeTargetSeries`."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeTargetSeries',
    ]

from storm.locals import (
    Int,
    Reference,
    Unicode,
    )
from zope.interface import implementer

from lp.app.validators.name import valid_name
from lp.registry.errors import InvalidName
from lp.registry.interfaces.ocirecipetargetseries import (
    IOCIRecipeTargetSeries,
    IOCIRecipeTargetSeriesSet,
    )
from lp.services.database.interfaces import IMasterStore
from lp.services.database.stormbase import StormBase


@implementer(IOCIRecipeTargetSeries)
class OCIRecipeTargetSeries(StormBase):
    """See `IOCIRecipeTargetSeries`."""

    __storm_table__ = "OCIRecipeTargetSeries"

    id = Int(primary=True)

    ociproject_id = Int(name='ociproject', allow_none=False)
    ociproject = Reference(ociproject_id, "OCIProject.id")

    name = Unicode(name="name", allow_none=False)

    def __init__(self, ociproject, name):
        if not valid_name(name):
            raise InvalidName(
                "%s is not a valid name for an OCI recipe series." % name)
        self.name = name
        self.ociproject = ociproject


@implementer(IOCIRecipeTargetSeriesSet)
class OCIRecipeTargetSeriesSet:
    """See `IOCIRecipeTargetSeriesSet`."""

    def new(self, ociproject, name):
        """See `IOCIRecipeTargetSeriesSet`."""
        store = IMasterStore(OCIRecipeTargetSeries)
        target_series = OCIRecipeTargetSeries(ociproject, name)
        store.add(target_series)
        return target_series
