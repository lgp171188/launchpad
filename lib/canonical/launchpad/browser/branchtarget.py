# Copyright 2005 Canonical Ltd.  All rights reserved.

"""IBranchTarget browser views."""

__metaclass__ = type

__all__ = [
    'BranchTargetView',
    'PersonBranchesView',
    ]

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.interfaces import IPerson, IProduct
from canonical.launchpad.webapp import LaunchpadView

# XXX This stuff was initially cargo-culted from ITicketTarget, some of it
# could be factored out. See bug 4011. -- David Allouche 2005-09-09


class BranchTargetView(LaunchpadView):

    def context_relationship(self):
        """The relationship text used for display.

        Explains how the this branch listing relates to the context object. 
        """
        url = self.request.getURL()
        if '+authoredbranches' in url:
            return "authored by"
        elif '+registeredbranches' in url:
            return "registered but not authored by"
        elif '+subscribedbranches' in url:
            return "subscribed to by"
        else:
            return "related to"

    def in_person_context(self):
        """Whether the context object is a person."""
        return IPerson.providedBy(self.context)

    def in_product_context(self):
        """Whether the context object is a product."""
        return IProduct.providedBy(self.context)

    def categories(self):
        """This organises the branches related to this target by
        "category", where a category corresponds to a particular branch
        status. It also determines the order of those categories, and the
        order of the branches inside each category. This is used for the
        +branches view.

        It is also used in IPerson, which is not an IBranchTarget but
        which does have a IPerson.branches. In this case, it will also
        detect which set of branches you want to see. The options are:

         - all branches (self.branches)
         - authored by this person (self.context.authored_branches)
         - registered by this person (self.context.registered_branches)
         - subscribed by this person (self.context.subscribed_branches)
        """
        categories = {}
        if not IPerson.providedBy(self.context):
            branches = self.branches
        else:
            url = self.request.getURL()
            if '+authoredbranches' in url:
                branches = self.context.authored_branches
            elif '+registeredbranches' in url:
                branches = self.context.registered_branches
            elif '+subscribedbranches' in url:
                branches = self.context.subscribed_branches
            else:
                branches = self.branches
        for branch in branches:
            if categories.has_key(branch.lifecycle_status):
                category = categories[branch.lifecycle_status]
            else:
                category = {}
                category['status'] = branch.lifecycle_status
                category['branches'] = []
                categories[branch.lifecycle_status] = category
            category['branches'].append(branch)
        categories = categories.values()
        return sorted(categories, key=self.category_sortkey)

    @staticmethod
    def category_sortkey(category):
        return category['status'].sortkey

    @cachedproperty
    # A cache to avoid repulling data from the database, which can be
    # particularly expensive
    def branches(self):
        return self.context.branches


class PersonBranchesView(LaunchpadView):
    """View used for the tabular listing of branches related to a person.

    The context must provide IPerson.
    """

    @cachedproperty
    def branches(self):
        """All branches related to this person, sorted for display."""
        branches = self.context.branches
        return sorted(branches, key=self._branch_sort_key)

    @staticmethod
    def _branch_sort_key(branch):
        """Key for the initial sorting of the branches table."""
        if branch.product is None:
            product = None
        else:
            product = branch.product.name
        status = branch.lifecycle_status.sortkey
        return (product, status, branch.name)

    @cachedproperty
    def _authored_branch_set(self):
        """Set of branches authored by the person."""
        # must be cached because it is used by branch_role
        return set(self.context.authored_branches)

    @cachedproperty
    def _registered_branch_set(self):
        """Set of branches registered but not authored by the person."""
        # must be cached because it is used by branch_role
        return set(self.context.registered_branches)

    @cachedproperty
    def _subscribed_branch_set(self):
        """Set of branches this person is subscribed to."""
        # must be cached because it is used by branch_role
        return set(self.context.subscribed_branches)

    def branch_role(self, branch):
        """Primary role of this person for this branch.

        This explains why a branch appears on the person's page. The person may
        be 'Author', 'Registrant' or 'Subscriber'.

        :precondition: the branch must be part of the list provided by
            PersonBranchesView.branches.
        :return: dictionnary of two items: 'title' and 'sortkey' describing the
            role of this person for this branch.
        """
        if branch in self._authored_branch_set:
            return {'title': 'Author', 'sortkey': 10}
        if branch in self._registered_branch_set:
            return {'title': 'Registrant', 'sortkey': 20}
        assert branch in self._subscribed_branch_set, (
            "Unable determine role of person %r for branch %r" % (
            self.context.name, branch.unique_name))
        return {'title': 'Subscriber', 'sortkey': 30}
        
