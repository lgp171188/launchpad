# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""View support classes for the bazaar application."""

__metaclass__ = type

__all__ = [
    'BazaarApplicationView',
    'BazaarApplicationNavigation',
    'BazaarProductView',
    ]

import operator

from zope.component import getUtility

from canonical.cachedproperty import cachedproperty

from canonical.launchpad.interfaces import (
    IBazaarApplication, IBranchSet, IProductSet, IProductSeriesSet)
from canonical.lp.dbschema import ImportStatus
from canonical.launchpad.webapp import (
    ApplicationMenu, canonical_url, enabled_with_permission,
    Link, Navigation, stepto)
import canonical.launchpad.layers


class BazaarBranchesMenu(ApplicationMenu):
    usedfor = IBazaarApplication
    facet = 'branches'
    links = ['importer']

    @enabled_with_permission('launchpad.Admin')
    def importer(self):
        target = 'series/'
        text = 'Branch Importer'
        summary = 'Manage CVS and SVN Trunk Imports'
        return Link(target, text, summary, icon='branch')


class BazaarApplicationView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.seriesset = getUtility(IProductSeriesSet)

    def branch_count(self):
        return getUtility(IBranchSet).count()

    def product_count(self):
        return getUtility(IProductSet).getProductsWithBranches().count()

    def branches_with_bugs_count(self):
        return getUtility(IBranchSet).countBranchesWithAssociatedBugs()

    def import_count(self):
        return self.seriesset.importcount()

    def testing_count(self):
        return self.seriesset.importcount(ImportStatus.TESTING.value)

    def autotested_count(self):
        return self.seriesset.importcount(ImportStatus.AUTOTESTED.value)

    def testfailed_count(self):
        return self.seriesset.importcount(ImportStatus.TESTFAILED.value)

    def processing_count(self):
        return self.seriesset.importcount(ImportStatus.PROCESSING.value)

    def syncing_count(self):
        return self.seriesset.importcount(ImportStatus.SYNCING.value)

    def stopped_count(self):
        return self.seriesset.importcount(ImportStatus.STOPPED.value)

    def hct_count(self):
        branches = self.seriesset.search(forimport=True,
            importstatus=ImportStatus.SYNCING.value)
        count = 0
        for branch in branches:
            for package in branch.sourcepackages:
                if package.shouldimport:
                    count += 1
                    continue
        return count

    @cachedproperty
    def recently_changed_branches(self):
        """Return the five most recently changed branches."""
        return list(getUtility(IBranchSet).getRecentlyChangedBranches(5))

    @cachedproperty
    def recently_imported_branches(self):
        """Return the five most recently imported branches."""
        return list(getUtility(IBranchSet).getRecentlyImportedBranches(5))

    @cachedproperty
    def recently_registered_branches(self):
        """Return the five most recently registered branches."""
        return list(getUtility(IBranchSet).getRecentlyRegisteredBranches(5))


class BazaarApplicationNavigation(Navigation):

    usedfor = IBazaarApplication

    newlayer = canonical.launchpad.layers.CodeLayer

    @stepto('series')
    def series(self):
        return getUtility(IProductSeriesSet)


class BazaarProductView:
    """Browser class for products gettable with Bazaar."""

    @cachedproperty
    def products(self):
        return sorted(
            getUtility(IProductSet).getProductsWithBranches(),
            key=lambda product: product.displayname.lower())

    @cachedproperty
    def summaries(self):
        # unwrapping the security proxies, so can add to the dict
        result = {}
        branchset = getUtility(IBranchSet)
        summaries = branchset.getBranchSummaryByProduct()
        for key, value in summaries.iteritems():
            result[key] = dict(value)

        for branch in branchset.getDevelopmentFocusBranches():
            result[branch.product.id]['dev_branch'] = branch
        
        for product in self.products:
            branch_url = canonical_url(product, rootsite='code')
            result[product.id]['branch_url'] = branch_url

        return result
        
