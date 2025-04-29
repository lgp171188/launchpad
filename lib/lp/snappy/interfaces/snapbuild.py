# Copyright 2015-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap package build interfaces."""

__all__ = [
    "CannotScheduleStoreUpload",
    "ISnapBuild",
    "ISnapBuildSet",
    "ISnapBuildStatusChangedEvent",
    "ISnapFile",
    "SnapBuildStoreUploadStatus",
]

import http.client

from lazr.enum import EnumeratedType, Item
from lazr.restful.declarations import (
    error_status,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
)
from lazr.restful.fields import CollectionField, Reference
from zope.interface import Attribute, Interface
from zope.interface.interfaces import IObjectEvent
from zope.schema import Bool, Choice, Datetime, Dict, Int, List, TextLine

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
from lp.services.fields import SnapBuildChannelsField
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.snappy.interfaces.snap import ISnap, ISnapBuildRequest
from lp.snappy.interfaces.snapbase import ISnapBase
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries


@error_status(http.client.BAD_REQUEST)
class CannotScheduleStoreUpload(Exception):
    """This build cannot be uploaded to the store."""


class ISnapBuildStatusChangedEvent(IObjectEvent):
    """The status of a snap package build changed."""


class ISnapFile(Interface):
    """A file produced by a snap package build."""

    snapbuild = Reference(
        # Really ISnapBuild, patched in _schema_circular_imports.py.
        Interface,
        title=_("The snap package build producing this file."),
        required=True,
        readonly=True,
    )

    libraryfile = Reference(
        ILibraryFileAlias,
        title=_("The library file alias for this file."),
        required=True,
        readonly=True,
    )


class SnapBuildStoreUploadStatus(EnumeratedType):
    """Snap build store upload status type

    Snap builds may be uploaded to the store. This represents the state of
    that process.
    """

    UNSCHEDULED = Item(
        """
        Unscheduled

        No upload of this snap build to the store is scheduled.
        """
    )

    PENDING = Item(
        """
        Pending

        This snap build is queued for upload to the store.
        """
    )

    FAILEDTOUPLOAD = Item(
        """
        Failed to upload

        The last attempt to upload this snap build to the store failed.
        """
    )

    # This is an impossible state for new releases (2019-06-19), due
    # to the store handling releases for us, however historical tasks
    # can have this status, so it is maintained here.
    FAILEDTORELEASE = Item(
        """
        Failed to release to channels

        The last attempt to release this snap build to its intended set of
        channels failed.
        """
    )

    UPLOADED = Item(
        """
        Uploaded

        This snap build was successfully uploaded to the store.
        """
    )


class ISnapBuildView(IPackageBuildView, IPrivacy):
    """`ISnapBuild` attributes that require launchpad.View permission."""

    build_request = Reference(
        ISnapBuildRequest,
        title=_("The build request that caused this build to be created."),
        required=False,
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

    snap = exported(
        Reference(
            ISnap,
            title=_("The snap package to build."),
            required=True,
            readonly=True,
        )
    )

    archive = exported(
        Reference(
            IArchive,
            title=_("The archive from which to build the snap package."),
            required=True,
            readonly=True,
        )
    )

    distro_arch_series = exported(
        Reference(
            IDistroArchSeries,
            title=_("The series and architecture to build on."),
            required=True,
            readonly=True,
        )
    )

    arch_tag = exported(
        TextLine(title=_("Architecture tag"), required=True, readonly=True)
    )

    target_architectures = exported(
        List(
            TextLine(),
            title=_("The target architectures to build for."),
            required=False,
            readonly=True,
        )
    )

    pocket = exported(
        Choice(
            title=_("The pocket for which to build."),
            description=(
                "The package stream within the source archive and "
                "distribution series to use when building the snap package.  "
                "If the source archive is a PPA, then the PPA's archive "
                "dependencies will be used to select the pocket in the "
                "distribution's primary archive."
            ),
            vocabulary=PackagePublishingPocket,
            required=True,
            readonly=True,
        )
    )

    snap_base = exported(
        Reference(
            ISnapBase,
            title=_("The snap base to use for this build."),
            required=False,
            readonly=True,
        )
    )

    channels = exported(
        SnapBuildChannelsField(
            title=_("Source snap channels to use for this build."),
            description_prefix=_(
                "A dictionary mapping snap names to channels to use for this "
                "build."
            ),
            extra_snap_names=["snapcraft", "snapd"],
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
            "The date when the build completed or is estimated to " "complete."
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
        # Really ISnapStoreUploadJob.
        value_type=Reference(schema=Interface),
        readonly=True,
    )

    # Really ISnapStoreUploadJob.
    last_store_upload_job = Reference(
        title=_("Last store upload job for this build."), schema=Interface
    )

    store_upload_status = exported(
        Choice(
            title=_("Store upload status"),
            vocabulary=SnapBuildStoreUploadStatus,
            required=True,
            readonly=False,
        )
    )

    store_upload_url = exported(
        TextLine(
            title=_("Store URL"),
            description=_(
                "The URL to use for managing this package in the store."
            ),
            required=False,
            readonly=True,
        )
    )

    store_upload_revision = exported(
        Int(
            title=_("Store revision"),
            description=_(
                "The revision assigned to this package by the store."
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
                "this snap build to the store.  (Deprecated; use "
                "store_upload_error_messages instead.)"
            ),
            required=False,
            readonly=True,
        )
    )

    store_upload_error_messages = exported(
        List(
            title=_("Store upload error messages"),
            description=_(
                "A list of dict(message, link) where message is an error "
                "description and link, if any, is an external link to extra "
                "details, from the last attempt to upload this snap build "
                "to the store."
            ),
            value_type=Dict(key_type=TextLine()),
            required=False,
            readonly=True,
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

    craft_platform = exported(
        TextLine(
            title=_("Craft platform name"),
            required=False,
            readonly=True,
        )
    )

    def getFiles():
        """Retrieve the build's `ISnapFile` records.

        :return: A result set of (`ISnapFile`, `ILibraryFileAlias`,
            `ILibraryFileContent`).
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up:

         * Build log: '.txt.gz'
         * Upload log: '_log.txt'

        Any filename not matching one of these extensions is looked up as a
        snap package output file.

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding `ILibraryFileAlias`.
        """

    @export_read_operation()
    @operation_for_version("devel")
    def getFileUrls():
        """URLs for all the files produced by this build.

        :return: A collection of URLs for this build."""


class ISnapBuildEdit(IBuildFarmJobEdit):
    """`ISnapBuild` attributes that require launchpad.Edit."""

    def addFile(lfa):
        """Add a file to this build.

        :param lfa: An `ILibraryFileAlias`.
        :return: An `ISnapFile`.
        """

    @export_write_operation()
    @operation_for_version("devel")
    def scheduleStoreUpload():
        """Schedule an upload of this build to the store.

        :raises CannotScheduleStoreUpload: if the build is not in a state
            where an upload can be scheduled.
        """


class ISnapBuildAdmin(IBuildFarmJobAdmin):
    """`ISnapBuild` attributes that require launchpad.Admin."""


# XXX cjwatson 2014-05-06 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class ISnapBuild(
    ISnapBuildView, ISnapBuildEdit, ISnapBuildAdmin, IPackageBuild
):
    """Build information for snap package builds."""


class ISnapBuildSet(ISpecificBuildFarmJobSource):
    """Utility for `ISnapBuild`."""

    def new(
        requester,
        snap,
        archive,
        distro_arch_series,
        pocket,
        snap_base=None,
        channels=None,
        date_created=DEFAULT,
        store_upload_metadata=None,
        build_request=None,
        target_architectures=None,
        craft_platform=None,
    ):
        """Create an `ISnapBuild`."""

    def preloadBuildsData(builds):
        """Load the data related to a list of snap builds."""
