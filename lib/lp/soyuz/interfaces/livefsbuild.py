# Copyright 2014-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Live filesystem build interfaces."""

__all__ = [
    "ILiveFSBuild",
    "ILiveFSBuildSet",
    "ILiveFSFile",
]

from lazr.restful.declarations import (
    export_read_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
)
from lazr.restful.fields import Reference
from zope.interface import Interface
from zope.schema import Bool, Choice, Dict, Int, TextLine

from lp import _
from lp.app.interfaces.launchpad import IPrivacy
from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJobAdmin,
    IBuildFarmJobEdit,
    ISpecificBuildFarmJobSource,
)
from lp.buildmaster.interfaces.packagebuild import (
    IPackageBuild,
    IPackageBuildView,
)
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.database.constants import DEFAULT
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.services.webservice.apihelpers import patch_reference_property
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries
from lp.soyuz.interfaces.livefs import ILiveFS


class ILiveFSFile(Interface):
    """A file produced by a live filesystem build."""

    livefsbuild = Reference(
        # Really ILiveFSBuild, patched below.
        Interface,
        title=_("The live filesystem build producing this file."),
        required=True,
        readonly=True,
    )
    libraryfile = Reference(
        ILibraryFileAlias,
        title=_("The library file alias for this file."),
        required=True,
        readonly=True,
    )


class ILiveFSBuildView(IPackageBuildView, IPrivacy):
    """`ILiveFSBuild` attributes that require launchpad.View permission."""

    requester = exported(
        Reference(
            IPerson,
            title=_("The person who requested this build."),
            required=True,
            readonly=True,
        )
    )

    livefs = exported(
        Reference(
            ILiveFS,
            title=_("The live filesystem to build."),
            required=True,
            readonly=True,
        )
    )

    archive = exported(
        Reference(
            IArchive,
            title=_("The archive from which to build the live filesystem."),
            required=True,
            readonly=True,
        )
    )

    distro_arch_series = exported(
        Reference(
            IDistroArchSeries,
            title=_("The series and architecture for which to build."),
            required=True,
            readonly=True,
        )
    )

    pocket = exported(
        Choice(
            title=_("The pocket for which to build."),
            vocabulary=PackagePublishingPocket,
            required=True,
            readonly=True,
        )
    )

    unique_key = exported(
        TextLine(
            title=_(
                "An optional unique key; if set, this identifies a class of "
                "builds for this live filesystem."
            ),
            required=False,
            readonly=True,
        )
    )

    metadata_override = exported(
        Dict(
            title=_(
                "A dict of data about the image; this will be merged into the "
                "metadata dict for the live filesystem."
            ),
            key_type=TextLine(),
            required=False,
            readonly=True,
        )
    )

    virtualized = Bool(
        title=_("If True, this build is virtualized."), readonly=True
    )

    version = exported(
        TextLine(
            title=_("A version string for this build."),
            required=True,
            readonly=True,
        )
    )

    score = exported(
        Int(
            title=_("Score of the related build farm job (if any)."),
            required=False,
            readonly=True,
        )
    )

    def getFiles():
        """Retrieve the build's `ILiveFSFile` records.

        :return: A result set of (`ILiveFSFile`, `ILibraryFileAlias`,
            `ILibraryFileContent`).
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up:

         * Build log: '.txt.gz'
         * Upload log: '_log.txt'

        Any filename not matching one of these extensions is looked up as a
        live filesystem output file.

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding `ILibraryFileAlias`.
        """

    @export_read_operation()
    @operation_for_version("devel")
    def getFileUrls():
        """URLs for all the files produced by this build.

        :return: A collection of URLs for this build."""


class ILiveFSBuildEdit(IBuildFarmJobEdit):
    """`ILiveFSBuild` attributes that require launchpad.Edit."""

    def addFile(lfa):
        """Add a file to this build.

        :param lfa: An `ILibraryFileAlias`.
        :return: An `ILiveFSFile`.
        """


class ILiveFSBuildAdmin(IBuildFarmJobAdmin):
    """`ILiveFSBuild` attributes that require launchpad.Admin."""


# XXX cjwatson 2014-05-06 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(singular_name="livefs_build", as_of="beta")
class ILiveFSBuild(
    ILiveFSBuildView, ILiveFSBuildEdit, ILiveFSBuildAdmin, IPackageBuild
):
    """Build information for live filesystem builds."""


class ILiveFSBuildSet(ISpecificBuildFarmJobSource):
    """Utility for `ILiveFSBuild`."""

    def new(
        requester,
        livefs,
        archive,
        distro_arch_series,
        pocket,
        unique_key=None,
        metadata_override=None,
        version=None,
        date_created=DEFAULT,
    ):
        """Create an `ILiveFSBuild`."""


patch_reference_property(ILiveFSFile, "livefsbuild", ILiveFSBuild)
