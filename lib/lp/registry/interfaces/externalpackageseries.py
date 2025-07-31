# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""External Package Series interface."""

__all__ = [
    "IExternalPackageSeries",
]

from lazr.restful.declarations import exported, exported_as_webservice_entry
from lazr.restful.fields import Reference
from zope.interface import Attribute
from zope.schema import TextLine

from lp import _
from lp.app.interfaces.launchpad import IHeadingContext
from lp.bugs.interfaces.bugtarget import IBugTarget, IHasOfficialBugTags
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.externalpackage import IExternalURL
from lp.registry.interfaces.role import IHasDrivers


@exported_as_webservice_entry(as_of="beta")
class IExternalPackageSeriesView(
    IHeadingContext,
    IBugTarget,
    IHasOfficialBugTags,
    IHasDrivers,
    IExternalURL,
):
    """`IExternalPackageSeries` attributes that require launchpad.View."""

    packagetype = Attribute("The package type")

    channel = Attribute("The package channel")

    display_channel = TextLine(title=_("Display channel name"), readonly=True)

    distribution = exported(
        Reference(IDistribution, title=_("The distribution."))
    )
    distroseries = exported(
        Reference(IDistroSeries, title=_("The distroseries."))
    )
    sourcepackagename = Attribute("The source package name.")

    distribution_sourcepackage = Attribute(
        "The IExternalPackage for this external package series."
    )

    name = exported(
        TextLine(title=_("The source package name as text"), readonly=True)
    )
    display_name = exported(
        TextLine(title=_("Display name for this package."), readonly=True)
    )
    displayname = Attribute("Display name (deprecated)")
    title = exported(
        TextLine(title=_("Title for this package."), readonly=True)
    )

    drivers = Attribute("The drivers for the distroseries.")

    def isMatching(other):
        """See `IExternalURL`."""

    def __eq__(other):
        """IExternalPackageSeries comparison method.

        ExternalPackageSeries compare equal only if their fields compare equal.
        """

    def __ne__(other):
        """IExternalPackageSeries comparison method.

        External packages compare not equal if either of their
        fields compare not equal.
        """


@exported_as_webservice_entry(as_of="beta")
class IExternalPackageSeries(
    IExternalPackageSeriesView,
):
    """Represents an ExternalPackage in a distroseries.

    Create IExternalPackageSeries by invoking
    `IDistroSeries.getExternalPackageSeries()`.
    """
