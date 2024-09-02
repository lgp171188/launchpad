# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views, menus and traversal related to PersonProducts."""

__all__ = [
    "PersonProductBreadcrumb",
    "PersonProductFacets",
    "PersonProductNavigation",
]

from zope.component import getUtility, queryAdapter
from zope.interface import implementer
from zope.traversing.interfaces import IPathAdapter

from lp.app.errors import NotFoundError
from lp.charms.interfaces.charmrecipe import ICharmRecipeSet
from lp.code.browser.vcslisting import PersonTargetDefaultVCSNavigationMixin
from lp.code.interfaces.branchnamespace import get_branch_namespace
from lp.registry.interfaces.personociproject import IPersonOCIProjectFactory
from lp.registry.interfaces.personproduct import IPersonProduct
from lp.rocks.interfaces.rockrecipe import IRockRecipeSet
from lp.services.webapp import (
    Navigation,
    StandardLaunchpadFacets,
    canonical_url,
    stepthrough,
)
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import IMultiFacetedBreadcrumb
from lp.snappy.interfaces.snap import ISnapSet


class PersonProductNavigation(
    PersonTargetDefaultVCSNavigationMixin, Navigation
):
    """Navigation to branches for this person/product."""

    usedfor = IPersonProduct

    @stepthrough("+oci")
    def traverse_oci(self, name):
        oci_project = self.context.product.getOCIProject(name)
        return getUtility(IPersonOCIProjectFactory).create(
            self.context.person, oci_project
        )

    def traverse(self, branch_name):
        """Look for a branch in the person/product namespace."""
        namespace = get_branch_namespace(
            person=self.context.person, product=self.context.product
        )
        branch = namespace.getByName(branch_name)
        if branch is None:
            raise NotFoundError
        else:
            return branch

    @stepthrough("+snap")
    def traverse_snap(self, name):
        return getUtility(ISnapSet).getByPillarAndName(
            owner=self.context.person, pillar=self.context.product, name=name
        )

    @stepthrough("+charm")
    def traverse_charm(self, name):
        return getUtility(ICharmRecipeSet).getByName(
            owner=self.context.person, project=self.context.product, name=name
        )

    @stepthrough("+rock")
    def traverse_rock(self, name):
        return getUtility(IRockRecipeSet).getByName(
            owner=self.context.person, project=self.context.product, name=name
        )


@implementer(IMultiFacetedBreadcrumb)
class PersonProductBreadcrumb(Breadcrumb):
    """Breadcrumb for an `IPersonProduct`."""

    @property
    def text(self):
        return self.context.product.displayname

    @property
    def url(self):
        if self._url is None:
            return canonical_url(self.context.product, rootsite=self.rootsite)
        else:
            return self._url

    @property
    def icon(self):
        return queryAdapter(
            self.context.product, IPathAdapter, name="image"
        ).icon()


class PersonProductFacets(StandardLaunchpadFacets):
    """The links that will appear in the facet menu for an IPerson."""

    usedfor = IPersonProduct
    enable_only = ["branches"]
