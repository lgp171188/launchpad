# Copyright 2015-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap package interfaces."""

__all__ = [
    "BadMacaroon",
    "BadSnapSearchContext",
    "BadSnapSource",
    "CannotAuthorizeStoreUploads",
    "CannotFetchSnapcraftYaml",
    "CannotModifySnapProcessor",
    "CannotParseSnapcraftYaml",
    "CannotRequestAutoBuilds",
    "DuplicateSnapName",
    "ISnap",
    "ISnapBuildRequest",
    "ISnapEdit",
    "ISnapDelete",
    "ISnapSet",
    "ISnapView",
    "MissingSnapcraftYaml",
    "NoSourceForSnap",
    "NoSuchSnap",
    "SNAP_SNAPCRAFT_CHANNEL_FEATURE_FLAG",
    "SNAP_USE_FETCH_SERVICE_FEATURE_FLAG",
    "SnapAuthorizationBadGeneratedMacaroon",
    "SnapBuildAlreadyPending",
    "SnapBuildArchiveOwnerMismatch",
    "SnapBuildDisallowedArchitecture",
    "SnapBuildRequestStatus",
    "SnapNotOwner",
    "SnapPrivacyMismatch",
    "SnapPrivacyPillarError",
]

import http.client

from lazr.enum import EnumeratedType, Item
from lazr.lifecycle.snapshot import doNotSnapshot
from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    collection_default_content,
    error_status,
    export_destructor_operation,
    export_factory_operation,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_collection,
    exported_as_webservice_entry,
    operation_for_version,
    operation_parameters,
    operation_returns_collection_of,
    operation_returns_entry,
)
from lazr.restful.fields import CollectionField, Reference, ReferenceChoice
from lazr.restful.interface import copy_field
from zope.interface import Attribute, Interface
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Dict,
    Int,
    List,
    Set,
    Text,
    TextLine,
)
from zope.security.interfaces import Forbidden, Unauthorized

from lp import _
from lp.app.enums import InformationType
from lp.app.errors import NameLookupFailed
from lp.app.interfaces.informationtype import IInformationType
from lp.app.validators.name import name_validator
from lp.buildmaster.builderproxy import FetchServicePolicy
from lp.buildmaster.interfaces.processor import IProcessor
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.gitref import IGitRef
from lp.code.interfaces.gitrepository import IGitRepository
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.role import IHasOwner
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    SnapBuildChannelsField,
    URIField,
)
from lp.services.webhooks.interfaces import IWebhookTarget
from lp.snappy.interfaces.snapbase import ISnapBase
from lp.snappy.interfaces.snappyseries import (
    ISnappyDistroSeries,
    ISnappySeries,
)
from lp.snappy.validators.channels import channels_validator
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries

SNAP_SNAPCRAFT_CHANNEL_FEATURE_FLAG = "snap.channels.snapcraft"
SNAP_USE_FETCH_SERVICE_FEATURE_FLAG = "snap.fetch_service.enable"


@error_status(http.client.BAD_REQUEST)
class SnapBuildAlreadyPending(Exception):
    """A build was requested when an identical build was already pending."""

    def __init__(self):
        super().__init__(
            "An identical build of this snap package is already pending."
        )


@error_status(http.client.FORBIDDEN)
class SnapBuildArchiveOwnerMismatch(Forbidden):
    """Builds against private archives require that owners match.

    The snap package owner must have write permission on the archive, so
    that a malicious snap package build can't steal any secrets that its
    owner didn't already have access to.  Furthermore, we want to make sure
    that future changes to the team owning the snap package don't grant it
    retrospective access to information about a private archive.  For now,
    the simplest way to do this is to require that the owners match exactly.
    """

    def __init__(self):
        super().__init__(
            "Snap package builds against private archives are only allowed "
            "if the snap package owner and the archive owner are equal."
        )


@error_status(http.client.BAD_REQUEST)
class SnapBuildDisallowedArchitecture(Exception):
    """A build was requested for a disallowed architecture."""

    def __init__(self, das, pocket):
        super().__init__(
            "This snap package is not allowed to build for %s/%s."
            % (das.distroseries.getSuite(pocket), das.architecturetag)
        )


@error_status(http.client.BAD_REQUEST)
class DuplicateSnapName(Exception):
    """Raised for snap packages with duplicate name/owner."""

    def __init__(self):
        super().__init__(
            "There is already a snap package with the same name and owner."
        )


@error_status(http.client.UNAUTHORIZED)
class SnapNotOwner(Unauthorized):
    """The registrant/requester is not the owner or a member of its team."""


class NoSuchSnap(NameLookupFailed):
    """The requested snap package does not exist."""

    _message_prefix = "No such snap package with this owner"


@error_status(http.client.BAD_REQUEST)
class NoSourceForSnap(Exception):
    """Snap packages must have a source (Bazaar or Git branch)."""

    def __init__(self):
        super().__init__(
            "New snap packages must have either a Bazaar branch or a Git "
            "branch."
        )


@error_status(http.client.BAD_REQUEST)
class BadSnapSource(Exception):
    """The elements of the source for a snap package are inconsistent."""


@error_status(http.client.BAD_REQUEST)
class SnapPrivacyMismatch(Exception):
    """Snap package privacy does not match its content."""

    def __init__(self, message=None):
        super().__init__(
            message
            or "Snap recipe contains private information and cannot be public."
        )


@error_status(http.client.BAD_REQUEST)
class SnapPrivacyPillarError(Exception):
    """Private Snaps should be based in a pillar."""

    def __init__(self, message=None):
        super().__init__(
            message or "Private Snap recipes should have a pillar."
        )


class BadSnapSearchContext(Exception):
    """The context is not valid for a snap package search."""


@error_status(http.client.FORBIDDEN)
class CannotModifySnapProcessor(Exception):
    """Tried to enable or disable a restricted processor on an snap package."""

    _fmt = (
        "%(processor)s is restricted, and may only be enabled or disabled "
        "by administrators."
    )

    def __init__(self, processor):
        super().__init__(self._fmt % {"processor": processor.name})


@error_status(http.client.BAD_REQUEST)
class CannotAuthorizeStoreUploads(Exception):
    """Cannot authorize uploads of a snap package to the store."""


@error_status(http.client.INTERNAL_SERVER_ERROR)
class SnapAuthorizationBadGeneratedMacaroon(Exception):
    """The macaroon generated to authorize store uploads is unusable."""


@error_status(http.client.BAD_REQUEST)
class BadMacaroon(Exception):
    """A macaroon supplied by the user is invalid."""


@error_status(http.client.BAD_REQUEST)
class CannotRequestAutoBuilds(Exception):
    """Snap package is not configured for automatic builds."""

    def __init__(self, field):
        super().__init__(
            "This snap package cannot have automatic builds created for it "
            "because %s is not set." % field
        )


class MissingSnapcraftYaml(Exception):
    """The repository for this snap package does not have a snapcraft.yaml."""

    def __init__(self, branch_name):
        super().__init__("Cannot find snapcraft.yaml in %s" % branch_name)


class CannotFetchSnapcraftYaml(Exception):
    """Launchpad cannot fetch this snap package's snapcraft.yaml."""

    def __init__(self, message, unsupported_remote=False):
        super().__init__(message)
        self.unsupported_remote = unsupported_remote


class CannotParseSnapcraftYaml(Exception):
    """Launchpad cannot parse this snap package's snapcraft.yaml."""


class SnapBuildRequestStatus(EnumeratedType):
    """The status of a request to build a snap package."""

    PENDING = Item(
        """
        Pending

        This snap build request is pending.
        """
    )

    FAILED = Item(
        """
        Failed

        This snap build request failed.
        """
    )

    COMPLETED = Item(
        """
        Completed

        This snap build request completed successfully.
        """
    )


# XXX cjwatson 2018-06-14 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class ISnapBuildRequest(Interface):
    """A request to build a snap package."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_requested = exported(
        Datetime(
            title=_("The time when this request was made"),
            required=True,
            readonly=True,
        )
    )

    date_finished = exported(
        Datetime(
            title=_("The time when this request finished"),
            required=False,
            readonly=True,
        )
    )

    snap = exported(
        Reference(
            # Really ISnap, patched in lp.snappy.interfaces.webservice.
            Interface,
            title=_("Snap package"),
            required=True,
            readonly=True,
        )
    )

    status = exported(
        Choice(
            title=_("Status"),
            vocabulary=SnapBuildRequestStatus,
            required=True,
            readonly=True,
        )
    )

    error_message = exported(
        TextLine(title=_("Error message"), required=True, readonly=True)
    )

    builds = exported(
        CollectionField(
            title=_("Builds produced by this request"),
            # Really ISnapBuild, patched in lp.snappy.interfaces.webservice.
            value_type=Reference(schema=Interface),
            required=True,
            readonly=True,
        )
    )

    requester = Reference(
        title=_("The person requesting the builds."),
        schema=IPerson,
        required=True,
        readonly=True,
    )

    archive = Reference(
        IArchive,
        title="The source archive for builds produced by this request",
        required=True,
        readonly=True,
    )

    pocket = Choice(
        title=_("The source pocket for builds produced by this request."),
        vocabulary=PackagePublishingPocket,
        required=True,
        readonly=True,
    )

    channels = Dict(
        title=_("Source snap channels for builds produced by this request"),
        key_type=TextLine(),
        required=False,
        readonly=True,
    )

    architectures = Set(
        title=_("If set, this request is limited to these architecture tags"),
        value_type=TextLine(),
        required=False,
        readonly=True,
    )


class ISnapView(Interface):
    """`ISnap` attributes that require launchpad.View permission."""

    id = Int(title=_("ID"), required=True, readonly=True)

    date_created = exported(
        Datetime(title=_("Date created"), required=True, readonly=True)
    )

    registrant = exported(
        PublicPersonChoice(
            title=_("Registrant"),
            required=True,
            readonly=True,
            vocabulary="ValidPersonOrTeam",
            description=_("The person who registered this snap package."),
        )
    )

    source = Attribute(
        "The source branch for this snap package (VCS-agnostic)."
    )

    available_processors = Attribute(
        "The architectures that are available to be enabled or disabled for "
        "this snap package."
    )

    @call_with(check_permissions=True, user=REQUEST_USER)
    @operation_parameters(
        processors=List(value_type=Reference(schema=IProcessor), required=True)
    )
    @export_write_operation()
    @operation_for_version("devel")
    def setProcessors(processors, check_permissions=False, user=None):
        """Set the architectures for which the snap package should be built."""

    def getAllowedArchitectures():
        """Return all distroarchseries that this package can build for.

        :return: Sequence of `IDistroArchSeries` instances.
        """

    can_upload_to_store = exported(
        Bool(
            title=_("Can upload to store"),
            required=True,
            readonly=True,
            description=_(
                "Whether everything is set up to allow uploading builds of "
                "this snap package to the store."
            ),
        )
    )

    @call_with(requester=REQUEST_USER)
    @operation_parameters(
        archive=Reference(schema=IArchive),
        distro_arch_series=Reference(schema=IDistroArchSeries),
        pocket=Choice(vocabulary=PackagePublishingPocket),
        snap_base=Reference(schema=ISnapBase),
        channels=SnapBuildChannelsField(
            title=_("Source snap channels to use for this build."),
            description_prefix=_(
                "A dictionary mapping snap names to channels to use for this "
                "build."
            ),
            required=False,
            extra_snap_names=["snapcraft", "snapd"],
        ),
    )
    # Really ISnapBuild, patched in lp.snappy.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("devel")
    def requestBuild(
        requester,
        archive,
        distro_arch_series,
        pocket,
        snap_base=None,
        channels=None,
        build_request=None,
        target_architectures=None,
        craft_platfrom=None,
    ):
        """Request that the snap package be built.

        :param requester: The person requesting the build.
        :param archive: The IArchive to associate the build with.
        :param distro_arch_series: The architecture to build for.
        :param pocket: The pocket that should be targeted.
        :param snap_base: The `ISnapBase` to use for this build.
        :param channels: A dictionary mapping snap names to channels to use
            for this build.
        :param build_request: The `ISnapBuildRequest` job being processed,
            if any.
        :param target_architectures: The optional list of target architectures
            that the snap is intended to run on (from 'build-for').
        :param craft_platform: The platform name to build for.
        :return: `ISnapBuild`.
        """

    @call_with(requester=REQUEST_USER)
    @operation_parameters(
        archive=Reference(schema=IArchive),
        pocket=Choice(vocabulary=PackagePublishingPocket),
        channels=SnapBuildChannelsField(
            title=_("Source snap channels to use for this build."),
            description_prefix=_(
                "A dictionary mapping snap names to channels to use for this "
                "build."
            ),
            required=False,
            extra_snap_names=["snapcraft", "snapd"],
        ),
    )
    @export_factory_operation(ISnapBuildRequest, [])
    @operation_for_version("devel")
    def requestBuilds(requester, archive, pocket, channels=None):
        """Request that the snap package be built for relevant architectures.

        This is an asynchronous operation; once the operation has finished,
        the resulting build request's C{status} will be "Completed" and its
        C{builds} collection will return the resulting builds.

        :param requester: The person requesting the builds.
        :param archive: The IArchive to associate the builds with.
        :param pocket: The pocket that should be targeted.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :return: An `ISnapBuildRequest`.
        """

    def requestBuildsFromJob(
        requester,
        archive,
        pocket,
        channels=None,
        architectures=None,
        allow_failures=False,
        fetch_snapcraft_yaml=True,
        build_request=None,
        logger=None,
    ):
        """Synchronous part of `Snap.requestBuilds`.

        Request that the snap package be built for relevant architectures.

        :param requester: The person requesting the builds.
        :param archive: The IArchive to associate the builds with.
        :param pocket: The pocket that should be targeted.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        :param allow_failures: If True, log exceptions other than "already
            pending" from individual build requests; if False, raise them to
            the caller.
        :param fetch_snapcraft_yaml: If True, fetch snapcraft.yaml from the
            appropriate branch or repository and use it to decide which
            builds to request; if False, fall back to building for all
            supported architectures.
        :param build_request: The `ISnapBuildRequest` job being processed,
            if any.
        :param logger: An optional logger.
        :raises CannotRequestAutoBuilds: if fetch_snapcraft_yaml is False
            and self.distro_series is not set.
        :return: A sequence of `ISnapBuild` instances.
        """

    def getBuildRequest(job_id):
        """Get an asynchronous build request by ID.

        :param job_id: The ID of the build request.
        :return: `ISnapBuildRequest`.
        """

    pending_build_requests = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Pending build requests for this snap package."),
                value_type=Reference(ISnapBuildRequest),
                required=True,
                readonly=True,
            )
        )
    )

    failed_build_requests = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Failed build requests for this snap package."),
                value_type=Reference(ISnapBuildRequest),
                required=True,
                readonly=True,
            )
        )
    )

    def getBuildSummariesForSnapBuildIds(snap_build_ids):
        """Return a dictionary containing a summary of the build statuses.

        :param snap_build_ids: A list of snap build IDs.
        :type source_ids: ``list``
        :return: A dict consisting of the overall status summaries for the
            given snap builds.
        """

    @call_with(user=REQUEST_USER)
    @operation_parameters(
        store_upload_revision=Int(title="Store revision", required=True)
    )
    # Really ISnapBuild, patched in lp.snappy.interfaces.webservice.
    @operation_returns_entry(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getBuildByStoreRevision(store_upload_revision, user=None):
        """Returns the build (if any) of that snap recipe
            that has the given store_upload_revision.

        :param store_upload_revision: The revision assigned by the store.
        :param user: The `IPerson` requesting this information.
        :return: An 'ISnapBuild' or None.
        """

    @call_with(user=REQUEST_USER)
    @operation_parameters(
        request_ids=List(
            title=_("A list of snap build request IDs."),
            value_type=Int(),
            required=False,
        ),
        build_ids=List(
            title=_("A list of snap build IDs."),
            value_type=Int(),
            required=False,
        ),
    )
    @export_read_operation()
    @operation_for_version("devel")
    def getBuildSummaries(request_ids=None, build_ids=None, user=None):
        """Return a dictionary containing a summary of build information.

        :param request_ids: A list of snap build request IDs.
        :param build_ids: A list of snap build IDs.
        :param user: The `IPerson` requesting this information.
        :return: A dict of {"requests", "builds"}, consisting of the overall
            status summaries for the given snap build requests and snap
            builds respectively.
        """

    builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("All builds of this snap package."),
                description=_(
                    "All builds of this snap package, sorted in descending "
                    "order of finishing (or starting if not completed "
                    "successfully)."
                ),
                # Really ISnapBuild, patched in
                # lp.snappy.interfaces.webservice.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    completed_builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Completed builds of this snap package."),
                description=_(
                    "Completed builds of this snap package, sorted in "
                    "descending order of finishing."
                ),
                # Really ISnapBuild, patched in
                # lp.snappy.interfaces.webservice.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    pending_builds = exported(
        doNotSnapshot(
            CollectionField(
                title=_("Pending builds of this snap package."),
                description=_(
                    "Pending builds of this snap package, sorted in "
                    "descending order of creation."
                ),
                # Really ISnapBuild, patched in
                # lp.snappy.interfaces.webservice.
                value_type=Reference(schema=Interface),
                readonly=True,
            )
        )
    )

    subscriptions = CollectionField(
        title=_("SnapSubscriptions associated with this snap recipe."),
        readonly=True,
        value_type=Reference(Interface),
    )

    subscribers = CollectionField(
        title=_("Persons subscribed to this snap recipe."),
        readonly=True,
        value_type=Reference(IPerson),
    )

    def getSubscription(person):
        """Returns the person's snap subscription for this snap recipe."""

    def hasSubscription(person):
        """Is this person subscribed to the snap recipe?"""

    def userCanBeSubscribed(person):
        """Checks if the given person can be subscribed to this snap recipe."""

    def visibleByUser(user):
        """Can the specified user see this snap recipe?"""

    def getAllowedInformationTypes(user):
        """Get a list of acceptable `InformationType`s for this snap recipe.

        If the user is a Launchpad admin, any type is acceptable.
        """

    def unsubscribe(person, unsubscribed_by):
        """Unsubscribe a person from this snap recipe."""


class ISnapEdit(IWebhookTarget):
    """`ISnap` methods that require launchpad.Edit permission."""

    # Really ISnapBuild, patched in lp.snappy.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_write_operation()
    @operation_for_version("devel")
    def requestAutoBuilds(
        allow_failures=False, fetch_snapcraft_yaml=False, logger=None
    ):
        """Create and return automatic builds for this snap package.

        This webservice API method is deprecated.  It is normally better to
        use the `requestBuilds` method instead, which can make dispatching
        decisions based on the contents of snapcraft.yaml.

        :param allow_failures: If True, log exceptions other than "already
            pending" from individual build requests; if False, raise them to
            the caller.
        :param fetch_snapcraft_yaml: If True, fetch snapcraft.yaml from the
            appropriate branch or repository and use it to decide which
            builds to request; if False, fall back to building for all
            supported architectures.
        :param logger: An optional logger.
        :raises CannotRequestAutoBuilds: if no auto_build_archive or
            auto_build_pocket is set.
        :raises IncompatibleArguments: if no distro_series is set.
        :return: A sequence of `ISnapBuild` instances.
        """

    @export_write_operation()
    @operation_for_version("devel")
    def beginAuthorization():
        """Begin authorizing uploads of this snap package to the store.

        This is intended for use by third-party sites integrating with
        Launchpad.  Most users should visit <snap URL>/+authorize instead.

        :param success_url: The URL to redirect to when authorization is
            complete.  If None (only allowed for internal use), defaults to
            the canonical URL of the snap.
        :raises CannotAuthorizeStoreUploads: if the snap package is not
            properly configured for store uploads.
        :raises BadRequestPackageUploadResponse: if the store returns an
            error or a response without a macaroon when asked to issue a
            package_upload macaroon.
        :raises SnapAuthorizationBadGeneratedMacaroon: if the package_upload
            macaroon returned by the store has unsuitable SSO caveats.
        :return: The SSO caveat ID from the package_upload macaroon returned
            by the store.  The third-party site should acquire a discharge
            macaroon for this caveat using OpenID and then call
            `completeAuthorization`.
        """

    @operation_parameters(
        root_macaroon=TextLine(
            title=_("Serialized root macaroon"),
            description=_(
                "Only required if not already set by beginAuthorization."
            ),
            required=False,
        ),
        discharge_macaroon=TextLine(
            title=_("Serialized discharge macaroon"),
            description=_(
                "Only required if root macaroon has SSO third-party caveat."
            ),
            required=False,
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def completeAuthorization(root_macaroon=None, discharge_macaroon=None):
        """Complete authorizing uploads of this snap package to the store.

        This is intended for use by third-party sites integrating with
        Launchpad.

        :param root_macaroon: A serialized root macaroon returned by the
            store.  Only required if not already set by beginAuthorization.
        :param discharge_macaroon: The serialized discharge macaroon
            returned by SSO via OpenID.  Only required if the root macaroon
            has a third-party caveat addressed to SSO.
        :raises CannotAuthorizeStoreUploads: if the snap package is not
            properly configured for store uploads.
        """


class ISnapDelete(Interface):
    """`ISnap` methods that require launchpad.Delete permission."""

    @export_destructor_operation()
    @operation_for_version("devel")
    def destroySelf():
        """Delete this snap package, provided that it has no builds."""


class ISnapEditableAttributes(IHasOwner):
    """`ISnap` attributes that can be edited.

    These attributes need launchpad.View to see, and launchpad.Edit to change.
    """

    date_last_modified = exported(
        Datetime(title=_("Date last modified"), required=True, readonly=True)
    )

    owner = exported(
        PersonChoice(
            title=_("Owner"),
            required=True,
            readonly=False,
            vocabulary="AllUserTeamsParticipationPlusSelf",
            description=_("The owner of this snap package."),
        )
    )

    project = ReferenceChoice(
        title=_("The project that this Snap is associated with"),
        schema=IProduct,
        vocabulary="Product",
        required=False,
        readonly=False,
    )

    private = exported(
        Bool(
            title=_("Private"),
            required=False,
            readonly=False,
            description=_("Whether or not this snap is private."),
        )
    )

    information_type = exported(
        Choice(
            title=_("Information type"),
            vocabulary=InformationType,
            required=True,
            readonly=False,
            default=InformationType.PUBLIC,
            description=_(
                "The type of information contained in this Snap recipe."
            ),
        )
    )

    distro_series = exported(
        Reference(
            IDistroSeries,
            title=_("Distro Series"),
            required=False,
            readonly=False,
            description=_(
                "The series for which the snap package should be built.  If "
                "not set, Launchpad will infer an appropriate series from "
                "snapcraft.yaml."
            ),
        )
    )

    name = exported(
        TextLine(
            title=_("Snap recipe name"),
            required=True,
            readonly=False,
            constraint=name_validator,
            description=_("The name of the snap build recipe."),
        )
    )

    description = exported(
        Text(
            title=_("Description"),
            required=False,
            readonly=False,
            description=_("A description of the snap package."),
        )
    )

    branch = exported(
        ReferenceChoice(
            title=_("Bazaar branch"),
            schema=IBranch,
            vocabulary="Branch",
            required=False,
            readonly=False,
            description=_(
                "A Bazaar branch containing a snap/snapcraft.yaml, "
                "build-aux/snap/snapcraft.yaml, snapcraft.yaml, or "
                ".snapcraft.yaml recipe at the top level."
            ),
        )
    )

    git_repository = exported(
        ReferenceChoice(
            title=_("Git repository"),
            schema=IGitRepository,
            vocabulary="GitRepository",
            required=False,
            readonly=True,
            description=_(
                "A Git repository with a branch containing a "
                "snap/snapcraft.yaml, build-aux/snap/snapcraft.yaml, "
                "snapcraft.yaml, or .snapcraft.yaml recipe at the top level."
            ),
        )
    )

    git_repository_url = exported(
        URIField(
            title=_("Git repository URL"),
            required=False,
            readonly=True,
            description=_(
                "The URL of a Git repository with a branch containing a "
                "snap/snapcraft.yaml, build-aux/snap/snapcraft.yaml, "
                "snapcraft.yaml, or .snapcraft.yaml recipe at the top level."
            ),
            allowed_schemes=["git", "http", "https"],
            allow_userinfo=True,
            allow_port=True,
            allow_query=False,
            allow_fragment=False,
            trailing_slash=False,
        )
    )

    git_path = TextLine(
        title=_("Git branch path"),
        required=False,
        readonly=False,
        description=_(
            "The path of the Git branch containing a snap/snapcraft.yaml, "
            "build-aux/snap/snapcraft.yaml, snapcraft.yaml, or "
            ".snapcraft.yaml recipe at the top level."
        ),
    )
    _api_git_path = exported(
        TextLine(
            title=git_path.title,
            required=False,
            readonly=False,
            description=git_path.description,
        ),
        exported_as="git_path",
    )

    git_ref = exported(
        Reference(
            IGitRef,
            title=_("Git branch"),
            required=False,
            readonly=False,
            description=_(
                "The Git branch containing a snap/snapcraft.yaml, "
                "build-aux/snap/snapcraft.yaml, snapcraft.yaml, or "
                ".snapcraft.yaml recipe at the top level."
            ),
        )
    )

    build_source_tarball = exported(
        Bool(
            title=_("Build source tarball"),
            required=True,
            readonly=False,
            description=_(
                "Whether builds of this snap package should also build a "
                "tarball containing all source code, including external "
                "dependencies."
            ),
        )
    )

    auto_build = exported(
        Bool(
            title=_("Automatically build when branch changes"),
            required=True,
            readonly=False,
            description=_(
                "Whether this snap package is built automatically when the "
                "branch containing its snap/snapcraft.yaml, "
                "build-aux/snap/snapcraft.yaml, snapcraft.yaml, or "
                ".snapcraft.yaml recipe changes."
            ),
        )
    )

    auto_build_archive = exported(
        Reference(
            IArchive,
            title=_("Source archive for automatic builds"),
            required=False,
            readonly=False,
            description=_(
                "The archive from which automatic builds of this snap package "
                "should be built."
            ),
        )
    )

    auto_build_pocket = exported(
        Choice(
            title=_("Pocket for automatic builds"),
            vocabulary=PackagePublishingPocket,
            required=False,
            readonly=False,
            description=_(
                "The package stream within the source archive and "
                "distribution series to use when building the snap package.  "
                "If the source archive is a PPA, then the PPA's archive "
                "dependencies will be used to select the pocket in the "
                "distribution's primary archive."
            ),
        )
    )

    auto_build_channels = exported(
        SnapBuildChannelsField(
            title=_("Source snap channels for automatic builds"),
            required=False,
            readonly=False,
            extra_snap_names=["snapcraft", "snapd"],
            description_prefix=_(
                "A dictionary mapping snap names to channels to use when "
                "building this snap package."
            ),
        )
    )

    is_stale = exported(
        Bool(
            title=_("Snap package is stale and is due to be rebuilt."),
            required=True,
            readonly=True,
        )
    )

    store_upload = exported(
        Bool(
            title=_("Automatically upload to store"),
            required=True,
            readonly=False,
            description=_(
                "Whether builds of this snap package are automatically "
                "uploaded to the store."
            ),
        )
    )

    # XXX cjwatson 2016-12-08: We should limit this to series that are
    # compatible with distro_series, but that entails validating the case
    # where both are changed in a single PATCH request in such a way that
    # neither is compatible with the old value of the other.  As far as I
    # can tell lazr.restful only supports per-field validation.
    store_series = exported(
        ReferenceChoice(
            title=_("Store series"),
            schema=ISnappySeries,
            vocabulary="SnappySeries",
            required=False,
            readonly=False,
            description=_(
                "The series in which this snap package should be published in "
                "the store."
            ),
        )
    )

    store_distro_series = ReferenceChoice(
        title=_("Store and distro series"),
        schema=ISnappyDistroSeries,
        vocabulary="SnappyDistroSeries",
        required=False,
        readonly=False,
    )

    store_name = exported(
        TextLine(
            title=_("Registered store package name"),
            required=False,
            readonly=False,
            description=_(
                "The registered name of this snap package in the store."
            ),
        )
    )

    store_secrets = List(
        value_type=TextLine(),
        title=_("Store upload tokens"),
        required=False,
        readonly=False,
        description=_(
            "Serialized secrets issued by the store and the login service to "
            "authorize uploads of this snap package."
        ),
    )

    store_channels = exported(
        List(
            title=_("Store channels"),
            required=False,
            readonly=False,
            constraint=channels_validator,
            description=_(
                "Channels to release this snap package to after uploading it "
                "to the store. A channel is defined by a combination of an "
                "optional track, a risk, and an optional branch, e.g. "
                "'2.1/stable/fix-123', '2.1/stable', 'stable/fix-123', or "
                "'stable'."
            ),
        )
    )

    def setProject(project):
        """Set the pillar project of this snap recipe."""


class ISnapAdminAttributes(Interface):
    """`ISnap` attributes that can be edited by admins.

    These attributes need launchpad.View to see, and launchpad.Admin to change.
    """

    require_virtualized = exported(
        Bool(
            title=_("Require virtualized builders"),
            required=True,
            readonly=False,
            description=_("Only build this snap package on virtual builders."),
        )
    )

    processors = exported(
        CollectionField(
            title=_("Processors"),
            description=_(
                "The architectures for which the snap package should be built."
            ),
            value_type=Reference(schema=IProcessor),
            readonly=False,
        )
    )

    allow_internet = exported(
        Bool(
            title=_("Allow external network access"),
            required=True,
            readonly=False,
            description=_(
                "Allow access to external network resources via a proxy.  "
                "Resources hosted on Launchpad itself are always allowed."
            ),
        )
    )

    pro_enable = exported(
        Bool(
            title=_("Enable Ubuntu Pro"),
            required=True,
            readonly=False,
            description=_(
                "Allow building this snap recipe using dependencies from "
                "Ubuntu Pro, if configured for the corresponding snap base."
            ),
        )
    )

    use_fetch_service = exported(
        Bool(
            title=_("Use fetch service"),
            required=True,
            readonly=False,
            description=_(
                "If set, Snap builds will use the fetch-service instead "
                "of the builder-proxy to access external resources."
            ),
        )
    )

    fetch_service_policy = exported(
        Choice(
            title=_("Fetch service policy"),
            vocabulary=FetchServicePolicy,
            required=False,
            readonly=False,
            default=FetchServicePolicy.STRICT,
            description=_(
                "Which policy to use when using the fetch service. Ignored if "
                "`use_fetch_service` flag is False."
            ),
        )
    )

    def subscribe(person, subscribed_by):
        """Subscribe a person to this snap recipe."""


# XXX cjwatson 2015-07-17 bug=760849: "beta" is a lie to get WADL
# generation working.  Individual attributes must set their version to
# "devel".
@exported_as_webservice_entry(as_of="beta")
class ISnap(
    ISnapView,
    ISnapEdit,
    ISnapDelete,
    ISnapEditableAttributes,
    ISnapAdminAttributes,
    IInformationType,
):
    """A buildable snap package."""


@exported_as_webservice_collection(ISnap)
class ISnapSet(Interface):
    """A utility to create and access snap packages."""

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        information_type=copy_field(ISnap["information_type"], required=False),
        processors=List(
            value_type=Reference(schema=IProcessor), required=False
        ),
    )
    @export_factory_operation(
        ISnap,
        [
            "owner",
            "distro_series",
            "name",
            "description",
            "branch",
            "git_repository",
            "git_repository_url",
            "git_path",
            "git_ref",
            "auto_build",
            "auto_build_archive",
            "auto_build_pocket",
            "store_upload",
            "store_series",
            "store_name",
            "store_channels",
            "project",
        ],
    )
    @operation_for_version("devel")
    def new(
        registrant,
        owner,
        distro_series,
        name,
        description=None,
        branch=None,
        git_repository=None,
        git_repository_url=None,
        git_path=None,
        git_ref=None,
        auto_build=False,
        auto_build_archive=None,
        auto_build_pocket=None,
        require_virtualized=True,
        processors=None,
        date_created=None,
        information_type=InformationType.PUBLIC,
        store_upload=False,
        store_series=None,
        store_name=None,
        store_secrets=None,
        store_channels=None,
        project=None,
        pro_enable=None,
        use_fetch_service=False,
        fetch_service_policy=FetchServicePolicy.STRICT,
    ):
        """Create an `ISnap`."""

    def exists(owner, name):
        """Check to see if a matching snap exists."""

    def getPossibleSnapInformationTypes(project):
        """Returns the list of possible InformationTypes for snaps based on
        the given project.
        """

    def findByIds(snap_ids):
        """Return all snap packages with the given ids."""

    def isValidInformationType(
        information_type, owner, branch=None, git_ref=None
    ):
        """Whether or not the information type context is valid."""

    @operation_parameters(
        owner=Reference(IPerson, title=_("Owner"), required=True),
        name=TextLine(title=_("Snap name"), required=True),
    )
    @operation_returns_entry(ISnap)
    @export_read_operation()
    @operation_for_version("devel")
    def getByName(owner, name):
        """Return the appropriate `ISnap` for the given objects."""

    def getByPillarAndName(owner, pillar, name):
        """Returns the appropriate `ISnap` for the given pillar and name."""

    @operation_parameters(
        owner=Reference(IPerson, title=_("Owner"), required=True)
    )
    @operation_returns_collection_of(ISnap)
    @export_read_operation()
    @operation_for_version("devel")
    def findByOwner(owner):
        """Return all snap packages with the given `owner`."""

    def findByPerson(person, visible_by_user=None):
        """Return all snap packages relevant to `person`.

        This returns snap packages for Bazaar or Git branches owned by
        `person`, or where `person` is the owner of the snap package.

        :param person: An `IPerson`.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        """

    def findByProject(project, visible_by_user=None):
        """Return all snap packages for the given project.

        :param project: An `IProduct`.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        """

    def findByBranch(branch, check_permissions=True):
        """Return all snap packages for the given Bazaar branch."""

    def findByGitRepository(repository, paths=None, check_permissions=True):
        """Return all snap packages for the given Git repository.

        :param repository: An `IGitRepository`.
        :param paths: If not None, only return snap packages for one of
            these Git reference paths.
        """

    def findByGitRef(ref):
        """Return all snap packages for the given Git reference."""

    def findByContext(context, visible_by_user=None, order_by_date=True):
        """Return all snap packages for the given context.

        :param context: An `IPerson`, `IProduct, `IBranch`,
            `IGitRepository`, or `IGitRef`.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        :param order_by_date: If True, order packages by descending
            modification date, then by descending creation date.
        :raises BadSnapSearchContext: if the context is not understood.
        """

    @operation_parameters(
        url=TextLine(title=_("The URL to search for.")),
        owner=Reference(IPerson, title=_("Owner"), required=False),
    )
    @call_with(visible_by_user=REQUEST_USER)
    @operation_returns_collection_of(ISnap)
    @export_read_operation()
    @operation_for_version("devel")
    def findByURL(url, owner=None, visible_by_user=None):
        """Return all snap packages that build from the given URL.

        This currently only works for packages that build directly from a
        URL, rather than being linked to a Bazaar branch or Git repository
        hosted in Launchpad.

        :param url: A URL.
        :param owner: Only return packages owned by this user.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        """

    @operation_parameters(
        url_prefix=TextLine(title=_("The URL prefix to search for.")),
        owner=Reference(IPerson, title=_("Owner"), required=False),
    )
    @call_with(visible_by_user=REQUEST_USER)
    @operation_returns_collection_of(ISnap)
    @export_read_operation()
    @operation_for_version("devel")
    def findByURLPrefix(url_prefix, owner=None, visible_by_user=None):
        """Return all snap packages that build from a URL with this prefix.

        This currently only works for packages that build directly from a
        URL, rather than being linked to a Bazaar branch or Git repository
        hosted in Launchpad.

        :param url_prefix: A URL prefix.
        :param owner: Only return packages owned by this user.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        """

    @operation_parameters(
        url_prefixes=List(
            title=_("The URL prefixes to search for."), value_type=TextLine()
        ),
        owner=Reference(IPerson, title=_("Owner"), required=False),
    )
    @call_with(visible_by_user=REQUEST_USER)
    @operation_returns_collection_of(ISnap)
    @export_read_operation()
    @operation_for_version("devel")
    def findByURLPrefixes(url_prefixes, owner=None, visible_by_user=None):
        """Return all snap packages that build from a URL with any of these
        prefixes.

        This currently only works for packages that build directly from a
        URL, rather than being linked to a Bazaar branch or Git repository
        hosted in Launchpad.

        :param url_prefixes: A list of URL prefixes.
        :param owner: Only return packages owned by this user.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        """

    @operation_parameters(
        store_name=TextLine(
            title=_("The registered store package name to search for.")
        ),
        owner=Reference(IPerson, title=_("Owner"), required=False),
    )
    @call_with(visible_by_user=REQUEST_USER)
    @operation_returns_collection_of(ISnap)
    @export_read_operation()
    @operation_for_version("devel")
    def findByStoreName(store_name, owner=None, visible_by_user=None):
        """Return all snap packages with the given store package name.

        :param store_name: A registered store package name.
        :param owner: Only return packages owned by this user.
        :param visible_by_user: If not None, only return packages visible by
            this user; otherwise, only return publicly-visible packages.
        """

    def preloadDataForSnaps(snaps, user):
        """Load the data related to a list of snap packages."""

    def getSnapcraftYaml(context, logger=None):
        """Fetch a package's snapcraft.yaml from code hosting, if possible.

        :param context: Either an `ISnap` or the source branch for a snap
            package.
        :param logger: An optional logger.

        :return: The package's parsed snapcraft.yaml.
        :raises MissingSnapcraftYaml: if this package has no snapcraft.yaml.
        :raises CannotFetchSnapcraftYaml: if it was not possible to fetch
            snapcraft.yaml from the code hosting backend for some other
            reason.
        :raises CannotParseSnapcraftYaml: if the fetched snapcraft.yaml
            cannot be parsed.
        """

    def makeAutoBuilds(logger=None):
        """Create and return automatic builds for stale snap packages.

        :param logger: An optional logger.
        """

    def detachFromBranch(branch):
        """Detach all snap packages from the given Bazaar branch.

        After this, any snap packages that previously used this branch will
        have no source and so cannot dispatch new builds.
        """

    def detachFromGitRepository(repository):
        """Detach all snap packages from the given Git repository.

        After this, any snap packages that previously used this repository
        will have no source and so cannot dispatch new builds.
        """

    @collection_default_content()
    def empty_list():
        """Return an empty collection of snap packages.

        This only exists to keep lazr.restful happy.
        """
