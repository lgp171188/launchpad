# Copyright 2009-2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "ExternalPackageSeriesBreadcrumb",
    "ExternalPackageSeriesNavigation",
    "ExternalPackageSeriesFacets",
]


from zope.interface import implementer

from lp.app.interfaces.headings import IHeadingBreadcrumb
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from lp.bugs.browser.structuralsubscription import (
    StructuralSubscriptionTargetTraversalMixin,
)
from lp.registry.interfaces.externalpackageseries import IExternalPackageSeries
from lp.services.webapp import (
    Navigation,
    StandardLaunchpadFacets,
    canonical_url,
    redirection,
    stepto,
)
from lp.services.webapp.breadcrumb import Breadcrumb
from lp.services.webapp.interfaces import IMultiFacetedBreadcrumb


@implementer(IHeadingBreadcrumb, IMultiFacetedBreadcrumb)
class ExternalPackageSeriesBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `IExternalPackageSeries`."""

    rootsite = "bugs"

    @property
    def text(self):
        return "%s external package in %s" % (
            self.context.sourcepackagename.name,
            self.context.distroseries.named_version,
        )


class ExternalPackageSeriesFacets(StandardLaunchpadFacets):
    usedfor = IExternalPackageSeries
    enable_only = [
        "bugs",
    ]


class ExternalPackageSeriesNavigation(
    Navigation,
    BugTargetTraversalMixin,
    StructuralSubscriptionTargetTraversalMixin,
):
    usedfor = IExternalPackageSeries

    @redirection("+editbugcontact")
    def redirect_editbugcontact(self):
        return "+subscribe"

    @stepto("+filebug")
    def filebug(self):
        """Redirect to the IExternalPackage +filebug page."""
        external_package = self.context.distribution_sourcepackage

        redirection_url = canonical_url(external_package, view_name="+filebug")
        if self.request.form.get("no-redirect") is not None:
            redirection_url += "?no-redirect"
        return self.redirectSubTree(redirection_url, status=303)
