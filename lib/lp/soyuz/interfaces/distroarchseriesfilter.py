# Copyright 2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Distro arch series filter interfaces."""

__all__ = [
    "IDistroArchSeriesFilter",
    "IDistroArchSeriesFilterSet",
    "NoSuchDistroArchSeriesFilter",
]

from lazr.restful.declarations import exported, exported_as_webservice_entry
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Choice, Datetime, Int

from lp import _
from lp.app.errors import NameLookupFailed
from lp.services.fields import PublicPersonChoice
from lp.soyuz.enums import DistroArchSeriesFilterSense
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries
from lp.soyuz.interfaces.packageset import IPackageset


class NoSuchDistroArchSeriesFilter(NameLookupFailed):
    """Raised when we try to look up a nonexistent DistroArchSeriesFilter."""

    _message_prefix = (
        "The given distro arch series has no DistroArchSeriesFilter"
    )


class IDistroArchSeriesFilterView(Interface):
    """`IDistroArchSeriesFilter` attributes that require launchpad.View."""

    id = Int(title=_("ID"), readonly=True, required=True)

    distroarchseries = exported(
        Reference(
            title=_("Distro arch series"),
            required=True,
            readonly=True,
            schema=IDistroArchSeries,
            description=_("The distro arch series that this filter is for."),
        )
    )

    packageset = exported(
        Reference(
            title=_("Package set"),
            required=True,
            readonly=True,
            schema=IPackageset,
            description=_(
                "The package set to be included in or excluded from this "
                "distro arch series."
            ),
        )
    )

    sense = exported(
        Choice(
            title=_("Sense"),
            vocabulary=DistroArchSeriesFilterSense,
            required=True,
            readonly=True,
            description=_(
                "Whether the filter represents packages to include or exclude "
                "from the distro arch series."
            ),
        )
    )

    creator = exported(
        PublicPersonChoice(
            title=_("Creator"),
            required=True,
            readonly=True,
            vocabulary="ValidPerson",
            description=_("The user who created this filter."),
        )
    )

    date_created = exported(
        Datetime(
            title=_("Date created"),
            required=True,
            readonly=True,
            description=_("The time when this filter was created."),
        )
    )

    date_last_modified = exported(
        Datetime(
            title=_("Date last modified"),
            required=True,
            readonly=True,
            description=_("The time when this filter was last modified."),
        )
    )

    def isSourceIncluded(sourcepackagename):
        """Is this source package name included by this filter?

        If the sense of the filter is INCLUDE, then this returns True iff
        the source package name is included in the related package set;
        otherwise, it returns True iff the source package name is not
        included in the related package set.

        :param sourcepackagename: an `ISourcePackageName`.
        :return: True if the source is included by this filter, otherwise
            False.
        """


class IDistroArchSeriesFilterEdit(Interface):
    """`IDistroArchSeriesFilter` attributes that require launchpad.Edit."""

    def destroySelf():
        """Delete this filter."""


# XXX cjwatson 2019-10-04 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class IDistroArchSeriesFilter(
    IDistroArchSeriesFilterView, IDistroArchSeriesFilterEdit
):
    """A filter for packages to be included in or excluded from a DAS.

    Since package sets can include other package sets, a single package set
    is flexible enough for this.  However, one might reasonably want to
    either include some packages ("this architecture is obsolescent or
    experimental and we only want to build a few packages for it") or
    exclude some packages ("this architecture can't handle some packages so
    we want to make them go away centrally").
    """


class IDistroArchSeriesFilterSet(Interface):
    """An interface for multiple distro arch series filters."""

    def new(distroarchseries, packageset, sense, creator, date_created=None):
        """Create an `IDistroArchSeriesFilter`."""

    def getByDistroArchSeries(distroarchseries):
        """Return the filter for this distro arch series, if any.

        :param distroarchseries: The `IDistroArchSeries` to search for.
        :return: An `IDistroArchSeriesFilter` instance.
        :raises NoSuchDistroArchSeriesFilter: if no filter is found.
        """

    def findByPackageset(packageset):
        """Return any filters using this package set.

        :param packageset: The `IPackageset` to search for.
        :return: A `ResultSet` of `IDistroArchSeriesFilter` instances.
        """
