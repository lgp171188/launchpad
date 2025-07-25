# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "ExternalPackageBreadcrumb",
    "ExternalPackageNavigation",
    "ExternalPackageFacets",
]


from zope.interface import implementer

from lp.app.interfaces.headings import IHeadingBreadcrumb
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from lp.bugs.browser.structuralsubscription import (
    StructuralSubscriptionTargetTraversalMixin,
)
from lp.registry.interfaces.externalpackage import IExternalPackage
from lp.services.webapp import Navigation, StandardLaunchpadFacets, redirection
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import IMultiFacetedBreadcrumb


@implementer(IHeadingBreadcrumb, IMultiFacetedBreadcrumb)
class ExternalPackageBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IExternalPackage`."""

    rootsite = "bugs"

    @property
    def text(self):
        return "%s external package" % self.context.sourcepackagename.name


class ExternalPackageFacets(StandardLaunchpadFacets):
    usedfor = IExternalPackage
    enable_only = [
        "bugs",
    ]


class ExternalPackageNavigation(
    Navigation,
    BugTargetTraversalMixin,
    StructuralSubscriptionTargetTraversalMixin,
):
    usedfor = IExternalPackage

    @redirection("+editbugcontact")
    def redirect_editbugcontact(self):
        return "+subscribe"
