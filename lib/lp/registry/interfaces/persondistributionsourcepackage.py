# Copyright 2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A person's view on a source package in a distribution."""

__all__ = [
    "IPersonDistributionSourcePackage",
    "IPersonDistributionSourcePackageFactory",
]

from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import TextLine

from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.interfaces.person import IPerson


class IPersonDistributionSourcePackage(Interface):
    """A person's view on a source package in a distribution."""

    person = Reference(IPerson)
    distro_source_package = Reference(IDistributionSourcePackage)
    display_name = TextLine()
    displayname = Attribute("Display name (deprecated)")


class IPersonDistributionSourcePackageFactory(Interface):
    """Creates `IPersonDistributionSourcePackage`s."""

    def create(person, distro_source_package):
        """Create and return an `IPersonDistributionSourcePackage`."""
