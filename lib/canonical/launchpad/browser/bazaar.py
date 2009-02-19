# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""View support classes for the bazaar application."""

__metaclass__ = type

__all__ = [
    'BazaarApplicationView',
    'BazaarProductView',
    ]

from datetime import datetime

from zope.component import getUtility

import bzrlib

from canonical.cachedproperty import cachedproperty
from canonical.config import config

from canonical.launchpad.interfaces.branch import IBranchCloud, IBranchSet
from canonical.launchpad.interfaces.codeimport import ICodeImportSet
from canonical.launchpad.interfaces.launchpad import IBazaarApplication
from canonical.launchpad.interfaces.product import IProduct, IProductSet
from canonical.launchpad.webapp import (
    ApplicationMenu, enabled_with_permission, LaunchpadView, Link)

from lazr.delegates import delegates

class BazaarBranchesMenu(ApplicationMenu):
    usedfor = IBazaarApplication
    facet = 'branches'
    links = ['importer']

    @enabled_with_permission('launchpad.Admin')
    def importer(self):
        target = 'series/'
        text = 'Branch importer'
        summary = 'Manage CVS and SVN Trunk Imports'
        return Link(target, text, summary, icon='branch')


class BazaarApplicationView(LaunchpadView):

    @property
    def branch_count(self):
        return getUtility(IBranchSet).count()

    @property
    def product_count(self):
        return getUtility(IProductSet).getProductsWithBranches().count()

    @property
    def branches_with_bugs_count(self):
        return getUtility(IBranchSet).countBranchesWithAssociatedBugs()

    @property
    def import_count(self):
        return getUtility(ICodeImportSet).getActiveImports().count()

    @property
    def bzr_version(self):
        return bzrlib.__version__

    @cachedproperty
    def recently_changed_branches(self):
        """Return the five most recently changed branches."""
        return list(getUtility(IBranchSet).getRecentlyChangedBranches(
            5, visible_by_user=self.user))

    @cachedproperty
    def recently_imported_branches(self):
        """Return the five most recently imported branches."""
        return list(getUtility(IBranchSet).getRecentlyImportedBranches(
            5, visible_by_user=self.user))

    @cachedproperty
    def recently_registered_branches(self):
        """Return the five most recently registered branches."""
        return list(getUtility(IBranchSet).getRecentlyRegisteredBranches(
            5, visible_by_user=self.user))

    @cachedproperty
    def short_product_tag_cloud(self):
        """Show a preview of the product tag cloud."""
        return BazaarProductView().products(
            num_products=config.launchpad.code_homepage_product_cloud_size)


def range_get(range_map, x):
    """Get a value for 'x' from 'range_map', defaulting to 'default'.

    A 'range map' is a map where the keys are ordinals. 'range_get' returns
    the value for the smallest key defined in the map that is larger than 'x'.
    If no such key exists, 'range_get' raises KeyError.
    """
    bigger_keys = sorted(key for key in range_map.iterkeys() if key >= x)
    if bigger_keys == []:
        raise KeyError(x)
    return range_map[min(bigger_keys)]


class ProductInfo:

    delegates(IProduct, 'product')

    def __init__(
        self, product, num_branches, branch_size, elapsed):
        self.product = product
        self.num_branches = num_branches
        self.branch_size = branch_size
        self.elapsed_since_commit = elapsed

    @property
    def branch_class(self):
        return "cloud-size-%s" % self.branch_size

    @property
    def time_darkness(self):
        if self.elapsed_since_commit is None:
            return "light"
        if self.elapsed_since_commit.days < 7:
            return "dark"
        if self.elapsed_since_commit.days < 31:
            return "medium"
        return "light"

    @property
    def html_class(self):
        return "%s cloud-%s" % (self.branch_class, self.time_darkness)

    @property
    def html_title(self):
        if self.num_branches == 1:
            size = "1 branch"
        else:
            size = "%d branches" % self.num_branches
        if self.elapsed_since_commit is None:
            commit = "no commits yet"
        elif self.elapsed_since_commit.days == 0:
            commit = "last commit less than a day old"
        elif self.elapsed_since_commit.days == 1:
            commit = "last commit one day old"
        else:
            commit = (
                "last commit %d days old" % self.elapsed_since_commit.days)
        return "%s, %s" % (size, commit)


class BazaarProductView:
    """Browser class for products gettable with Bazaar."""

    def _distribute(self, values, percentiles):
        """Return a mapping from values to percentiles.

        :param values: A list of ordinal values.
        :param percentiles: A list of percentage values, represented as
            floats in the range [0, 1].
        :return: A dict mapping the value at percentile to the percentile.
        """
        assert max(percentiles) <= 1.0
        assert min(percentiles) >= 0.0
        values.sort()
        num_values = len(values)
        distribution = {}
        last_index = None
        for cutoff in percentiles:
            if cutoff == 1.0:
                index = -1
            else:
                index = int(num_values * cutoff)
            if last_index != index:
                distribution[values[index]] = cutoff
                last_index = index
        return distribution

    def _make_distribution_map(self, values, percentile_map):
        """Given some values and a map of percentiles to other values, return
        a function that will take a value in the same domain as 'values' and
        map it to a value in the 'percentile_map' dict.

        If the 'percentile_map' dict has an entry for 1.0, that will be used
        as the default value.
        """
        distribution = self._distribute(values, percentile_map.keys())
        def getter(x):
            percentile = range_get(distribution, x)
            return percentile_map[percentile]
        return getter

    def products(self, num_products=None):
        product_info = sorted(
            list(getUtility(IBranchCloud).getProductsWithInfo(num_products)),
            key=lambda data: data[0].name)
        now = datetime.today()
        counts = sorted(zip(*product_info)[1])
        size_mapping = {
            0.2: 'smallest',
            0.4: 'small',
            0.6: 'medium',
            0.8: 'large',
            1.0: 'largest',
            }
        num_branches_to_size = self._make_distribution_map(
            counts, size_mapping)

        for product, num_branches, last_revision_date in product_info:
            # Projects with no branches are not interesting.
            if num_branches == 0:
                continue
            branch_size = num_branches_to_size(num_branches)
            elapsed = now - last_revision_date
            yield ProductInfo(
                product, num_branches, branch_size, elapsed)
