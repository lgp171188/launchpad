# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Package file interfaces."""

__all__ = [
    "IBinaryPackageFile",
    "IPackageReleaseFile",
    "ISourcePackageReleaseFile",
]

from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Bool, Int

from lp import _
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.soyuz.interfaces.binarypackagerelease import IBinaryPackageRelease
from lp.soyuz.interfaces.sourcepackagerelease import ISourcePackageRelease


class IPackageReleaseFile(Interface):
    """A link between a source/binary package release and the librarian."""

    id = Int(title=_("ID"), required=True, readonly=True)

    libraryfileID = Int(
        title=_("The LibraryFileAlias id for this file"),
        required=True,
        readonly=True,
    )

    libraryfile = Reference(
        ILibraryFileAlias,
        title=_("The library file alias for this file"),
        required=True,
        readonly=False,
    )

    filetype = Int(
        title=_("The type of this file"), required=True, readonly=False
    )


class IBinaryPackageFile(IPackageReleaseFile):
    """A binary package to librarian link record."""

    binarypackagerelease = Reference(
        IBinaryPackageRelease,
        title=_("The binary package release being published"),
        required=True,
        readonly=False,
    )

    binarypackagereleaseID = Int(
        title=_("ID of the binary package release being published"),
        required=True,
        readonly=False,
    )


class ISourcePackageReleaseFile(IPackageReleaseFile):
    """A source package release to librarian link record."""

    sourcepackagerelease = Reference(
        ISourcePackageRelease,
        title=_("The source package release being published"),
        required=True,
        readonly=False,
    )

    sourcepackagereleaseID = Int(
        title=_("ID of the source package release being published"),
        required=True,
        readonly=False,
    )

    is_orig = Bool(
        title=_("Whether this file is an original tarball"),
        required=True,
        readonly=False,
    )
