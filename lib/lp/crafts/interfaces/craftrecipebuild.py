# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe build interfaces."""

__all__ = [
    "ICraftFile",
    "ICraftRecipeBuild",
    "ICraftRecipeBuildSet",
]

from lazr.restful.declarations import (
    export_read_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
)
from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import Bool, Datetime, Dict, Int, TextLine

from lp import _
from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJobEdit,
    ISpecificBuildFarmJobSource,
)
from lp.buildmaster.interfaces.packagebuild import (
    IPackageBuild,
    IPackageBuildView,
)
from lp.crafts.interfaces.craftrecipe import (
    ICraftRecipe,
    ICraftRecipeBuildRequest,
)
from lp.registry.interfaces.person import IPerson
from lp.services.database.constants import DEFAULT
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries


class ICraftRecipeBuildView(IPackageBuildView):
    """ICraftRecipeBuild attributes that require launchpad.View."""

    build_request = Reference(
        ICraftRecipeBuildRequest,
        title=_("The build request that caused this build to be created."),
        required=True,
        readonly=True,
    )

    requester = exported(
        Reference(
            IPerson,
            title=_("The person who requested this build."),
            required=True,
            readonly=True,
        )
    )

    recipe = exported(
        Reference(
            ICraftRecipe,
            title=_("The craft recipe to build."),
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

    arch_tag = exported(
        TextLine(title=_("Architecture tag"), required=True, readonly=True)
    )

    channels = exported(
        Dict(
            title=_("Source snap channels to use for this build."),
            description=_(
                "A dictionary mapping snap names to channels to use for this "
                "build.  Currently only 'core', 'core18', 'core20', "
                "and 'sourcecraft' keys are supported."
            ),
            key_type=TextLine(),
        )
    )

    virtualized = Bool(
        title=_("If True, this build is virtualized."), readonly=True
    )

    score = exported(
        Int(
            title=_("Score of the related build farm job (if any)."),
            required=False,
            readonly=True,
        )
    )

    eta = Datetime(
        title=_("The datetime when the build job is estimated to complete."),
        readonly=True,
    )

    estimate = Bool(
        title=_("If true, the date value is an estimate."), readonly=True
    )

    date = Datetime(
        title=_(
            "The date when the build completed or is estimated to complete."
        ),
        readonly=True,
    )

    revision_id = exported(
        TextLine(
            title=_("Revision ID"),
            required=False,
            readonly=True,
            description=_(
                "The revision ID of the branch used for this build, if "
                "available."
            ),
        )
    )

    store_upload_metadata = Attribute(
        _("A dict of data about store upload progress.")
    )

    build_metadata_url = exported(
        TextLine(
            title=_("URL of the build metadata file"),
            description=_(
                "URL of the metadata file generated by the fetch service, if "
                "it exists."
            ),
            required=False,
            readonly=True,
        )
    )

    def getFiles():
        """Retrieve the build's ICraftFile records.

        :return: A result set of (ICraftFile, ILibraryFileAlias,
            ILibraryFileContent).
        """

    def getFileByName(filename):
        """Return the corresponding ILibraryFileAlias in this context.

        The following file types (and extension) can be looked up:

         * Build log: '.txt.gz'
         * Upload log: '_log.txt'

        Any filename not matching one of these extensions is looked up as a
        craft recipe output file.

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding ILibraryFileAlias.
        """

    @export_read_operation()
    @operation_for_version("devel")
    def getFileUrls():
        """URLs for all the files produced by this build.

        :return: A collection of URLs for this build."""


class ICraftRecipeBuildEdit(IBuildFarmJobEdit):
    """ICraftRecipeBuild methods that require launchpad.Edit."""

    def addFile(lfa):
        """Add a file to this build.

        :param lfa: An ILibraryFileAlias.
        :return: An ICraftFile.
        """


class ICraftRecipeBuildAdmin(Interface):
    """ICraftRecipeBuild methods that require launchpad.Admin."""

    def rescore(score):
        """Change the build's score."""


# XXX ruinedyourlife 2024-10-02
# beta" is a lie to get WADL generation working,
# see https://bugs.launchpad.net/lazr.restful/+bug/760849
# Individual attributes must set their version to "devel".
@exported_as_webservice_entry(as_of="beta")
class ICraftRecipeBuild(
    ICraftRecipeBuildView,
    ICraftRecipeBuildEdit,
    ICraftRecipeBuildAdmin,
    IPackageBuild,
):
    """A build record for a craft recipe."""


class ICraftRecipeBuildSet(ISpecificBuildFarmJobSource):
    """Utility to create and access ICraftRecipeBuilds."""

    def new(
        build_request,
        recipe,
        distro_arch_series,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
    ):
        """Create an ICraftRecipeBuild."""

    def preloadBuildsData(builds):
        """Load the data related to a list of craft recipe builds."""


class ICraftFile(Interface):
    """A file produced by a craft recipe build."""

    build = Reference(
        ICraftRecipeBuild,
        title=_("The craft recipe build producing this file."),
        required=True,
        readonly=True,
    )

    library_file = Reference(
        ILibraryFileAlias,
        title=_("The library file alias for this file."),
        required=True,
        readonly=True,
    )
