# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""The implementation of the branch cloud."""

__all__ = [
    "BranchCloud",
]


from datetime import datetime, timedelta, timezone

from storm.expr import Alias, Func
from storm.locals import Count, Desc, Max, Not
from zope.interface import provider

from lp.code.interfaces.branch import IBranchCloud
from lp.code.model.revision import RevisionCache
from lp.registry.model.product import Product
from lp.services.database.interfaces import IStandbyStore


@provider(IBranchCloud)
class BranchCloud:
    """See `IBranchCloud`."""

    @staticmethod
    def getProductsWithInfo(num_products=None):
        """See `IBranchCloud`."""
        distinct_revision_author = Func(
            "distinct", RevisionCache.revision_author_id
        )
        commits = Alias(Count(RevisionCache.revision_id))
        epoch = datetime.now(timezone.utc) - timedelta(days=30)
        # It doesn't matter if this query is even a whole day out of date, so
        # use the standby store.
        result = IStandbyStore(RevisionCache).find(
            (
                Product.name,
                commits,
                Count(distinct_revision_author),
                Max(RevisionCache.revision_date),
            ),
            RevisionCache.product == Product.id,
            Not(RevisionCache.private),
            RevisionCache.revision_date >= epoch,
        )
        result = result.group_by(Product.name)
        result = result.order_by(Desc(commits))
        if num_products:
            result.config(limit=num_products)
        return result
