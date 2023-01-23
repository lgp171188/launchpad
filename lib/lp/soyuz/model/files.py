# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "BinaryPackageFile",
    "SourceFileMixin",
    "SourcePackageReleaseFile",
]

from storm.locals import Int, Reference
from zope.interface import implementer

from lp.registry.interfaces.sourcepackage import SourcePackageFileType
from lp.services.database.enumcol import DBEnum
from lp.services.database.stormbase import StormBase
from lp.soyuz.enums import BinaryPackageFileType
from lp.soyuz.interfaces.files import (
    IBinaryPackageFile,
    ISourcePackageReleaseFile,
)


@implementer(IBinaryPackageFile)
class BinaryPackageFile(StormBase):
    """See IBinaryPackageFile"""

    __storm_table__ = "BinaryPackageFile"

    id = Int(primary=True)
    binarypackagerelease_id = Int(
        name="binarypackagerelease", allow_none=False
    )
    binarypackagerelease = Reference(
        binarypackagerelease_id, "BinaryPackageRelease.id"
    )
    libraryfile_id = Int(name="libraryfile", allow_none=False)
    libraryfile = Reference(libraryfile_id, "LibraryFileAlias.id")
    filetype = DBEnum(
        name="filetype", enum=BinaryPackageFileType, allow_none=False
    )

    def __init__(self, binarypackagerelease, libraryfile, filetype):
        super().__init__()
        self.binarypackagerelease = binarypackagerelease
        self.libraryfile = libraryfile
        self.filetype = filetype


class SourceFileMixin:
    """Mix-in class for common functionality between source file classes."""

    @property
    def is_orig(self):
        return self.filetype in (
            SourcePackageFileType.ORIG_TARBALL,
            SourcePackageFileType.COMPONENT_ORIG_TARBALL,
            SourcePackageFileType.ORIG_TARBALL_SIGNATURE,
            SourcePackageFileType.COMPONENT_ORIG_TARBALL_SIGNATURE,
        )


@implementer(ISourcePackageReleaseFile)
class SourcePackageReleaseFile(SourceFileMixin, StormBase):
    """See ISourcePackageFile"""

    __storm_table__ = "SourcePackageReleaseFile"

    id = Int(primary=True)
    sourcepackagerelease_id = Int(
        name="sourcepackagerelease", allow_none=False
    )
    sourcepackagerelease = Reference(
        sourcepackagerelease_id, "SourcePackageRelease.id"
    )
    libraryfile_id = Int(name="libraryfile", allow_none=False)
    libraryfile = Reference(libraryfile_id, "LibraryFileAlias.id")
    filetype = DBEnum(
        name="filetype", enum=SourcePackageFileType, allow_none=False
    )

    def __init__(self, sourcepackagerelease, libraryfile, filetype):
        super().__init__()
        self.sourcepackagerelease = sourcepackagerelease
        self.libraryfile = libraryfile
        self.filetype = filetype
