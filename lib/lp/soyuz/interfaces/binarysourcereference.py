# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interface for references from binary packages to source packages."""

__metaclass__ = type
__all__ = [
    'IBinarySourceReference',
    'IBinarySourceReferenceSet',
    'UnparsableBuiltUsing',
    ]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import (
    Choice,
    Int,
    )

from lp import _
from lp.soyuz.enums import BinarySourceReferenceType
from lp.soyuz.interfaces.binarypackagerelease import IBinaryPackageRelease
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease


class UnparsableBuiltUsing(Exception):
    """A Built-Using field could not be parsed."""


class IBinarySourceReference(Interface):
    """A reference from a binary package to a source package."""

    id = Int(title=_("ID"))

    binary_package_release = Reference(
        IBinaryPackageRelease,
        title=_("The referencing binary package release."),
        required=True, readonly=True)
    source_package_release = Reference(
        ISourcePackageRelease,
        title=_("The referenced source package release."),
        required=True, readonly=True)
    reference_type = Choice(
        title=_("The type of the reference."),
        vocabulary=BinarySourceReferenceType,
        required=True, readonly=True)


class IBinarySourceReferenceSet(Interface):
    """A set of references from binary packages to source packages."""

    def createFromRelationship(bpr, relationship, reference_type):
        """Create references from a text relationship field.

        :param bpr: The `IBinaryPackageRelease` from which new references
            should be created.
        :param relationship: A text relationship field containing one or
            more source package relations in the usual Debian encoding (e.g.
            "source1 (= 1.0), source2 (= 2.0)").
        :param reference_type: The `BinarySourceReferenceType` of references
            to create.
        :return: A list of new `IBinarySourceReference`s.
        """

    def createFromSourcePackageReleases(bpr, sprs, reference_type):
        """Create references from a sequence of source package releases.

        This is a convenience method for use in tests.

        :param bpr: The `IBinaryPackageRelease` from which new references
            should be created.
        :param sprs: A sequence of `ISourcePackageRelease`s.
        :param reference_type: The `BinarySourceReferenceType` of references
            to create.
        :return: A list of new `IBinarySourceReference`s.
        """

    def findByBinaryPackageRelease(bpr, reference_type):
        """Find references from a given binary package release.

        :param bpr: An `IBinaryPackageRelease` to search for.
        :param reference_type: A `BinarySourceReferenceType` to search for.
        :return: A `ResultSet` of matching `IBinarySourceReference`s.
        """
