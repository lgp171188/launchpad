# Copyright 2009, 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""External package interfaces."""

__all__ = [
    "IExternalURL",
    "IExternalPackage",
    "ExternalPackageType",
]

from lazr.enum import DBEnumeratedType, DBItem
from lazr.restful.declarations import exported, exported_as_webservice_entry
from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import TextLine

from lp import _
from lp.app.interfaces.launchpad import IHeadingContext
from lp.bugs.interfaces.bugtarget import IBugTarget, IHasOfficialBugTags
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.role import IHasDrivers


class IExternalURL(Interface):
    """Uses +external url"""

    def isMatching(other):
        """Returns if it matches the other object.
        +external url lacks necessary data, so we only match the necessary
        attributes.
        """


@exported_as_webservice_entry(as_of="beta")
class IExternalPackageView(
    IHeadingContext,
    IBugTarget,
    IHasOfficialBugTags,
    IHasDrivers,
    IExternalURL,
):
    """`IExternalPackage` attributes that require launchpad.View."""

    packagetype = Attribute("The package type")

    channel = Attribute("The package channel")

    display_channel = TextLine(title=_("Display channel name"), readonly=True)

    distribution = exported(
        Reference(IDistribution, title=_("The distribution."))
    )
    sourcepackagename = Attribute("The source package name.")

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

    drivers = Attribute("The drivers for the distribution.")

    def isMatching(other):
        """See `IExternalURL`."""

    def __eq__(other):
        """IExternalPackage comparison method.

        Distro sourcepackages compare equal only if their fields compare equal.
        """

    def __ne__(other):
        """IExternalPackage comparison method.

        External packages compare not equal if either of their
        fields compare not equal.
        """


@exported_as_webservice_entry(as_of="beta")
class IExternalPackage(
    IExternalPackageView,
):
    """Represents an ExternalPackage in a distribution.

    Create IExternalPackage by invoking `IDistribution.getExternalPackage()`.
    """


class ExternalPackageType(DBEnumeratedType):
    """ExternalPackageType

    The various possible types for an ExternalPackage.
    """

    UNKNOWN = DBItem(
        0,
        """
        Unknown

        Unknown external package
        """,
    )

    SNAP = DBItem(
        1,
        """
        Snap

        Snap external package
        """,
    )

    CHARM = DBItem(
        2,
        """
        Charm

        Charm external package
        """,
    )

    ROCK = DBItem(
        3,
        """
        Rock

        Rock external package
        """,
    )

    PYTHON = DBItem(
        4,
        """
        Python

        Python external package
        """,
    )

    CONDA = DBItem(
        5,
        """
        Conda

        Conda external package
        """,
    )

    CARGO = DBItem(
        6,
        """
        Cargo

        Cargo external package
        """,
    )

    MAVEN = DBItem(
        7,
        """
        Maven

        Maven external package
        """,
    )
