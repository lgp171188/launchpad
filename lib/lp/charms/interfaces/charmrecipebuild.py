# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe build interfaces."""

__all__ = [
    "CannotScheduleStoreUpload",
    "CharmRecipeBuildStoreUploadStatus",
    "ICharmFile",
    "ICharmRecipeBuild",
    "ICharmRecipeBuildSet",
]

import http.client

from lazr.enum import EnumeratedType, Item
from lazr.restful.declarations import (
    error_status,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
)
from lazr.restful.fields import CollectionField, Reference
from zope.interface import Attribute, Interface
from zope.schema import Bool, Choice, Datetime, Int, TextLine

from lp import _
from lp.buildmaster.interfaces.buildfarmjob import (
    IBuildFarmJobAdmin,
    IBuildFarmJobEdit,
    ISpecificBuildFarmJobSource,
)
from lp.buildmaster.interfaces.packagebuild import (
    IPackageBuild,
    IPackageBuildView,
)
from lp.charms.interfaces.charmrecipe import (
    ICharmRecipe,
    ICharmRecipeBuildRequest,
)
from lp.registry.interfaces.person import IPerson
from lp.services.database.constants import DEFAULT
from lp.services.fields import SnapBuildChannelsField
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries


@error_status(http.client.BAD_REQUEST)
class CannotScheduleStoreUpload(Exception):
    """This build cannot be uploaded to the store."""


class CharmRecipeBuildStoreUploadStatus(EnumeratedType):
    """Charm recipe build store upload status type

    Charm recipe builds may be uploaded to Charmhub. This represents the
    state of that process.
    """

    UNSCHEDULED = Item(
        """
        Unscheduled

        No upload of this charm recipe build to Charmhub is scheduled.
        """
    )

    PENDING = Item(
        """
        Pending

        This charm recipe build is queued for upload to Charmhub.
        """
    )

    FAILEDTOUPLOAD = Item(
        """
        Failed to upload

        The last attempt to upload this charm recipe build to Charmhub
        failed.
        """
    )

    FAILEDTORELEASE = Item(
        """
        Failed to release to channels

        The last attempt to release this charm recipe build to its intended
        set of channels failed.
        """
    )

    UPLOADED = Item(
        """
        Uploaded

        This charm recipe build was successfully uploaded to Charmhub.
        """
    )


class ICharmRecipeBuildView(IPackageBuildView):
    """`ICharmRecipeBuild` attributes that require launchpad.View."""

    build_request = Reference(
        ICharmRecipeBuildRequest,
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
            ICharmRecipe,
            title=_("The charm recipe to build."),
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
        SnapBuildChannelsField(
            title=_("Source snap channels to use for this build."),
            description_prefix=_(
                "A dictionary mapping snap names to channels to use for this "
                "build."
            ),
            extra_snap_names=["charmcraft"],
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

    store_upload_jobs = CollectionField(
        title=_("Store upload jobs for this build."),
        # Really ICharmhubUploadJob.
        value_type=Reference(schema=Interface),
        readonly=True,
    )

    # Really ICharmhubUploadJob.
    last_store_upload_job = Reference(
        title=_("Last store upload job for this build."), schema=Interface
    )

    store_upload_status = exported(
        Choice(
            title=_("Store upload status"),
            vocabulary=CharmRecipeBuildStoreUploadStatus,
            required=True,
            readonly=False,
        )
    )

    store_upload_revision = exported(
        Int(
            title=_("Store revision"),
            description=_(
                "The revision assigned to this charm recipe build by Charmhub."
            ),
            required=False,
            readonly=True,
        )
    )

    store_upload_error_message = exported(
        TextLine(
            title=_("Store upload error message"),
            description=_(
                "The error message, if any, from the last attempt to upload "
                "this charm recipe build to Charmhub."
            ),
            required=False,
            readonly=True,
        )
    )

    store_upload_metadata = Attribute(
        _("A dict of data about store upload progress.")
    )

    def getFiles():
        """Retrieve the build's `ICharmFile` records.

        :return: A result set of (`ICharmFile`, `ILibraryFileAlias`,
            `ILibraryFileContent`).
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up:

         * Build log: '.txt.gz'
         * Upload log: '_log.txt'

        Any filename not matching one of these extensions is looked up as a
        charm recipe output file.

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding `ILibraryFileAlias`.
        """


class ICharmRecipeBuildEdit(IBuildFarmJobEdit):
    """`ICharmRecipeBuild` methods that require launchpad.Edit."""

    def addFile(lfa):
        """Add a file to this build.

        :param lfa: An `ILibraryFileAlias`.
        :return: An `ICharmFile`.
        """

    @export_write_operation()
    @operation_for_version("devel")
    def scheduleStoreUpload():
        """Schedule an upload of this build to the store.

        :raises CannotScheduleStoreUpload: if the build is not in a state
            where an upload can be scheduled.
        """


class ICharmRecipeBuildAdmin(IBuildFarmJobAdmin):
    """`ICharmRecipeBuild` methods that require launchpad.Admin."""


# XXX cjwatson 2021-09-15 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class ICharmRecipeBuild(
    ICharmRecipeBuildView,
    ICharmRecipeBuildEdit,
    ICharmRecipeBuildAdmin,
    IPackageBuild,
):
    """A build record for a charm recipe."""


class ICharmRecipeBuildSet(ISpecificBuildFarmJobSource):
    """Utility to create and access `ICharmRecipeBuild`s."""

    def new(
        build_request,
        recipe,
        distro_arch_series,
        channels=None,
        store_upload_metadata=None,
        date_created=DEFAULT,
    ):
        """Create an `ICharmRecipeBuild`."""

    def preloadBuildsData(builds):
        """Load the data related to a list of charm recipe builds."""


class ICharmFile(Interface):
    """A file produced by a charm recipe build."""

    build = Reference(
        ICharmRecipeBuild,
        title=_("The charm recipe build producing this file."),
        required=True,
        readonly=True,
    )

    library_file = Reference(
        ILibraryFileAlias,
        title=_("the library file alias for this file."),
        required=True,
        readonly=True,
    )
