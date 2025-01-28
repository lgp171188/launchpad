# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Archive interfaces."""

__all__ = [
    "ALLOW_RELEASE_BUILDS",
    "AlreadySubscribed",
    "ArchiveAlreadyDeleted",
    "ArchiveDependencyError",
    "ArchiveDisabled",
    "ArchiveNotPrivate",
    "CannotCopy",
    "CannotSwitchPrivacy",
    "ComponentNotFound",
    "CannotModifyArchiveProcessor",
    "CannotUploadToArchive",
    "CannotUploadToPPA",
    "CannotUploadToPocket",
    "CannotUploadToSeries",
    "DuplicateTokenName",
    "FULL_COMPONENT_SUPPORT",
    "IArchive",
    "IArchiveAdmin",
    "IArchiveAppend",
    "IArchiveEdit",
    "IArchiveEditDependenciesForm",
    "IArchiveSubscriberView",
    "IArchivePublic",
    "IArchiveSet",
    "IArchiveView",
    "IDistributionArchive",
    "InsufficientUploadRights",
    "InvalidComponent",
    "InvalidExternalDependencies",
    "InvalidPocketForPartnerArchive",
    "InvalidPocketForPPA",
    "IPPA",
    "MAIN_ARCHIVE_PURPOSES",
    "NAMED_AUTH_TOKEN_FEATURE_FLAG",
    "NamedAuthTokenFeatureDisabled",
    "NoRightsForArchive",
    "NoRightsForComponent",
    "NoSuchPPA",
    "NoTokensForTeams",
    "PocketNotFound",
    "PriorityNotFound",
    "RedirectedPocket",
    "SectionNotFound",
    "VersionRequiresName",
    "default_name_by_purpose",
    "validate_external_dependencies",
]

import http.client
import re
import typing
from datetime import datetime
from pathlib import PurePath
from urllib.parse import urlparse

from lazr.restful.declarations import (
    REQUEST_USER,
    call_with,
    collection_default_content,
    error_status,
    export_destructor_operation,
    export_factory_operation,
    export_operation_as,
    export_read_operation,
    export_write_operation,
    exported,
    exported_as_webservice_collection,
    exported_as_webservice_entry,
    mutator_for,
    operation_for_version,
    operation_parameters,
    operation_returns_collection_of,
    operation_returns_entry,
    rename_parameters_as,
)
from lazr.restful.fields import CollectionField, Reference
from lazr.restful.interface import copy_field
from zope.interface import Attribute, Interface
from zope.schema import (
    Bool,
    Choice,
    Datetime,
    Dict,
    Int,
    List,
    Object,
    Text,
    TextLine,
)
from zope.security.interfaces import Unauthorized

from lp import _
from lp.app.errors import NameLookupFailed
from lp.app.interfaces.launchpad import IPrivacy
from lp.app.validators.name import name_validator
from lp.buildmaster.interfaces.processor import IProcessor
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.gpg import IGPGKey
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.role import IHasOwner
from lp.services.fields import (
    PersonChoice,
    PublicPersonChoice,
    StrippedTextLine,
)
from lp.soyuz.enums import (
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveRepositoryFormat,
    PackagePublishingStatus,
)
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.soyuz.interfaces.component import IComponent

NAMED_AUTH_TOKEN_FEATURE_FLAG = "soyuz.named_auth_token.allow_new"


@error_status(http.client.BAD_REQUEST)
class ArchiveDependencyError(Exception):
    """Raised when an `IArchiveDependency` does not fit the context archive.

    A given dependency is considered inappropriate when:

     * It is the archive itself,
     * It is not a PPA,
     * It is already recorded.
    """


# Exceptions used in the webservice that need to be in this file to get
# picked up therein.
@error_status(http.client.BAD_REQUEST)
class CannotCopy(Exception):
    """Exception raised when a copy cannot be performed."""


@error_status(http.client.BAD_REQUEST)
class CannotSwitchPrivacy(Exception):
    """Raised when switching the privacy of an archive that has
    publishing records."""


class PocketNotFound(NameLookupFailed):
    """Invalid pocket."""

    _message_prefix = "No such pocket"


@error_status(http.client.BAD_REQUEST)
class AlreadySubscribed(Exception):
    """Raised when creating a subscription for a subscribed person."""


@error_status(http.client.BAD_REQUEST)
class ArchiveNotPrivate(Exception):
    """Raised when creating an archive subscription for a public archive."""


@error_status(http.client.BAD_REQUEST)
class NoTokensForTeams(Exception):
    """Raised when creating a token for a team, rather than a person."""


class ComponentNotFound(NameLookupFailed):
    """Invalid component name."""

    _message_prefix = "No such component"


@error_status(http.client.BAD_REQUEST)
class InvalidComponent(Exception):
    """Invalid component name."""


class SectionNotFound(NameLookupFailed):
    """Invalid section name."""

    _message_prefix = "No such section"


class PriorityNotFound(NameLookupFailed):
    """Invalid priority name."""

    _message_prefix = "No such priority"


class NoSuchPPA(NameLookupFailed):
    """Raised when we try to look up an PPA that doesn't exist."""

    _message_prefix = "No such ppa"


@error_status(http.client.BAD_REQUEST)
class VersionRequiresName(Exception):
    """Raised on some queries when version is specified but name is not."""


@error_status(http.client.BAD_REQUEST)
class ArchiveAlreadyDeleted(Exception):
    """Archive already deleted."""


@error_status(http.client.FORBIDDEN)
class CannotUploadToArchive(Exception):
    """A reason for not being able to upload to an archive."""

    _fmt = "%(person)s has no upload rights to %(archive)s."

    def __init__(self, **args):
        """Construct a `CannotUploadToArchive`."""
        super().__init__(self._fmt % args)


class InvalidPocketForPartnerArchive(CannotUploadToArchive):
    """Partner archives only support some pockets."""

    _fmt = "Partner uploads must be for the RELEASE or PROPOSED pocket."


@error_status(http.client.FORBIDDEN)
class CannotUploadToPocket(Exception):
    """Returned when a pocket is closed for uploads."""

    def __init__(self, distroseries, pocket):
        super().__init__(
            "Not permitted to upload to the %s pocket in a series in the "
            "'%s' state." % (pocket.name, distroseries.status.name)
        )


@error_status(http.client.FORBIDDEN)
class RedirectedPocket(Exception):
    """Returned for a pocket that would normally be redirected to another.

    This is used in contexts (e.g. copies) where actually doing the
    redirection would be Too Much Magic."""

    def __init__(self, distroseries, pocket, preferred):
        Exception.__init__(
            self,
            "Not permitted to upload directly to %s; try %s instead."
            % (
                distroseries.getSuite(pocket),
                distroseries.getSuite(preferred),
            ),
        )


class CannotUploadToPPA(CannotUploadToArchive):
    """Raised when a person cannot upload to a PPA."""

    _fmt = "Signer has no upload rights to this PPA."


class NoRightsForArchive(CannotUploadToArchive):
    """Raised when a person has absolutely no upload rights to an archive."""

    _fmt = (
        "The signer of this package has no upload rights to this "
        "distribution's primary archive.  Did you mean to upload to "
        "a PPA?"
    )


class InsufficientUploadRights(CannotUploadToArchive):
    """Raised when a person has insufficient upload rights."""

    _fmt = (
        "The signer of this package is lacking the upload rights for "
        "the source package, component or package set in question."
    )


class NoRightsForComponent(CannotUploadToArchive):
    """Raised when a person may not upload to a component."""

    _fmt = (
        "Signer is not permitted to upload to the component '%(component)s'."
    )

    def __init__(self, component):
        super().__init__(component=component.name)


class InvalidPocketForPPA(CannotUploadToArchive):
    """PPAs only support some pockets."""

    _fmt = "PPA uploads must be for the RELEASE pocket."


class ArchiveDisabled(CannotUploadToArchive):
    """Uploading to a disabled archive is not allowed."""

    _fmt = "%(archive_name)s is disabled."

    def __init__(self, archive_name):
        super().__init__(archive_name=archive_name)


class CannotUploadToSeries(CannotUploadToArchive):
    """Uploading to an obsolete series is not allowed."""

    _fmt = "%(distroseries)s is obsolete and will not accept new uploads."

    def __init__(self, distroseries):
        super().__init__(distroseries=distroseries.name)


@error_status(http.client.BAD_REQUEST)
class InvalidExternalDependencies(Exception):
    """Tried to set external dependencies to an invalid value."""

    def __init__(self, errors):
        error_msg = "Invalid external dependencies:\n%s\n" % "\n".join(errors)
        super().__init__(error_msg)
        self.errors = errors


@error_status(http.client.FORBIDDEN)
class CannotModifyArchiveProcessor(Exception):
    """Tried to enable or disable a restricted processor on an archive."""

    _fmt = (
        "%(processor)s is restricted, and may only be enabled or disabled "
        "by administrators."
    )

    def __init__(self, processor):
        super().__init__(self._fmt % {"processor": processor.name})


@error_status(http.client.CONFLICT)
class DuplicateTokenName(Exception):
    """Raised when creating a named token and an active token for this archive
    with this name already exists."""


@error_status(http.client.UNAUTHORIZED)
class NamedAuthTokenFeatureDisabled(Unauthorized):
    """Only certain users can create named authorization tokens."""

    def __init__(self):
        super().__init__(
            "You do not have permission to create named authorization tokens"
        )


class IArchivePublic(IPrivacy, IHasOwner):
    """An Archive interface for publicly available operations."""

    # Most of this stuff should really be on View, but it's needed for
    # security checks and URL generation and things like that.
    # Others are presently needed because invisible (private or disabled)
    # archives can show up in copy histories and archive dependency
    # lists.

    id = Attribute("The archive ID.")

    owner = exported(
        PersonChoice(
            title=_("Owner"),
            required=True,
            vocabulary="ValidOwner",
            description=_("""The archive owner."""),
        )
    )

    name = exported(
        TextLine(
            title=_("Name"),
            required=True,
            constraint=name_validator,
            description=_(
                "At least one lowercase letter or number, followed by "
                "letters, numbers, dots, hyphens or pluses. "
                "Keep this name short; it is used in URLs."
            ),
        )
    )

    displayname = exported(
        StrippedTextLine(
            title=_("Display name"),
            required=True,
            description=_("A short title for the archive."),
        )
    )

    reference = exported(
        TextLine(
            title=_("Reference"),
            required=True,
            readonly=True,
            description=_("A string to uniquely identify the archive."),
        )
    )

    distribution = exported(
        Reference(
            # Really IDistribution, patched in lp.soyuz.interfaces.webservice.
            Interface,
            title=_(
                "The distribution that uses or is used by this " "archive."
            ),
        )
    )

    enabled = Bool(
        title=_("Enabled"),
        required=False,
        description=_("Accept and build packages uploaded to the archive."),
    )

    # This is redefined from IPrivacy.private because the attribute is
    # read-only. The value is guarded by a validator.
    private = exported(
        Bool(
            title=_("Private"),
            required=False,
            description=_(
                "Restrict access to the archive to its owner and "
                "subscribers. This can only be changed if the archive has "
                "never had any sources published."
            ),
        )
    )

    is_primary = Attribute("True if this archive is a primary archive.")

    is_ppa = Attribute("True if this archive is a PPA.")

    is_partner = Attribute("True if this archive is a partner archive.")

    is_copy = Attribute("True if this archive is a copy archive.")

    is_main = Bool(
        title=_("True if archive is a main archive type"), required=False
    )

    suppress_subscription_notifications = exported(
        Bool(
            title=_("Suppress subscription notifications"),
            required=True,
            description=_(
                "Whether subscribers to private PPAs get emails about their "
                "subscriptions. Has no effect on a public PPA."
            ),
        )
    )

    def checkArchivePermission(person, component_or_package=None):
        """Check to see if person is allowed to upload to component.

        :param person: An `IPerson` whom should be checked for authentication.
        :param component_or_package: The context `IComponent` or an
            `ISourcePackageName` for the check.  This parameter is
            not required if the archive is a PPA.

        :return: True if 'person' is allowed to upload to the specified
            component or package name.
        :raise TypeError: If component_or_package is not one of
            `IComponent` or `ISourcePackageName`.

        """


class IArchiveSubscriberView(Interface):
    archive_url = Attribute("External archive URL.")
    dependencies = exported(
        CollectionField(
            title=_("Archive dependencies recorded for this archive."),
            # Really IArchiveDependency, patched in
            # lp.soyuz.interfaces.webservice.
            value_type=Reference(schema=Interface),
            readonly=True,
        )
    )
    description = exported(
        Text(
            title=_("Description"),
            required=False,
            description=_(
                "A short description of the archive. URLs are allowed and "
                "will be rendered as links."
            ),
        )
    )
    is_active = Bool(
        title=_("True if the archive is in the active state"),
        required=False,
        readonly=True,
    )
    num_pkgs_building = Attribute(
        "Tuple of packages building and waiting to build"
    )
    publish = Bool(
        title=_("Publish"),
        required=False,
        description=_(
            "Whether or not to update the apt repository.  If "
            "disabled, nothing will be published.  If the archive is "
            "private then additionally no builds will be dispatched."
        ),
    )
    can_be_published = Bool(
        title=_("Can be published"),
        required=True,
        description=_(
            "True if this archive can be published, considering both the "
            "explicit publish flag and any other constraints."
        ),
    )
    series_with_sources = Attribute(
        "DistroSeries to which this archive has published sources"
    )
    signing_key_owner = Reference(
        title=_("Archive signing key owner"), required=False, schema=IPerson
    )
    signing_key_fingerprint = exported(
        Text(
            title=_("Archive signing key fingerprint"),
            required=False,
            description=_(
                "A OpenPGP signing key fingerprint (40 chars) "
                "for this PPA or None if there is no signing "
                "key available."
            ),
        )
    )
    signing_key = Object(
        title=_("Repository signing key."), required=False, schema=IGPGKey
    )
    signing_key_keyserver_url = TextLine(
        title=_("Keyserver URL for archive signing key."), required=False
    )
    signing_key_display_name = TextLine(
        title=_("Display name for archive signing key."), required=False
    )

    @export_read_operation()
    @operation_for_version("devel")
    def getSigningKeyData():
        """Get the public key used to sign this repository.

        If the repository has a signing key but it cannot be retrieved from
        the keyserver, then the response will have an appropriate 4xx or 5xx
        HTTP status code.  Otherwise, returns the ASCII-armoured public key
        material as a text string, or None if the repository has no signing
        key.
        """

    def getAuthToken(person):
        """Returns an IArchiveAuthToken for the archive in question for
        IPerson provided.

        :return: A IArchiveAuthToken, or None if the user has none.
        """

    @export_operation_as("getPublishedSources")
    @rename_parameters_as(name="source_name", distroseries="distro_series")
    @operation_parameters(
        name=TextLine(title=_("Source package name"), required=False),
        version=TextLine(title=_("Version"), required=False),
        status=Choice(
            title=_("Package Publishing Status"),
            description=_("The status of this publishing record"),
            vocabulary=PackagePublishingStatus,
            required=False,
        ),
        distroseries=Reference(
            IDistroSeries, title=_("Distroseries name"), required=False
        ),
        pocket=Choice(
            title=_("Pocket"),
            description=_("The pocket into which this entry is published"),
            vocabulary=PackagePublishingPocket,
            required=False,
            readonly=True,
        ),
        exact_match=Bool(
            title=_("Exact Match"),
            description=_(
                "Whether or not to filter source names by exact" " matching."
            ),
            required=False,
        ),
        created_since_date=Datetime(
            title=_("Created Since Date"),
            description=_(
                "Return entries whose `date_created` is greater "
                "than or equal to this date."
            ),
            required=False,
        ),
        component_name=TextLine(title=_("Component name"), required=False),
        order_by_date=Bool(
            title=_("Order by creation date"),
            description=_(
                "Return newest results first. This is recommended "
                "for applications that need to catch up with "
                "publications since their last run. If not "
                "specified, results are ordered by source "
                "package name (lexicographically), then by "
                "descending version and then descending ID."
            ),
            required=False,
        ),
        order_by_date_ascending=Bool(
            title=_("Order by ascending creation date"),
            description=_("Return oldest results first."),
            required=False,
        ),
    )
    # Really ISourcePackagePublishingHistory, patched in
    # lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def api_getPublishedSources(
        name=None,
        version=None,
        status=None,
        distroseries=None,
        pocket=None,
        exact_match=False,
        created_since_date=None,
        component_name=None,
        order_by_date=False,
        order_by_date_ascending=False,
    ):
        """All `ISourcePackagePublishingHistory` target to this archive."""
        # It loads additional related objects only needed in the API call
        # context (i.e. security checks and entries marshalling).

    def getPublishedSources(
        name=None,
        version=None,
        status=None,
        distroseries=None,
        pocket=None,
        exact_match=False,
        created_since_date=None,
        eager_load=False,
        component_name=None,
        order_by_date=False,
        order_by_date_ascending=False,
        include_removed=True,
        only_unpublished=False,
    ):
        """All `ISourcePackagePublishingHistory` target to this archive.

        :param name: source name filter (exact match or SQL LIKE controlled
                     by 'exact_match' argument).
                     Name can be a single string or a list of strings.
        :param version: source version filter (always exact match).
        :param status: `PackagePublishingStatus` filter, can be a sequence.
        :param distroseries: `IDistroSeries` filter.
        :param pocket: `PackagePublishingPocket` filter.  This may be an
            iterable of more than one pocket or a single pocket.
        :param exact_match: either or not filter source names by exact
                             matching.
        :param created_since_date: Only return results whose `date_created`
            is greater than or equal to this date.
        :param component_name: component filter. Only return source packages
            that are in this component.
        :param order_by_date: Order publications by descending creation date
            and then by descending ID.  This is suitable for applications
            that need to catch up with publications since their last run.
            If not specified, publications are ordered by source
            package name (lexicographically), then by descending version
            and then descending ID.
        :param order_by_date_ascending: Order publications by descending
            creation date and then by ascending ID.
        :param include_removed: If True, include publications that have been
            removed from disk as well as those that have not.
        :param only_unpublished: If True, only include publications that
            have never been published to disk.

        :return: SelectResults containing `ISourcePackagePublishingHistory`,
            ordered by name. If there are multiple results for the same
            name then they are sub-ordered newest first.
        """

    def newAuthToken(person, token=None, date_created=None):
        """Create a new authorization token.

        :param person: An IPerson whom this token is for.
        :param token: Optional unicode text to use as the token. One will be
            generated if not given.
        :param date_created: Optional, defaults to now.

        :return: A new IArchiveAuthToken
        """

    @call_with(eager_load=True)
    @rename_parameters_as(
        name="binary_name", distroarchseries="distro_arch_series"
    )
    @operation_parameters(
        name=TextLine(title=_("Binary Package Name"), required=False),
        version=TextLine(title=_("Version"), required=False),
        status=Choice(
            title=_("Package Publishing Status"),
            description=_("The status of this publishing record"),
            vocabulary=PackagePublishingStatus,
            required=False,
        ),
        distroarchseries=Reference(
            # Really IDistroArchSeries, patched in
            # lp.soyuz.interfaces.webservice.
            Interface,
            title=_("Distro Arch Series"),
            required=False,
        ),
        pocket=Choice(
            title=_("Pocket"),
            description=_("The pocket into which this entry is published"),
            vocabulary=PackagePublishingPocket,
            required=False,
            readonly=True,
        ),
        exact_match=Bool(
            description=_(
                "Whether or not to filter binary names by exact " "matching."
            ),
            required=False,
        ),
        created_since_date=Datetime(
            title=_("Created Since Date"),
            description=_(
                "Return entries whose `date_created` is greater "
                "than or equal to this date."
            ),
            required=False,
        ),
        ordered=Bool(
            title=_("Ordered"),
            description=_(
                "Return ordered results by default, but specifying "
                "False will return results more quickly."
            ),
            required=False,
            readonly=True,
        ),
        order_by_date=Bool(
            title=_("Order by creation date"),
            description=_(
                "Return newest results first. This is recommended "
                "for applications that need to catch up with "
                "publications since their last run."
            ),
            required=False,
        ),
        order_by_date_ascending=Bool(
            title=_("Order by ascending creation date"),
            description=_("Return oldest results first."),
            required=False,
        ),
        component_name=TextLine(title=_("Component name"), required=False),
    )
    # Really IBinaryPackagePublishingHistory, patched in
    # lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_operation_as("getPublishedBinaries")
    @export_read_operation()
    @operation_for_version("beta")
    def getAllPublishedBinaries(
        name=None,
        version=None,
        status=None,
        distroarchseries=None,
        pocket=None,
        exact_match=False,
        created_since_date=None,
        ordered=True,
        order_by_date=False,
        order_by_date_ascending=False,
        include_removed=True,
        only_unpublished=False,
        eager_load=False,
        component_name=None,
    ):
        """All `IBinaryPackagePublishingHistory` target to this archive.

        :param name: binary name filter (exact match or SQL LIKE controlled
                      by 'exact_match' argument).
        :param version: binary version filter (always exact match).
        :param status: `PackagePublishingStatus` filter, can be a list.
        :param distroarchseries: `IDistroArchSeries` filter, can be a list.
        :param pocket: `PackagePublishingPocket` filter.
        :param exact_match: either or not filter source names by exact
                             matching.
        :param created_since_date: Only return publications created on or
            after this date.
        :param ordered: Normally publications are ordered by binary package
            name and then ID order (creation order).  If this parameter is
            False then the results will be unordered.  This will make the
            operation much quicker to return results if you don't care about
            ordering.
        :param order_by_date: Order publications by descending creation date
            and then by descending ID.  This is suitable for applications
            that need to catch up with publications since their last run.
        :param include_removed: If True, include publications that have been
            removed from disk as well as those that have not.
        :param only_unpublished: If True, only include publications that
            have never been published to disk.
        :param component_name: component filter. Only return binaries that are
            in this component.

        :return: A collection containing `BinaryPackagePublishingHistory`.
        """

    def getFileByName(filename):
        """Return the corresponding `ILibraryFileAlias` in this context.

        The following file types (and extension) can be looked up in the
        archive context:

         * Source files: '.orig.tar.gz', 'tar.gz', '.diff.gz' and '.dsc';
         * Binary files: '.deb' and '.udeb';
         * Source changesfile: '_source.changes';
         * Package diffs: '.diff.gz';

        :param filename: exactly filename to be looked up.

        :raises AssertionError if the given filename contains a unsupported
            filename and/or extension, see the list above.
        :raises NotFoundError if no file could not be found.

        :return the corresponding `ILibraryFileAlias` is the file was found.
        """

    def getSourceFileByName(name, version, filename):
        """Return the `ILibraryFileAlias` for a source name/version/filename.

        This can be used to avoid ambiguities with `getFileByName` in
        imported archives, where the upstream archive software may not
        always have had robust historical filename uniqueness checks.

        :param name: The name of the source package.
        :param version: The version of the source package.
        :param filename: The exact filename to look up.

        :raises NotFoundError: if no matching file could be found.
        :return: the corresponding `ILibraryFileAlias`.
        """

    def getPoolFileByPath(
        path: PurePath, live_at: typing.Optional[datetime] = None
    ):
        """Return the `ILibraryFileAlias` for a path in this archive's pool.

        :param path: A `PurePath` for where a source or binary package file
            is published in this archive's pool, e.g.
            "pool/main/p/package/package_1.dsc".
        :param live_at: If not None, return only files that existed in the
            archive at this `datetime`.
        :return: An `ILibraryFileAlias`, or None.
        """


class IArchiveView(IHasBuildRecords):
    """Archive interface for operations restricted by view privilege."""

    title = TextLine(title=_("Name"), required=False, readonly=True)

    require_virtualized = exported(
        Bool(
            title=_("Require virtualized builders"),
            required=False,
            readonly=False,
            description=_(
                "Only build the archive's packages on virtual builders."
            ),
        )
    )

    build_debug_symbols = exported(
        Bool(
            title=_("Build debug symbols"),
            required=False,
            readonly=False,
            description=_(
                "Create debug symbol packages for builds in the archive."
            ),
        ),
        as_of="devel",
    )
    publish_debug_symbols = exported(
        Bool(
            title=_("Publish debug symbols"),
            required=False,
            readonly=False,
            description=_(
                "Publish debug symbol packages in the apt repository."
            ),
        ),
        as_of="devel",
    )

    permit_obsolete_series_uploads = exported(
        Bool(
            title=_("Permit uploads to obsolete series"),
            required=False,
            readonly=False,
            description=_("Allow uploads targeted to obsolete series."),
        ),
        as_of="devel",
    )

    authorized_size = exported(
        Int(
            title=_("Authorized size"),
            required=False,
            max=2**31 - 1,
            description=_("Maximum size, in MiB, allowed for the archive."),
        )
    )

    purpose = Int(title=_("Purpose of archive."), required=True, readonly=True)

    status = exported(
        Int(title=_("Status of archive."), required=True, readonly=True),
        as_of="devel",
    )

    sources_cached = Int(
        title=_("Number of sources cached"),
        required=False,
        description=_("Number of source packages cached in this PPA."),
    )

    binaries_cached = Int(
        title=_("Number of binaries cached"),
        required=False,
        description=_("Number of binary packages cached in this PPA."),
    )

    package_description_cache = Attribute(
        "Concatenation of the source and binary packages published in this "
        "archive. Its content is used for indexed searches across archives."
    )

    default_component = Reference(
        IComponent,
        title=_(
            "The default component for this archive. Publications without a "
            "valid component will be assigned this one."
        ),
    )

    number_of_sources = Attribute(
        "The number of sources published in the context archive."
    )
    number_of_binaries = Attribute(
        "The number of binaries published in the context archive."
    )
    sources_size = Attribute(
        "The size of sources published in the context archive."
    )
    binaries_size = Attribute(
        "The size of binaries published in the context archive."
    )
    estimated_size = Attribute("Estimated archive size.")

    total_count = Int(
        title=_("Total number of builds in archive"),
        required=True,
        default=0,
        description=_(
            "The total number of builds in this archive. "
            "This counter does not include discontinued "
            "(superseded, cancelled, obsoleted) builds"
        ),
    )

    pending_count = Int(
        title=_("Number of pending builds in archive"),
        required=True,
        default=0,
        description=_("The number of pending builds in this archive."),
    )

    succeeded_count = Int(
        title=_("Number of successful builds in archive"),
        required=True,
        default=0,
        description=_("The number of successful builds in this archive."),
    )

    building_count = Int(
        title=_("Number of active builds in archive"),
        required=True,
        default=0,
        description=_("The number of active builds in this archive."),
    )

    failed_count = Int(
        title=_("Number of failed builds in archive"),
        required=True,
        default=0,
        description=_("The number of failed builds in this archive."),
    )

    date_created = Datetime(
        title=_("Date created"),
        required=False,
        readonly=True,
        description=_("The time when the archive was created."),
    )

    external_dependencies = exported(
        Text(
            title=_("External dependencies"),
            required=False,
            readonly=False,
            description=_(
                "Newline-separated list of repositories to be used to "
                "retrieve any external build-dependencies when building "
                "packages in the archive, in the format:\n"
                "deb http[s]://[user:pass@]<host>[/path] %(series)s[-pocket] "
                "[components]\n"
                "The series variable is replaced with the series name of the "
                "context build.\n"
                "NOTE: This is for migration of OEM PPAs only!"
            ),
        )
    )

    dirty_suites = Attribute(
        "Suites that the next publisher run should publish regardless of "
        "pending publications."
    )

    metadata_overrides = exported(
        Dict(
            title=_(
                "A JSON object containing metadata overrides for this archive."
            ),
            description=_(
                "Accepted keys are `Origin`, `Label`, `Suite` and `Snapshots`."
                "The values for all these keys should be a string and can use "
                "a `{series}` placeholder, which will get substituted by the "
                "name of the series that is currently being published."
            ),
            key_type=TextLine(),
            required=False,
            readonly=True,
        ),
        as_of="devel",
    )

    processors = exported(
        CollectionField(
            title=_("Processors"),
            description=_("The architectures on which the archive can build."),
            value_type=Reference(schema=IProcessor),
            readonly=True,
        ),
        as_of="devel",
    )

    enabled_restricted_processors = exported(
        CollectionField(
            title=_("Enabled restricted processors"),
            description=_("DEPRECATED. Use processors instead."),
            value_type=Reference(schema=IProcessor),
            readonly=True,
        ),
        as_of="devel",
    )

    available_processors = Attribute(
        "The architectures that are available to be enabled or disabled for "
        "this archive."
    )

    # XXX jugmac00 2023-02-13: Move to IArchiveRestricted
    # see https://code.launchpad.net/~jugmac00/launchpad/+git/launchpad/+merge/437207  # noqa: E501
    publishing_method = exported(
        Choice(
            title=_("Publishing method"),
            vocabulary=ArchivePublishingMethod,
            required=True,
            readonly=False,
        )
    )

    repository_format = exported(
        Choice(
            title=_("Repository format"),
            vocabulary=ArchiveRepositoryFormat,
            required=True,
            readonly=False,
        )
    )

    api_publish = exported(
        Bool(
            title=_("Publishing enabled"),
            required=True,
            readonly=False,
            description=_(
                "Whether or not to update the apt repository.  If "
                "disabled, nothing will be published.  If the archive "
                "is private then additionally no builds will "
                "be dispatched."
            ),
        ),
        exported_as="publish",
    )

    @call_with(check_permissions=True, user=REQUEST_USER)
    @operation_parameters(
        processors=List(
            value_type=Reference(schema=IProcessor), required=True
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def setProcessors(processors, check_permissions=False, user=None):
        """Set the architectures on which the archive can build."""

    def getSourcesForDeletion(name=None, status=None, distroseries=None):
        """All `ISourcePackagePublishingHistory` available for deletion.

        :param: name: optional source name filter (SQL LIKE)
        :param: status: `PackagePublishingStatus` filter, can be a sequence.
        :param: distroseries: `IDistroSeries` filter.

        :return: SelectResults containing `ISourcePackagePublishingHistory`.
        """

    def getPublishedOnDiskBinaries(
        name=None,
        version=None,
        status=None,
        distroarchseries=None,
        exact_match=False,
    ):
        """Unique `IBinaryPackagePublishingHistory` target to this archive.

        In spite of getAllPublishedBinaries method, this method only returns
        distinct binary publications inside this Archive, i.e, it excludes
        architecture-independent publication for other architectures than the
        nominatedarchindep. In few words it represents the binary files
        published in the archive disk pool.

        :param: name: binary name filter (exact match or SQL LIKE controlled
                      by 'exact_match' argument).
        :param: version: binary version filter (always exact match).
        :param: status: `PackagePublishingStatus` filter, can be a list.
        :param: distroarchseries: `IDistroArchSeries` filter, can be a list.
        :param: pocket: `PackagePublishingPocket` filter.
        :param: exact_match: either or not filter source names by exact
                             matching.

        :return: SelectResults containing `IBinaryPackagePublishingHistory`.
        """

    def allowUpdatesToReleasePocket():
        """Return whether the archive allows publishing to the release pocket.

        If a distroseries is stable, normally release pocket publishings are
        not allowed.  However some archive types allow this.

        :return: True or False
        """

    def getComponentsForSeries(distroseries):
        """Calculate the components available for use in this archive.

        :return: An `IResultSet` of `IComponent` objects.
        """

    def updateArchiveCache():
        """Concentrate cached information about the archive contents.

        Group the relevant package information (source name, binary names,
        binary summaries and distroseries with binaries) strings in the
        IArchive.package_description_cache search indexes (fti).

        Updates 'sources_cached' and 'binaries_cached' counters.

        Also include owner 'name' and 'displayname' to avoid inspecting the
        Person table indexes while searching.
        """

    def findDepCandidates(
        distro_arch_series, pocket, component, source_package_name, dep_name
    ):
        """Return matching binaries in this archive and its dependencies.

        Return all published `IBinaryPackagePublishingHistory` records with
        the given name, in this archive and dependencies as specified by the
        given build context, using the usual archive dependency rules.

        We can't just use the first, since there may be other versions
        published in other dependency archives.

        :param distro_arch_series: the context `IDistroArchSeries`.
        :param pocket: the context `PackagePublishingPocket`.
        :param component: the context `IComponent`.
        :param source_package_name: the context source package name (as text).
        :param dep_name: the name of the binary package to look up.
        :return: a sequence of matching `IBinaryPackagePublishingHistory`
            records.
        """

    def getPermissions(person, item, perm_type):
        """Get the `IArchivePermission` record with the supplied details.

        :param person: An `IPerson`
        :param item: An `IComponent`, `ISourcePackageName`
        :param perm_type: An ArchivePermissionType enum,
        :return: An `IResultSet` of `IArchivePermission` records.
        """

    def canUploadSuiteSourcePackage(person, suitesourcepackage):
        """Check if 'person' upload 'suitesourcepackage' to 'archive'.

        :param person: An `IPerson` who might be uploading.
        :param suitesourcepackage: An `ISuiteSourcePackage` to be uploaded.
        :return: True if they can, False if they cannot.
        """

    def canModifySuite(distroseries, pocket):
        """Decides whether or not to allow uploads for a given DS/pocket.

        Some archive types (e.g. PPAs) allow uploads to the RELEASE pocket
        regardless of the distroseries state.  For others (principally
        primary archives), only allow uploads for RELEASE pocket in
        unreleased distroseries, and conversely only allow uploads for
        non-RELEASE pockets in released distroseries.
        For instance, in edgy time :

                warty         -> DENY
                edgy          -> ALLOW
                warty-updates -> ALLOW
                edgy-security -> DENY

        Note that FROZEN is not considered either 'stable' or 'unstable'
        state.  Uploads to a FROZEN distroseries will end up in the
        UNAPPROVED queue.

        Return True if the upload is allowed and False if denied.
        """

    def checkUploadToPocket(distroseries, pocket, person=None):
        """Check if an upload to a particular archive and pocket is possible.

        :param distroseries: A `IDistroSeries`
        :param pocket: A `PackagePublishingPocket`
        :param person: Check for redirected pockets if this person is not a
            queue admin.
        :return: Reason why uploading is not possible or None
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        distroseries=Reference(
            IDistroSeries, title=_("The distro series"), required=True
        ),
        sourcepackagename=TextLine(
            title=_("Source package name"), required=True
        ),
        component=TextLine(title=_("Component"), required=True),
        pocket=Choice(
            title=_("Pocket"),
            description=_("The pocket into which this entry is published"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
        strict_component=Bool(title=_("Strict component"), required=False),
    )
    @export_operation_as("checkUpload")
    @export_read_operation()
    @operation_for_version("beta")
    def _checkUpload(
        person,
        distroseries,
        sourcepackagename,
        component,
        pocket,
        strict_component=True,
    ):
        """Wrapper around checkUpload for the web service API."""

    def checkUpload(
        person,
        distroseries,
        sourcepackagename,
        component,
        pocket,
        strict_component=True,
    ):
        """Check if 'person' upload 'suitesourcepackage' to 'archive'.

        :param person: An `IPerson` who might be uploading.
        :param distroseries: The `IDistroSeries` being uploaded to.
        :param sourcepackagename: The `ISourcePackageName` being uploaded.
        :param component: The `Component` being uploaded to.
        :param pocket: The `PackagePublishingPocket` of 'distroseries' being
            uploaded to.
        :param strict_component: True if access to the specific component for
            the package is needed to upload to it. If False, then access to
            any component will do.
        :return: The reason for not being able to upload, None otherwise.
        """

    def verifyUpload(
        person,
        sourcepackagename,
        component,
        distroseries,
        strict_component=True,
        pocket=None,
    ):
        """Can 'person' upload 'sourcepackagename' to this archive ?

        :param person: The `IPerson` trying to upload to the package. Referred
            to as 'the signer' in upload code.
        :param sourcepackagename: The source package being uploaded. None if
            the package is new.
        :param archive: The `IArchive` being uploaded to.
        :param component: The `IComponent` that the source package belongs to.
        :param distroseries: The upload's target distro series.
        :param strict_component: True if access to the specific component for
            the package is needed to upload to it. If False, then access to
            any component will do.
        :param pocket: The `PackagePublishingPocket` being uploaded to. If
            None, then pocket permissions are not checked.
        :return: CannotUploadToArchive if 'person' cannot upload to the
            archive,
            None otherwise.
        """

    def canAdministerQueue(
        person, components=None, pocket=None, distroseries=None
    ):
        """Check to see if person is allowed to administer queue items.

        :param person: An `IPerson` who should be checked for authentication.
        :param components: The context `IComponent`(s) for the check.
        :param pocket: The context `PackagePublishingPocket` for the check.
        :param distroseries: The context `IDistroSeries` for the check.

        :return: True if 'person' is allowed to administer the package upload
        queue for all given 'components', or for the given 'pocket'
        (optionally restricted to a single 'distroseries').  If 'components'
        is empty or None and 'pocket' is None, check if 'person' has any
        queue admin permissions for this archive.
        """

    def getBinaryPackageRelease(name, version, archtag):
        """Find the specified `IBinaryPackageRelease` in the archive.

        :param name: The `IBinaryPackageName` of the package.
        :param version: The version of the package.
        :param archtag: The architecture tag of the package's build. 'all'
            will not work here -- 'i386' (the build DAS) must be used instead.

        :return The binary package release with the given name and version,
            or None if one does not exist or there is more than one.
        """

    def getBinaryPackageReleaseByFileName(filename):
        """Return the corresponding `IBinaryPackageRelease` in this context.

        :param filename: The filename to look up.
        :return: The `IBinaryPackageRelease` with the specified filename,
            or None if it was not found.
        """

    def requestPackageCopy(
        target_location,
        requestor,
        suite=None,
        copy_binaries=False,
        reason=None,
    ):
        """Return a new `PackageCopyRequest` for this archive.

        :param target_location: the archive location to which the packages
            are to be copied.
        :param requestor: The `IPerson` who is requesting the package copy
            operation.
        :param suite: The `IDistroSeries` name with optional pocket, for
            example, 'hoary-security'. If this is not provided it will
            default to the current series' release pocket.
        :param copy_binaries: Whether or not binary packages should be copied
            as well.
        :param reason: The reason for this package copy request.

        :raises NotFoundError: if the provided suite is not found for this
            archive's distribution.

        :return The new `IPackageCopyRequest`
        """

    @operation_parameters(
        # Really IPackageset, patched in lp.soyuz.interfaces.webservice.
        packageset=Reference(Interface, title=_("Package set"), required=True),
        direct_permissions=Bool(
            title=_("Ignore package set hierarchy"), required=False
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getUploadersForPackageset(packageset, direct_permissions=True):
        """The `ArchivePermission` records for uploaders to the package set.

        :param packageset: An `IPackageset`.
        :param direct_permissions: If True, only consider permissions granted
            directly for the package set at hand. Otherwise, include any
            uploaders for package sets that include this one.

        :return: `ArchivePermission` records for all the uploaders who are
            authorized to upload to the named source package set.
        """

    @operation_parameters(person=Reference(schema=IPerson))
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getPackagesetsForUploader(person):
        """The `ArchivePermission` records for the person's package sets.

        :param person: An `IPerson` for whom you want to find out which
            package sets they have access to.

        :return: `ArchivePermission` records for all the package sets that
            'person' is allowed to upload to.
        """

    def getComponentsForUploader(person):
        """Return the components that 'person' can upload to this archive.

        :param person: An `IPerson` wishing to upload to an archive.
        :return: A `set` of `IComponent`s that 'person' can upload to.
        """

    @operation_parameters(person=Reference(schema=IPerson))
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getPocketsForUploader(person):
        """Return the pockets that 'person' can upload to this archive.

        :param person: An `IPerson` wishing to upload to an archive.
        :return: A `set` of `PackagePublishingPocket` items that 'person'
            can upload to.
        """

    @operation_parameters(
        sourcepackagename=TextLine(
            title=_("Source package name"), required=True
        ),
        person=Reference(schema=IPerson),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getPackagesetsForSourceUploader(sourcepackagename, person):
        """The package set based permissions for a given source and uploader.

        Return the `IArchivePermission` records that
            * apply to this archive
            * relate to
                - package sets that include the given source package name
                - the given `person`

        :param sourcepackagename: the source package name; can be
            either a string or a `ISourcePackageName`.
        :param person: An `IPerson` for whom you want to find out which
            package sets they have access to.

        :raises NoSuchSourcePackageName: if a source package with the
            given name could not be found.
        :return: `ArchivePermission` records for the package sets that
            include the given source package name and to which the given
            person may upload.
        """

    @operation_parameters(
        sourcepackagename=TextLine(
            title=_("Source package name"), required=True
        ),
        direct_permissions=Bool(
            title=_("Ignore package set hierarchy"), required=False
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getPackagesetsForSource(sourcepackagename, direct_permissions=True):
        """All package set based permissions for the given source.

        This method is meant to aid the process of "debugging" package set
        based archive permission since It allows the listing of permissions
        for the given source package in this archive (irrespective of the
        principal).

        :param sourcepackagename: the source package name; can be
            either a string or a `ISourcePackageName`.
        :param direct_permissions: If set only package sets that directly
            include the given source will be considered.

        :raises NoSuchSourcePackageName: if a source package with the
            given name could not be found.
        :return: `ArchivePermission` records for the package sets that
            include the given source package name and apply to the
            archive in question.
        """

    @operation_parameters(
        sourcepackagename=TextLine(
            title=_("Source package name"), required=True
        ),
        person=Reference(schema=IPerson),
        distroseries=Reference(
            IDistroSeries, title=_("The distro series"), required=False
        ),
    )
    @export_read_operation()
    @operation_for_version("beta")
    def isSourceUploadAllowed(sourcepackagename, person, distroseries=None):
        """True if the person is allowed to upload the given source package.

        Return True if there exists a permission that combines
            * this archive
            * a package set that includes the given source package name
            * the given person or a team they are a member of

        If the source package name is included by *any* package set with
        an explicit permission then only such explicit permissions will
        be considered.

        :param sourcepackagename: the source package name; can be
            either a string or a `ISourcePackageName`.
        :param person: An `IPerson` for whom you want to find out which
            package sets they have access to.
        :param distroseries: The `IDistroSeries` for which to check
            permissions. If none is supplied then `currentseries` in
            the archive's distribution is assumed.

        :raises NoSuchSourcePackageName: if a source package with the
            given name could not be found.
        :return: True if the person is allowed to upload the source package.
        """

    def updatePackageDownloadCount(bpr, day, country, count):
        """Update the daily download count for a given package.

        :param bpr: The `IBinaryPackageRelease` to update the count for.
        :param day: The date to update the count for.
        :param country: The `ICountry` to update the count for.
        :param count: The new download count.

        If there's no matching `IBinaryPackageReleaseDownloadCount` entry,
        we create one with the given count.  Otherwise we just increase the
        count of the existing one by the given amount.
        """

    def getPackageDownloadTotal(bpr):
        """Get the total download count for a given package."""

    def getPockets():
        """Return iterable containing valid pocket names for this archive."""

    def getOverridePolicy(distroseries, pocket, phased_update_percentage=None):
        """Returns an instantiated `IOverridePolicy` for the archive."""

    @operation_parameters(
        include_needsbuild=Bool(
            title=_("Include builds with state NEEDSBUILD"), required=False
        )
    )
    @export_read_operation()
    @operation_for_version("beta")
    def getBuildCounters(include_needsbuild=True):
        """Return a dictionary containing the build counters for an archive.

        This is necessary currently because the IArchive.failed_builds etc.
        counters are not in use.

        The returned dictionary contains the following keys and values:

         * 'total': total number of builds (includes SUPERSEDED);
         * 'pending': number of builds in BUILDING or NEEDSBUILD state;
         * 'failed': number of builds in FAILEDTOBUILD, MANUALDEPWAIT,
           CHROOTWAIT and FAILEDTOUPLOAD state;
         * 'succeeded': number of SUCCESSFULLYBUILT builds.
         * 'superseded': number of SUPERSEDED builds.

        :param include_needsbuild: Indicates whether to include builds with
            the status NEEDSBUILD in the pending and total counts. This is
            useful in situations where a build that hasn't started isn't
            considered a build by the user.
        :type include_needsbuild: ``bool``
        :return: a dictionary with the 4 keys specified above.
        :rtype: ``dict``.
        """

    @operation_parameters(
        source_ids=List(
            title=_("A list of source publishing history record ids."),
            value_type=Int(),
        )
    )
    @export_read_operation()
    @operation_for_version("beta")
    def getBuildSummariesForSourceIds(source_ids):
        """Return a dictionary containing a summary of the build statuses.

        Only information for sources belonging to the current archive will
        be returned. See
        `IPublishingSet`.getBuildStatusSummariesForSourceIdsAndArchive() for
        details.

        :param source_ids: A list of source publishing history record ids.
        :type source_ids: ``list``
        :return: A dict consisting of the overall status summaries for the
            given ids that belong in the archive.
        """

    @operation_parameters(
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        dependency=Reference(schema=Interface)
    )
    # Really IArchiveDependency, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_entry(schema=Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getArchiveDependency(dependency):
        """Return the `IArchiveDependency` object for the given dependency.

        :param dependency: is an `IArchive` object.

        :return: `IArchiveDependency` or None if a corresponding object
            could not be found.
        """

    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getAllPermissions():
        """Return all `IArchivePermission` records for this archive.

        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(person=Reference(schema=IPerson))
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getPermissionsForPerson(person):
        """Return the `IArchivePermission` records applicable to the person.

        :param person: An `IPerson`
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(
        source_package_name=TextLine(
            title=_("Source Package Name"), required=True
        )
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getUploadersForPackage(source_package_name):
        """Return `IArchivePermission` records for the package's uploaders.

        :param source_package_name: An `ISourcePackageName` or textual name
            for the source package.
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(
        component_name=TextLine(title=_("Component Name"), required=False)
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getUploadersForComponent(component_name=None):
        """Return `IArchivePermission` records for the component's uploaders.

        :param component_name: An `IComponent` or textual name for the
            component.
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(
        component_name=TextLine(title=_("Component Name"), required=True)
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getQueueAdminsForComponent(component_name):
        """Return `IArchivePermission` records for authorized queue admins.

        :param component_name: An `IComponent` or textual name for the
            component.
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(person=Reference(schema=IPerson))
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("beta")
    def getComponentsForQueueAdmin(person):
        """Return `IArchivePermission` for the person's queue admin
        components.

        :param person: An `IPerson`.
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getUploadersForPocket(pocket):
        """Return `IArchivePermission` records for the pocket's uploaders.

        :param pocket: A `PackagePublishingPocket`.
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
        distroseries=Reference(
            IDistroSeries, title=_("Distro series"), required=False
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getQueueAdminsForPocket(pocket, distroseries=None):
        """Return `IArchivePermission` records for authorized queue admins.

        :param pocket: A `PackagePublishingPocket`.
        :param distroseries: An optional `IDistroSeries`.
        :return: A list of `IArchivePermission` records.
        """

    @operation_parameters(person=Reference(schema=IPerson))
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @operation_returns_collection_of(Interface)
    @export_read_operation()
    @operation_for_version("devel")
    def getPocketsForQueueAdmin(person):
        """Return `IArchivePermission` for the person's queue admin pockets.

        :param person: An `IPerson`.
        :return: A list of `IArchivePermission` records.
        """

    def hasAnyPermission(person):
        """Whether or not this person has any permission at all on this
        archive.

        :param person: The `IPerson` for whom the check is performed.
        :return: A boolean indicating if the person has any permission on this
            archive at all.
        """

    def getPackageDownloadCount(bpr, day, country):
        """Get the `IBinaryPackageDownloadCount` with the given key."""

    def getFilesAndSha1s(source_files):
        """Return a dictionary with the filenames and the SHA1s for each
        source file.

        :param source_files: A list of filenames to return SHA1s of
        :return: A dictionary of filenames and SHA1s.
        """

    @call_with(person=REQUEST_USER)
    @operation_parameters(
        source_name=TextLine(title=_("Source package name")),
        version=TextLine(title=_("Version")),
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        from_archive=Reference(schema=Interface),
        to_pocket=TextLine(title=_("Target pocket name")),
        to_series=TextLine(
            title=_("Target distroseries name"), required=False
        ),
        include_binaries=Bool(
            title=_("Include Binaries"),
            description=_(
                "Whether or not to copy binaries already built for"
                " this source"
            ),
            required=False,
        ),
        sponsored=Reference(
            schema=IPerson,
            title=_("Sponsored Person"),
            description=_("The person who is being sponsored for this copy."),
        ),
        unembargo=Bool(title=_("Unembargo restricted files")),
        auto_approve=Bool(
            title=_("Automatic approval"),
            description=_(
                "Automatically approve this copy (queue admins " "only)."
            ),
            required=False,
        ),
        silent=Bool(
            title=_("Silent"),
            description=_(
                "Don't notify anyone about this copy. For use by queue "
                "admins only."
            ),
            required=False,
        ),
        from_pocket=TextLine(title=_("Source pocket name"), required=False),
        from_series=TextLine(
            title=_("Source distroseries name"), required=False
        ),
        phased_update_percentage=Int(
            title=_("Phased update percentage"),
            description=_(
                "The percentage of users for whom this package"
                " should be recommended, or None to publish the"
                " update for everyone."
            ),
            required=False,
        ),
        move=Bool(
            title=_("Move"),
            description=_(
                "If true, delete the source publication after copying it to "
                "the destination."
            ),
            required=False,
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def copyPackage(
        source_name,
        version,
        from_archive,
        to_pocket,
        person,
        to_series=None,
        include_binaries=False,
        sponsored=None,
        unembargo=False,
        auto_approve=False,
        silent=False,
        from_pocket=None,
        from_series=None,
        phased_update_percentage=None,
        move=False,
    ):
        """Copy a single named source into this archive.

        Asynchronously copy a specific version of a named source to the
        destination archive if necessary.  Calls to this method will return
        immediately if the copy passes basic security checks and the copy
        will happen sometime later with full checking.

        If the source or target distribution has a development series alias,
        then it may be used as the source or target distroseries name
        respectively; but note that this will always be resolved to the true
        development series of that distribution, which may not match the
        alias in the respective published archives.

        :param source_name: a string name of the package to copy.
        :param version: the version of the package to copy.
        :param from_archive: the source archive from which to copy.
        :param to_pocket: the target pocket (as a string).
        :param to_series: the target distroseries (as a string).
        :param include_binaries: optional boolean, controls whether or not
            the published binaries for each given source should also be
            copied along with the source.
        :param person: the `IPerson` who requests the sync.
        :param sponsored: the `IPerson` who is being sponsored. Specifying
            this will ensure that the person's email address is used as the
            "From:" on the announcement email and will also be recorded as
            the creator of the new source publication.
        :param unembargo: if True, allow copying restricted files from a
            private archive to a public archive, and re-upload them to the
            public librarian when doing so.
        :param auto_approve: if True and the `IPerson` requesting the sync
            has queue admin permissions on the target, accept the copy
            immediately rather than setting it to unapproved.
        :param silent: Suppress any emails that the copy would generate.
            Only usable with queue admin permissions on the target.
        :param from_pocket: the source pocket (as a string). If omitted,
            copy from any pocket with a matching version.
        :param from_series: the source distroseries (as a string). If
            omitted, copy from any series with a matching version.
        :param phased_update_percentage: the phased update percentage to
            apply to the copied publication.
        :param move: if True, delete the source publication after copying it
            to the destination.

        :raises NoSuchSourcePackageName: if the source name is invalid
        :raises PocketNotFound: if the pocket name is invalid
        :raises NoSuchDistroSeries: if the distro series name is invalid
        :raises CannotCopy: if there is a problem copying.
        """

    @call_with(person=REQUEST_USER)
    @operation_parameters(
        source_names=List(
            title=_("Source package names"), value_type=TextLine()
        ),
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        from_archive=Reference(schema=Interface),
        to_pocket=TextLine(title=_("Pocket name")),
        to_series=TextLine(
            title=_("Distroseries name"),
            description=_("The distro series to copy packages into."),
            required=False,
        ),
        from_series=TextLine(
            title=_("Distroseries name"),
            description=_("The distro series to copy packages from."),
            required=False,
        ),
        include_binaries=Bool(
            title=_("Include Binaries"),
            description=_(
                "Whether or not to copy binaries already built for"
                " this source"
            ),
            required=False,
        ),
        sponsored=Reference(
            schema=IPerson,
            title=_("Sponsored Person"),
            description=_("The person who is being sponsored for this copy."),
        ),
        unembargo=Bool(title=_("Unembargo restricted files")),
        auto_approve=Bool(
            title=_("Automatic approval"),
            description=_(
                "Automatically approve this copy (queue admins " "only)."
            ),
            required=False,
        ),
        silent=Bool(
            title=_("Silent"),
            description=_(
                "Don't notify anyone about this copy. For use by queue "
                "admins only."
            ),
            required=False,
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def copyPackages(
        source_names,
        from_archive,
        to_pocket,
        person,
        to_series=None,
        from_series=None,
        include_binaries=False,
        sponsored=None,
        unembargo=False,
        auto_approve=False,
        silent=False,
    ):
        """Copy multiple named sources into this archive from another.

        Asynchronously copy the most recent PUBLISHED versions of the named
        sources to the destination archive if necessary.  Calls to this
        method will return immediately if the copy passes basic security
        checks and the copy will happen sometime later with full checking.

        Partial changes of the destination archive can happen because each
        source is copied in its own transaction.

        If the source or target distribution has a development series alias,
        then it may be used as the source or target distroseries name
        respectively; but note that this will always be resolved to the true
        development series of that distribution, which may not match the
        alias in the respective published archives.

        :param source_names: a list of string names of packages to copy.
        :param from_archive: the source archive from which to copy.
        :param to_pocket: the target pocket (as a string).
        :param to_series: the target distroseries (as a string).
        :param from_series: the source distroseries (as a string).
        :param include_binaries: optional boolean, controls whether or not
            the published binaries for each given source should also be
            copied along with the source.
        :param person: the `IPerson` who requests the sync.
        :param sponsored: the `IPerson` who is being sponsored. Specifying
            this will ensure that the person's email address is used as the
            "From:" on the announcement email and will also be recorded as
            the creator of the new source publication.
        :param unembargo: if True, allow copying restricted files from a
            private archive to a public archive, and re-upload them to the
            public librarian when doing so.
        :param auto_approve: if True and the `IPerson` requesting the sync
            has queue admin permissions on the target, accept the copies
            immediately rather than setting it to unapproved.
        :param silent: Suppress any emails that the copy would generate.
            Only usable with queue admin permissions on the target.

        :raises NoSuchSourcePackageName: if the source name is invalid
        :raises PocketNotFound: if the pocket name is invalid
        :raises NoSuchDistroSeries: if the distro series name is invalid
        :raises CannotCopy: if there is a problem copying.
        """

    @call_with(person=REQUEST_USER)
    @operation_parameters(
        # Really ICIBuild, patched in lp.soyuz.interfaces.webservice.
        ci_build=Reference(schema=Interface),
        to_series=TextLine(title=_("Target distroseries name")),
        to_pocket=TextLine(title=_("Target pocket name")),
        to_channel=TextLine(title=_("Target channel"), required=False),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def uploadCIBuild(ci_build, person, to_series, to_pocket, to_channel=None):
        """Upload the output of a CI build to this archive."""


class IArchiveAppend(Interface):
    """Archive interface for operations restricted by append privilege."""

    @call_with(person=REQUEST_USER)
    @operation_parameters(
        source_names=List(
            title=_("Source package names"), value_type=TextLine()
        ),
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        from_archive=Reference(schema=Interface),
        to_pocket=TextLine(title=_("Pocket name")),
        to_series=TextLine(
            title=_("Distroseries name"),
            description=_("The distro series to copy packages into."),
            required=False,
        ),
        from_series=TextLine(
            title=_("Distroseries name"),
            description=_("The distro series to copy packages from."),
            required=False,
        ),
        include_binaries=Bool(
            title=_("Include Binaries"),
            description=_(
                "Whether or not to copy binaries already built for"
                " this source"
            ),
            required=False,
        ),
    )
    @export_write_operation()
    @operation_for_version("beta")
    # Source_names is a string because exporting a SourcePackageName is
    # rather nonsensical as it only has id and name columns.
    def syncSources(
        source_names,
        from_archive,
        to_pocket,
        to_series=None,
        from_series=None,
        include_binaries=False,
        person=None,
    ):
        """Synchronise (copy) named sources into this archive from another.

        DEPRECATED: syncSource and syncSources are deprecated, and will
        be removed entirely in the future. Use the asynchronous
        copyPackage method instead, and poll getPublishedSources if you
        need to await completion.

        It will copy the most recent PUBLISHED versions of the named
        sources to the destination archive if necessary.

        This operation will only succeeds when all requested packages
        are synchronised between the archives. If any of the requested
        copies cannot be performed, the whole operation will fail. There
        will be no partial changes of the destination archive.

        If the source or target distribution has a development series alias,
        then it may be used as the source or target distroseries name
        respectively; but note that this will always be resolved to the true
        development series of that distribution, which may not match the
        alias in the respective published archives.

        :param source_names: a list of string names of packages to copy.
        :param from_archive: the source archive from which to copy.
        :param to_pocket: the target pocket (as a string).
        :param to_series: the target distroseries (as a string).
        :param from_series: the source distroseries (as a string).
        :param include_binaries: optional boolean, controls whether or not
            the published binaries for each given source should also be
            copied along with the source.
        :param person: the `IPerson` who requests the sync.

        :raises NoSuchSourcePackageName: if the source name is invalid
        :raises PocketNotFound: if the pocket name is invalid
        :raises NoSuchDistroSeries: if the distro series name is invalid
        :raises CannotCopy: if there is a problem copying.
        """

    @call_with(person=REQUEST_USER)
    @operation_parameters(
        source_name=TextLine(title=_("Source package name")),
        version=TextLine(title=_("Version")),
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        from_archive=Reference(schema=Interface),
        to_pocket=TextLine(title=_("Pocket name")),
        to_series=TextLine(title=_("Distroseries name"), required=False),
        include_binaries=Bool(
            title=_("Include Binaries"),
            description=_(
                "Whether or not to copy binaries already built for"
                " this source"
            ),
            required=False,
        ),
    )
    @export_write_operation()
    @operation_for_version("beta")
    # XXX Julian 2008-11-05
    # This method takes source_name and version as strings because
    # SourcePackageRelease is not exported on the API yet.  When it is,
    # we should consider either changing this method or adding a new one
    # that takes that object instead.
    def syncSource(
        source_name,
        version,
        from_archive,
        to_pocket,
        to_series=None,
        include_binaries=False,
        person=None,
    ):
        """Synchronise (copy) a single named source into this archive.

        DEPRECATED: syncSource and syncSources are deprecated, and will
        be removed entirely in the future. Use the asynchronous
        copyPackage method instead, and poll getPublishedSources if you
        need to await completion.

        Copy a specific version of a named source to the destination
        archive if necessary.

        If the source distribution has a development series alias, then it
        may be used as the source distroseries name; but note that this will
        always be resolved to the true development series of that
        distribution, which may not match the alias in the published source
        archive.

        :param source_name: a string name of the package to copy.
        :param version: the version of the package to copy.
        :param from_archive: the source archive from which to copy.
        :param to_pocket: the target pocket (as a string).
        :param to_series: the target distroseries (as a string).
        :param include_binaries: optional boolean, controls whether or not
            the published binaries for each given source should also be
            copied along with the source.
        :param person: the `IPerson` who requests the sync.

        :raises NoSuchSourcePackageName: if the source name is invalid
        :raises PocketNotFound: if the pocket name is invalid
        :raises NoSuchDistroSeries: if the distro series name is invalid
        :raises CannotCopy: if there is a problem copying.
        """

    @call_with(registrant=REQUEST_USER)
    @operation_parameters(
        subscriber=PublicPersonChoice(
            title=_("Subscriber"),
            required=True,
            vocabulary="ValidPersonOrTeam",
            description=_("The person who is subscribed."),
        ),
        date_expires=Datetime(
            title=_("Date of Expiration"),
            required=False,
            description=_(
                "The timestamp when the subscription will " "expire."
            ),
        ),
        description=Text(
            title=_("Description"),
            required=False,
            description=_("Free text describing this subscription."),
        ),
    )
    # Really IArchiveSubscriber, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("beta")
    def newSubscription(
        subscriber, registrant, date_expires=None, description=None
    ):
        """Create a new subscription to this archive.

        Create an `ArchiveSubscriber` record which allows an `IPerson` to
        access a private repository.

        :param subscriber: An `IPerson` who is allowed to access the
            repository for this archive.
        :param registrant: An `IPerson` who created this subscription.
        :param date_expires: When the subscription should expire; None if
            it should not expire (default).
        :param description: An option textual description of the subscription
            being created.

        :return: The `IArchiveSubscriber` that was created.
        """

    @operation_parameters(job_id=Int())
    @export_write_operation()
    @operation_for_version("devel")
    def removeCopyNotification(job_id):
        """Remove a copy notification that's displayed on the +packages page.

        Copy notifications are shown on the +packages page when a
        `PlainPackageCopyJob` is in progress or failed.  Calling this
        method will delete failed jobs so they no longer appear on the
        page.

        You need to have upload privileges on the PPA to use this.

        :param job_id: The ID of the `PlainPackageCopyJob` to be removed.
        """

    @operation_parameters(
        distroseries=Reference(
            IDistroSeries, title=_("Distro series"), required=True
        ),
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def markSuiteDirty(distroseries, pocket):
        """Mark a suite as dirty in this archive.

        The next publisher run will publish this suite regardless of whether
        it has any pending publications.

        :param distroseries: An `IDistroSeries`.
        :param pocket: A `PackagePublishingPocket`.
        """


class IArchiveEdit(Interface):
    """Archive interface for operations restricted by edit privilege."""

    @operation_parameters(
        person=Reference(schema=IPerson),
        source_package_name=TextLine(
            title=_("Source Package Name"), required=True
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("beta")
    def newPackageUploader(person, source_package_name):
        """Add permission for a person to upload a package to this archive.

        :param person: An `IPerson` whom should be given permission.
        :param source_package_name: An `ISourcePackageName` or textual package
            name.
        :return: An `IArchivePermission` which is the newly-created
            permission.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        component_name=TextLine(title=_("Component Name"), required=True),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("beta")
    def newComponentUploader(person, component_name):
        """Add permission for a person to upload to a component.

        :param person: An `IPerson` whom should be given permission.
        :param component: An `IComponent` or textual component name.
        :return: An `IArchivePermission` which is the newly-created
            permission.
        :raises InvalidComponent: if this archive is a PPA and the component
            is not 'main'.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("devel")
    def newPocketUploader(person, pocket):
        """Add permission for a person to upload to a pocket.

        :param person: An `IPerson` whom should be given permission.
        :param pocket: A `PackagePublishingPocket`.
        :return: An `IArchivePermission` which is the newly-created
            permission.
        :raises InvalidPocketForPartnerArchive: if this archive is a partner
            archive and the pocket is not RELEASE or PROPOSED.
        :raises InvalidPocketForPPA: if this archive is a PPA and the pocket
            is not RELEASE.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        component_name=TextLine(title=_("Component Name"), required=True),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("beta")
    def newQueueAdmin(person, component_name):
        """Add permission for a person to administer a distroseries queue.

        The supplied person will gain permission to administer the
        distroseries queue for packages in the supplied component.

        :param person: An `IPerson` whom should be given permission.
        :param component: An `IComponent` or textual component name.
        :return: An `IArchivePermission` which is the newly-created
            permission.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
        distroseries=Reference(
            IDistroSeries, title=_("Distro series"), required=True
        ),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("devel")
    def newPocketQueueAdmin(person, pocket, distroseries=None):
        """Add permission for a person to administer a distroseries queue.

        The supplied person will gain permission to administer the
        distroseries queue for packages in the supplied series and pocket.

        :param person: An `IPerson` whom should be given permission.
        :param pocket: A `PackagePublishingPocket`.
        :param distroseries: An optional `IDistroSeries`.
        :return: An `IArchivePermission` which is the newly-created
            permission.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        # Really IPackageset, patched in lp.soyuz.interfaces.webservice.
        packageset=Reference(Interface, title=_("Package set"), required=True),
        explicit=Bool(title=_("Explicit"), required=False),
    )
    # Really IArchivePermission, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("beta")
    def newPackagesetUploader(person, packageset, explicit=False):
        """Add a package set based permission for a person.

        :param person: An `IPerson` for whom you want to add permission.
        :param packageset: An `IPackageset`.
        :param explicit: True if the package set in question requires
            specialist skills for proper handling.

        :return: The new `ArchivePermission`, or the existing one if it
            already exists.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        source_package_name=TextLine(
            title=_("Source Package Name"), required=True
        ),
    )
    @export_write_operation()
    @operation_for_version("beta")
    def deletePackageUploader(person, source_package_name):
        """Revoke permission for the person to upload the package.

        :param person: An `IPerson` whose permission should be revoked.
        :param source_package_name: An `ISourcePackageName` or textual package
            name.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        component_name=TextLine(title=_("Component Name"), required=True),
    )
    @export_write_operation()
    @operation_for_version("beta")
    def deleteComponentUploader(person, component_name):
        """Revoke permission for the person to upload to the component.

        :param person: An `IPerson` whose permission should be revoked.
        :param component: An `IComponent` or textual component name.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def deletePocketUploader(person, pocket):
        """Revoke permission for the person to upload to the pocket.

        :param person: An `IPerson` whose permission should be revoked.
        :param distroseries: An `IDistroSeries`.
        :param pocket: A `PackagePublishingPocket`.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        component_name=TextLine(title=_("Component Name"), required=True),
    )
    @export_write_operation()
    @operation_for_version("beta")
    def deleteQueueAdmin(person, component_name):
        """Revoke permission for the person to administer distroseries queues.

        The supplied person will lose permission to administer the
        distroseries queue for packages in the supplied component.

        :param person: An `IPerson` whose permission should be revoked.
        :param component: An `IComponent` or textual component name.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        pocket=Choice(
            title=_("Pocket"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
        distroseries=Reference(
            IDistroSeries, title=_("Distro series"), required=True
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def deletePocketQueueAdmin(person, pocket, distroseries=None):
        """Revoke permission for the person to administer distroseries queues.

        The supplied person will lose permission to administer the
        distroseries queue for packages in the supplied series and pocket.

        :param person: An `IPerson` whose permission should be revoked.
        :param pocket: A `PackagePublishingPocket`.
        :param distroseries: An optional `IDistroSeries`.
        """

    @operation_parameters(
        person=Reference(schema=IPerson),
        # Really IPackageset, patched in lp.soyuz.interfaces.webservice.
        packageset=Reference(Interface, title=_("Package set"), required=True),
        explicit=Bool(title=_("Explicit"), required=False),
    )
    @export_write_operation()
    @operation_for_version("beta")
    def deletePackagesetUploader(person, packageset, explicit=False):
        """Revoke upload permissions for a person.

        :param person: An `IPerson` for whom you want to revoke permission.
        :param packageset: An `IPackageset`.
        :param explicit: The value of the 'explicit' flag for the permission
            to be revoked.
        """

    def enable():
        """Enable the archive."""

    def disable():
        """Disable the archive."""

    def addArchiveDependency(dependency, pocket, component=None):
        """Record an archive dependency record for the context archive.

        :param dependency: is an `IArchive` object.
        :param pocket: is an `PackagePublishingPocket` enum.
        :param component: is an optional `IComponent` object, if not given
            the archive dependency will be tied to the component used
            for a corresponding source in primary archive.

        :raise: `ArchiveDependencyError` if given 'dependency' does not fit
            the context archive.
        :return: a `IArchiveDependency` object targeted to the context
            `IArchive` requiring 'dependency' `IArchive`.
        """

    @operation_parameters(
        dependency=Reference(schema=Interface, required=True),
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        pocket=Choice(
            title=_("Pocket"),
            description=_("The pocket into which this entry is published"),
            vocabulary=PackagePublishingPocket,
            required=True,
        ),
        component=TextLine(title=_("Component"), required=False),
    )
    @export_operation_as("addArchiveDependency")
    # Really IArchive, patched in lp.soyuz.interfaces.webservice.
    @export_factory_operation(Interface, [])
    @operation_for_version("devel")
    def _addArchiveDependency(dependency, pocket, component=None):
        """Record an archive dependency record for the context archive.

        :param dependency: is an `IArchive` object.
        :param pocket: is an `PackagePublishingPocket` enum.
        :param component: is the name of a component.  If not given,
            the archive dependency will be tied to the component used
            for a corresponding source in primary archive.

        :raise: `ArchiveDependencyError` if given 'dependency' does not fit
            the context archive.
        :return: a `IArchiveDependency` object targeted to the context
            `IArchive` requiring 'dependency' `IArchive`.
        """

    @operation_parameters(
        # Really IArchive, patched in lp.soyuz.interfaces.webservice.
        dependency=Reference(schema=Interface, required=True),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def removeArchiveDependency(dependency):
        """Remove the `IArchiveDependency` record for the given dependency.

        :param dependency: is an `IArchive` object.
        """

    @call_with(as_dict=True)
    @operation_parameters(
        name=TextLine(title=_("Authorization token name"), required=True),
        token=TextLine(
            title=_("Optional secret for this named token"), required=False
        ),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def newNamedAuthToken(name, token=None, as_dict=False):
        """Create a new named authorization token.

        :param name: An identifier string for this token.
        :param token: Optional unicode text to use as the token. One will be
            generated if not given.
        :param as_dict: Optional boolean, controls whether the return value is
            a dictionary or a full object.

        :return: An `ArchiveAuthToken` object or a dictionary where the value
            of `token` is the secret and the value of `archive_url` is the
            externally-usable archive URL including basic auth.
        """

    @call_with(as_dict=True)
    @operation_parameters(
        names=List(
            title=_("Authorization token names"),
            value_type=TextLine(),
            required=True,
        )
    )
    @export_write_operation()
    @operation_for_version("devel")
    def newNamedAuthTokens(names, as_dict=False):
        """Create named authorization tokens in bulk.

        :param names: A list of token names.
        :param as_dict: Optional boolean, controls whether the return value is
            a list of dictionaries or a list of full objects.

        :return: A list of `ArchiveAuthToken` objects or a dictionary of
            {name: {token, archive_url} where `name` is a token name,
            `token` is the secret and `archive_url` is the externally-usable
            archive URL including basic auth.
        """

    @call_with(as_dict=True)
    @operation_parameters(
        name=TextLine(title=_("Authorization token name"), required=True)
    )
    @export_read_operation()
    @operation_for_version("devel")
    def getNamedAuthToken(name, as_dict=False):
        """Return a named authorization token for the given name in this
         archive.

        :param name: The identifier string for a token.
        :param as_dict: Optional boolean, controls whether the return value is
            a dictionary or a full object.

        :return: An `ArchiveAuthToken` object or a dictionary where the value
            of `token` is the secret and the value of `archive_url` is the
            externally-usable archive URL including basic auth.
        :raises NotFoundError: if no matching token could be found.
        """

    @call_with(as_dict=True)
    @operation_parameters(
        names=List(
            title=_("Authorization token names"),
            value_type=TextLine(),
            required=False,
        )
    )
    @export_read_operation()
    @operation_for_version("devel")
    def getNamedAuthTokens(names=None, as_dict=False):
        """Return a subset of active named authorization tokens for this
        archive if `names` is specified, or all active named authorization
        tokens for this archive is `names` is null.

        :param names: An optional list of token names.
        :param as_dict: Optional boolean, controls whether the return value is
            a list of dictionaries or a list of full objects.

        :return: A list of `ArchiveAuthToken` objects or a list of dictionaries
            where `token` is the secret and `archive_url` is the
            externally-usable archive URL including basic auth.
        """

    @operation_parameters(
        name=TextLine(title=_("Authorization token name"), required=True)
    )
    @export_write_operation()
    @operation_for_version("devel")
    def revokeNamedAuthToken(name):
        """Deactivate a named authorization token.

        :param name: The identifier string for a token.
        :raises NotFoundError: if no matching token could be found.
        """

    @operation_parameters(
        names=List(
            title=_("Authorization token names"),
            value_type=TextLine(),
            required=True,
        )
    )
    @export_write_operation()
    @operation_for_version("devel")
    def revokeNamedAuthTokens(names):
        """Deactivate named authorization tokens in bulk.

        :param names: A list of token names.
        """

    @mutator_for(IArchiveView["metadata_overrides"])
    @operation_parameters(
        metadata_overrides=copy_field(IArchiveView["metadata_overrides"]),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def setMetadataOverrides(metadata_overrides):
        """Set the metadata overrides for this archive.

        :param metadata_overrides: A JSON object containing metadata overrides
            for this archive.
        """


class IArchiveDelete(Interface):
    """Archive interface for operations restricted by delete privilege."""

    @export_destructor_operation()
    @call_with(deleted_by=REQUEST_USER)
    @operation_for_version("devel")
    def delete(deleted_by):
        """Delete this archive.

        :param deleted_by: The `IPerson` requesting the deletion.

        The ArchiveStatus will be set to DELETING and any published
        packages will be marked as DELETED by deleted_by.

        The publisher is responsible for deleting the repository area
        when it sees the status change and sets it to DELETED once
        processed.
        """


class IArchiveAdmin(Interface):
    """Archive interface for operations restricted by commercial."""

    @operation_parameters(
        processor=Reference(schema=IProcessor, required=True),
    )
    @export_write_operation()
    @operation_for_version("devel")
    def enableRestrictedProcessor(processor):
        """Add the processor to the set of enabled restricted processors.

        DEPRECATED. Use setProcessors instead.

        :param processor: is an `IProcessor` object.
        """


class IArchiveRestricted(Interface):
    """A writeable interface for restricted attributes of archives."""

    relative_build_score = exported(
        Int(
            title=_("Relative build score"),
            required=True,
            readonly=False,
            description=_(
                "A delta to apply to all build scores for the archive. Builds "
                "with a higher score will build sooner."
            ),
        )
    )


@exported_as_webservice_entry(as_of="beta")
class IArchive(
    IArchivePublic,
    IArchiveAppend,
    IArchiveEdit,
    IArchiveDelete,
    IArchiveSubscriberView,
    IArchiveView,
    IArchiveAdmin,
    IArchiveRestricted,
):
    """Main Archive interface."""


class IPPA(IArchive):
    """Marker interface so traversal works differently for PPAs."""


class IDistributionArchive(IArchive):
    """Marker interface so traversal works differently for distro archives."""


class IArchiveEditDependenciesForm(Interface):
    """Schema used to edit dependencies settings within a archive."""

    dependency_candidate = Choice(
        title=_("Add PPA dependency"), required=False, vocabulary="PPA"
    )


@exported_as_webservice_collection(IArchive)
class IArchiveSet(Interface):
    """Interface for ArchiveSet"""

    title = Attribute("Title")

    @collection_default_content()
    def empty_list():
        """There is no default content, but lazr.restful needs some anyway."""

    def new(
        purpose,
        owner,
        name=None,
        displayname=None,
        distribution=None,
        description=None,
        enabled=True,
        require_virtualized=True,
        private=False,
        suppress_subscription_notifications=False,
        processors=None,
        publishing_method=None,
        repository_format=None,
        metadata_overrides=None,
    ):
        """Create a new archive.

        On named-ppa creation, the signing key for the default PPA for the
        given owner will be used if it is present.

        :param purpose: `ArchivePurpose`;
        :param owner: `IPerson` owning the Archive;
        :param name: optional text to be used as the archive name, if not
            given it uses the names defined in
            `IArchiveSet._getDefaultArchiveNameForPurpose`;
        :param displayname: optional text that will be used as a reference
            to this archive in the UI. If not provided a default text
            (including the archive name and the owner displayname)  will be
            used.
        :param distribution: optional `IDistribution` to which the archive
            will be attached;
        :param description: optional text to be set as the archive
            description;
        :param enabled: whether the archive shall be enabled post creation
        :param require_virtualized: whether builds for the new archive shall
            be carried out on virtual builders
        :param private: whether or not to make the PPA private
        :param suppress_subscription_notifications: whether to suppress
            emails to subscribers about new subscriptions.
        :param processors: list of `IProcessors` for which the archive should
            build. If omitted, processors with `build_by_default` will be used.
        :param publishing_method: `ArchivePublishingMethod` for this archive
            (defaults to `LOCAL`).
        :param repository_format: `ArchiveRepositoryFormat` for this archive
            (defaults to `DEBIAN`).

        :return: an `IArchive` object.
        :raises AssertionError if name is already taken within distribution.
        """

    def get(archive_id):
        """Return the IArchive with the given archive_id."""

    @call_with(check_permissions=True, user=REQUEST_USER)
    @operation_parameters(
        reference=TextLine(title=_("Archive reference string"), required=True)
    )
    @operation_returns_entry(schema=IArchive)
    @export_read_operation()
    @operation_for_version("devel")
    def getByReference(reference, check_permissions=False, user=None):
        """Return the IArchive with the given archive reference."""

    def getPPAByDistributionAndOwnerName(distribution, person_name, ppa_name):
        """Return a single PPA.

        :param distribution: The context IDistribution.
        :param person_name: The context IPerson.
        :param ppa_name: The name of the archive (PPA)
        """

    def getByDistroPurpose(distribution, purpose, name=None):
        """Return the IArchive with the given distribution and purpose.

        It uses the default names defined in
        `IArchiveSet._getDefaultArchiveNameForPurpose`.

        :raises AssertionError if used for with ArchivePurpose.PPA.
        """

    def getByDistroAndName(distribution, name):
        """Return the `IArchive` with the given distribution and name."""

    def __iter__():
        """Iterates over existent archives, including the main_archives."""

    def getPPAOwnedByPerson(
        person, name=None, statuses=None, has_packages=False
    ):
        """Return the named PPA owned by person.

        :param person: An `IPerson`.  Required.
        :param name: The PPA name.  Optional.
        :param statuses: A list of statuses the PPAs must match.  Optional.
        :param has_packages: If True will only select PPAs that have published
            source packages.

        If the name is not supplied it will default to the
        first PPA that the person created.

        :raises NoSuchPPA: if the named PPA does not exist.
        """

    def getPPAsForUser(user):
        """Return all PPAs the given user can participate.

        The result is ordered by PPA displayname.
        """

    def getPPADistributionsForUser(user):
        """Return the `Distribution`s of all PPAs for the given user."""

    def getArchivesPendingSigningKey(purpose=ArchivePurpose.PPA):
        """Return all archives with `purpose` pending signing key generation.

        The result is ordered by archive creation date.

        :param purpose: Only return archives with this `ArchivePurpose`.
        """

    def getArchivesWith1024BitRSASigningKey(limit):
        """Return all archives with only a 1024-bit RSA signing key.

        The result is ordered by archive id.

        :param limit: Limit the size of archive result set to this integer.
        """

    def getLatestPPASourcePublicationsForDistribution(distribution):
        """The latest 5 PPA source publications for a given distribution.

        Private PPAs are excluded from the result.
        """

    def getMostActivePPAsForDistribution(distribution):
        """Return the 5 most active PPAs.

        The activity is currently measured by number of uploaded (published)
        sources for each PPA during the last 7 days.

        Private PPAs are excluded from the result.

        :return A list with up to 5 dictionaries containing the ppa 'title'
            and the number of 'uploads' keys and corresponding values.
        """

    def getArchivesForDistribution(
        distribution,
        name=None,
        purposes=None,
        check_permissions=True,
        user=None,
        exclude_disabled=True,
        exclude_pristine=False,
    ):
        """Return a list of all the archives for a distribution.

        This will return all the archives for the given distribution, with
        the following parameters:

        :param distribution: target `IDistribution`
        :param name: An optional archive name which will further restrict
            the results to only those archives with this name.
        :param purposes: An optional archive purpose or list of purposes with
            which to filter the results.
        :param check_permissions: If False, return both public and private
            archives regardless of user permission checks. This is intended
            for use by internal scripts.
        :param user: An optional `IPerson` who is requesting the archives,
            which is used to include private archives for which the user
            has permission. If it is not supplied, only public archives
            will be returned. These checks are skipped if
            `check_permissions` is False.
        :param exclude_disabled: Whether to exclude disabled archives.
        :param exclude_pristine: Whether to exclude archives that have never
            had any publications.

        :return: A queryset of all the archives for the given
            distribution matching the given params.
        """

    def getPrivatePPAs():
        """Return a result set containing all private PPAs."""

    def getPublicationsInArchives(
        source_package_name, archive_list, distribution=None, distroseries=None
    ):
        """Return a result set of publishing records for the source package.

        :param source_package_name: an `ISourcePackageName` identifying the
            source package for which the publishings will be returned.
        :param archive_list: a list of at least one archive with which to
            restrict the search.
        :param distribution: the distribution by which the results will
            be limited.
        :param distroseries: the distroseries by which the results will
            be limited.
        :return: a resultset of the `ISourcePackagePublishingHistory` objects
            that are currently published in the given archives.
        """

    def checkViewPermission(
        archives: typing.List[IArchive], user: IPerson
    ) -> typing.Dict[IArchive, bool]:
        """
        Given a collection of archives, check if the user can view
        each of them.

        Anyone can see a public and enabled archive.

        Only Launchpad admins and uploaders can view private or disabled
        archives.

        :param archives: a collection of `IArchive` objects
        :param user: a user (a `IPerson` object)
        :return: a mapping of `IArchive` -> `bool`, where the values represent
            the result of the permission check.
        """


default_name_by_purpose = {
    ArchivePurpose.PRIMARY: "primary",
    ArchivePurpose.PPA: "ppa",
    ArchivePurpose.PARTNER: "partner",
}


MAIN_ARCHIVE_PURPOSES = (
    ArchivePurpose.PRIMARY,
    ArchivePurpose.PARTNER,
)

ALLOW_RELEASE_BUILDS = (
    ArchivePurpose.PARTNER,
    ArchivePurpose.PPA,
    ArchivePurpose.COPY,
)

FULL_COMPONENT_SUPPORT = (
    ArchivePurpose.PRIMARY,
    ArchivePurpose.COPY,
)


def validate_external_dependencies(ext_deps):
    """Validate the external_dependencies field.

    :param ext_deps: The dependencies form field to check.
    """
    errors = []
    if ext_deps is None:
        return errors
    # The field can consist of multiple entries separated by
    # newlines, so process each in turn.
    for dep in ext_deps.splitlines():
        dep_without_options = re.sub(r"^([^ ]*) \[[^]]*\] ", r"\1 ", dep)
        try:
            deb, url, suite, components = dep_without_options.split(" ", 3)
        except ValueError:
            errors.append(
                "'%s' is not a complete and valid sources.list entry" % dep
            )
            continue

        if deb != "deb":
            errors.append("%s: Must start with 'deb'" % dep)
        url_components = urlparse(url)
        if not url_components[0] or not url_components[1]:
            errors.append("%s: Invalid URL" % dep)

    return errors
