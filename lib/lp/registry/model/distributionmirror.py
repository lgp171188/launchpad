# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Module docstring goes here."""

__all__ = [
    "DistributionMirror",
    "MirrorDistroArchSeries",
    "MirrorDistroSeriesSource",
    "MirrorProbeRecord",
    "DistributionMirrorSet",
    "MirrorCDImageDistroSeries",
]

from datetime import MINYEAR, datetime, timedelta, timezone

from storm.expr import Cast, Coalesce, LeftJoin
from storm.locals import (
    And,
    Bool,
    DateTime,
    Desc,
    Int,
    Max,
    Or,
    Reference,
    Select,
    Store,
    Unicode,
)
from storm.store import EmptyResultSet
from zope.interface import implementer

from lp.archivepublisher.diskpool import poolify
from lp.registry.errors import (
    CannotTransitionToCountryMirror,
    CountryMirrorAlreadySet,
    InvalidMirrorReviewState,
    MirrorHasNoHTTPURL,
    MirrorNotOfficial,
    MirrorNotProbed,
)
from lp.registry.interfaces.distributionmirror import (
    PROBE_INTERVAL,
    IDistributionMirror,
    IDistributionMirrorSet,
    IMirrorCDImageDistroSeries,
    IMirrorDistroArchSeries,
    IMirrorDistroSeriesSource,
    IMirrorProbeRecord,
    MirrorContent,
    MirrorFreshness,
    MirrorSpeed,
    MirrorStatus,
)
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.person import validate_public_person
from lp.registry.interfaces.pocket import PackagePublishingPocket, pocketsuffix
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackage import SourcePackageFileType
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.mail.helpers import (
    get_contact_email_addresses,
    get_email_template,
)
from lp.services.mail.sendmail import format_address, simple_sendmail
from lp.services.propertycache import cachedproperty, get_property_cache
from lp.services.webapp import canonical_url, urlappend
from lp.soyuz.enums import BinaryPackageFileType, PackagePublishingStatus
from lp.soyuz.interfaces.distroarchseries import IDistroArchSeries
from lp.soyuz.model.files import BinaryPackageFile, SourcePackageReleaseFile
from lp.soyuz.model.publishing import (
    BinaryPackagePublishingHistory,
    SourcePackagePublishingHistory,
)


@implementer(IDistributionMirror)
class DistributionMirror(StormBase):
    """See IDistributionMirror"""

    __storm_table__ = "DistributionMirror"
    __storm_order__ = ("-speed", "name", "id")

    id = Int(primary=True)
    owner_id = Int(
        name="owner", validator=validate_public_person, allow_none=False
    )
    owner = Reference(owner_id, "Person.id")
    reviewer_id = Int(
        name="reviewer", validator=validate_public_person, default=None
    )
    reviewer = Reference(reviewer_id, "Person.id")
    distribution_id = Int(name="distribution", allow_none=False)
    distribution = Reference(distribution_id, "Distribution.id")
    name = Unicode(allow_none=False)
    display_name = Unicode(name="displayname", allow_none=True, default=None)
    description = Unicode(allow_none=True, default=None)
    http_base_url = Unicode(allow_none=True, default=None)
    https_base_url = Unicode(allow_none=True, default=None)
    ftp_base_url = Unicode(allow_none=True, default=None)
    rsync_base_url = Unicode(allow_none=True, default=None)
    enabled = Bool(allow_none=False, default=False)
    speed = DBEnum(allow_none=False, enum=MirrorSpeed)
    country_id = Int(name="country", allow_none=False)
    country = Reference(country_id, "Country.id")
    content = DBEnum(allow_none=False, enum=MirrorContent)
    official_candidate = Bool(allow_none=False, default=False)
    status = DBEnum(
        allow_none=False,
        default=MirrorStatus.PENDING_REVIEW,
        enum=MirrorStatus,
    )
    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )
    date_reviewed = DateTime(tzinfo=timezone.utc, default=None)
    whiteboard = Unicode(allow_none=True, default=None)
    country_dns_mirror = Bool(allow_none=False, default=False)

    def __init__(
        self,
        owner,
        distribution,
        name,
        speed,
        country,
        content,
        display_name=None,
        description=None,
        http_base_url=None,
        https_base_url=None,
        ftp_base_url=None,
        rsync_base_url=None,
        enabled=False,
        official_candidate=False,
        whiteboard=None,
    ):
        self.owner = owner
        self.distribution = distribution
        self.name = name
        self.speed = speed
        self.country = country
        self.content = content
        self.display_name = display_name
        self.description = description
        self.http_base_url = http_base_url
        self.https_base_url = https_base_url
        self.ftp_base_url = ftp_base_url
        self.rsync_base_url = rsync_base_url
        self.enabled = enabled
        self.official_candidate = official_candidate
        self.whiteboard = whiteboard

    @property
    def base_url(self):
        """See IDistributionMirror"""
        if self.https_base_url is not None:
            return self.https_base_url
        elif self.http_base_url is not None:
            return self.http_base_url
        else:
            return self.ftp_base_url

    @property
    def last_probe_record(self):
        """See IDistributionMirror"""
        return (
            Store.of(self)
            .find(MirrorProbeRecord, distribution_mirror=self)
            .order_by(MirrorProbeRecord.date_created)
            .last()
        )

    @property
    def all_probe_records(self):
        """See IDistributionMirror"""
        return (
            Store.of(self)
            .find(MirrorProbeRecord, distribution_mirror=self)
            .order_by(Desc(MirrorProbeRecord.date_created))
        )

    @property
    def displayname(self):
        return self.display_name

    @property
    def title(self):
        """See IDistributionMirror"""
        if self.display_name:
            return self.display_name
        else:
            return self.name.capitalize()

    @cachedproperty
    def arch_mirror_freshness(self):
        """See IDistributionMirror"""
        store = Store.of(self)
        mirror = (
            store.find(
                MirrorDistroArchSeries,
                And(
                    MirrorDistroArchSeries.distribution_mirror == self,
                    MirrorDistroArchSeries.freshness
                    != MirrorFreshness.UNKNOWN,
                ),
            )
            .order_by(Desc(MirrorDistroArchSeries.freshness))
            .first()
        )
        if not mirror:
            return None
        else:
            return mirror.freshness

    @cachedproperty
    def source_mirror_freshness(self):
        """See IDistributionMirror"""
        store = Store.of(self)
        mirror = (
            store.find(
                MirrorDistroSeriesSource,
                And(
                    MirrorDistroSeriesSource.distribution_mirror == self,
                    MirrorDistroSeriesSource.freshness
                    != MirrorFreshness.UNKNOWN,
                ),
            )
            .order_by(Desc(MirrorDistroSeriesSource.freshness))
            .first()
        )
        if not mirror:
            return None
        else:
            return mirror.freshness

    def destroySelf(self):
        """Delete this mirror from the database.

        Only mirrors which have never been probed can be deleted.
        """
        assert (
            self.last_probe_record is None
        ), "This mirror has been probed and thus can't be removed."
        Store.of(self).remove(self)

    def verifyTransitionToCountryMirror(self):
        """Verify that a mirror can be set as a country mirror.

        Return True if valid, otherwise raise a subclass of
        CannotTransitionToCountryMirror.
        """

        current_country_mirror = self.distribution.getCountryMirror(
            self.country, self.content
        )

        if current_country_mirror is not None:
            # Country already has a country mirror.
            raise CountryMirrorAlreadySet(
                "%s already has a country %s mirror set."
                % (self.country.name, self.content)
            )

        if not self.isOfficial():
            # Only official mirrors may be set as country mirrors.
            raise MirrorNotOfficial(
                "This mirror may not be set as a country mirror as it is not "
                "an official mirror."
            )

        if self.http_base_url is None:
            # Country mirrors must have HTTP URLs set.
            raise MirrorHasNoHTTPURL(
                "This mirror may not be set as a country mirror as it does "
                "not have an HTTP URL set."
            )

        if not self.last_probe_record:
            # Only mirrors which have been probed may be set as country
            # mirrors.
            raise MirrorNotProbed(
                "This mirror may not be set as a country mirror as it has "
                "not been probed."
            )

        # Verification done.
        return True

    def canTransitionToCountryMirror(self):
        """See `IDistributionMirror`."""
        try:
            return self.verifyTransitionToCountryMirror()
        except CannotTransitionToCountryMirror:
            return False

    def transitionToCountryMirror(self, country_dns_mirror):
        """See `IDistributionMirror`."""

        # country_dns_mirror has not been changed, do nothing.
        if self.country_dns_mirror == country_dns_mirror:
            return

        # Environment sanity checks.
        if country_dns_mirror:
            self.verifyTransitionToCountryMirror()

        self.country_dns_mirror = country_dns_mirror

    def getOverallFreshness(self):
        """See IDistributionMirror"""
        # XXX Guilherme Salgado 2006-08-16:
        # We shouldn't be using MirrorFreshness to represent the overall
        # freshness of a mirror, but for now it'll do the job and we'll use
        # the UNKNOWN freshness to represent a mirror without any content
        # (which may mean the mirror was never verified or it was verified
        # and no content was found).
        if self.content == MirrorContent.RELEASE:
            if self.cdimage_series:
                return MirrorFreshness.UP
            else:
                return MirrorFreshness.UNKNOWN

        elif self.content == MirrorContent.ARCHIVE:
            # Return the worst (i.e. highest valued) mirror freshness out of
            # all mirrors (binary and source) for this distribution mirror.
            arch_mirror_freshness = self.arch_mirror_freshness
            source_mirror_freshness = self.source_mirror_freshness

            # Return unknown if no content
            if (
                arch_mirror_freshness is None
                and source_mirror_freshness is None
            ):
                return MirrorFreshness.UNKNOWN

            # Return arch_mirror freshness if we have no source mirror.
            if (
                arch_mirror_freshness is not None
                and source_mirror_freshness is None
            ):
                return arch_mirror_freshness

            # Return source_mirror freshness if we have no arch mirror.
            if (
                arch_mirror_freshness is None
                and source_mirror_freshness is not None
            ):
                return source_mirror_freshness

            # Return the freshest data if we have data for both.
            if source_mirror_freshness > arch_mirror_freshness:
                return source_mirror_freshness
            else:
                return arch_mirror_freshness
        else:
            raise AssertionError(
                "DistributionMirror.content is not ARCHIVE nor RELEASE: %r"
                % self.content
            )

    def isOfficial(self):
        """See IDistributionMirror"""
        return self.official_candidate and self.status == MirrorStatus.OFFICIAL

    def resubmitForReview(self):
        """See IDistributionMirror"""
        if self.status != MirrorStatus.BROKEN:
            raise InvalidMirrorReviewState(
                "DistributionMirror.status is not BROKEN"
            )
        self.status = MirrorStatus.PENDING_REVIEW

    def shouldDisable(self, expected_file_count=None):
        """See IDistributionMirror"""
        if self.content == MirrorContent.RELEASE:
            if expected_file_count is None:
                raise AssertionError(
                    "For series mirrors we need to know the "
                    "expected_file_count in order to tell if it should "
                    "be disabled or not."
                )
            if expected_file_count > len(self.cdimage_series):
                return True
        else:
            if self.source_series.is_empty() and self.arch_series.is_empty():
                return True
        return False

    def disable(self, notify_owner, log):
        """See IDistributionMirror"""
        assert self.last_probe_record is not None, (
            "This method can't be called on a mirror that has never been "
            "probed."
        )
        if self.enabled or self.all_probe_records.count() == 1:
            self._sendFailureNotification(notify_owner, log)
        self.enabled = False

    def _sendFailureNotification(self, notify_owner, log):
        """Send a failure notification to the distribution's mirror admins and
        to the mirror owner, in case notify_owner is True.
        """
        template = get_email_template(
            "notify-mirror-owner.txt", app="registry"
        )
        fromaddress = format_address(
            "Launchpad Mirror Prober", config.canonical.noreply_from_address
        )

        replacements = {
            "distro": self.distribution.title,
            "mirror_name": self.name,
            "mirror_url": canonical_url(self),
            "log_snippet": "\n".join(log.split("\n")[:20]),
            "logfile_url": self.last_probe_record.log_file.http_url,
        }
        message = template % replacements
        subject = "Launchpad: Verification of %s failed" % self.name

        mirror_admin_addresses = get_contact_email_addresses(
            self.distribution.mirror_admin
        )
        for admin_address in mirror_admin_addresses:
            simple_sendmail(fromaddress, admin_address, subject, message)

        if notify_owner:
            owner_addresses = get_contact_email_addresses(self.owner)
            for owner_address in owner_addresses:
                simple_sendmail(fromaddress, owner_address, subject, message)

    def newProbeRecord(self, log_file):
        """See IDistributionMirror"""
        return MirrorProbeRecord(distribution_mirror=self, log_file=log_file)

    def deleteMirrorDistroArchSeries(
        self, distro_arch_series, pocket, component
    ):
        """See IDistributionMirror"""
        mirror = (
            IStore(MirrorDistroArchSeries)
            .find(
                MirrorDistroArchSeries,
                distribution_mirror=self,
                distro_arch_series=distro_arch_series,
                pocket=pocket,
                component=component,
            )
            .one()
        )
        if mirror is not None:
            Store.of(mirror).remove(mirror)

    def _getMirrorDistroArchSeries(
        self, distro_arch_series, pocket, component
    ):
        """Return MirrorDistroArchSeries given a arch series and pocket."""

        return (
            IStore(MirrorDistroArchSeries)
            .find(
                MirrorDistroArchSeries,
                distribution_mirror=self,
                distro_arch_series=distro_arch_series,
                pocket=pocket,
                component=component,
            )
            .one()
        )

    def ensureMirrorDistroArchSeries(
        self, distro_arch_series, pocket, component
    ):
        """See `IDistributionMirror`."""
        assert IDistroArchSeries.providedBy(distro_arch_series)
        mirror = self._getMirrorDistroArchSeries(
            distro_arch_series=distro_arch_series,
            pocket=pocket,
            component=component,
        )
        if mirror is None:
            mirror = MirrorDistroArchSeries(
                pocket=pocket,
                distribution_mirror=self,
                distro_arch_series=distro_arch_series,
                component=component,
            )
        return mirror

    def _getMirrorDistroSeriesSource(self, distroseries, pocket, component):
        """Return MirrorDistroSeriesSource given a arch series and pocket."""

        return (
            IStore(MirrorDistroSeriesSource)
            .find(
                MirrorDistroSeriesSource,
                distribution_mirror=self,
                distroseries=distroseries,
                pocket=pocket,
                component=component,
            )
            .one()
        )

    def ensureMirrorDistroSeriesSource(self, distroseries, pocket, component):
        """See `IDistributionMirror`."""
        assert IDistroSeries.providedBy(distroseries)
        mirror = self._getMirrorDistroSeriesSource(
            distroseries=distroseries, pocket=pocket, component=component
        )
        if mirror is None:
            mirror = MirrorDistroSeriesSource(
                distribution_mirror=self,
                distroseries=distroseries,
                pocket=pocket,
                component=component,
            )
        return mirror

    def deleteMirrorDistroSeriesSource(self, distroseries, pocket, component):
        """See IDistributionMirror"""
        mirror = (
            IStore(MirrorDistroSeriesSource)
            .find(
                MirrorDistroSeriesSource,
                distribution_mirror=self,
                distroseries=distroseries,
                pocket=pocket,
                component=component,
            )
            .one()
        )
        if mirror is not None:
            Store.of(mirror).remove(mirror)

    def ensureMirrorCDImageSeries(self, distroseries, flavour):
        """See IDistributionMirror"""
        mirror = (
            IStore(MirrorCDImageDistroSeries)
            .find(
                MirrorCDImageDistroSeries,
                distribution_mirror=self,
                distroseries=distroseries,
                flavour=flavour,
            )
            .one()
        )
        if mirror is None:
            mirror = MirrorCDImageDistroSeries(
                distribution_mirror=self,
                distroseries=distroseries,
                flavour=flavour,
            )
        del get_property_cache(self).cdimage_series
        return mirror

    def deleteMirrorCDImageSeries(self, distroseries, flavour):
        """See IDistributionMirror"""
        mirror = (
            IStore(MirrorCDImageDistroSeries)
            .find(
                MirrorCDImageDistroSeries,
                distribution_mirror=self,
                distroseries=distroseries,
                flavour=flavour,
            )
            .one()
        )
        if mirror is not None:
            Store.of(mirror).remove(mirror)
        del get_property_cache(self).cdimage_series

    def deleteAllMirrorCDImageSeries(self):
        """See IDistributionMirror"""
        for mirror in self.cdimage_series:
            Store.of(mirror).remove(mirror)
        del get_property_cache(self).cdimage_series

    @property
    def arch_series(self):
        """See IDistributionMirror"""
        return IStore(MirrorDistroArchSeries).find(
            MirrorDistroArchSeries, distribution_mirror=self
        )

    @cachedproperty
    def cdimage_series(self):
        """See IDistributionMirror"""
        return list(
            IStore(MirrorCDImageDistroSeries).find(
                MirrorCDImageDistroSeries, distribution_mirror=self
            )
        )

    @property
    def source_series(self):
        """See IDistributionMirror"""
        return IStore(MirrorDistroSeriesSource).find(
            MirrorDistroSeriesSource, distribution_mirror=self
        )

    def getSummarizedMirroredSourceSeries(self):
        """See IDistributionMirror"""
        return IStore(MirrorDistroSeriesSource).find(
            MirrorDistroSeriesSource,
            MirrorDistroSeriesSource.id.is_in(
                Select(
                    MirrorDistroSeriesSource.id,
                    where=(
                        MirrorDistroSeriesSource.distribution_mirror == self
                    ),
                    order_by=(
                        MirrorDistroSeriesSource.distribution_mirror_id,
                        MirrorDistroSeriesSource.distroseries_id,
                        Desc(MirrorDistroSeriesSource.freshness),
                    ),
                    distinct=(
                        MirrorDistroSeriesSource.distribution_mirror_id,
                        MirrorDistroSeriesSource.distroseries_id,
                    ),
                )
            ),
        )

    def getSummarizedMirroredArchSeries(self):
        """See IDistributionMirror"""
        return IStore(MirrorDistroArchSeries).find(
            MirrorDistroArchSeries,
            MirrorDistroArchSeries.id.is_in(
                Select(
                    MirrorDistroArchSeries.id,
                    where=(MirrorDistroArchSeries.distribution_mirror == self),
                    order_by=(
                        MirrorDistroArchSeries.distribution_mirror_id,
                        MirrorDistroArchSeries.distro_arch_series_id,
                        Desc(MirrorDistroArchSeries.freshness),
                    ),
                    distinct=(
                        MirrorDistroArchSeries.distribution_mirror_id,
                        MirrorDistroArchSeries.distro_arch_series_id,
                    ),
                )
            ),
        )

    def getExpectedPackagesPaths(self):
        """See IDistributionMirror"""
        paths = []
        for series in self.distribution.series:
            for pocket, suffix in sorted(pocketsuffix.items()):
                for component in series.components:
                    for arch_series in series.architectures:
                        # Skip unsupported series and unofficial architectures
                        # for official series and ones which were not on the
                        # mirror on its last probe.
                        if (
                            series.status == SeriesStatus.OBSOLETE
                            or not arch_series.official
                        ) and not self._getMirrorDistroArchSeries(
                            arch_series, pocket, component
                        ):
                            continue

                        path = "dists/%s%s/%s/binary-%s/Packages.gz" % (
                            series.name,
                            suffix,
                            component.name,
                            arch_series.architecturetag,
                        )
                        paths.append((arch_series, pocket, component, path))
        return paths

    def getExpectedSourcesPaths(self):
        """See IDistributionMirror"""
        paths = []
        for series in self.distribution.series:
            for pocket, suffix in sorted(pocketsuffix.items()):
                for component in series.components:
                    # Skip sources for series which are obsolete and ones
                    # which were not on the mirror on its last probe.
                    if (
                        series.status == SeriesStatus.OBSOLETE
                        and not self._getMirrorDistroSeriesSource(
                            series, pocket, component
                        )
                    ):
                        continue

                    path = "dists/%s%s/%s/source/Sources.gz" % (
                        series.name,
                        suffix,
                        component.name,
                    )
                    paths.append((series, pocket, component, path))
        return paths


@implementer(IDistributionMirrorSet)
class DistributionMirrorSet:
    """See IDistributionMirrorSet"""

    def __getitem__(self, mirror_id):
        """See IDistributionMirrorSet"""
        return IStore(DistributionMirror).get(DistributionMirror, mirror_id)

    def getMirrorsToProbe(
        self, content_type, ignore_last_probe=False, limit=None
    ):
        """See IDistributionMirrorSet"""
        tables = [
            DistributionMirror,
            LeftJoin(
                MirrorProbeRecord,
                MirrorProbeRecord.distribution_mirror == DistributionMirror.id,
            ),
        ]
        results = (
            IStore(DistributionMirror)
            .using(*tables)
            .find(
                (DistributionMirror.id, Max(MirrorProbeRecord.date_created)),
                DistributionMirror.content == content_type,
                DistributionMirror.official_candidate,
                DistributionMirror.status == MirrorStatus.OFFICIAL,
            )
            .group_by(DistributionMirror.id)
        )

        if not ignore_last_probe:
            results = results.having(
                Or(
                    Max(MirrorProbeRecord.date_created) == None,
                    Max(MirrorProbeRecord.date_created)
                    < (
                        UTC_NOW
                        - Cast(timedelta(hours=PROBE_INTERVAL), "interval")
                    ),
                )
            )

        results = results.order_by(
            Max(
                Coalesce(MirrorProbeRecord.date_created, datetime(1970, 1, 1))
            ),
            DistributionMirror.id,
        )

        if limit is not None:
            results = results.config(limit=limit)

        mirror_ids = {mirror_id for mirror_id, _ in results}
        if not mirror_ids:
            return EmptyResultSet()
        return IStore(DistributionMirror).find(
            DistributionMirror, DistributionMirror.id.is_in(mirror_ids)
        )

    def getByName(self, name):
        """See IDistributionMirrorSet"""
        return (
            IStore(DistributionMirror)
            .find(DistributionMirror, name=name)
            .one()
        )

    def getByHttpUrl(self, url):
        """See IDistributionMirrorSet"""
        return (
            IStore(DistributionMirror)
            .find(DistributionMirror, http_base_url=url)
            .one()
        )

    def getByHttpsUrl(self, url):
        """See IDistributionMirrorSet"""
        return (
            IStore(DistributionMirror)
            .find(DistributionMirror, https_base_url=url)
            .one()
        )

    def getByFtpUrl(self, url):
        """See IDistributionMirrorSet"""
        return (
            IStore(DistributionMirror)
            .find(DistributionMirror, ftp_base_url=url)
            .one()
        )

    def getByRsyncUrl(self, url):
        """See IDistributionMirrorSet"""
        return (
            IStore(DistributionMirror)
            .find(DistributionMirror, rsync_base_url=url)
            .one()
        )


class _MirrorSeriesMixIn:
    """A class containing some commonalities between MirrorDistroArchSeries
    and MirrorDistroSeriesSource.

    This class is not meant to be used alone. Instead, both
    MirrorDistroSeriesSource and MirrorDistroArchSeries should inherit from
    it and override the methods and attributes that say so.
    """

    # The freshness_times map defines levels for specifying how up to date a
    # mirror is; we use published files to assess whether a certain level is
    # fulfilled by a mirror. The map is used in combination with a special
    # freshness UP that maps to the latest published file for that
    # distribution series, component and pocket: if that file is found, we
    # consider the distribution to be up to date; if it is not found we then
    # look through the rest of the map to try and determine at what level
    # the mirror is.
    freshness_times = [
        (MirrorFreshness.ONEHOURBEHIND, 1.5),
        (MirrorFreshness.TWOHOURSBEHIND, 2.5),
        (MirrorFreshness.SIXHOURSBEHIND, 6.5),
        (MirrorFreshness.ONEDAYBEHIND, 24.5),
        (MirrorFreshness.TWODAYSBEHIND, 48.5),
        (MirrorFreshness.ONEWEEKBEHIND, 168.5),
    ]

    def _getPackageReleaseURLFromPublishingRecord(self, publishing_record):
        """Given a publishing record, return a dictionary mapping
        MirrorFreshness items to URLs of files on this mirror.

        Must be overwritten on subclasses.
        """
        raise NotImplementedError

    def getLatestPublishingEntry(self, time_interval):
        """Return the publishing entry with the most recent datepublished.

        Time interval must be a tuple of the form (start, end), and only
        records whose datepublished is between start and end are considered.
        """
        raise NotImplementedError

    def getURLsToCheckUpdateness(self, when=None):
        """See IMirrorDistroSeriesSource or IMirrorDistroArchSeries."""
        if when is None:
            when = datetime.now(timezone.utc)

        start = datetime(MINYEAR, 1, 1, tzinfo=timezone.utc)
        time_interval = (start, when)
        latest_upload = self.getLatestPublishingEntry(time_interval)
        if latest_upload is None:
            return {}

        url = self._getPackageReleaseURLFromPublishingRecord(latest_upload)
        urls = {MirrorFreshness.UP: url}

        # For each freshness in self.freshness_times, do:
        #   1) if latest_upload was published before the start of this
        #      freshness' time interval, skip it and move to the next item.
        #   2) if latest_upload was published between this freshness' time
        #      interval, adjust the end of the time interval to be identical
        #      to latest_upload.datepublished. We do this because even if the
        #      mirror doesn't have the latest upload, we can't skip that whole
        #      time interval: the mirror might have other packages published
        #      in that interval.
        #      This happens in pathological cases where two publications were
        #      done successively after a long period of time with no
        #      publication: if the mirror lacks the latest published package,
        #      we still need to check the corresponding interval or we will
        #      misreport the mirror as being very out of date.
        #   3) search for publishing records whose datepublished is between
        #      the specified time interval, and if one is found, append an
        #      item to the urls dictionary containing this freshness and the
        #      url on this mirror from where the file correspondent to that
        #      publishing record can be downloaded.
        last_threshold = 0
        for freshness, threshold in self.freshness_times:
            start = when - timedelta(hours=threshold)
            end = when - timedelta(hours=last_threshold)
            last_threshold = threshold
            if latest_upload.datepublished < start:
                continue
            if latest_upload.datepublished < end:
                end = latest_upload.datepublished

            time_interval = (start, end)
            upload = self.getLatestPublishingEntry(time_interval)

            if upload is None:
                # No uploads that would allow us to know the mirror was in
                # this freshness, so we better skip it.
                continue

            url = self._getPackageReleaseURLFromPublishingRecord(upload)
            urls.update({freshness: url})

        return urls


@implementer(IMirrorCDImageDistroSeries)
class MirrorCDImageDistroSeries(StormBase):
    """See IMirrorCDImageDistroSeries"""

    __storm_table__ = "MirrorCDImageDistroSeries"
    __storm_order__ = "id"

    id = Int(primary=True)
    distribution_mirror_id = Int(name="distribution_mirror", allow_none=False)
    distribution_mirror = Reference(
        distribution_mirror_id, "DistributionMirror.id"
    )
    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")
    flavour = Unicode(allow_none=False)

    def __init__(self, distribution_mirror, distroseries, flavour):
        self.distribution_mirror = distribution_mirror
        self.distroseries = distroseries
        self.flavour = flavour


@implementer(IMirrorDistroArchSeries)
class MirrorDistroArchSeries(StormBase, _MirrorSeriesMixIn):
    """See IMirrorDistroArchSeries"""

    __storm_table__ = "MirrorDistroArchSeries"
    __storm_order__ = [
        "distroarchseries",
        "component",
        "pocket",
        "freshness",
        "id",
    ]

    id = Int(primary=True)
    distribution_mirror_id = Int(name="distribution_mirror", allow_none=False)
    distribution_mirror = Reference(
        distribution_mirror_id, "DistributionMirror.id"
    )
    distro_arch_series_id = Int(name="distroarchseries", allow_none=False)
    distro_arch_series = Reference(
        distro_arch_series_id, "DistroArchSeries.id"
    )
    component_id = Int(name="component", allow_none=False)
    component = Reference(component_id, "Component.id")
    freshness = DBEnum(
        allow_none=False, default=MirrorFreshness.UNKNOWN, enum=MirrorFreshness
    )
    pocket = DBEnum(allow_none=False, enum=PackagePublishingPocket)

    def __init__(
        self, distribution_mirror, distro_arch_series, component, pocket
    ):
        self.distribution_mirror = distribution_mirror
        self.distro_arch_series = distro_arch_series
        self.component = component
        self.pocket = pocket

    def getLatestPublishingEntry(self, time_interval, deb_only=True):
        """Return the BinaryPackagePublishingHistory record with the
        most recent datepublished.

        :deb_only: If True, return only publishing records whose
                   binarypackagerelease's binarypackagefile.filetype is
                   BinaryPackageFileType.DEB.
        """
        clauses = [
            BinaryPackagePublishingHistory.pocket == self.pocket,
            BinaryPackagePublishingHistory.component == self.component,
            BinaryPackagePublishingHistory.distroarchseries
            == self.distro_arch_series,
            BinaryPackagePublishingHistory.archive
            == self.distro_arch_series.main_archive,
            BinaryPackagePublishingHistory.status
            == PackagePublishingStatus.PUBLISHED,
        ]

        if deb_only:
            clauses.extend(
                [
                    BinaryPackagePublishingHistory.binarypackagereleaseID
                    == BinaryPackageFile.binarypackagerelease_id,
                    BinaryPackageFile.filetype == BinaryPackageFileType.DEB,
                ]
            )

        if time_interval is not None:
            start, end = time_interval
            assert end > start, "%s is not more recent than %s" % (end, start)
            clauses.extend(
                [
                    BinaryPackagePublishingHistory.datepublished >= start,
                    BinaryPackagePublishingHistory.datepublished < end,
                ]
            )
        rows = (
            IStore(BinaryPackagePublishingHistory)
            .find(BinaryPackagePublishingHistory, *clauses)
            .order_by(BinaryPackagePublishingHistory.datepublished)
        )
        return rows.last()

    def _getPackageReleaseURLFromPublishingRecord(self, publishing_record):
        """Return the URL on this mirror from where the BinaryPackageRelease.

        Given a BinaryPackagePublishingHistory, return the URL on
        this mirror from where the BinaryPackageRelease file can be
        downloaded.
        """
        bpr = publishing_record.binarypackagerelease
        base_url = self.distribution_mirror.base_url
        path = poolify(bpr.sourcepackagename, self.component.name).as_posix()
        file = (
            IStore(BinaryPackageFile)
            .find(
                BinaryPackageFile,
                binarypackagerelease=bpr,
                filetype=BinaryPackageFileType.DEB,
            )
            .one()
        )
        full_path = "pool/%s/%s" % (path, file.libraryfile.filename)
        return urlappend(base_url, full_path)


@implementer(IMirrorDistroSeriesSource)
class MirrorDistroSeriesSource(StormBase, _MirrorSeriesMixIn):
    """See IMirrorDistroSeriesSource"""

    __storm_table__ = "MirrorDistroSeriesSource"
    __storm_order__ = [
        "distroseries",
        "component",
        "pocket",
        "freshness",
        "id",
    ]

    id = Int(primary=True)
    distribution_mirror_id = Int(name="distribution_mirror", allow_none=False)
    distribution_mirror = Reference(
        distribution_mirror_id, "DistributionMirror.id"
    )
    distroseries_id = Int(name="distroseries", allow_none=False)
    distroseries = Reference(distroseries_id, "DistroSeries.id")
    component_id = Int(name="component", allow_none=False)
    component = Reference(component_id, "Component.id")
    freshness = DBEnum(
        allow_none=False, default=MirrorFreshness.UNKNOWN, enum=MirrorFreshness
    )
    pocket = DBEnum(allow_none=False, enum=PackagePublishingPocket)

    def __init__(self, distribution_mirror, distroseries, component, pocket):
        self.distribution_mirror = distribution_mirror
        self.distroseries = distroseries
        self.component = component
        self.pocket = pocket

    def getLatestPublishingEntry(self, time_interval):
        clauses = [
            SourcePackagePublishingHistory.pocket == self.pocket,
            SourcePackagePublishingHistory.component == self.component,
            SourcePackagePublishingHistory.distroseries == self.distroseries,
            SourcePackagePublishingHistory.archive
            == self.distroseries.main_archive,
            SourcePackagePublishingHistory.status
            == PackagePublishingStatus.PUBLISHED,
        ]

        if time_interval is not None:
            start, end = time_interval
            assert end > start
            clauses.extend(
                [
                    SourcePackagePublishingHistory.datepublished >= start,
                    SourcePackagePublishingHistory.datepublished < end,
                ]
            )
        rows = (
            IStore(SourcePackagePublishingHistory)
            .find(SourcePackagePublishingHistory, *clauses)
            .order_by(SourcePackagePublishingHistory.datepublished)
        )
        return rows.last()

    def _getPackageReleaseURLFromPublishingRecord(self, publishing_record):
        """return the URL on this mirror from where the SourcePackageRelease.

        Given a SourcePackagePublishingHistory, return the URL on
        this mirror from where the SourcePackageRelease file can be
        downloaded.
        """
        spr = publishing_record.sourcepackagerelease
        base_url = self.distribution_mirror.base_url
        sourcename = spr.name
        path = poolify(sourcename, self.component.name)
        file = (
            IStore(SourcePackageReleaseFile)
            .find(
                SourcePackageReleaseFile,
                sourcepackagerelease=spr,
                filetype=SourcePackageFileType.DSC,
            )
            .one()
        )
        full_path = "pool/%s/%s" % (path, file.libraryfile.filename)
        return urlappend(base_url, full_path)


@implementer(IMirrorProbeRecord)
class MirrorProbeRecord(StormBase):
    """See IMirrorProbeRecord"""

    __storm_table__ = "MirrorProbeRecord"
    __storm_order__ = "id"

    id = Int(primary=True)
    distribution_mirror_id = Int(name="distribution_mirror", allow_none=False)
    distribution_mirror = Reference(
        distribution_mirror_id, "DistributionMirror.id"
    )
    log_file_id = Int(name="log_file", allow_none=False)
    log_file = Reference(log_file_id, "LibraryFileAlias.id")
    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )

    def __init__(self, distribution_mirror, log_file):
        self.distribution_mirror = distribution_mirror
        self.log_file = log_file
