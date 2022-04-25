# Copyright 2019-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Interfaces for a build record for OCI recipes."""

__all__ = [
    'CannotScheduleRegistryUpload',
    'IOCIFile',
    'IOCIFileSet',
    'IOCIRecipeBuild',
    'IOCIRecipeBuildSet',
    'OCIRecipeBuildRegistryUploadStatus',
    'OCIRecipeBuildSetRegistryUploadStatus',
    ]

import http.client

from lazr.enum import (
    EnumeratedType,
    Item,
    )
from lazr.restful.declarations import (
    error_status,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_entry,
    operation_for_version,
    )
from lazr.restful.fields import (
    CollectionField,
    Reference,
    )
from zope.interface import (
    Attribute,
    Interface,
    )
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Dict,
    Int,
    List,
    TextLine,
    )

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
from lp.oci.interfaces.ocirecipe import (
    IOCIRecipe,
    IOCIRecipeBuildRequest,
    )
from lp.services.database.constants import DEFAULT
from lp.services.fields import PublicPersonChoice
from lp.services.librarian.interfaces import ILibraryFileAlias
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries


@error_status(http.client.BAD_REQUEST)
class CannotScheduleRegistryUpload(Exception):
    """This build cannot be uploaded to registries."""


class OCIRecipeBuildRegistryUploadStatus(EnumeratedType):
    """OCI build registry upload status type

    OCI builds may be uploaded to a registry. This represents the state of
    that process.
    """

    UNSCHEDULED = Item("""
        Unscheduled

        No upload of this OCI build to a registry is scheduled.
        """)

    PENDING = Item("""
        Pending

        This OCI build is queued for upload to a registry.
        """)

    FAILEDTOUPLOAD = Item("""
        Failed to upload

        The last attempt to upload this OCI build to a registry failed.
        """)

    UPLOADED = Item("""
        Uploaded

        This OCI build was successfully uploaded to a registry.
        """)

    SUPERSEDED = Item("""
        Superseded

        The upload has been cancelled because another build will upload a
        more recent version.
    """)


class OCIRecipeBuildSetRegistryUploadStatus(EnumeratedType):
    """OCI build registry upload status type

    OCI builds may be uploaded to a registry. This represents the state of
    that process.
    """

    UNSCHEDULED = Item("""
        Unscheduled

        No upload of these OCI builds to a registry is scheduled.
        """)

    PENDING = Item("""
        Pending

        These OCI builds are queued for upload to a registry.
        """)

    FAILEDTOUPLOAD = Item("""
        Failed to upload

        The last attempt to upload these OCI builds to a registry failed.
        """)

    UPLOADED = Item("""
        Uploaded

        These OCI builds were successfully uploaded to a registry.
        """)

    PARTIAL = Item("""
        Partial

        Some OCI builds have uploaded to a registry.
    """)


class IOCIRecipeBuildView(IPackageBuildView, IPrivacy):
    """`IOCIRecipeBuild` attributes that require launchpad.View permission."""

    build_request = Reference(
        IOCIRecipeBuildRequest,
        title=_("The build request that caused this build to be created."),
        required=False, readonly=True)

    requester = exported(PublicPersonChoice(
        title=_("Requester"),
        description=_("The person who requested this OCI recipe build."),
        vocabulary='ValidPersonOrTeam', required=True, readonly=True))

    recipe = exported(Reference(
        IOCIRecipe,
        title=_("The OCI recipe to build."),
        required=True,
        readonly=True))

    eta = exported(Datetime(
        title=_("The datetime when the build job is estimated to complete."),
        readonly=True))

    estimate = exported(Bool(
        title=_("If true, the date value is an estimate."), readonly=True))

    date = exported(Datetime(
        title=_(
            "The date when the build completed or is estimated to complete."),
        readonly=True))

    def getFiles():
        """Retrieve the build's `IOCIFile` records.

        :return: A result set of (`IOCIFile`, `ILibraryFileAlias`,
            `ILibraryFileContent`).
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The `filename` may be that of the build log, the upload log, or any
        of this build's `OCIFile`s.

        :param filename: The filename to look up.
        :raises NotFoundError: if no file exists with the given name.
        :return: The corresponding `ILibraryFileAlias`.
        """

    @export_read_operation()
    @operation_for_version("devel")
    def getFileUrls():
        """URLs for all the files produced by this build.

        :return: A collection of URLs for this build.
        """

    def getLayerFileByDigest(layer_file_digest):
        """Retrieve a layer file by the digest.

        :param layer_file_digest: The digest to look up.
        :raises NotFoundError: if no file exists with the given digest.
        :return: The corresponding `ILibraryFileAlias`.
        """

    distro_arch_series = exported(Reference(
        IDistroArchSeries,
        title=_("The series and architecture for which to build."),
        required=True, readonly=True))

    score = exported(Int(
        title=_("Score of the related build farm job (if any)."),
        required=False, readonly=True))

    manifest = Attribute(_("The manifest of the image."))

    digests = Attribute(_("File containing the image digests."))

    registry_upload_jobs = CollectionField(
        title=_("Registry upload jobs for this build."),
        # Really IOCIRegistryUploadJob.
        value_type=Reference(schema=Interface),
        readonly=True)

    # Really IOCIRegistryUploadJob
    last_registry_upload_job = Reference(
        title=_("Last registry upload job for this build."), schema=Interface)

    registry_upload_status = exported(Choice(
        title=_("Registry upload status"),
        vocabulary=OCIRecipeBuildRegistryUploadStatus,
        required=True, readonly=False
    ))

    registry_upload_error_summary = exported(TextLine(
        title=_("Registry upload error summary"),
        description=_(
            "The error summary, if any, from the last attempt to upload this "
            "build to a registry."),
        required=False, readonly=True))

    registry_upload_errors = exported(List(
        title=_("Detailed registry upload errors"),
        description=_(
            "A list of errors, as described in "
            "https://docs.docker.com/registry/spec/api/#errors, from the last "
            "attempt to upload this build to a registry."),
        value_type=Dict(key_type=TextLine()),
        required=False, readonly=True))

    def hasMoreRecentBuild():
        """Checks if this recipe has a more recent build currently building or
        already built for the same processor.

        :return: True if another build superseded this one.
        """


class IOCIRecipeBuildEdit(IBuildFarmJobEdit):
    """`IOCIRecipeBuild` attributes that require launchpad.Edit permission."""

    def addFile(lfa, layer_file_digest):
        """Add an OCI file to this build.

        :param lfa: An `ILibraryFileAlias`.
        :param layer_file_digest: Digest for this file, used for image layers.
        :return: An `IOCILayerFile`.
        """

    @export_write_operation()
    @operation_for_version("devel")
    def scheduleRegistryUpload():
        """Schedule an upload of this build to each configured registry.

        :raises CannotScheduleRegistryUpload: if the build is not in a state
            where an upload can be scheduled.
        """


class IOCIRecipeBuildAdmin(IBuildFarmJobAdmin):
    """`IOCIRecipeBuild` attributes that require launchpad.Admin permission."""


@exported_as_webservice_entry(
    publish_web_link=True, as_of="devel", singular_name="oci_recipe_build")
class IOCIRecipeBuild(IOCIRecipeBuildAdmin, IOCIRecipeBuildEdit,
                      IOCIRecipeBuildView, IPackageBuild):
    """A build record for an OCI recipe."""


class IOCIRecipeBuildSet(ISpecificBuildFarmJobSource):
    """A utility to create and access OCIRecipeBuilds."""

    def new(requester, recipe, distro_arch_series,
            date_created=DEFAULT):
        """Create an `IOCIRecipeBuild`."""

    def preloadBuildsData(builds):
        """Load the data related to a list of OCI recipe builds."""


class IOCIFile(Interface):
    """A link between an OCI recipe build and a file in the librarian."""

    build = Reference(
        IOCIRecipeBuild,
        title=_("The OCI recipe build producing this file."),
        required=True, readonly=True)

    library_file = Reference(
        ILibraryFileAlias, title=_("A file in the librarian."),
        required=True, readonly=True)

    layer_file_digest = TextLine(
        title=_("Content-addressable hash of the file''s contents, "
                "used for reassembling image layers when pushing "
                "a build to a registry. This hash is in an opaque format "
                "generated by the OCI build tool."),
        required=False, readonly=True)

    date_last_used = Datetime(
        title=_("The datetime this file was last used in a build."),
        required=True,
        readonly=False)


class IOCIFileSet(Interface):
    """A file artifact of an OCIRecipeBuild."""

    def getByLayerDigest(layer_file_digest):
        """Return an `IOCIFile` with the matching layer_file_digest."""
