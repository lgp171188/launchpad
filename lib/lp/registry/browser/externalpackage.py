# Copyright 2009-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "ExternalPackageBreadcrumb",
    "ExternalPackageNavigation",
    "ExternalPackageURL",
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
from lp.services.webapp.interfaces import (
    ICanonicalUrlData,
    IMultiFacetedBreadcrumb,
)
from lp.services.webapp.menu import Link


@implementer(ICanonicalUrlData)
class ExternalPackageURL:
    """External package URL creation rules."""

    rootsite = None

    def __init__(self, context):
        self.context = context

    @property
    def inside(self):
        return self.context.distribution

    @property
    def path(self):
        return "+external/%s" % self.context.name


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


class ExternalPackageLinksMixin:
    def new_bugs(self):
        base_path = "+bugs"
        get_data = "?field.status:list=NEW"
        return Link(base_path + get_data, "New bugs", site="bugs")


class ExternalPackageNavigation(
    Navigation,
    BugTargetTraversalMixin,
    StructuralSubscriptionTargetTraversalMixin,
):
    usedfor = IExternalPackage

    @redirection("+editbugcontact")
    def redirect_editbugcontact(self):
        return "+subscribe"
