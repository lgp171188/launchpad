# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database class for table Archive."""

__all__ = [
    "Archive",
    "ArchiveSet",
    "get_archive_privacy_filter",
    "get_enabled_archive_filter",
    "validate_ppa",
]

import http.client
import logging
import re
import typing
from datetime import datetime, timedelta, timezone
from operator import attrgetter
from pathlib import PurePath

import six
from lazr.lifecycle.event import ObjectCreatedEvent
from lazr.restful.declarations import error_status
from storm.databases.postgres import JSON as PgJSON
from storm.expr import (
    Alias,
    And,
    Asc,
    Cast,
    Count,
    Desc,
    Exists,
    Is,
    Join,
    Not,
    Or,
    Select,
    Sum,
    Union,
)
from storm.properties import JSON, Bool, DateTime, Int, Unicode
from storm.references import Reference
from storm.store import EmptyResultSet, Store
from zope.component import getAdapter, getUtility
from zope.event import notify
from zope.interface import alsoProvides, implementer
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import (
    IncompatibleArchiveStatus,
    IncompatibleArguments,
    NotFoundError,
)
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.app.interfaces.security import IAuthorization
from lp.app.validators.name import valid_name
from lp.archivepublisher.debversion import Version
from lp.archivepublisher.diskpool import unpoolify
from lp.archivepublisher.interfaces.publisherconfig import IPublisherConfigSet
from lp.archiveuploader.utils import (
    determine_binary_file_type,
    re_isadeb,
    re_issource,
)
from lp.buildmaster.enums import BuildQueueStatus, BuildStatus
from lp.buildmaster.interfaces.buildfarmjob import IBuildFarmJobSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.model.processor import Processor
from lp.registry.enums import INCLUSIVE_TEAM_POLICY, PersonVisibility
from lp.registry.errors import NoSuchDistroSeries
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.gpg import IGPGKeySet
from lp.registry.interfaces.person import IPerson, IPersonSet, validate_person
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.role import IHasOwner, IPersonRoles
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.registry.model.gpgkey import GPGKey
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.registry.model.teammembership import TeamParticipation
from lp.services.config import config
from lp.services.database.bulk import create, load_referencing, load_related
from lp.services.database.constants import UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStandbyStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.database.stormexpr import BulkUpdate
from lp.services.features import getFeatureFlag
from lp.services.gpg.interfaces import IGPGHandler
from lp.services.job.interfaces.job import JobStatus
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import (
    IArchiveSigningKeySet,
    ISigningKeySet,
)
from lp.services.signing.model.signingkey import ArchiveSigningKey, SigningKey
from lp.services.tokens import create_token
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import ILaunchBag
from lp.services.webapp.url import urlappend
from lp.soyuz.adapters.archivedependencies import expand_dependencies
from lp.soyuz.adapters.packagelocation import PackageLocation
from lp.soyuz.enums import (
    ArchivePermissionType,
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveRepositoryFormat,
    ArchiveStatus,
    ArchiveSubscriberStatus,
    PackageCopyPolicy,
    PackagePublishingStatus,
    PackageUploadStatus,
    archive_suffixes,
)
from lp.soyuz.interfaces.archive import (
    FULL_COMPONENT_SUPPORT,
    IPPA,
    MAIN_ARCHIVE_PURPOSES,
    NAMED_AUTH_TOKEN_FEATURE_FLAG,
    AlreadySubscribed,
    ArchiveAlreadyDeleted,
    ArchiveDependencyError,
    ArchiveDisabled,
    ArchiveNotPrivate,
    CannotCopy,
    CannotModifyArchiveProcessor,
    CannotSwitchPrivacy,
    CannotUploadToPocket,
    CannotUploadToPPA,
    CannotUploadToSeries,
    ComponentNotFound,
    DuplicateTokenName,
    IArchive,
    IArchiveSet,
    IDistributionArchive,
    InsufficientUploadRights,
    InvalidComponent,
    InvalidExternalDependencies,
    InvalidPocketForPartnerArchive,
    InvalidPocketForPPA,
    NamedAuthTokenFeatureDisabled,
    NoRightsForArchive,
    NoRightsForComponent,
    NoSuchPPA,
    NoTokensForTeams,
    PocketNotFound,
    RedirectedPocket,
    VersionRequiresName,
    default_name_by_purpose,
    validate_external_dependencies,
)
from lp.soyuz.interfaces.archiveauthtoken import IArchiveAuthTokenSet
from lp.soyuz.interfaces.archivejob import ICIBuildUploadJobSource
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet
from lp.soyuz.interfaces.archivesubscriber import (
    ArchiveSubscriptionError,
    IArchiveSubscriberSet,
)
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.soyuz.interfaces.buildrecords import IHasBuildRecords
from lp.soyuz.interfaces.component import IComponent, IComponentSet
from lp.soyuz.interfaces.packagecopyjob import IPlainPackageCopyJobSource
from lp.soyuz.interfaces.packagecopyrequest import IPackageCopyRequestSet
from lp.soyuz.interfaces.publishing import (
    IPublishingSet,
    active_publishing_status,
)
from lp.soyuz.model.archiveauthtoken import ArchiveAuthToken
from lp.soyuz.model.archivedependency import ArchiveDependency
from lp.soyuz.model.archivepermission import ArchivePermission
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagename import BinaryPackageName
from lp.soyuz.model.binarypackagerelease import (
    BinaryPackageRelease,
    BinaryPackageReleaseDownloadCount,
)
from lp.soyuz.model.component import Component
from lp.soyuz.model.files import BinaryPackageFile, SourcePackageReleaseFile
from lp.soyuz.model.packagediff import PackageDiff
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
)
from lp.soyuz.model.queue import PackageUpload, PackageUploadSource
from lp.soyuz.model.section import Section
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease

ARCHIVE_REFERENCE_TEMPLATES = {
    ArchivePurpose.PRIMARY: "%(distribution)s",
    ArchivePurpose.PPA: "~%(owner)s/%(distribution)s/%(archive)s",
    ArchivePurpose.PARTNER: "%(distribution)s/%(archive)s",
    ArchivePurpose.COPY: "%(distribution)s/%(archive)s",
}


@error_status(http.client.BAD_REQUEST)
class CannotSetMetadataOverrides(Exception):
    """Raised when someone tries to set invalid metadata overrides keys or
    non empty string values.
    """


def storm_validate_external_dependencies(archive, attr, value):
    assert attr == "external_dependencies"
    errors = validate_external_dependencies(value)
    if len(errors) > 0:
        raise InvalidExternalDependencies(errors)
    return value


@implementer(IArchive, IHasOwner, IHasBuildRecords)
class Archive(StormBase):
    __storm_table__ = "Archive"
    __storm_order__ = "id"

    id = Int(primary=True)

    owner_id = Int(name="owner", validator=validate_person, allow_none=False)
    owner = Reference(owner_id, "Person.id")

    def _validate_archive_name(self, attr, value):
        """Only allow renaming of COPY archives.

        Also assert the name is valid when set via an unproxied object.
        """
        if not self._creating:
            renamable = self.is_copy or (
                self.is_ppa and self.status == ArchiveStatus.DELETED
            )
            assert (
                renamable
            ), "Only COPY archives and deleted PPAs can be renamed."
        assert valid_name(value), "Invalid name given to unproxied object."
        return value

    def _validate_archive_privacy(self, attr, value):
        """Require private team owners to have private archives.

        If the owner of the archive is private, then the archive cannot be
        made public.
        """
        if value is False:
            # The archive is transitioning from private to public.
            assert (
                self.owner.visibility != PersonVisibility.PRIVATE
            ), "Private teams may not have public PPAs."

        if not self.getPublishedSources().is_empty():
            if (
                # For local publishing, we can't switch privacy after
                # anything has been published to it, because the publisher
                # uses different paths on disk for public and private
                # archives.
                self.publishing_method == ArchivePublishingMethod.LOCAL
                # Refuse to switch from private to public even for non-local
                # publishing, partly as a safety measure and partly because
                # the files in the archive would have to be unrestricted and
                # we don't have code to do that yet.
                #
                # Switching an archive from public to private should ideally
                # also restrict any files published only in that archive.
                # However, that's quite complex because we'd have to check
                # whether the files are published anywhere else, and nothing
                # breaks if we leave the files alone.  It's not ideal that
                # we might have files reachable from the public librarian
                # that are now only published in a private archive, but
                # since Launchpad won't give out any links to those, it
                # could be worse.
                or not value
            ):
                raise CannotSwitchPrivacy(
                    "This archive has had sources published and therefore "
                    "cannot have its privacy switched."
                )

        return value

    name = Unicode(
        name="name", allow_none=False, validator=_validate_archive_name
    )

    displayname = Unicode(name="displayname", allow_none=False)

    description = Unicode(name="description", allow_none=True, default=None)

    distribution_id = Int(name="distribution", allow_none=True)
    distribution = Reference(distribution_id, "Distribution.id")

    purpose = DBEnum(name="purpose", allow_none=False, enum=ArchivePurpose)

    status = DBEnum(
        name="status",
        allow_none=False,
        enum=ArchiveStatus,
        default=ArchiveStatus.ACTIVE,
    )

    _enabled = Bool(name="enabled", allow_none=False, default=True)
    enabled = property(lambda x: x._enabled)

    publish = Bool(name="publish", allow_none=False, default=True)

    private = Bool(
        name="private",
        allow_none=False,
        default=False,
        validator=_validate_archive_privacy,
    )

    require_virtualized = Bool(
        name="require_virtualized", allow_none=False, default=True
    )

    build_debug_symbols = Bool(
        name="build_debug_symbols", allow_none=False, default=False
    )
    publish_debug_symbols = Bool(
        name="publish_debug_symbols", allow_none=True, default=False
    )

    permit_obsolete_series_uploads = Bool(
        name="permit_obsolete_series_uploads", default=False
    )

    authorized_size = Int(name="authorized_size", allow_none=True)

    sources_cached = Int(name="sources_cached", allow_none=True, default=0)

    binaries_cached = Int(name="binaries_cached", allow_none=True, default=0)

    package_description_cache = Unicode(
        name="package_description_cache", allow_none=True, default=None
    )

    total_count = Int(name="total_count", allow_none=False, default=0)

    pending_count = Int(name="pending_count", allow_none=False, default=0)

    succeeded_count = Int(name="succeeded_count", allow_none=False, default=0)

    building_count = Int(name="building_count", allow_none=False, default=0)

    failed_count = Int(name="failed_count", allow_none=False, default=0)

    date_created = DateTime(name="date_created", tzinfo=timezone.utc)

    signing_key_owner_id = Int(name="signing_key_owner")
    signing_key_owner = Reference(signing_key_owner_id, "Person.id")
    signing_key_fingerprint = Unicode()

    relative_build_score = Int(
        name="relative_build_score", allow_none=False, default=0
    )

    # This field is specifically and only intended for OEM migration to
    # Launchpad and should be re-examined in October 2010 to see if it
    # is still relevant.
    external_dependencies = Unicode(
        name="external_dependencies",
        allow_none=True,
        default=None,
        validator=storm_validate_external_dependencies,
    )

    suppress_subscription_notifications = Bool(
        name="suppress_subscription_notifications",
        allow_none=False,
        default=False,
    )

    dirty_suites = JSON(name="dirty_suites", allow_none=True)

    metadata_overrides = PgJSON(name="metadata_overrides", allow_none=True)

    _publishing_method = DBEnum(
        name="publishing_method", allow_none=True, enum=ArchivePublishingMethod
    )

    _repository_format = DBEnum(
        name="repository_format", allow_none=True, enum=ArchiveRepositoryFormat
    )

    _creating = False

    def __init__(
        self,
        owner,
        distribution,
        name,
        displayname,
        purpose,
        description=None,
        publish=True,
        require_virtualized=True,
        signing_key_owner=None,
        signing_key_fingerprint=None,
        publishing_method=None,
        repository_format=None,
        metadata_overrides=None,
    ):
        super().__init__()
        try:
            self._creating = True
            self.owner = owner
            self.distribution = distribution
            self.name = name
            self.displayname = displayname
            self.purpose = purpose
            self.description = description
            self.publish = publish
            self.require_virtualized = require_virtualized
            self.signing_key_owner = signing_key_owner
            self.signing_key_fingerprint = signing_key_fingerprint
            self.publishing_method = publishing_method
            self.repository_format = repository_format
            self.metadata_overrides = metadata_overrides
        except Exception:
            # If validating references such as `owner` fails, then the new
            # object may have been added to the store first.  Remove it
            # again in that case.
            store = Store.of(self)
            if store is not None:
                store.remove(self)
            raise
        self.__storm_loaded__()
        del self._creating

    def __storm_loaded__(self):
        # Provide the additional marker interface depending on what type
        # of archive this is.  See also the lp:url declarations in
        # zcml/archive.zcml.
        if self.is_ppa:
            alsoProvides(self, IPPA)
        else:
            alsoProvides(self, IDistributionArchive)

    @property
    def title(self):
        """See `IArchive`."""
        return self.displayname

    @cachedproperty
    def signing_key(self):
        """See `IArchive`."""
        if self.signing_key_fingerprint is not None:
            return getUtility(IGPGKeySet).getByFingerprint(
                self.signing_key_fingerprint
            )

    def getSigningKeyData(self):
        """See `IArchive`."""
        if self.signing_key_fingerprint is not None:
            # This may raise GPGKeyNotFoundError, which we allow to
            # propagate as an HTTP error.
            key_data = (
                getUtility(IGPGHandler)
                .retrieveKey(self.signing_key_fingerprint)
                .export()
            )
            # Ideally we'd just return a byte string, but lazr.restful
            # really wants methods to return something that can be
            # serialised as JSON, so instead rely on ASCII-armouring
            # producing something that we can decode as text.
            return key_data.decode("UTF-8")

    @property
    def signing_key_keyserver_url(self):
        if self.signing_key_fingerprint is not None:
            return getUtility(IGPGHandler).getURLForKeyInServer(
                self.signing_key_fingerprint, public=True
            )

    @cachedproperty
    def signing_key_display_name(self):
        if self.signing_key is not None:
            # Signing key is stored as a GPGKey.
            return self.signing_key.displayname
        elif self.signing_key_fingerprint is not None:
            signing_key = getUtility(ISigningKeySet).get(
                SigningKeyType.OPENPGP, self.signing_key_fingerprint
            )
            if signing_key is not None:
                # Signing key is stored on the signing service.
                try:
                    pyme_key = getUtility(IGPGHandler).importPublicKey(
                        signing_key.public_key
                    )
                except Exception:
                    logging.getLogger(__name__).exception(
                        "Failed to import public key %s from SigningKey",
                        self.signing_key_fingerprint,
                    )
                else:
                    return pyme_key.displayname

    @property
    def is_ppa(self):
        """See `IArchive`."""
        return self.purpose == ArchivePurpose.PPA

    @property
    def is_primary(self):
        """See `IArchive`."""
        return self.purpose == ArchivePurpose.PRIMARY

    @property
    def is_partner(self):
        """See `IArchive`."""
        return self.purpose == ArchivePurpose.PARTNER

    @property
    def is_copy(self):
        """See `IArchive`."""
        return self.purpose == ArchivePurpose.COPY

    @property
    def is_main(self):
        """See `IArchive`."""
        return self.purpose in MAIN_ARCHIVE_PURPOSES

    @property
    def is_active(self):
        """See `IArchive`."""
        return self.status == ArchiveStatus.ACTIVE

    @property
    def can_be_published(self):
        """See `IArchive`."""
        # The explicit publish flag must be set.
        if not self.publish:
            return False
        # Archives published via Artifactory don't (currently?) require
        # local key generation.
        if self.publishing_method == ArchivePublishingMethod.ARTIFACTORY:
            return True
        # In production configurations, PPAs and copy archives can only be
        # published once their signing key has been generated.
        return (
            not config.personalpackagearchive.require_signing_keys
            or (not self.is_ppa and not self.is_copy)
            or self.signing_key_fingerprint is not None
        )

    @property
    def api_publish(self):
        """See `IArchive`."""
        return self.publish

    @api_publish.setter
    def api_publish(self, value):
        if value is True and self.status != ArchiveStatus.ACTIVE:
            raise IncompatibleArchiveStatus("Deleted PPAs can't be enabled.")
        self.publish = value

    @property
    def reference(self):
        template = ARCHIVE_REFERENCE_TEMPLATES.get(self.purpose)
        if template is None:
            raise AssertionError(
                "No archive reference template for %s." % self.purpose.name
            )
        return template % {
            "archive": self.name,
            "owner": self.owner.name,
            "distribution": self.distribution.name,
        }

    @property
    def series_with_sources(self):
        """See `IArchive`."""
        # Import DistroSeries here to avoid circular imports.
        from lp.registry.model.distroseries import DistroSeries

        distro_series = (
            IStore(DistroSeries)
            .find(
                DistroSeries,
                DistroSeries.distribution == self.distribution,
                SourcePackagePublishingHistory.distroseries == DistroSeries.id,
                SourcePackagePublishingHistory.archive == self,
                SourcePackagePublishingHistory.status.is_in(
                    active_publishing_status
                ),
            )
            .config(distinct=True)
        )

        # Ensure the ordering is the same as presented by
        # Distribution.series
        return sorted(
            distro_series, key=lambda a: Version(a.version), reverse=True
        )

    @property
    def dependencies(self):
        # Circular import.
        from lp.registry.model.person import Person

        return (
            IStore(ArchiveDependency)
            .find(
                ArchiveDependency,
                ArchiveDependency.dependency == Archive.id,
                Archive.owner == Person.id,
                ArchiveDependency.archive == self,
            )
            .order_by(Person.display_name)
        )

    @cachedproperty
    def default_component(self):
        """See `IArchive`."""
        if self.is_partner:
            return getUtility(IComponentSet)["partner"]
        elif self.is_ppa:
            return getUtility(IComponentSet)["main"]
        else:
            return None

    @cachedproperty
    def _known_subscribers(self):
        return set()

    @property
    def archive_url(self):
        """See `IArchive`."""
        if self.is_ppa:
            if self.private:
                url = config.personalpackagearchive.private_base_url
            else:
                url = config.personalpackagearchive.base_url
            return urlappend(
                url,
                "/".join((self.owner.name, self.name, self.distribution.name)),
            )

        db_pubconf = getUtility(IPublisherConfigSet).getByDistribution(
            self.distribution
        )
        if self.is_copy:
            url = urlappend(
                db_pubconf.copy_base_url,
                self.distribution.name + "-" + self.name,
            )
            return urlappend(url, self.distribution.name)

        try:
            postfix = archive_suffixes[self.purpose]
        except KeyError:
            raise AssertionError(
                "archive_url unknown for purpose: %s" % self.purpose
            )
        return urlappend(db_pubconf.base_url, self.distribution.name + postfix)

    def getBuildRecords(
        self,
        build_state=None,
        name=None,
        pocket=None,
        arch_tag=None,
        user=None,
        binary_only=True,
    ):
        """See IHasBuildRecords"""
        # Ignore "user", since anyone already accessing this archive
        # will implicitly have permission to see it.

        if binary_only:
            return getUtility(IBinaryPackageBuildSet).getBuildsForArchive(
                self, build_state, name, pocket, arch_tag
            )
        else:
            if arch_tag is not None or name is not None or pocket is not None:
                raise IncompatibleArguments(
                    "The 'arch_tag' and 'name' parameters can be used only "
                    "with binary_only=True."
                )
            return getUtility(IBuildFarmJobSet).getBuildsForArchive(
                self, status=build_state
            )

    def api_getPublishedSources(
        self,
        name=None,
        version=None,
        status=None,
        distroseries=None,
        pocket=None,
        exact_match=False,
        created_since_date=None,
        order_by_date=False,
        order_by_date_ascending=False,
        component_name=None,
    ):
        """See `IArchive`."""
        # 'eager_load' and 'include_removed' arguments are always True
        # for API calls.
        published_sources = self.getPublishedSources(
            name=name,
            version=version,
            status=status,
            distroseries=distroseries,
            pocket=pocket,
            exact_match=exact_match,
            created_since_date=created_since_date,
            eager_load=True,
            component_name=component_name,
            order_by_date=order_by_date,
            order_by_date_ascending=order_by_date_ascending,
            include_removed=True,
        )

        def load_api_extra_objects(rows):
            """Load extra related-objects needed by API calls."""
            # Pre-cache related `PackageUpload`s and `PackageUploadSource`s
            # which are immediately used in the API context for checking
            # permissions on the returned entries.
            uploads = load_related(PackageUpload, rows, ["packageupload_id"])
            pu_sources = load_referencing(
                PackageUploadSource, uploads, ["packageupload_id"]
            )
            for pu_source in pu_sources:
                upload = pu_source.packageupload
                get_property_cache(upload).sources = [pu_source]
            # Pre-cache `SourcePackageName`s which are immediately used
            # in the API context for materializing the returned entries.
            # XXX cprov 2014-04-23: load_related() does not support
            # nested attributes as foreign keys (uses getattr instead of
            # attrgetter).
            spn_ids = set(
                map(
                    attrgetter("sourcepackagerelease.sourcepackagename_id"),
                    rows,
                )
            )
            list(
                Store.of(self).find(
                    SourcePackageName, SourcePackageName.id.is_in(spn_ids)
                )
            )
            # Bypass PackageUpload security-check query by caching
            # `SourcePackageRelease.published_archives` results.
            # All published sources are visible to the user, since they
            # are published in the context archive. No need to check
            # additional archives the source is published.
            for pub_source in rows:
                spr = pub_source.sourcepackagerelease
                get_property_cache(spr).published_archives = [self]

        return DecoratedResultSet(
            published_sources, pre_iter_hook=load_api_extra_objects
        )

    def getPublishedSources(
        self,
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
        """See `IArchive`."""
        clauses = [SourcePackagePublishingHistory.archive == self]

        if order_by_date:
            order_by = [
                Desc(SourcePackagePublishingHistory.datecreated),
                Desc(SourcePackagePublishingHistory.id),
            ]
        elif order_by_date_ascending:
            order_by = [
                Asc(SourcePackagePublishingHistory.datecreated),
                Asc(SourcePackagePublishingHistory.id),
            ]
        else:
            order_by = [
                SourcePackageName.name,
                Desc(SourcePackagePublishingHistory.id),
            ]

        if not (order_by_date or order_by_date_ascending) or name is not None:
            clauses.append(
                SourcePackagePublishingHistory.sourcepackagename_id
                == SourcePackageName.id
            )

        if name is not None:
            if isinstance(name, str):
                if exact_match:
                    clauses.append(SourcePackageName.name == name)
                else:
                    clauses.append(
                        SourcePackageName.name.contains_string(name)
                    )
            elif len(name) != 0:
                clauses.append(SourcePackageName.name.is_in(name))

        if (
            not (order_by_date or order_by_date_ascending)
            or version is not None
        ):
            clauses.append(
                SourcePackagePublishingHistory.sourcepackagerelease_id
                == SourcePackageRelease.id
            )

        if version is not None:
            if name is None:
                raise VersionRequiresName(
                    "The 'version' parameter can be used only together with"
                    " the 'name' parameter."
                )
            clauses.append(
                Cast(SourcePackageRelease.version, "text")
                == six.ensure_text(version)
            )
        elif not (order_by_date or order_by_date_ascending):
            order_by.insert(1, Desc(SourcePackageRelease.version))

        if component_name is not None:
            clauses.extend(
                [
                    SourcePackagePublishingHistory.component_id
                    == Component.id,
                    Component.name == component_name,
                ]
            )

        if status is not None:
            try:
                status = tuple(status)
            except TypeError:
                status = (status,)
            clauses.append(SourcePackagePublishingHistory.status.is_in(status))

        if distroseries is not None:
            clauses.append(
                SourcePackagePublishingHistory.distroseries == distroseries
            )

        if pocket is not None:
            try:
                pockets = tuple(pocket)
            except TypeError:
                pockets = (pocket,)
            clauses.append(
                SourcePackagePublishingHistory.pocket.is_in(pockets)
            )

        if created_since_date is not None:
            clauses.append(
                SourcePackagePublishingHistory.datecreated
                >= created_since_date
            )

        if not include_removed:
            clauses.append(SourcePackagePublishingHistory.dateremoved == None)

        if only_unpublished:
            clauses.append(
                SourcePackagePublishingHistory.datepublished == None
            )

        store = Store.of(self)
        resultset = store.find(
            SourcePackagePublishingHistory, *clauses
        ).order_by(*order_by)
        if not eager_load:
            return resultset

        # Its not clear that this eager load is necessary or sufficient, it
        # replaces a prejoin that had pathological query plans.
        def eager_load(rows):
            # \o/ circular imports.
            from lp.registry.model.distroseries import DistroSeries

            ids = set(map(attrgetter("distroseries_id"), rows))
            ids.discard(None)
            if ids:
                list(store.find(DistroSeries, DistroSeries.id.is_in(ids)))
            ids = set(map(attrgetter("section_id"), rows))
            ids.discard(None)
            if ids:
                list(store.find(Section, Section.id.is_in(ids)))
            ids = set(map(attrgetter("sourcepackagerelease_id"), rows))
            ids.discard(None)
            if not ids:
                return
            releases = list(
                store.find(
                    SourcePackageRelease, SourcePackageRelease.id.is_in(ids)
                )
            )
            ids = set(map(attrgetter("creator_id"), releases))
            ids.discard(None)
            if ids:
                list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(ids))

        return DecoratedResultSet(resultset, pre_iter_hook=eager_load)

    def getSourcesForDeletion(self, name=None, status=None, distroseries=None):
        """See `IArchive`."""
        # We will return sources that can be deleted, or deleted sources that
        # still have published binaries. We can use scheduleddeletiondate
        # rather than linking through BPB, BPR and BPPH since we don't condemn
        # sources until their binaries are all gone due to GPL compliance.
        clauses = [
            SourcePackagePublishingHistory.archive == self,
            SourcePackagePublishingHistory.sourcepackagerelease_id
            == SourcePackageRelease.id,
            SourcePackagePublishingHistory.sourcepackagename_id
            == SourcePackageName.id,
            SourcePackagePublishingHistory.scheduleddeletiondate == None,
        ]

        if status:
            try:
                status = tuple(status)
            except TypeError:
                status = (status,)
            clauses.append(SourcePackagePublishingHistory.status.is_in(status))

        if distroseries:
            clauses.append(
                SourcePackagePublishingHistory.distroseries == distroseries
            )

        if name:
            clauses.append(SourcePackageName.name.contains_string(name))

        sources = (
            Store.of(self)
            .find(SourcePackagePublishingHistory, *clauses)
            .order_by(
                SourcePackageName.name,
                Desc(SourcePackageRelease.version),
                Desc(SourcePackagePublishingHistory.id),
            )
        )

        def eager_load(rows):
            load_related(
                SourcePackageRelease, rows, ["sourcepackagerelease_id"]
            )

        return DecoratedResultSet(sources, pre_iter_hook=eager_load)

    @property
    def number_of_sources(self):
        """See `IArchive`."""
        return self.getPublishedSources(
            status=PackagePublishingStatus.PUBLISHED
        ).count()

    @property
    def sources_size(self):
        """See `IArchive`."""
        result = IStore(LibraryFileContent).find(
            (
                LibraryFileAlias.filename,
                LibraryFileContent.sha1,
                LibraryFileContent.filesize,
            ),
            SourcePackagePublishingHistory.archive == self.id,
            SourcePackagePublishingHistory.dateremoved == None,
            SourcePackagePublishingHistory.sourcepackagerelease_id
            == SourcePackageReleaseFile.sourcepackagerelease_id,
            SourcePackageReleaseFile.libraryfile_id == LibraryFileAlias.id,
            LibraryFileAlias.content_id == LibraryFileContent.id,
        )

        # Note: we can't use the LFC.sha1 instead of LFA.filename above
        # because some archives publish the same file content with different
        # names in the archive, so although the duplication will be removed
        # in the librarian by the librarian-gc, we do not (yet) remove
        # this duplication in the pool when the filenames are different.

        # We need to select distinct on the (filename, filesize) result
        # so that we only count duplicate files (with the same filename)
        # once (ie. the same tarball used for different distroseries) as
        # we do avoid this duplication in the pool when the names are
        # the same.
        result = result.config(distinct=True)

        return result.sum(LibraryFileContent.filesize) or 0

    def _getBinaryPublishingBaseClauses(
        self,
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
        need_bpr=False,
        component_name=None,
    ):
        """Base clauses for binary publishing queries.

        Returns a list of 'clauses' (to be joined in the callsite).
        """
        clauses = [BinaryPackagePublishingHistory.archive == self]

        if order_by_date or order_by_date_ascending:
            ordered = False

        if order_by_date:
            order_by = [
                Desc(BinaryPackagePublishingHistory.datecreated),
                Desc(BinaryPackagePublishingHistory.id),
            ]
        elif order_by_date_ascending:
            order_by = [
                Asc(BinaryPackagePublishingHistory.datecreated),
                Asc(BinaryPackagePublishingHistory.id),
            ]
        elif ordered:
            order_by = [
                BinaryPackageName.name,
                Desc(BinaryPackagePublishingHistory.id),
            ]
        else:
            # Strictly speaking, this is ordering, but it's an indexed
            # ordering so it will be quick.  It's needed so that we can
            # batch results on the webservice.
            order_by = [Desc(BinaryPackagePublishingHistory.id)]

        if ordered or name is not None:
            clauses.append(
                BinaryPackagePublishingHistory.binarypackagename_id
                == BinaryPackageName.id
            )

        if name is not None:
            if exact_match:
                clauses.append(BinaryPackageName.name == name)
            else:
                clauses.append(BinaryPackageName.name.contains_string(name))

        if need_bpr or ordered or version is not None:
            clauses.append(
                BinaryPackagePublishingHistory.binarypackagerelease_id
                == BinaryPackageRelease.id
            )

        if version is not None:
            if name is None:
                raise VersionRequiresName(
                    "The 'version' parameter can be used only together with"
                    " the 'name' parameter."
                )

            clauses.append(
                Cast(BinaryPackageRelease.version, "text")
                == six.ensure_text(version)
            )
        elif ordered:
            order_by.insert(1, Desc(BinaryPackageRelease.version))

        if status is not None:
            try:
                status = tuple(status)
            except TypeError:
                status = (status,)
            clauses.append(BinaryPackagePublishingHistory.status.is_in(status))

        if distroarchseries is not None:
            try:
                distroarchseries = tuple(distroarchseries)
            except TypeError:
                distroarchseries = (distroarchseries,)
            clauses.append(
                BinaryPackagePublishingHistory.distroarchseries_id.is_in(
                    [d.id for d in distroarchseries]
                )
            )

        if pocket is not None:
            clauses.append(BinaryPackagePublishingHistory.pocket == pocket)

        if created_since_date is not None:
            clauses.append(
                BinaryPackagePublishingHistory.datecreated
                >= created_since_date
            )

        if not include_removed:
            clauses.append(BinaryPackagePublishingHistory.dateremoved == None)

        if only_unpublished:
            clauses.append(
                BinaryPackagePublishingHistory.datepublished == None
            )

        if component_name is not None:
            clauses.extend(
                [
                    BinaryPackagePublishingHistory.component_id
                    == Component.id,
                    Component.name == component_name,
                ]
            )

        return clauses, order_by

    def getAllPublishedBinaries(
        self,
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
        """See `IArchive`."""
        # Circular imports.
        from lp.registry.model.distroseries import DistroSeries
        from lp.soyuz.model.distroarchseries import DistroArchSeries

        clauses, order_by = self._getBinaryPublishingBaseClauses(
            name=name,
            version=version,
            status=status,
            pocket=pocket,
            distroarchseries=distroarchseries,
            exact_match=exact_match,
            created_since_date=created_since_date,
            ordered=ordered,
            order_by_date=order_by_date,
            order_by_date_ascending=order_by_date_ascending,
            include_removed=include_removed,
            only_unpublished=only_unpublished,
            component_name=component_name,
        )

        result = (
            Store.of(self)
            .find(BinaryPackagePublishingHistory, *clauses)
            .order_by(*order_by)
        )

        def eager_load_api(bpphs):
            bprs = load_related(
                BinaryPackageRelease, bpphs, ["binarypackagerelease_id"]
            )
            load_related(BinaryPackageName, bprs, ["binarypackagename_id"])
            bpbs = load_related(BinaryPackageBuild, bprs, ["build_id"])
            sprs = load_related(
                SourcePackageRelease, bpbs, ["source_package_release_id"]
            )
            load_related(SourcePackageName, sprs, ["sourcepackagename_id"])
            load_related(Component, bpphs, ["component_id"])
            load_related(Section, bpphs, ["section_id"])
            dases = load_related(
                DistroArchSeries, bpphs, ["distroarchseries_id"]
            )
            load_related(DistroSeries, dases, ["distroseries_id"])

        if eager_load:
            result = DecoratedResultSet(result, pre_iter_hook=eager_load_api)
        return result

    def getPublishedOnDiskBinaries(
        self,
        name=None,
        version=None,
        status=None,
        distroarchseries=None,
        pocket=None,
        exact_match=False,
    ):
        """See `IArchive`."""
        # Circular imports.
        from lp.registry.model.distroseries import DistroSeries
        from lp.soyuz.model.distroarchseries import DistroArchSeries

        clauses, order_by = self._getBinaryPublishingBaseClauses(
            name=name,
            version=version,
            status=status,
            pocket=pocket,
            distroarchseries=distroarchseries,
            exact_match=exact_match,
            need_bpr=True,
        )

        clauses.extend(
            [
                BinaryPackagePublishingHistory.distroarchseries_id
                == DistroArchSeries.id,
                DistroArchSeries.distroseries == DistroSeries.id,
            ]
        )

        store = Store.of(self)

        # Retrieve only the binaries published for the 'nominated architecture
        # independent' (usually i386) in the distroseries in question.
        # It includes all architecture-independent binaries only once and the
        # architecture-specific built for 'nominatedarchindep'.
        nominated_arch_independent_clauses = clauses + [
            DistroSeries.nominatedarchindep_id
            == BinaryPackagePublishingHistory.distroarchseries_id,
        ]
        nominated_arch_independents = store.find(
            BinaryPackagePublishingHistory, *nominated_arch_independent_clauses
        )

        # Retrieve all architecture-specific binary publications except
        # 'nominatedarchindep' (already included in the previous query).
        no_nominated_arch_independent_clauses = clauses + [
            DistroSeries.nominatedarchindep_id
            != BinaryPackagePublishingHistory.distroarchseries_id,
            BinaryPackageRelease.architecturespecific == True,
        ]
        no_nominated_arch_independents = store.find(
            BinaryPackagePublishingHistory,
            *no_nominated_arch_independent_clauses,
        )

        # XXX cprov 20071016: It's not possible to use the same ordering
        # schema returned by self._getBinaryPublishingBaseClauses.
        # It results in:
        # ERROR:  missing FROM-clause entry for table "binarypackagename"
        unique_binary_publications = nominated_arch_independents.union(
            no_nominated_arch_independents
        ).order_by(BinaryPackagePublishingHistory.id)

        return unique_binary_publications

    @property
    def number_of_binaries(self):
        """See `IArchive`."""
        return self.getPublishedOnDiskBinaries(
            status=PackagePublishingStatus.PUBLISHED
        ).count()

    @property
    def binaries_size(self):
        """See `IArchive`."""
        result = IStore(LibraryFileContent).find(
            (
                LibraryFileAlias.filename,
                LibraryFileContent.sha1,
                LibraryFileContent.filesize,
            ),
            BinaryPackagePublishingHistory.archive == self.id,
            BinaryPackagePublishingHistory.dateremoved == None,
            BinaryPackagePublishingHistory.binarypackagerelease_id
            == BinaryPackageFile.binarypackagerelease_id,
            BinaryPackageFile.libraryfile_id == LibraryFileAlias.id,
            LibraryFileAlias.content_id == LibraryFileContent.id,
        )
        # See `IArchive.sources_size`.
        result = result.config(distinct=True)
        return result.sum(LibraryFileContent.filesize) or 0

    @property
    def estimated_size(self):
        """See `IArchive`."""
        size = self.sources_size + self.binaries_size
        # 'cruft' represents the increase in the size of the archive
        # indexes related to each publication. We assume it is around 1K
        # but that's over-estimated.
        cruft = (self.number_of_sources + self.number_of_binaries) * 1024
        return size + cruft

    def allowUpdatesToReleasePocket(self):
        """See `IArchive`."""
        purposeToPermissionMap = {
            ArchivePurpose.COPY: True,
            ArchivePurpose.PARTNER: True,
            ArchivePurpose.PPA: True,
            ArchivePurpose.PRIMARY: False,
        }

        try:
            permission = purposeToPermissionMap[self.purpose]
        except KeyError:
            # Future proofing for when new archive types are added.
            permission = False

        return permission

    def getComponentsForSeries(self, distroseries):
        """See `IArchive`."""
        # DistroSeries.components and Archive.default_component are
        # cachedproperties, so this is fairly cheap.
        if self.purpose in FULL_COMPONENT_SUPPORT:
            return distroseries.components
        else:
            return [self.default_component]

    def updateArchiveCache(self):
        """See `IArchive`."""
        # Circular imports.
        from lp.registry.model.distribution import Distribution
        from lp.registry.model.distroseries import DistroSeries
        from lp.soyuz.model.distributionsourcepackagecache import (
            DistributionSourcePackageCache,
        )
        from lp.soyuz.model.distroseriespackagecache import (
            DistroSeriesPackageCache,
        )

        # Compiled regexp to remove punctuation.
        clean_text = re.compile(r"(,|;|:|\.|\?|!)")

        # XXX cprov 20080402 bug=207969: The set() is only used because we
        # have a limitation in our FTI setup, it only indexes the first 2500
        # chars of the target columns. When such limitation
        # gets fixed we should probably change it to a normal list and
        # benefit of the FTI rank for ordering.
        cache_contents = set()

        def add_cache_content(content):
            """Sanitise and add contents to the cache."""
            content = clean_text.sub(" ", content)
            terms = [term.lower() for term in content.strip().split()]
            for term in terms:
                cache_contents.add(term)

        # Cache owner name and displayname.
        add_cache_content(self.owner.name)
        add_cache_content(self.owner.displayname)

        # Cache source package name and its binaries information, binary
        # names and summaries.
        sources_cached = IStore(DistributionSourcePackageCache).find(
            (DistributionSourcePackageCache, Distribution),
            DistributionSourcePackageCache.archive == self,
            DistributionSourcePackageCache.distribution_id == Distribution.id,
        )
        for cache, _ in sources_cached:
            add_cache_content(cache.distribution.name)
            add_cache_content(cache.name)
            add_cache_content(cache.binpkgnames)
            add_cache_content(cache.binpkgsummaries)

        # Cache distroseries names with binaries.
        binaries_cached = IStore(DistroSeriesPackageCache).find(
            (DistroSeriesPackageCache, DistroSeries),
            DistroSeriesPackageCache.archive == self,
            DistroSeriesPackageCache.distroseries_id == DistroSeries.id,
        )
        for cache, _ in binaries_cached:
            add_cache_content(cache.distroseries.name)

        # Collapse all relevant terms in 'package_description_cache' and
        # update the package counters.
        self.package_description_cache = " ".join(sorted(cache_contents))
        self.sources_cached = sources_cached.count()
        self.binaries_cached = binaries_cached.count()

    def findDepCandidates(
        self,
        distro_arch_series,
        pocket,
        component,
        source_package_name,
        dep_name,
    ):
        """See `IArchive`."""
        deps = expand_dependencies(
            self,
            distro_arch_series,
            pocket,
            component,
            source_package_name,
            self.dependencies,
        )
        archive_clause = Or(
            [
                And(
                    BinaryPackagePublishingHistory.archive == archive,
                    BinaryPackagePublishingHistory.pocket == pocket,
                    Component.name.is_in(components),
                )
                for (archive, not_used, pocket, components) in deps
            ]
        )

        return (
            IStandbyStore(BinaryPackagePublishingHistory)
            .find(
                BinaryPackagePublishingHistory,
                BinaryPackageName.name == dep_name,
                BinaryPackagePublishingHistory.binarypackagename
                == BinaryPackageName.id,
                BinaryPackagePublishingHistory.binarypackagerelease
                == BinaryPackageRelease.id,
                BinaryPackagePublishingHistory.distroarchseries
                == distro_arch_series,
                BinaryPackagePublishingHistory.status
                == PackagePublishingStatus.PUBLISHED,
                BinaryPackagePublishingHistory.component_id == Component.id,
                archive_clause,
            )
            .order_by(Desc(BinaryPackagePublishingHistory.id))
        )

    def getArchiveDependency(self, dependency):
        """See `IArchive`."""
        return (
            IStore(ArchiveDependency)
            .find(ArchiveDependency, archive=self, dependency=dependency)
            .one()
        )

    def removeArchiveDependency(self, dependency):
        """See `IArchive`."""
        dependency = self.getArchiveDependency(dependency)
        if dependency is None:
            raise AssertionError("This dependency does not exist.")
        dependency.destroySelf()

    def addArchiveDependency(self, dependency, pocket, component=None):
        """See `IArchive`."""
        if dependency == self:
            raise ArchiveDependencyError(
                "An archive should not depend on itself."
            )

        a_dependency = self.getArchiveDependency(dependency)
        if a_dependency is not None:
            raise ArchiveDependencyError(
                "This dependency is already registered."
            )
        if not check_permission("launchpad.View", dependency):
            raise ArchiveDependencyError(
                "You don't have permission to use this dependency."
            )
        if not dependency.enabled:
            raise ArchiveDependencyError("Dependencies must not be disabled.")
        if dependency.distribution != self.distribution:
            raise ArchiveDependencyError(
                "Dependencies must be for the same distribution."
            )
        if dependency.private and not self.private:
            raise ArchiveDependencyError(
                "Public PPAs cannot depend on private ones."
            )

        if dependency.is_ppa:
            if pocket is not PackagePublishingPocket.RELEASE:
                raise ArchiveDependencyError(
                    "Non-primary archives only support the RELEASE pocket."
                )
            if (
                component is not None
                and component != dependency.default_component
            ):
                raise ArchiveDependencyError(
                    "Non-primary archives only support the '%s' component."
                    % dependency.default_component.name
                )
        return ArchiveDependency(
            parent=self,
            dependency=dependency,
            pocket=pocket,
            component=component,
        )

    def _addArchiveDependency(self, dependency, pocket, component=None):
        """See `IArchive`."""
        if isinstance(component, str):
            try:
                component = getUtility(IComponentSet)[component]
            except NotFoundError as e:
                raise ComponentNotFound(e)
        return self.addArchiveDependency(dependency, pocket, component)

    def getPermissions(self, user, item, perm_type, distroseries=None):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.checkAuthenticated(
            user, self, perm_type, item, distroseries=distroseries
        )

    def getAllPermissions(self):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.permissionsForArchive(self)

    def getPermissionsForPerson(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.permissionsForPerson(self, person)

    def getUploadersForPackage(self, source_package_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.uploadersForPackage(self, source_package_name)

    def getUploadersForComponent(self, component_name=None):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.uploadersForComponent(self, component_name)

    def getUploadersForPocket(self, pocket):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.uploadersForPocket(self, pocket)

    def getQueueAdminsForComponent(self, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.queueAdminsForComponent(self, component_name)

    def getComponentsForQueueAdmin(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.componentsForQueueAdmin(self, person)

    def getQueueAdminsForPocket(self, pocket, distroseries=None):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.queueAdminsForPocket(
            self, pocket, distroseries=distroseries
        )

    def getPocketsForQueueAdmin(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.pocketsForQueueAdmin(self, person)

    def hasAnyPermission(self, person):
        """See `IArchive`."""
        any_perm_on_archive = Store.of(self).find(
            TeamParticipation,
            ArchivePermission.archive == self.id,
            TeamParticipation.person == person,
            TeamParticipation.team == ArchivePermission.person_id,
        )
        return not any_perm_on_archive.is_empty()

    def getBuildCounters(self, include_needsbuild=True):
        """See `IArchiveSet`."""

        # First grab a count of each build state for all the builds in
        # this archive:
        store = Store.of(self)
        extra_exprs = []
        if not include_needsbuild:
            extra_exprs.append(
                BinaryPackageBuild.status != BuildStatus.NEEDSBUILD
            )

        result = (
            store.find(
                (BinaryPackageBuild.status, Count(BinaryPackageBuild.id)),
                BinaryPackageBuild.archive == self,
                *extra_exprs,
            )
            .group_by(BinaryPackageBuild.status)
            .order_by(BinaryPackageBuild.status)
        )

        # Create a map for each count summary to a number of buildstates:
        count_map = {
            "failed": (
                BuildStatus.CHROOTWAIT,
                BuildStatus.FAILEDTOBUILD,
                BuildStatus.FAILEDTOUPLOAD,
                BuildStatus.MANUALDEPWAIT,
            ),
            "pending": [
                BuildStatus.BUILDING,
                BuildStatus.GATHERING,
                BuildStatus.UPLOADING,
            ],
            "succeeded": (BuildStatus.FULLYBUILT,),
            "superseded": (BuildStatus.SUPERSEDED,),
            # The 'total' count is a list because we may append to it
            # later.
            "total": [
                BuildStatus.CHROOTWAIT,
                BuildStatus.FAILEDTOBUILD,
                BuildStatus.FAILEDTOUPLOAD,
                BuildStatus.MANUALDEPWAIT,
                BuildStatus.BUILDING,
                BuildStatus.GATHERING,
                BuildStatus.UPLOADING,
                BuildStatus.FULLYBUILT,
                BuildStatus.SUPERSEDED,
            ],
        }

        # If we were asked to include builds with the state NEEDSBUILD,
        # then include those builds in the 'pending' and total counts.
        if include_needsbuild:
            count_map["pending"].append(BuildStatus.NEEDSBUILD)
            count_map["total"].append(BuildStatus.NEEDSBUILD)

        # Initialize all the counts in the map to zero:
        build_counts = {count_type: 0 for count_type in count_map}

        # For each count type that we want to return ('failed', 'total'),
        # there may be a number of corresponding buildstate counts.
        # So for each buildstate count in the result set...
        for buildstate, count in result:
            # ...go through the count map checking which counts this
            # buildstate belongs to and add it to the aggregated
            # count.
            for count_type, build_states in count_map.items():
                if buildstate in build_states:
                    build_counts[count_type] += count

        return build_counts

    def getBuildSummariesForSourceIds(self, source_ids):
        """See `IArchive`."""
        publishing_set = getUtility(IPublishingSet)
        return publishing_set.getBuildStatusSummariesForSourceIdsAndArchive(
            source_ids, archive=self
        )

    def checkArchivePermission(self, user, item=None):
        """See `IArchive`."""
        # PPA access is immediately granted if the user is in the PPA
        # team.
        if self.is_ppa:
            if user.inTeam(self.owner):
                return True
            else:
                # If the user is not in the PPA team, default to using
                # the main component for further ACL checks.  This is
                # not ideal since PPAs don't use components, but when
                # packagesets replace them for main archive uploads this
                # interface will no longer require them because we can
                # then relax the database constraint on
                # ArchivePermission.
                item = self.default_component

        # Flatly refuse uploads to copy archives, at least for now.
        if self.is_copy:
            return False

        # Otherwise any archive, including PPAs, uses the standard
        # ArchivePermission entries.
        return self._authenticate(user, item, ArchivePermissionType.UPLOAD)

    def canUploadSuiteSourcePackage(self, person, suitesourcepackage):
        """See `IArchive`."""
        sourcepackage = suitesourcepackage.sourcepackage
        pocket = suitesourcepackage.pocket
        distroseries = sourcepackage.distroseries
        sourcepackagename = sourcepackage.sourcepackagename
        component = sourcepackage.latest_published_component
        # strict_component is True because the source package already
        # exists (otherwise we couldn't have a suitesourcepackage
        # object) and nascentupload passes True as a matter of policy
        # when the package exists.
        reason = self.checkUpload(
            person,
            distroseries,
            sourcepackagename,
            component,
            pocket,
            strict_component=True,
        )
        return reason is None

    def canModifySuite(self, distroseries, pocket):
        """See `IArchive`."""
        # PPA and PARTNER allow everything.
        if self.allowUpdatesToReleasePocket():
            return True

        # Allow everything for distroseries in FROZEN state.
        if distroseries.status == SeriesStatus.FROZEN:
            return True

        # Define stable/released states.
        stable_states = (
            SeriesStatus.SUPPORTED,
            SeriesStatus.CURRENT,
            SeriesStatus.OBSOLETE,
        )

        # Deny uploads for RELEASE pocket in stable states.
        if (
            pocket == PackagePublishingPocket.RELEASE
            and distroseries.status in stable_states
        ):
            return False

        # Deny uploads for post-release-only pockets in unstable states.
        pre_release_pockets = (
            PackagePublishingPocket.RELEASE,
            PackagePublishingPocket.PROPOSED,
            PackagePublishingPocket.BACKPORTS,
        )
        if (
            pocket not in pre_release_pockets
            and distroseries.status not in stable_states
        ):
            return False

        # Allow anything else.
        return True

    def checkUploadToPocket(self, distroseries, pocket, person=None):
        """See `IArchive`."""
        if self.is_partner:
            if pocket not in (
                PackagePublishingPocket.RELEASE,
                PackagePublishingPocket.PROPOSED,
            ):
                return InvalidPocketForPartnerArchive()
        elif self.is_ppa:
            if pocket != PackagePublishingPocket.RELEASE:
                return InvalidPocketForPPA()
        elif self.is_copy:
            # Any pocket is allowed for COPY archives, otherwise it can
            # make the buildd-manager throw exceptions when dispatching
            # existing builds after a series is released.
            return
        else:
            if (
                self.purpose == ArchivePurpose.PRIMARY
                and person is not None
                and not self.canAdministerQueue(
                    person, pocket=pocket, distroseries=distroseries
                )
                and pocket == PackagePublishingPocket.RELEASE
                and self.distribution.redirect_release_uploads
            ):
                return RedirectedPocket(
                    distroseries, pocket, PackagePublishingPocket.PROPOSED
                )
            # Uploads to the partner archive are allowed in any distroseries
            # state.
            # XXX julian 2005-05-29 bug=117557:
            # This is a greasy hack until bug #117557 is fixed.
            if not self.canModifySuite(distroseries, pocket):
                return CannotUploadToPocket(distroseries, pocket)

    def _checkUpload(
        self,
        person,
        distroseries,
        sourcepackagename,
        component,
        pocket,
        strict_component=True,
    ):
        """See `IArchive`."""
        if isinstance(component, str):
            component = getUtility(IComponentSet)[component]
        if isinstance(sourcepackagename, str):
            sourcepackagename = getUtility(ISourcePackageNameSet)[
                sourcepackagename
            ]
        reason = self.checkUpload(
            person,
            distroseries,
            sourcepackagename,
            component,
            pocket,
            strict_component,
        )
        if reason is not None:
            raise reason
        return True

    def checkUpload(
        self,
        person,
        distroseries,
        sourcepackagename,
        component,
        pocket,
        strict_component=True,
    ):
        """See `IArchive`."""
        reason = self.checkUploadToPocket(distroseries, pocket)
        if reason is not None:
            return reason
        return self.verifyUpload(
            person,
            sourcepackagename,
            component,
            distroseries,
            strict_component=strict_component,
            pocket=pocket,
        )

    def verifyUpload(
        self,
        person,
        sourcepackagename,
        component,
        distroseries,
        strict_component=True,
        pocket=None,
    ):
        """See `IArchive`."""
        if not self.enabled:
            return ArchiveDisabled(self.displayname)

        # If the target series is OBSOLETE and permit_obsolete_series_uploads
        # is not set, reject.
        if (
            distroseries
            and distroseries.status == SeriesStatus.OBSOLETE
            and not self.permit_obsolete_series_uploads
        ):
            return CannotUploadToSeries(distroseries)

        # For PPAs...
        if self.is_ppa:
            if not self.checkArchivePermission(person):
                return CannotUploadToPPA()
            else:
                return None

        # Users with pocket upload permissions may upload to anything in the
        # given pocket.
        if pocket is not None and self.checkArchivePermission(person, pocket):
            return None

        if sourcepackagename is not None:
            # Check whether user may upload because they hold a permission for
            #   - the given source package directly
            #   - a package set in the correct distro series that includes the
            #     given source package
            source_allowed = self.checkArchivePermission(
                person, sourcepackagename
            )
            set_allowed = self.isSourceUploadAllowed(
                sourcepackagename, person, distroseries
            )
            if source_allowed or set_allowed:
                return None

        if self.getComponentsForUploader(person).is_empty():
            if self.getPackagesetsForUploader(person).is_empty():
                return NoRightsForArchive()
            else:
                return InsufficientUploadRights()

        if (
            component is not None
            and strict_component
            and not self.checkArchivePermission(person, component)
        ):
            return NoRightsForComponent(component)

        return None

    def canAdministerQueue(
        self, user, components=None, pocket=None, distroseries=None
    ):
        """See `IArchive`."""
        if components is None:
            components = []
        elif IComponent.providedBy(components):
            components = [components]
        component_permissions = self.getComponentsForQueueAdmin(user)
        if not component_permissions.is_empty():
            allowed_components = {
                permission.component for permission in component_permissions
            }
            # The intersection of allowed_components and components must be
            # equal to components to allow the operation to go ahead.
            if allowed_components.intersection(components) == set(components):
                return True
        if pocket is not None:
            pocket_permissions = self.getPocketsForQueueAdmin(user)
            for permission in pocket_permissions:
                if (
                    permission.pocket == pocket
                    and permission.distroseries in (None, distroseries)
                ):
                    return True
        return False

    def _authenticate(self, user, item, permission, distroseries=None):
        """Private helper method to check permissions."""
        permissions = self.getPermissions(
            user, item, permission, distroseries=distroseries
        )
        return not permissions.is_empty()

    def newPackageUploader(self, person, source_package_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newPackageUploader(
            self, person, source_package_name
        )

    def newPackagesetUploader(self, person, packageset, explicit=False):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newPackagesetUploader(
            self, person, packageset, explicit
        )

    def newComponentUploader(self, person, component_name):
        """See `IArchive`."""
        if self.is_ppa:
            if IComponent.providedBy(component_name):
                name = component_name.name
            elif isinstance(component_name, str):
                name = component_name
            else:
                name = None

            if name != self.default_component.name:
                raise InvalidComponent(
                    "Component for PPAs should be '%s'"
                    % self.default_component.name
                )

        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newComponentUploader(
            self, person, component_name
        )

    def newPocketUploader(self, person, pocket):
        if self.is_partner:
            if pocket not in (
                PackagePublishingPocket.RELEASE,
                PackagePublishingPocket.PROPOSED,
            ):
                raise InvalidPocketForPartnerArchive()
        elif self.is_ppa:
            if pocket != PackagePublishingPocket.RELEASE:
                raise InvalidPocketForPPA()

        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newPocketUploader(self, person, pocket)

    def newQueueAdmin(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newQueueAdmin(self, person, component_name)

    def newPocketQueueAdmin(self, person, pocket, distroseries=None):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.newPocketQueueAdmin(
            self, person, pocket, distroseries=distroseries
        )

    def deletePackageUploader(self, person, source_package_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deletePackageUploader(
            self, person, source_package_name
        )

    def deleteComponentUploader(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deleteComponentUploader(
            self, person, component_name
        )

    def deletePocketUploader(self, person, pocket):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deletePocketUploader(self, person, pocket)

    def deleteQueueAdmin(self, person, component_name):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deleteQueueAdmin(self, person, component_name)

    def deletePocketQueueAdmin(self, person, pocket, distroseries=None):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deletePocketQueueAdmin(
            self, person, pocket, distroseries=distroseries
        )

    def getUploadersForPackageset(self, packageset, direct_permissions=True):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.uploadersForPackageset(
            self, packageset, direct_permissions
        )

    def deletePackagesetUploader(self, person, packageset, explicit=False):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.deletePackagesetUploader(
            self, person, packageset, explicit
        )

    def getComponentsForUploader(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.componentsForUploader(self, person)

    def getPocketsForUploader(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.pocketsForUploader(self, person)

    def getPackagesetsForUploader(self, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.packagesetsForUploader(self, person)

    def getPackagesetsForSourceUploader(self, sourcepackagename, person):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.packagesetsForSourceUploader(
            self, sourcepackagename, person
        )

    def getPackagesetsForSource(
        self, sourcepackagename, direct_permissions=True
    ):
        """See `IArchive`."""
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.packagesetsForSource(
            self, sourcepackagename, direct_permissions
        )

    def isSourceUploadAllowed(
        self, sourcepackagename, person, distroseries=None
    ):
        """See `IArchive`."""
        if distroseries is None:
            distroseries = self.distribution.currentseries
        permission_set = getUtility(IArchivePermissionSet)
        return permission_set.isSourceUploadAllowed(
            self, sourcepackagename, person, distroseries
        )

    def getFileByName(self, filename):
        """See `IArchive`."""
        base_clauses = (
            LibraryFileAlias.filename == filename,
            LibraryFileAlias.content != None,
        )

        if re_issource.match(filename):
            clauses = (
                SourcePackagePublishingHistory.archive == self.id,
                SourcePackagePublishingHistory.sourcepackagerelease_id
                == SourcePackageReleaseFile.sourcepackagerelease_id,
                SourcePackageReleaseFile.libraryfile_id == LibraryFileAlias.id,
            )
        elif re_isadeb.match(filename):
            clauses = (
                BinaryPackagePublishingHistory.archive == self.id,
                BinaryPackagePublishingHistory.binarypackagerelease_id
                == BinaryPackageFile.binarypackagerelease_id,
                BinaryPackageFile.libraryfile_id == LibraryFileAlias.id,
            )
        elif filename.endswith(".changes"):
            clauses = (
                SourcePackagePublishingHistory.archive == self.id,
                SourcePackagePublishingHistory.sourcepackagerelease_id
                == PackageUploadSource.sourcepackagerelease_id,
                PackageUploadSource.packageupload_id == PackageUpload.id,
                PackageUpload.status == PackageUploadStatus.DONE,
                PackageUpload.changes_file_id == LibraryFileAlias.id,
            )
        else:
            raise NotFoundError(filename)

        def do_query():
            result = IStore(LibraryFileAlias).find(
                LibraryFileAlias, *(base_clauses + clauses)
            )
            result = result.config(distinct=True)
            result.order_by(LibraryFileAlias.id)
            return result.first()

        archive_file = do_query()

        if archive_file is None:
            # If a diff.gz wasn't found in the source-files domain, try in
            # the PackageDiff domain.
            if filename.endswith(".diff.gz"):
                clauses = (
                    SourcePackagePublishingHistory.archive == self.id,
                    SourcePackagePublishingHistory.sourcepackagerelease_id
                    == PackageDiff.to_source_id,
                    PackageDiff.diff_content_id == LibraryFileAlias.id,
                )
                package_diff_file = do_query()
                if package_diff_file is not None:
                    return package_diff_file

            raise NotFoundError(filename)

        return archive_file

    def getSourceFileByName(self, name, version, filename):
        """See `IArchive`."""
        result = IStore(LibraryFileAlias).find(
            LibraryFileAlias,
            SourcePackagePublishingHistory.archive == self,
            SourcePackagePublishingHistory.sourcepackagerelease_id
            == SourcePackageRelease.id,
            SourcePackageRelease.sourcepackagename == SourcePackageName.id,
            SourcePackageName.name == name,
            Cast(SourcePackageRelease.version, "text") == version,
            SourcePackageRelease.id
            == SourcePackageReleaseFile.sourcepackagerelease_id,
            SourcePackageReleaseFile.libraryfile_id == LibraryFileAlias.id,
            LibraryFileAlias.filename == filename,
            LibraryFileAlias.content != None,
        )
        result = result.config(distinct=True).order_by(LibraryFileAlias.id)
        # Unlike `getFileByName`, we are guaranteed at most one match even
        # for files in imported archives.
        archive_file = result.one()
        if archive_file is None:
            raise NotFoundError(filename)
        return archive_file

    def getPoolFileByPath(
        self, path: PurePath, live_at: typing.Optional[datetime] = None
    ) -> typing.Optional[LibraryFileAlias]:
        """See `IArchive`."""
        try:
            component, source, filename = unpoolify(PurePath(*path.parts[1:]))
        except ValueError:
            return None
        if filename is None:
            return None

        store = IStore(LibraryFileAlias)
        clauses = [
            Component.name == component,
            SourcePackageName.name == source,
            LibraryFileAlias.filename == filename,
        ]
        # Decide whether to look for source or binary publications.  We
        # could just try both and UNION them, but this query is likely to be
        # hot and is complex enough as it is, so don't push our luck.
        binary = determine_binary_file_type(filename) is not None
        if binary:
            xPPH = BinaryPackagePublishingHistory
            xPF = BinaryPackageFile
            # XXX cjwatson 20220922: Simplify this once
            # BinaryPackagePublishingHistory.sourcepackagename has finished
            # populating.
            clauses.extend(
                [
                    BinaryPackagePublishingHistory.binarypackagerelease
                    == BinaryPackageRelease.id,
                    BinaryPackageRelease.build == BinaryPackageBuild.id,
                    BinaryPackageBuild.source_package_name
                    == SourcePackageName.id,
                    BinaryPackagePublishingHistory.binarypackagerelease
                    == BinaryPackageFile.binarypackagerelease_id,
                ]
            )
        else:
            xPPH = SourcePackagePublishingHistory
            xPF = SourcePackageReleaseFile
            clauses.extend(
                [
                    SourcePackagePublishingHistory.sourcepackagename
                    == SourcePackageName.id,
                    SourcePackagePublishingHistory.sourcepackagerelease
                    == SourcePackageReleaseFile.sourcepackagerelease_id,
                ]
            )
        clauses.extend(
            [
                xPPH.archive == self,
                xPPH.component == Component.id,
                xPPH.datepublished != None,
                xPF.libraryfile == LibraryFileAlias.id,
            ]
        )
        if live_at:
            clauses.extend(
                [
                    xPPH.datepublished <= live_at,
                    Or(
                        xPPH.dateremoved == None,
                        xPPH.dateremoved > live_at,
                    ),
                ]
            )
        else:
            clauses.append(xPPH.dateremoved == None)
        return (
            store.find(LibraryFileAlias, *clauses)
            .config(distinct=True)
            .order_by("id")
            .last()
        )

    def getBinaryPackageRelease(self, name, version, archtag):
        """See `IArchive`."""
        from lp.soyuz.model.distroarchseries import DistroArchSeries

        results = (
            IStore(BinaryPackageRelease)
            .find(
                BinaryPackageRelease,
                BinaryPackagePublishingHistory.archive == self,
                BinaryPackagePublishingHistory.binarypackagename == name,
                BinaryPackagePublishingHistory.binarypackagerelease_id
                == BinaryPackageRelease.id,
                Cast(BinaryPackageRelease.version, "text") == version,
                BinaryPackageBuild.id == BinaryPackageRelease.build_id,
                DistroArchSeries.id
                == BinaryPackageBuild.distro_arch_series_id,
                DistroArchSeries.architecturetag == archtag,
            )
            .config(distinct=True)
        )
        if results.count() > 1:
            return None
        return results.one()

    def getBinaryPackageReleaseByFileName(self, filename):
        return (
            IStore(BinaryPackageRelease)
            .find(
                BinaryPackageRelease,
                BinaryPackageFile.binarypackagerelease_id
                == BinaryPackageRelease.id,
                BinaryPackageFile.libraryfile_id == LibraryFileAlias.id,
                LibraryFileAlias.filename == filename,
                BinaryPackagePublishingHistory.archive == self,
                BinaryPackagePublishingHistory.binarypackagerelease_id
                == BinaryPackageRelease.id,
            )
            .order_by(Desc(BinaryPackagePublishingHistory.id))
            .first()
        )

    def requestPackageCopy(
        self,
        target_location,
        requestor,
        suite=None,
        copy_binaries=False,
        reason=None,
    ):
        """See `IArchive`."""
        if suite is None:
            distroseries = self.distribution.currentseries
            pocket = PackagePublishingPocket.RELEASE
        else:
            # Note: a NotFoundError will be raised if it is not found.
            distroseries, pocket = self.distribution.getDistroSeriesAndPocket(
                suite
            )

        source_location = PackageLocation(
            self, self.distribution, distroseries, pocket
        )

        return getUtility(IPackageCopyRequestSet).new(
            source_location, target_location, requestor, copy_binaries, reason
        )

    def syncSources(
        self,
        source_names,
        from_archive,
        to_pocket,
        to_series=None,
        from_series=None,
        include_binaries=False,
        person=None,
    ):
        """See `IArchive`."""
        # Find and validate the source package names in source_names.
        sources = self._collectLatestPublishedSources(
            from_archive, from_series, source_names
        )
        self._copySources(
            sources, to_pocket, to_series, include_binaries, person=person
        )

    def _validateAndFindSource(
        self,
        from_archive,
        source_name,
        version,
        from_series=None,
        from_pocket=None,
    ):
        # Check to see if the source package exists, and raise a useful error
        # if it doesn't.
        getUtility(ISourcePackageNameSet)[source_name]
        # Find and validate the source package version required.
        source = from_archive.getPublishedSources(
            name=source_name,
            version=version,
            exact_match=True,
            distroseries=from_series,
            pocket=from_pocket,
        ).first()
        if source is None:
            raise CannotCopy(
                "%s is not published in %s."
                % (source_name, from_archive.displayname)
            )
        return source

    def syncSource(
        self,
        source_name,
        version,
        from_archive,
        to_pocket,
        to_series=None,
        include_binaries=False,
        person=None,
    ):
        """See `IArchive`."""
        source = self._validateAndFindSource(
            from_archive, source_name, version
        )

        self._copySources(
            [source], to_pocket, to_series, include_binaries, person=person
        )

    def copyPackage(
        self,
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
        """See `IArchive`."""
        # Asynchronously copy a package using the job system.
        from lp.soyuz.scripts.packagecopier import check_copy_permissions

        if phased_update_percentage is not None:
            if phased_update_percentage < 0 or phased_update_percentage > 100:
                raise ValueError(
                    "phased_update_percentage must be between 0 and 100 "
                    "(inclusive)."
                )
            elif phased_update_percentage == 100:
                phased_update_percentage = None
        pocket = self._text_to_pocket(to_pocket)
        series = self._text_to_series(to_series)
        if from_pocket:
            from_pocket = self._text_to_pocket(from_pocket)
        if from_series:
            from_series = self._text_to_series(
                from_series, distribution=from_archive.distribution
            )
        # Upload permission checks, this will raise CannotCopy as
        # necessary.
        source = self._validateAndFindSource(
            from_archive,
            source_name,
            version,
            from_series=from_series,
            from_pocket=from_pocket,
        )
        if series is None:
            series = source.distroseries
        check_copy_permissions(
            person, self, series, pocket, [source], move=move
        )

        job_source = getUtility(IPlainPackageCopyJobSource)
        job_source.create(
            package_name=source_name,
            source_archive=from_archive,
            target_archive=self,
            target_distroseries=series,
            target_pocket=pocket,
            package_version=version,
            include_binaries=include_binaries,
            copy_policy=PackageCopyPolicy.INSECURE,
            requester=person,
            sponsored=sponsored,
            unembargo=unembargo,
            auto_approve=auto_approve,
            silent=silent,
            source_distroseries=from_series,
            source_pocket=from_pocket,
            phased_update_percentage=phased_update_percentage,
            move=move,
        )

    def copyPackages(
        self,
        source_names,
        from_archive,
        to_pocket,
        person,
        to_series=None,
        from_series=None,
        include_binaries=None,
        sponsored=None,
        unembargo=False,
        auto_approve=False,
        silent=False,
        move=False,
    ):
        """See `IArchive`."""
        from lp.soyuz.scripts.packagecopier import check_copy_permissions

        sources = self._collectLatestPublishedSources(
            from_archive, from_series, source_names
        )

        # Now do a mass check of permissions.
        pocket = self._text_to_pocket(to_pocket)
        series = self._text_to_series(to_series)
        check_copy_permissions(
            person, self, series, pocket, sources, move=move
        )

        # If we get this far then we can create the PackageCopyJob.
        copy_tasks = []
        for source in sources:
            task = (
                source.sourcepackagerelease.sourcepackagename.name,
                source.sourcepackagerelease.version,
                from_archive,
                self,
                series if series is not None else source.distroseries,
                pocket,
            )
            copy_tasks.append(task)

        job_source = getUtility(IPlainPackageCopyJobSource)
        job_source.createMultiple(
            copy_tasks,
            person,
            copy_policy=PackageCopyPolicy.MASS_SYNC,
            include_binaries=include_binaries,
            sponsored=sponsored,
            unembargo=unembargo,
            auto_approve=auto_approve,
            silent=silent,
            move=move,
        )

    def _collectLatestPublishedSources(
        self, from_archive, from_series, source_names
    ):
        """Private helper to collect the latest published sources for an
        archive.

        :raises NoSuchSourcePackageName: If any of the source_names do not
            exist.
        :raises CannotCopy: If none of the source_names are published in
            from_archive.
        """
        from_series_obj = self._text_to_series(
            from_series, distribution=from_archive.distribution
        )
        # XXX bigjools bug=810421
        # This code is inefficient.  It should try to bulk load all the
        # sourcepackagenames and publications instead of iterating.
        sources = []
        for name in source_names:
            # Check to see if the source package exists. This will raise
            # a NoSuchSourcePackageName exception if the source package
            # doesn't exist.
            getUtility(ISourcePackageNameSet)[name]
            # Grabbing the item at index 0 ensures it's the most recent
            # publication.
            published_sources = from_archive.getPublishedSources(
                name=name,
                distroseries=from_series_obj,
                exact_match=True,
                status=active_publishing_status,
            )
            first_source = published_sources.first()
            if first_source is not None:
                sources.append(first_source)
        if not sources:
            raise CannotCopy(
                "None of the supplied package names are published in %s."
                % from_archive.displayname
            )
        return sources

    def _text_to_series(self, to_series, distribution=None):
        if distribution is None:
            distribution = self.distribution
        if to_series is not None:
            result = getUtility(IDistroSeriesSet).queryByName(
                distribution, to_series, follow_aliases=True
            )
            if result is None:
                raise NoSuchDistroSeries(to_series)
            series = result
        else:
            series = None

        return series

    def _text_to_pocket(self, to_pocket):
        # Convert the to_pocket string to its enum.
        try:
            pocket = PackagePublishingPocket.items[to_pocket.upper()]
        except KeyError:
            raise PocketNotFound(to_pocket.upper())

        return pocket

    def _copySources(
        self,
        sources,
        to_pocket,
        to_series=None,
        include_binaries=False,
        person=None,
    ):
        """Private helper function to copy sources to this archive.

        It takes a list of SourcePackagePublishingHistory but the other args
        are strings.
        """
        # Circular imports.
        from lp.soyuz.scripts.packagecopier import do_copy

        pocket = self._text_to_pocket(to_pocket)
        series = self._text_to_series(to_series)
        reason = self.checkUploadToPocket(series, pocket, person=person)
        if reason:
            # Wrap any forbidden-pocket error in CannotCopy.
            raise CannotCopy(str(reason))

        # Perform the copy, may raise CannotCopy. Don't do any further
        # permission checking: this method is protected by
        # launchpad.Append, which is mostly more restrictive than archive
        # permissions.
        do_copy(
            sources,
            self,
            series,
            pocket,
            include_binaries,
            person=person,
            check_permissions=False,
            unembargo=True,
        )

    def uploadCIBuild(
        self, ci_build, person, to_series, to_pocket, to_channel=None
    ):
        """See `IArchive`."""
        series = self._text_to_series(to_series)
        pocket = self._text_to_pocket(to_pocket)
        if self.publishing_method != ArchivePublishingMethod.ARTIFACTORY:
            raise CannotCopy(
                "CI builds may only be uploaded to archives published using "
                "Artifactory."
            )
        dsp = ci_build.git_repository.target
        if not IDistributionSourcePackage.providedBy(dsp):
            raise CannotCopy(
                "Only CI builds for repositories in package namespaces may be "
                "uploaded to archives."
            )
        if ci_build.status != BuildStatus.FULLYBUILT:
            raise CannotCopy(
                "%r has status '%s', not '%s'."
                % (ci_build, ci_build.status.title, BuildStatus.FULLYBUILT)
            )
        # Check upload permissions.
        reason = self.checkUpload(
            person=person,
            distroseries=series,
            sourcepackagename=dsp.sourcepackagename,
            component=None,
            pocket=pocket,
        )
        if reason is not None:
            raise CannotCopy(reason)
        getUtility(ICIBuildUploadJobSource).create(
            ci_build=ci_build,
            requester=person,
            target_archive=self,
            target_distroseries=series,
            target_pocket=pocket,
            target_channel=to_channel,
        )

    def getAuthToken(self, person):
        """See `IArchive`."""

        token_set = getUtility(IArchiveAuthTokenSet)
        return token_set.getActiveTokenForArchiveAndPerson(self, person)

    def newAuthToken(self, person, token=None, date_created=None):
        """See `IArchive`."""

        # Bail if the archive isn't private
        if not self.private:
            raise ArchiveNotPrivate("Archive must be private.")

        # Tokens can only be created for individuals.
        if person.is_team:
            raise NoTokensForTeams(
                "Subscription tokens can be created for individuals only."
            )

        # Ensure that the current subscription does not already have a token
        if self.getAuthToken(person) is not None:
            raise ArchiveSubscriptionError(
                "%s already has a token for %s."
                % (person.displayname, self.displayname)
            )

        # Now onto the actual token creation:
        if token is None:
            token = create_token(20)
        archive_auth_token = ArchiveAuthToken()
        archive_auth_token.archive = self
        archive_auth_token.person = person
        archive_auth_token.token = token
        if date_created is not None:
            archive_auth_token.date_created = date_created
        IStore(ArchiveAuthToken).add(archive_auth_token)
        return archive_auth_token

    def newNamedAuthToken(self, name, token=None, as_dict=False):
        """See `IArchive`."""

        if not getFeatureFlag(NAMED_AUTH_TOKEN_FEATURE_FLAG):
            raise NamedAuthTokenFeatureDisabled()

        # Bail if the archive isn't private
        if not self.private:
            raise ArchiveNotPrivate("Archive must be private.")

        try:
            # Check for duplicate name.
            self.getNamedAuthToken(name)
            raise DuplicateTokenName(
                "An active token with name %s for archive %s already exists."
                % (name, self.displayname)
            )
        except NotFoundError:
            # No duplicate name found: continue.
            pass

        # Now onto the actual token creation:
        if token is None:
            token = create_token(20)
        archive_auth_token = ArchiveAuthToken()
        archive_auth_token.archive = self
        archive_auth_token.name = name
        archive_auth_token.token = token
        IStore(ArchiveAuthToken).add(archive_auth_token)
        if as_dict:
            return archive_auth_token.asDict()
        else:
            return archive_auth_token

    def newNamedAuthTokens(self, names, as_dict=False):
        """See `IArchive`."""

        if not getFeatureFlag(NAMED_AUTH_TOKEN_FEATURE_FLAG):
            raise NamedAuthTokenFeatureDisabled()

        # Bail if the archive isn't private
        if not self.private:
            raise ArchiveNotPrivate("Archive must be private.")

        # Check for duplicate names.
        token_set = getUtility(IArchiveAuthTokenSet)
        dup_tokens = token_set.getActiveNamedTokensForArchive(self, names)
        dup_names = {token.name for token in dup_tokens}

        values = [
            (name, create_token(20), self) for name in set(names) - dup_names
        ]
        tokens = create(
            (
                ArchiveAuthToken.name,
                ArchiveAuthToken.token,
                ArchiveAuthToken.archive,
            ),
            values,
            get_objects=True,
        )

        # Return all requested tokens, including duplicates.
        tokens.extend(dup_tokens)
        if as_dict:
            return {token.name: token.asDict() for token in tokens}
        else:
            return tokens

    def getNamedAuthToken(self, name, as_dict=False):
        """See `IArchive`."""
        token_set = getUtility(IArchiveAuthTokenSet)
        auth_token = token_set.getActiveNamedTokenForArchive(self, name)
        if auth_token is not None:
            if as_dict:
                return auth_token.asDict()
            else:
                return auth_token
        else:
            raise NotFoundError(name)

    def getNamedAuthTokens(self, names=None, as_dict=False):
        """See `IArchive`."""
        token_set = getUtility(IArchiveAuthTokenSet)
        auth_tokens = token_set.getActiveNamedTokensForArchive(self, names)
        if as_dict:
            return [auth_token.asDict() for auth_token in auth_tokens]
        else:
            return auth_tokens

    def revokeNamedAuthToken(self, name):
        """See `IArchive`."""
        token_set = getUtility(IArchiveAuthTokenSet)
        auth_token = token_set.getActiveNamedTokenForArchive(self, name)
        if auth_token is not None:
            auth_token.deactivate()
        else:
            raise NotFoundError(name)

    def revokeNamedAuthTokens(self, names):
        """See `IArchive`."""
        token_set = getUtility(IArchiveAuthTokenSet)
        token_set.deactivateNamedTokensForArchive(self, names)

    def setMetadataOverrides(self, metadata_overrides):
        """See `IArchive`."""
        allowed_keys = sorted(["Origin", "Label", "Suite", "Snapshots"])

        if not all(key in allowed_keys for key in metadata_overrides.keys()):
            allowed_keys_str = ", ".join(f"'{k}'" for k in allowed_keys)
            raise CannotSetMetadataOverrides(
                "Invalid metadata override key. Allowed keys are "
                f"{{{allowed_keys_str}}}."
            )

        for key, value in metadata_overrides.items():
            if not isinstance(value, str) or not value:
                raise CannotSetMetadataOverrides(
                    f"Value for '{key}' must be a non-empty string."
                )

        self.metadata_overrides = metadata_overrides

    def newSubscription(
        self, subscriber, registrant, date_expires=None, description=None
    ):
        """See `IArchive`."""
        from lp.soyuz.model.archivesubscriber import ArchiveSubscriber

        # We do not currently allow subscriptions for non-private archives:
        if self.private is False:
            raise ArchiveNotPrivate(
                "Only private archives can have subscriptions."
            )

        # Ensure there is not already a current subscription for subscriber:
        subscriptions = getUtility(IArchiveSubscriberSet).getBySubscriber(
            subscriber, archive=self
        )
        if not subscriptions.is_empty():
            raise AlreadySubscribed(
                "%s already has a current subscription for '%s'."
                % (subscriber.displayname, self.displayname)
            )

        subscription = ArchiveSubscriber()
        subscription.archive = self
        subscription.registrant = registrant
        subscription.subscriber = subscriber
        subscription.date_expires = date_expires
        subscription.description = description
        subscription.status = ArchiveSubscriberStatus.CURRENT
        subscription.date_created = UTC_NOW
        IStore(ArchiveSubscriber).add(subscription)

        # Notify any listeners that a new subscription was created.
        # This is used currently for sending email notifications.
        notify(ObjectCreatedEvent(subscription))

        return subscription

    @property
    def num_pkgs_building(self):
        """See `IArchive`."""
        store = Store.of(self)

        sprs_building = store.find(
            BinaryPackageBuild.source_package_release_id,
            BinaryPackageBuild.archive == self,
            BinaryPackageBuild.status == BuildStatus.BUILDING,
        )
        sprs_waiting = store.find(
            BinaryPackageBuild.source_package_release_id,
            BinaryPackageBuild.archive == self,
            BinaryPackageBuild.status == BuildStatus.NEEDSBUILD,
        )

        # A package is not counted as waiting if it already has at least
        # one build building.
        pkgs_building_count = sprs_building.count()
        pkgs_waiting_count = sprs_waiting.difference(sprs_building).count()

        return pkgs_building_count, pkgs_waiting_count

    def updatePackageDownloadCount(self, bpr, day, country, count):
        """See `IArchive`."""
        store = Store.of(self)
        entry = store.find(
            BinaryPackageReleaseDownloadCount,
            archive=self,
            binary_package_release=bpr,
            day=day,
            country=country,
        ).one()
        if entry is None:
            entry = BinaryPackageReleaseDownloadCount(
                archive=self,
                binary_package_release=bpr,
                day=day,
                country=country,
                count=count,
            )
        else:
            entry.count += count

    def getPackageDownloadTotal(self, bpr):
        """See `IArchive`."""
        store = Store.of(self)
        count = store.find(
            Sum(BinaryPackageReleaseDownloadCount.count),
            BinaryPackageReleaseDownloadCount.archive == self,
            BinaryPackageReleaseDownloadCount.binary_package_release == bpr,
        ).one()
        return count or 0

    def getPackageDownloadCount(self, bpr, day, country):
        """See `IArchive`."""
        return (
            Store.of(self)
            .find(
                BinaryPackageReleaseDownloadCount,
                archive=self,
                binary_package_release=bpr,
                day=day,
                country=country,
            )
            .one()
        )

    def _setBuildQueueStatuses(self, status):
        """Update the pending BuildQueues' statuses for this archive."""
        Store.of(self).execute(
            """
            UPDATE BuildQueue SET status = %s
            FROM BinaryPackageBuild
            WHERE
                -- insert self.id here
                BinaryPackageBuild.archive = %s
                AND BuildQueue.build_farm_job =
                    BinaryPackageBuild.build_farm_job
                -- Build is in state BuildStatus.NEEDSBUILD (0)
                AND BinaryPackageBuild.status = %s
                AND BuildQueue.status != %s;
            """,
            params=(
                status.value,
                self.id,
                BuildStatus.NEEDSBUILD.value,
                status.value,
            ),
        )

    def _recalculateBuildVirtualization(self):
        """Update virtualized columns for this archive."""
        store = Store.of(self)
        bpb_clauses = [
            BinaryPackageBuild.archive == self,
            BinaryPackageBuild.status == BuildStatus.NEEDSBUILD,
        ]
        bq_clauses = bpb_clauses + [
            BuildQueue._build_farm_job_id
            == BinaryPackageBuild.build_farm_job_id,
        ]
        if self.require_virtualized:
            # We can avoid the Processor join in this case.
            value = True
            match = False
            proc_tables = []
            proc_clauses = []
            # BulkUpdate doesn't support an empty list of values.
            bpb_rows = store.find(
                BinaryPackageBuild,
                BinaryPackageBuild.virtualized == match,
                *bpb_clauses,
            )
            bpb_rows.set(virtualized=value)
        else:
            value = Not(Processor.supports_nonvirtualized)
            match = Processor.supports_nonvirtualized
            proc_tables = [Processor]
            proc_clauses = [BinaryPackageBuild.processor_id == Processor.id]
            store.execute(
                BulkUpdate(
                    {BinaryPackageBuild.virtualized: value},
                    table=BinaryPackageBuild,
                    values=proc_tables,
                    where=And(
                        BinaryPackageBuild.virtualized == match,
                        *(bpb_clauses + proc_clauses),
                    ),
                )
            )
        store.execute(
            BulkUpdate(
                {BuildQueue.virtualized: value},
                table=BuildQueue,
                values=([BinaryPackageBuild] + proc_tables),
                where=And(
                    BuildQueue.virtualized == match,
                    *(bq_clauses + proc_clauses),
                ),
            )
        )
        store.invalidate()

    def enable(self):
        """See `IArchive`."""
        assert self._enabled == False, "This archive is already enabled."
        assert self.is_active, "Deleted archives can't be enabled."
        self._enabled = True
        self._setBuildQueueStatuses(BuildQueueStatus.WAITING)
        # Suspended builds may have the wrong virtualization setting (due to
        # changes to either Archive.require_virtualized or
        # Processor.supports_nonvirtualized) and need to be updated.
        self._recalculateBuildVirtualization()

    def disable(self):
        """See `IArchive`."""
        assert self._enabled == True, "This archive is already disabled."
        self._enabled = False
        self._setBuildQueueStatuses(BuildQueueStatus.SUSPENDED)

    def delete(self, deleted_by):
        """See `IArchive`."""
        if self.status != ArchiveStatus.ACTIVE:
            raise ArchiveAlreadyDeleted("Archive already deleted.")

        # Mark the archive's status as DELETING so the repository can be
        # removed by the publisher.
        self.status = ArchiveStatus.DELETING
        if self.enabled:
            self.disable()

    def getFilesAndSha1s(self, source_files):
        """See `IArchive`."""
        return dict(
            Store.of(self)
            .find(
                (LibraryFileAlias.filename, LibraryFileContent.sha1),
                SourcePackagePublishingHistory.archive == self,
                SourcePackagePublishingHistory.sourcepackagerelease
                == SourcePackageReleaseFile.sourcepackagerelease_id,
                LibraryFileAlias.id == SourcePackageReleaseFile.libraryfile_id,
                LibraryFileAlias.filename.is_in(source_files),
                LibraryFileContent.id == LibraryFileAlias.content_id,
            )
            .config(distinct=True)
        )

    def _getEnabledRestrictedProcessors(self):
        """Retrieve the restricted architectures this archive can build on."""
        return [proc for proc in self.processors if proc.restricted]

    def _setEnabledRestrictedProcessors(self, value):
        """Set the restricted architectures this archive can build on."""
        self.setProcessors(
            [proc for proc in self.processors if not proc.restricted]
            + list(value)
        )

    enabled_restricted_processors = property(
        _getEnabledRestrictedProcessors, _setEnabledRestrictedProcessors
    )

    def enableRestrictedProcessor(self, processor):
        """See `IArchive`."""
        # This method can only be called by people with launchpad.Admin, so
        # we don't need to check permissions again.
        self.setProcessors(set(self.processors + [processor]))

    @property
    def available_processors(self):
        """See `IArchive`."""
        # Circular imports.
        from lp.registry.model.distroseries import DistroSeries
        from lp.soyuz.model.distroarchseries import DistroArchSeries

        clauses = [
            Processor.id == DistroArchSeries.processor_id,
            DistroArchSeries.distroseries == DistroSeries.id,
            DistroSeries.distribution == self.distribution,
        ]
        if not self.permit_obsolete_series_uploads:
            clauses.append(DistroSeries.status != SeriesStatus.OBSOLETE)
        return Store.of(self).find(Processor, *clauses).config(distinct=True)

    def _getProcessors(self):
        return list(
            Store.of(self).find(
                Processor,
                Processor.id == ArchiveArch.processor_id,
                ArchiveArch.archive == self,
            )
        )

    def setProcessors(self, processors, check_permissions=False, user=None):
        """See `IArchive`."""
        if check_permissions:
            can_modify = None
            if user is not None:
                roles = IPersonRoles(user)
                authz = lambda perm: getAdapter(self, IAuthorization, perm)
                if authz("launchpad.Admin").checkAuthenticated(roles):
                    can_modify = lambda proc: True
                elif authz("launchpad.Edit").checkAuthenticated(roles):
                    can_modify = lambda proc: not proc.restricted
            if can_modify is None:
                raise Unauthorized(
                    "Permission launchpad.Admin or launchpad.Edit required "
                    "on %s." % self
                )
        else:
            can_modify = lambda proc: True

        enablements = dict(
            Store.of(self).find(
                (Processor, ArchiveArch),
                Processor.id == ArchiveArch.processor_id,
                ArchiveArch.archive == self,
            )
        )
        for proc in enablements:
            if proc not in processors:
                if not can_modify(proc):
                    raise CannotModifyArchiveProcessor(proc)
                Store.of(self).remove(enablements[proc])
        for proc in processors:
            if proc not in self.processors:
                if not can_modify(proc):
                    raise CannotModifyArchiveProcessor(proc)
                archivearch = ArchiveArch()
                archivearch.archive = self
                archivearch.processor = proc
                Store.of(self).add(archivearch)

    processors = property(_getProcessors, setProcessors)

    def getPockets(self):
        """See `IArchive`."""
        if self.is_ppa:
            return [PackagePublishingPocket.RELEASE]

        # Cast to a list so we don't trip up with the security proxy not
        # understanding EnumItems.
        return list(PackagePublishingPocket.items)

    def _getExistingOverrideSequence(
        self, archive, distroseries, pocket, phased_update_percentage
    ):
        from lp.soyuz.adapters.overrides import FromExistingOverridePolicy

        return [
            FromExistingOverridePolicy(
                archive,
                distroseries,
                None,
                phased_update_percentage=phased_update_percentage,
            ),
            FromExistingOverridePolicy(
                archive,
                distroseries,
                None,
                phased_update_percentage=phased_update_percentage,
                any_arch=True,
            ),
            FromExistingOverridePolicy(
                archive,
                distroseries,
                None,
                phased_update_percentage=phased_update_percentage,
                include_deleted=True,
            ),
            FromExistingOverridePolicy(
                archive,
                distroseries,
                None,
                phased_update_percentage=phased_update_percentage,
                include_deleted=True,
                any_arch=True,
            ),
        ]

    def getOverridePolicy(
        self, distroseries, pocket, phased_update_percentage=None
    ):
        """See `IArchive`."""
        # Circular imports.
        from lp.soyuz.adapters.overrides import (
            ConstantOverridePolicy,
            FallbackOverridePolicy,
            FromSourceOverridePolicy,
            UnknownOverridePolicy,
        )

        if self.is_main:
            # If there's no matching live publication, fall back to
            # other archs, then to matching but deleted, then to deleted
            # on other archs, then to archive-specific defaults.
            policies = self._getExistingOverrideSequence(
                self,
                distroseries,
                None,
                phased_update_percentage=phased_update_percentage,
            )
            if self.is_primary:
                # If there are any parent relationships with
                # inherit_overrides set, run through those before using
                # defaults.
                parents = [
                    dsp.parent_series
                    for dsp in getUtility(
                        IDistroSeriesParentSet
                    ).getByDerivedSeries(distroseries)
                    if dsp.inherit_overrides
                ]
                for parent in parents:
                    policies.extend(
                        self._getExistingOverrideSequence(
                            parent.main_archive,
                            parent,
                            None,
                            phased_update_percentage=phased_update_percentage,
                        )
                    )

                policies.extend(
                    [
                        FromSourceOverridePolicy(
                            phased_update_percentage=phased_update_percentage
                        ),
                        UnknownOverridePolicy(
                            self,
                            distroseries,
                            pocket,
                            phased_update_percentage=phased_update_percentage,
                        ),
                    ]
                )
            elif self.is_partner:
                policies.append(
                    ConstantOverridePolicy(
                        component=getUtility(IComponentSet)["partner"],
                        phased_update_percentage=phased_update_percentage,
                        new=True,
                    )
                )
            return FallbackOverridePolicy(policies)
        elif self.is_ppa:
            return ConstantOverridePolicy(
                component=getUtility(IComponentSet)["main"]
            )
        elif self.is_copy:
            return self.distribution.main_archive.getOverridePolicy(
                distroseries,
                pocket,
                phased_update_percentage=phased_update_percentage,
            )
        raise AssertionError(
            "No IOverridePolicy for purpose %r" % self.purpose
        )

    def removeCopyNotification(self, job_id):
        """See `IArchive`."""
        # Circular imports R us.
        from lp.soyuz.model.packagecopyjob import PlainPackageCopyJob

        pcj = PlainPackageCopyJob.get(job_id)
        job = pcj.job
        if job.status != JobStatus.FAILED:
            raise AssertionError("Job is not failed")
        Store.of(pcj.context).remove(pcj.context)
        job.destroySelf()

    def markSuiteDirty(self, distroseries, pocket):
        """See `IArchive`."""
        if distroseries.distribution != self.distribution:
            raise ValueError(
                "%s is not a series of %s." % (distroseries, self.distribution)
            )
        suite = distroseries.getSuite(pocket)
        if self.dirty_suites is None:
            self.dirty_suites = [suite]
        elif suite not in self.dirty_suites:
            self.dirty_suites.append(suite)

    @property
    def publishing_method(self):
        # XXX cjwatson 2022-04-04: Remove once this column has been backfilled.
        return (
            ArchivePublishingMethod.LOCAL
            if self._publishing_method is None
            else self._publishing_method
        )

    @publishing_method.setter
    def publishing_method(self, value):
        self._publishing_method = value

    @property
    def repository_format(self):
        # XXX cjwatson 2022-04-04: Remove once this column has been backfilled.
        return (
            ArchiveRepositoryFormat.DEBIAN
            if self._repository_format is None
            else self._repository_format
        )

    @repository_format.setter
    def repository_format(self, value):
        self._repository_format = value


def validate_ppa(owner, distribution, proposed_name, private=False):
    """Can 'person' create a PPA called 'proposed_name'?

    :param owner: The proposed owner of the PPA.
    :param proposed_name: The proposed name.
    :param private: Whether or not to make it private.
    """
    assert proposed_name is not None
    creator = getUtility(ILaunchBag).user
    if private:
        # NOTE: This duplicates the policy in lp/soyuz/configure.zcml
        # which says that one needs 'launchpad.Commercial' permission to set
        # 'private', and the logic in `AdminArchive` which determines
        # who is granted launchpad.Admin permissions. The difference is
        # that here we grant ability to set 'private' to people with a
        # commercial subscription.
        if not (owner.private or creator.checkAllowVisibility()):
            return "%s is not allowed to make private PPAs" % creator.name
    elif owner.private:
        return "Private teams may not have public archives."
    if owner.is_team and (owner.membership_policy in INCLUSIVE_TEAM_POLICY):
        return "Open teams cannot have PPAs."
    if not distribution.supports_ppas:
        return "%s does not support PPAs." % distribution.displayname
    if proposed_name == distribution.name:
        return "A PPA cannot have the same name as its distribution."
    if proposed_name == "ubuntu":
        return 'A PPA cannot be named "ubuntu".'
    try:
        owner.getPPAByName(distribution, proposed_name)
    except NoSuchPPA:
        return None
    else:
        text = "You already have a PPA for %s named '%s'." % (
            distribution.displayname,
            proposed_name,
        )
        if owner.is_team:
            text = "%s already has a PPA for %s named '%s'." % (
                owner.displayname,
                distribution.displayname,
                proposed_name,
            )
        return text


@implementer(IArchiveSet)
class ArchiveSet:
    title = "Archives registered in Launchpad"

    def get(self, archive_id):
        """See `IArchiveSet`."""
        return IStore(Archive).get(Archive, archive_id)

    def getByReference(self, reference, check_permissions=False, user=None):
        """See `IArchiveSet`."""
        from lp.registry.interfaces.distribution import IDistributionSet

        bits = reference.split("/")
        if len(bits) < 1:
            return None
        if bits[0].startswith("~") or bits[0].startswith("ppa:"):
            # PPA reference (~OWNER/DISTRO/ARCHIVE or ppa:OWNER/DISTRO/ARCHIVE)
            if len(bits) != 3:
                return None
            if bits[0].startswith("~"):
                first_bit = bits[0][1:]
            else:
                # ppa:OWNER
                first_bit = bits[0][4:]
            person = getUtility(IPersonSet).getByName(first_bit)
            if person is None:
                return None
            distro = getUtility(IDistributionSet).getByName(bits[1])
            if distro is None:
                return None
            archive = self.getPPAOwnedByPerson(
                person, distribution=distro, name=bits[2]
            )
        else:
            # Official archive reference (DISTRO or DISTRO/ARCHIVE)
            distro = getUtility(IDistributionSet).getByName(bits[0])
            if distro is None:
                return None
            if len(bits) == 1:
                archive = distro.main_archive
            elif len(bits) == 2:
                archive = self.getByDistroAndName(distro, bits[1])
            else:
                return None
        if archive is None or not check_permissions:
            return archive
        authz = getAdapter(
            removeSecurityProxy(archive),
            IAuthorization,
            "launchpad.SubscriberView",
        )
        if (user is None and authz.checkUnauthenticated()) or (
            user is not None and authz.checkAuthenticated(IPersonRoles(user))
        ):
            return archive
        return None

    def getPPAByDistributionAndOwnerName(
        self, distribution, person_name, ppa_name
    ):
        """See `IArchiveSet`"""
        # Circular import.
        from lp.registry.model.person import Person

        return (
            IStore(Archive)
            .find(
                Archive,
                Archive.purpose == ArchivePurpose.PPA,
                Archive.distribution == distribution,
                Archive.owner == Person.id,
                Archive.name == ppa_name,
                Person.name == person_name,
            )
            .one()
        )

    def _getDefaultArchiveNameByPurpose(self, purpose):
        """Return the default for a archive in a given purpose.

        The default names are:

         * PRIMARY: 'primary';
         * PARTNER: 'partner';
         * PPA: 'ppa'.

        :param purpose: queried `ArchivePurpose`.

        :raise: `AssertionError` If the given purpose is not in this list,
            i.e. doesn't have a default name.

        :return: the name text to be used as name.
        """
        if purpose not in default_name_by_purpose.keys():
            raise AssertionError(
                "'%s' purpose has no default name." % purpose.name
            )

        return default_name_by_purpose[purpose]

    def getByDistroPurpose(self, distribution, purpose, name=None):
        """See `IArchiveSet`."""
        if purpose == ArchivePurpose.PPA:
            raise AssertionError(
                "This method should not be used to lookup PPAs. "
                "Use 'getPPAByDistributionAndOwnerName' instead."
            )

        if name is None:
            name = self._getDefaultArchiveNameByPurpose(purpose)

        return (
            IStore(Archive)
            .find(
                Archive, distribution=distribution, purpose=purpose, name=name
            )
            .one()
        )

    def getByDistroAndName(self, distribution, name):
        """See `IArchiveSet`."""
        return (
            IStore(Archive)
            .find(
                Archive,
                Archive.distribution == distribution,
                Archive.name == name,
                Archive.purpose != ArchivePurpose.PPA,
            )
            .one()
        )

    def _getDefaultDisplayname(self, name, owner, distribution, purpose):
        """See `IArchive`."""
        if purpose == ArchivePurpose.PPA:
            if name == default_name_by_purpose.get(purpose):
                displayname = "PPA for %s" % owner.displayname
            else:
                displayname = "PPA named %s for %s" % (name, owner.displayname)
            return displayname

        if purpose == ArchivePurpose.COPY:
            displayname = "Copy archive %s for %s" % (name, owner.displayname)
            return displayname

        return "%s for %s" % (purpose.title, distribution.title)

    def new(
        self,
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
        publishing_method=ArchivePublishingMethod.LOCAL,
        repository_format=ArchiveRepositoryFormat.DEBIAN,
        metadata_overrides=None,
    ):
        """See `IArchiveSet`."""
        if distribution is None:
            distribution = getUtility(ILaunchpadCelebrities).ubuntu

        if name is None:
            name = self._getDefaultArchiveNameByPurpose(purpose)

        # Deny Archives names equal their distribution names. This conflict
        # results in archives with awkward repository URLs
        if name == distribution.name:
            raise AssertionError(
                "Archives cannot have the same name as their distribution."
            )

        # If displayname is not given, create a default one.
        if displayname is None:
            displayname = self._getDefaultDisplayname(
                name=name,
                owner=owner,
                distribution=distribution,
                purpose=purpose,
            )

        # Copy archives are to be instantiated with the 'publish' flag turned
        # off.
        if purpose == ArchivePurpose.COPY:
            publish = False
        else:
            publish = True

        # For non-PPA archives we enforce unique names within the context of a
        # distribution.
        if purpose != ArchivePurpose.PPA:
            archive = (
                IStore(Archive)
                .find(Archive, distribution=distribution, name=name)
                .one()
            )
            if archive is not None:
                raise AssertionError(
                    "archive '%s' exists already in '%s'."
                    % (name, distribution.name)
                )
        else:
            archive = (
                IStore(Archive)
                .find(
                    Archive,
                    owner=owner,
                    distribution=distribution,
                    name=name,
                    purpose=ArchivePurpose.PPA,
                )
                .one()
            )
            if archive is not None:
                raise AssertionError(
                    "Person '%s' already has a PPA for %s named '%s'."
                    % (owner.name, distribution.name, name)
                )

        # Signing-key for the default PPA is reused when it's already present.
        signing_key_owner = None
        signing_key_fingerprint = None
        if purpose == ArchivePurpose.PPA:
            if owner.archive is not None:
                signing_key_owner = owner.archive.signing_key_owner
                # Check if the archive has a replacement 4096-bit RSA key
                # generated and propagate that, if it exists. There is no
                # need to populate the 'archivesigningkey' table here because
                # the new archive will only have a single secure signing key
                # and all such archives can be migrated en masse to the
                # 'archivesigningkey' table later.
                signing_key = getUtility(
                    IArchiveSigningKeySet
                ).get4096BitRSASigningKey(owner.archive)
                if signing_key:
                    signing_key_fingerprint = signing_key.fingerprint
                else:
                    signing_key_fingerprint = (
                        owner.archive.signing_key_fingerprint
                    )
            else:
                # owner.archive is a cached property and we've just cached it.
                del get_property_cache(owner).archive

        new_archive = Archive(
            owner=owner,
            distribution=distribution,
            name=name,
            displayname=displayname,
            description=description,
            purpose=purpose,
            publish=publish,
            signing_key_owner=signing_key_owner,
            signing_key_fingerprint=signing_key_fingerprint,
            require_virtualized=require_virtualized,
            publishing_method=publishing_method,
            repository_format=repository_format,
            metadata_overrides=metadata_overrides,
        )

        # Upon creation archives are enabled by default.
        if not enabled:
            new_archive.disable()

        # Private teams cannot have public PPAs.
        if owner.visibility == PersonVisibility.PRIVATE:
            new_archive.private = True
        else:
            new_archive.private = private

        if new_archive.is_ppa:
            new_archive.authorized_size = (
                20480 if new_archive.private else 8192
            )

        new_archive.suppress_subscription_notifications = (
            suppress_subscription_notifications
        )

        if processors is None:
            processors = [
                p
                for p in getUtility(IProcessorSet).getAll()
                if p.build_by_default
            ]
        new_archive.setProcessors(processors)

        Store.of(new_archive).flush()
        return new_archive

    def __iter__(self):
        """See `IArchiveSet`."""
        return iter(IStore(Archive).find(Archive))

    def getPPAOwnedByPerson(
        self,
        person,
        distribution=None,
        name=None,
        statuses=None,
        has_packages=False,
    ):
        """See `IArchiveSet`."""
        # See Person._members which also directly queries this.
        store = Store.of(person)
        clause = [
            Archive.purpose == ArchivePurpose.PPA,
            Archive.owner == person,
        ]
        if distribution is not None:
            clause.append(Archive.distribution == distribution)
        if name is not None:
            assert distribution is not None
            clause.append(Archive.name == name)
        if statuses is not None:
            clause.append(Archive.status.is_in(statuses))
        if has_packages:
            clause.append(SourcePackagePublishingHistory.archive == Archive.id)
        return store.find(Archive, *clause).order_by(Archive.id).first()

    def _getPPAsForUserClause(self, user):
        """Base clause for getPPAsForUser and getPPADistributionsForUser."""
        direct_membership = Select(
            Archive.id,
            where=And(
                Is(Archive._enabled, True),
                Archive.purpose == ArchivePurpose.PPA,
                TeamParticipation.team == Archive.owner_id,
                TeamParticipation.person == user,
            ),
        )
        third_party_upload_acl = Select(
            Archive.id,
            where=And(
                Archive.purpose == ArchivePurpose.PPA,
                ArchivePermission.archive == Archive.id,
                TeamParticipation.person == user,
                TeamParticipation.team == ArchivePermission.person_id,
            ),
        )
        return Archive.id.is_in(
            Union(direct_membership, third_party_upload_acl)
        )

    def getPPAsForUser(self, user):
        """See `IArchiveSet`."""
        from lp.registry.model.person import Person

        # If there's no user logged in, then there are no archives.
        if user is None:
            return EmptyResultSet()
        store = Store.of(user)
        result = store.find(Archive, self._getPPAsForUserClause(user))
        result.order_by(Archive.displayname)

        def preload_owners(rows):
            load_related(Person, rows, ["owner_id"])

        return DecoratedResultSet(result, pre_iter_hook=preload_owners)

    def getPPADistributionsForUser(self, user):
        """See `IArchiveSet`."""
        from lp.registry.model.distribution import Distribution

        # If there's no user logged in, then there are no archives.
        if user is None:
            return EmptyResultSet()
        store = Store.of(user)
        result = store.find(
            Distribution,
            Distribution.id == Archive.distribution_id,
            self._getPPAsForUserClause(user),
        )
        return result.config(distinct=True)

    def getArchivesPendingSigningKey(self, purpose=ArchivePurpose.PPA):
        """See `IArchiveSet`."""
        origin = (
            Archive,
            Join(
                SourcePackagePublishingHistory,
                SourcePackagePublishingHistory.archive == Archive.id,
            ),
        )
        results = (
            IStore(Archive)
            .using(*origin)
            .find(
                Archive,
                Archive.signing_key_fingerprint == None,
                Archive.purpose == purpose,
                Is(Archive._enabled, True),
            )
        )
        results.order_by(Archive.date_created)
        return results.config(distinct=True)

    def getArchivesWith1024BitRSASigningKey(self, limit):
        """See `IArchiveSet`."""
        join = (
            Archive,
            Join(
                GPGKey,
                GPGKey.fingerprint == Archive.signing_key_fingerprint,
            ),
            Join(
                SigningKey,
                SigningKey.fingerprint == Archive.signing_key_fingerprint,
            ),
        )
        subquery_join = (
            ArchiveSigningKey,
            Join(
                SigningKey,
                SigningKey.id == ArchiveSigningKey.signing_key_id,
            ),
            Join(
                GPGKey,
                GPGKey.fingerprint == SigningKey.fingerprint,
            ),
        )
        subquery_results = (
            IStore(ArchiveSigningKey)
            .using(*subquery_join)
            .find(
                ArchiveSigningKey.archive_id,
                GPGKey.keysize == 4096,
            )
        )
        results = (
            IStore(Archive)
            .using(*join)
            .find(
                Archive,
                Archive.purpose == ArchivePurpose.PPA,
                GPGKey.keysize == 1024,
                Not(Archive.id.is_in(subquery_results)),
            )
        )
        results.order_by(Archive.id)
        return results.config(distinct=True, limit=limit)

    def getLatestPPASourcePublicationsForDistribution(self, distribution):
        """See `IArchiveSet`."""
        # Circular import.
        from lp.registry.model.distroseries import DistroSeries

        return (
            IStore(SourcePackagePublishingHistory)
            .find(
                SourcePackagePublishingHistory,
                SourcePackagePublishingHistory.archive == Archive.id,
                SourcePackagePublishingHistory.distroseries == DistroSeries.id,
                Is(Archive.private, False),
                Is(Archive._enabled, True),
                Archive.distribution == distribution,
                DistroSeries.distribution == distribution,
                Archive.purpose == ArchivePurpose.PPA,
            )
            .order_by(
                Desc(SourcePackagePublishingHistory.datecreated),
                Desc(SourcePackagePublishingHistory.id),
            )[:5]
        )

    def getMostActivePPAsForDistribution(self, distribution):
        """See `IArchiveSet`."""
        spph_count = Alias(Count(SourcePackagePublishingHistory.id))
        results = (
            IStore(Archive)
            .find(
                (Archive, spph_count),
                SourcePackagePublishingHistory.archive == Archive.id,
                Is(Archive.private, False),
                SourcePackagePublishingHistory.datecreated
                >= UTC_NOW - Cast(timedelta(weeks=1), "interval"),
                Archive.distribution == distribution,
                Archive.purpose == ArchivePurpose.PPA,
            )
            .group_by(Archive.id)
            .order_by(Desc(spph_count), Archive.id)[:5]
        )

        most_active = []
        for archive, number_of_uploads in results:
            the_dict = {"archive": archive, "uploads": number_of_uploads}
            most_active.append(the_dict)

        return most_active

    def getPrivatePPAs(self):
        """See `IArchiveSet`."""
        return IStore(Archive).find(
            Archive,
            Is(Archive.private, True),
            Archive.purpose == ArchivePurpose.PPA,
        )

    def getArchivesForDistribution(
        self,
        distribution,
        name=None,
        purposes=None,
        check_permissions=True,
        user=None,
        exclude_disabled=True,
        exclude_pristine=False,
    ):
        """See `IArchiveSet`."""
        extra_exprs = []

        # If a single purpose is passed in, convert it into a tuple,
        # otherwise assume a list was passed in.
        if purposes in ArchivePurpose:
            purposes = (purposes,)

        if purposes:
            extra_exprs.append(Archive.purpose.is_in(purposes))

        if name is not None:
            extra_exprs.append(Archive.name == name)

        public_archive = And(
            Is(Archive.private, False), Is(Archive._enabled, True)
        )

        if not check_permissions:
            pass
        elif user is not None:
            admins = getUtility(ILaunchpadCelebrities).admin
            if not user.inTeam(admins):
                # Enforce privacy-awareness for logged-in, non-admin users,
                # so that they can only see the private archives that they're
                # allowed to see.

                # Create a subselect to capture all the teams that are
                # owners of archives AND the user is a member of:
                user_teams_subselect = Select(
                    TeamParticipation.team_id,
                    where=And(
                        TeamParticipation.person == user,
                        TeamParticipation.team_id == Archive.owner_id,
                    ),
                )

                # Append the extra expression to capture either public
                # archives, or archives owned by the user, or archives
                # owned by a team of which the user is a member:
                # Note: 'Archive.owner_id == user.id'
                # is unnecessary below because there is a TeamParticipation
                # entry showing that each person is a member of the "team"
                # that consists of themselves.

                # FIXME: Include private PPA's if user is an uploader
                extra_exprs.append(
                    Or(
                        public_archive,
                        Archive.owner_id.is_in(user_teams_subselect),
                    )
                )
        else:
            # Anonymous user; filter to include only public archives in
            # the results.
            extra_exprs.append(public_archive)

        if exclude_disabled:
            extra_exprs.append(Is(Archive._enabled, True))

        if exclude_pristine:
            extra_exprs.append(
                Exists(
                    Select(
                        1,
                        tables=[SourcePackagePublishingHistory],
                        where=(
                            SourcePackagePublishingHistory.archive
                            == Archive.id
                        ),
                    )
                )
            )

        query = Store.of(distribution).find(
            Archive, Archive.distribution == distribution, *extra_exprs
        )

        return query.order_by(Archive.name)

    def getPublicationsInArchives(
        self,
        source_package_name,
        archive_list,
        distribution=None,
        distroseries=None,
    ):
        """See `IArchiveSet`."""
        archive_ids = [archive.id for archive in archive_list]

        store = Store.of(source_package_name)

        # Return all the published source pubs for the given name in the
        # given list of archives. Note: importing DistroSeries here to
        # avoid circular imports.
        from lp.registry.model.distroseries import DistroSeries

        clauses = [
            Archive.id.is_in(archive_ids),
            SourcePackagePublishingHistory.archive == Archive.id,
            (
                SourcePackagePublishingHistory.status
                == PackagePublishingStatus.PUBLISHED
            ),
            SourcePackagePublishingHistory.sourcepackagename
            == source_package_name,
        ]
        if distribution is not None:
            clauses.extend(
                [
                    SourcePackagePublishingHistory.distroseries
                    == DistroSeries.id,
                    DistroSeries.distribution == distribution,
                ]
            )
        if distroseries is not None:
            clauses.append(
                SourcePackagePublishingHistory.distroseries == distroseries
            )
        results = store.find(SourcePackagePublishingHistory, *clauses)

        return results.order_by(SourcePackagePublishingHistory.id)

    def checkViewPermission(
        self, archives: typing.List[IArchive], user: IPerson
    ) -> typing.Dict[IArchive, bool]:
        """See `IArchiveSet`."""
        allowed_ids = set()
        ids_to_check_in_database = []
        roles = IPersonRoles(user)
        for archive in archives:
            # No further checks are required if the archive is public and
            # enabled.
            if not archive.private and archive.enabled:
                allowed_ids.add(archive.id)

            # Administrators are allowed to view private archives.
            elif roles.in_admin or roles.in_commercial_admin:
                allowed_ids.add(archive.id)

            # Registry experts are allowed to view public but disabled archives
            # (since they are allowed to disable archives).
            elif (
                not archive.private
                and not archive.enabled
                and roles.in_registry_experts
            ):
                allowed_ids.add(archive.id)

            # Users that are direct owners (not through a team)
            # can view the PPA.
            # This is an optimization to avoid making a database query
            # when a user is the direct owner of the PPA.
            # Team ownership is accounted for in `get_enabled_archive_filter`
            # below
            elif user.id == removeSecurityProxy(archive).owner_id:
                allowed_ids.add(archive.id)

            else:
                ids_to_check_in_database.append(archive.id)

        if ids_to_check_in_database:
            store = IStore(Archive)
            allowed_ids.update(
                store.find(
                    Archive.id,
                    Archive.id.is_in(ids_to_check_in_database),
                    get_enabled_archive_filter(user),
                )
            )
        return {archive: archive.id in allowed_ids for archive in archives}

    def empty_list(self):
        """See `IArchiveSet."""
        return []


class ArchiveArch(StormBase):
    """Link table to back Archive.processors."""

    __storm_table__ = "ArchiveArch"
    id = Int(primary=True)

    archive_id = Int(name="archive", allow_none=False)
    archive = Reference(archive_id, "Archive.id")
    processor_id = Int(name="processor", allow_none=False)
    processor = Reference(processor_id, Processor.id)


def get_archive_privacy_filter(user):
    """Get a simplified Archive privacy Storm filter.

    Incorrect and deprecated. Use get_enabled_archive_filter instead.
    """
    if user is None:
        privacy_filter = Not(Archive.private)
    elif IPersonRoles(user).in_admin:
        privacy_filter = True
    else:
        privacy_filter = Or(
            Not(Archive.private),
            Archive.owner_id.is_in(
                Select(
                    TeamParticipation.team_id,
                    where=(TeamParticipation.person == user),
                )
            ),
        )
    return privacy_filter


def get_enabled_archive_filter(
    user, purpose=None, include_public=False, include_subscribed=False
):
    """Return a filter that can be used with a Storm query to filter Archives.

    The archive must be enabled, plus satisfy the other specified conditions.
    """
    purpose_term = True
    if purpose:
        purpose_term = Archive.purpose == purpose
    if user is None:
        if include_public:
            terms = [
                purpose_term,
                Is(Archive.private, False),
                Is(Archive._enabled, True),
            ]
            return And(*terms)
        else:
            return False

    # Administrator are allowed to view private archives.
    roles = IPersonRoles(user)
    if roles.in_admin or roles.in_commercial_admin:
        return purpose_term

    main = getUtility(IComponentSet)["main"]
    user_teams = Select(
        TeamParticipation.team_id, where=TeamParticipation.person == user
    )

    is_owner = Archive.owner_id.is_in(user_teams)

    from lp.soyuz.model.archivesubscriber import ArchiveSubscriber

    is_allowed = Select(
        ArchivePermission.archive_id,
        where=And(
            ArchivePermission.permission == ArchivePermissionType.UPLOAD,
            ArchivePermission.component == main,
            ArchivePermission.person_id.is_in(user_teams),
        ),
        tables=ArchivePermission,
        distinct=True,
    )

    is_subscribed = Select(
        ArchiveSubscriber.archive_id,
        where=And(
            ArchiveSubscriber.status == ArchiveSubscriberStatus.CURRENT,
            ArchiveSubscriber.subscriber_id.is_in(user_teams),
        ),
        tables=ArchiveSubscriber,
        distinct=True,
    )

    filter_terms = [
        is_owner,
        And(
            Archive.purpose == ArchivePurpose.PPA, Archive.id.is_in(is_allowed)
        ),
    ]
    if include_subscribed:
        filter_terms.append(
            And(
                Archive.purpose == ArchivePurpose.PPA,
                Archive.id.is_in(is_subscribed),
            )
        )

    if include_public:
        filter_terms.append(
            And(Is(Archive._enabled, True), Is(Archive.private, False))
        )
    return And(purpose_term, Or(*filter_terms))
