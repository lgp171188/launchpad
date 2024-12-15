# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Classes to represent source packages in a distribution."""

__all__ = [
    "DistributionSourcePackage",
    "DistributionSourcePackageInDatabase",
]

import itertools
from operator import attrgetter, itemgetter
from threading import local

import six
import transaction
from breezy.lru_cache import LRUCache
from storm.databases.postgres import JSON
from storm.expr import And, Cast, Desc
from storm.locals import SQL, Bool, Int, Not, Reference, Store, Unicode
from zope.interface import implementer

from lp.bugs.interfaces.bugsummary import IBugSummaryDimension
from lp.bugs.model.bugtarget import BugTargetBase
from lp.bugs.model.structuralsubscription import (
    StructuralSubscriptionTargetMixin,
)
from lp.code.model.hasbranches import (
    HasBranchesMixin,
    HasCodeImportsMixin,
    HasMergeProposalsMixin,
)
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.model.distroseries import DistroSeries
from lp.registry.model.hasdrivers import HasDriversMixin
from lp.registry.model.karma import KarmaTotalCache
from lp.registry.model.packaging import Packaging
from lp.registry.model.sourcepackage import (
    SourcePackage,
    SourcePackageQuestionTargetMixin,
)
from lp.services.database.bulk import load
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.propertycache import cachedproperty
from lp.services.webhooks.model import WebhookTargetMixin
from lp.soyuz.enums import ArchivePurpose, PackagePublishingStatus
from lp.soyuz.model.archive import Archive
from lp.soyuz.model.distributionsourcepackagerelease import (
    DistributionSourcePackageRelease,
)
from lp.soyuz.model.publishing import SourcePackagePublishingHistory
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease
from lp.translations.interfaces.customlanguagecode import (
    IHasCustomLanguageCodes,
)
from lp.translations.model.customlanguagecode import (
    CustomLanguageCode,
    HasCustomLanguageCodesMixin,
)


class DistributionSourcePackageProperty:
    def __init__(self, attrname, default=None):
        self.attrname = attrname
        self.default = default

    def __get__(self, obj, class_):
        return getattr(obj._self_in_database, self.attrname, self.default)

    def __set__(self, obj, value):
        if obj._self_in_database is None:
            obj._new(obj.distribution, obj.sourcepackagename)
        setattr(obj._self_in_database, self.attrname, value)


@implementer(
    IBugSummaryDimension, IDistributionSourcePackage, IHasCustomLanguageCodes
)
class DistributionSourcePackage(
    BugTargetBase,
    SourcePackageQuestionTargetMixin,
    StructuralSubscriptionTargetMixin,
    HasBranchesMixin,
    HasCodeImportsMixin,
    HasCustomLanguageCodesMixin,
    HasMergeProposalsMixin,
    HasDriversMixin,
    WebhookTargetMixin,
):
    """This is a "Magic Distribution Source Package". It is not a
    Storm model, but instead it represents a source package with a particular
    name in a particular distribution. You can then ask it all sorts of
    things about the releases that are published under its name, the latest
    or current release, etc.
    """

    bug_reporting_guidelines = DistributionSourcePackageProperty(
        "bug_reporting_guidelines"
    )
    content_templates = DistributionSourcePackageProperty("content_templates")
    bug_reported_acknowledgement = DistributionSourcePackageProperty(
        "bug_reported_acknowledgement"
    )
    bug_count = DistributionSourcePackageProperty("bug_count")
    po_message_count = DistributionSourcePackageProperty("po_message_count")
    enable_bugfiling_duplicate_search = DistributionSourcePackageProperty(
        "enable_bugfiling_duplicate_search", default=True
    )

    def __init__(self, distribution, sourcepackagename):
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename

    def __repr__(self):
        return f"<{self.__class__.__name__} '{self.display_name}'>"

    @property
    def name(self):
        """See `IDistributionSourcePackage`."""
        return self.sourcepackagename.name

    @property
    def display_name(self):
        """See `IDistributionSourcePackage`."""
        return "%s in %s" % (
            self.sourcepackagename.name,
            self.distribution.displayname,
        )

    displayname = display_name

    @property
    def bugtargetdisplayname(self):
        """See `IBugTarget`."""
        return "%s (%s)" % (self.name, self.distribution.displayname)

    @property
    def bugtargetname(self):
        """See `IBugTarget`."""
        return "%s (%s)" % (self.name, self.distribution.displayname)

    @property
    def title(self):
        """See `IDistributionSourcePackage`."""
        return "%s package in %s" % (
            self.sourcepackagename.name,
            self.distribution.displayname,
        )

    @property
    def summary(self):
        """See `IDistributionSourcePackage`."""
        if self.development_version is None:
            return None
        return self.development_version.summary

    @property
    def development_version(self):
        """See `IDistributionSourcePackage`."""
        series = self.distribution.currentseries
        if series is None:
            return None
        return series.getSourcePackage(self.sourcepackagename)

    @property
    def _self_in_database(self):
        """Return the equivalent database-backed record of self."""
        # XXX: allenap 2008-11-13 bug=297736: This is a temporary
        # measure while DistributionSourcePackage is not yet hooked
        # into the database but we need access to some of the fields
        # in the database.
        return self._get(self.distribution, self.sourcepackagename)

    @property
    def is_official(self):
        """See `DistributionSourcePackage`."""
        # This will need to verify that the package has not been deleted
        # in the future.
        return self._get(self.distribution, self.sourcepackagename) is not None

    @property
    def drivers(self):
        """See `IHasDrivers`."""
        return self.distribution.drivers

    def delete(self):
        """See `DistributionSourcePackage`."""
        dsp_in_db = self._self_in_database
        if dsp_in_db is not None and self.publishing_history.is_empty():
            IStore(dsp_in_db).remove(dsp_in_db)
            return True
        return False

    @property
    def latest_overall_publication(self):
        """See `IDistributionSourcePackage`."""
        # XXX kiko 2008-06-03: This is magical code that finds the
        # latest relevant publication. It relies on ordering of status
        # and pocket enum values, which is arguably evil but much faster
        # than CASE sorting; at any rate this can be fixed when
        # https://bugs.launchpad.net/soyuz/+bug/236922 is.
        spph = (
            IStore(SourcePackagePublishingHistory)
            .find(
                SourcePackagePublishingHistory,
                SourcePackagePublishingHistory.distroseries == DistroSeries.id,
                DistroSeries.distribution == self.distribution,
                SourcePackagePublishingHistory.sourcepackagename
                == self.sourcepackagename,
                SourcePackagePublishingHistory.archive_id.is_in(
                    self.distribution.all_distro_archive_ids
                ),
                Not(
                    SourcePackagePublishingHistory.pocket.is_in(
                        {
                            PackagePublishingPocket.PROPOSED,
                            PackagePublishingPocket.BACKPORTS,
                        }
                    )
                ),
                SourcePackagePublishingHistory.status.is_in(
                    {
                        PackagePublishingStatus.PUBLISHED,
                        PackagePublishingStatus.OBSOLETE,
                    }
                ),
            )
            .order_by(
                SourcePackagePublishingHistory.status,
                SQL("to_number(DistroSeries.version, '99.99') DESC"),
                Desc(SourcePackagePublishingHistory.pocket),
            )
            .first()
        )
        return spph

    def getVersion(self, version):
        """See `IDistributionSourcePackage`."""
        spr = (
            IStore(SourcePackagePublishingHistory)
            .find(
                SourcePackageRelease,
                SourcePackagePublishingHistory.distroseries == DistroSeries.id,
                DistroSeries.distribution == self.distribution,
                SourcePackagePublishingHistory.archive_id.is_in(
                    self.distribution.all_distro_archive_ids
                ),
                SourcePackagePublishingHistory.sourcepackagerelease
                == SourcePackageRelease.id,
                SourcePackagePublishingHistory.sourcepackagename
                == self.sourcepackagename,
                SourcePackageRelease.sourcepackagename
                == self.sourcepackagename,
                Cast(SourcePackageRelease.version, "text")
                == six.ensure_text(version),
            )
            .order_by(SourcePackagePublishingHistory.datecreated)
            .last()
        )
        if spr is None:
            return None
        return DistributionSourcePackageRelease(
            distribution=self.distribution, sourcepackagerelease=spr
        )

    # XXX kiko 2006-08-16: Bad method name, no need to be a property.
    @property
    def currentrelease(self):
        """See `IDistributionSourcePackage`."""
        releases = self.distribution.getCurrentSourceReleases(
            [self.sourcepackagename]
        )
        return releases.get(self)

    def get_distroseries_packages(self, active_only=True):
        """See `IDistributionSourcePackage`."""
        result = []
        for series in self.distribution.series:
            if active_only:
                if not series.active:
                    continue
            candidate = SourcePackage(self.sourcepackagename, series)
            if candidate.currentrelease is not None:
                result.append(candidate)
        return result

    def findRelatedArchives(
        self,
        exclude_archive=None,
        archive_purpose=ArchivePurpose.PPA,
        required_karma=0,
    ):
        """See `IDistributionSourcePackage`."""

        extra_args = []

        # Exclude the specified archive where appropriate
        if exclude_archive is not None:
            extra_args.append(Archive.id != exclude_archive.id)

        # Filter by archive purpose where appropriate
        if archive_purpose is not None:
            extra_args.append(Archive.purpose == archive_purpose)

        # Include only those archives containing the source package released
        # by a person with karma for this source package greater than that
        # specified.
        if required_karma > 0:
            extra_args.append(KarmaTotalCache.karma_total >= required_karma)

        store = Store.of(self.distribution)
        results = store.find(
            Archive,
            Archive.distribution == self.distribution,
            Archive._enabled == True,
            Archive.private == False,
            SourcePackagePublishingHistory.archive == Archive.id,
            (
                SourcePackagePublishingHistory.status
                == PackagePublishingStatus.PUBLISHED
            ),
            (
                SourcePackagePublishingHistory.sourcepackagerelease
                == SourcePackageRelease.id
            ),
            (
                SourcePackagePublishingHistory.sourcepackagename
                == self.sourcepackagename
            ),
            # Ensure that the package was not copied.
            SourcePackageRelease.upload_archive == Archive.id,
            # Next, the joins for the ordering by soyuz karma of the
            # SPR creator.
            KarmaTotalCache.person == SourcePackageRelease.creator_id,
            *extra_args,
        )

        # Note: If and when we later have a field on IArchive to order by,
        # such as IArchive.rank, we will then be able to return distinct
        # results. As it is, we cannot return distinct results while ordering
        # by a non-selected column.
        results.order_by(Desc(KarmaTotalCache.karma_total), Archive.id)

        return results

    @property
    def publishing_history(self):
        """See `IDistributionSourcePackage`."""
        return self._getPublishingHistoryQuery()

    @cachedproperty
    def binary_names(self):
        """See `IDistributionSourcePackage`."""
        names = []
        if not self.publishing_history.is_empty():
            binaries = self.publishing_history[0].getBuiltBinaries()
            names = [binary.binary_package_name for binary in binaries]
        return names

    @property
    def upstream_product(self):
        store = Store.of(self.sourcepackagename)
        condition = And(
            Packaging.sourcepackagename == self.sourcepackagename,
            Packaging.distroseries_id == DistroSeries.id,
            DistroSeries.distribution == self.distribution,
        )
        result = store.find(Packaging, condition)
        result.order_by("debversion_sort_key(version) DESC")
        if result.is_empty():
            return None
        else:
            return result[0].productseries.product

    # XXX kiko 2006-08-16: Bad method name, no need to be a property.
    @property
    def current_publishing_records(self):
        """See `IDistributionSourcePackage`."""
        status = PackagePublishingStatus.PUBLISHED
        return self._getPublishingHistoryQuery(status)

    def _getPublishingHistoryQuery(self, status=None):
        conditions = [
            SourcePackagePublishingHistory.archive_id.is_in(
                self.distribution.all_distro_archive_ids
            ),
            SourcePackagePublishingHistory.distroseries_id == DistroSeries.id,
            DistroSeries.distribution == self.distribution,
            SourcePackagePublishingHistory.sourcepackagename
            == self.sourcepackagename,
            SourcePackageRelease.id
            == SourcePackagePublishingHistory.sourcepackagerelease_id,
        ]

        if status is not None:
            conditions.append(SourcePackagePublishingHistory.status == status)

        res = IStore(SourcePackagePublishingHistory).find(
            (SourcePackagePublishingHistory, SourcePackageRelease), *conditions
        )
        res.order_by(
            Desc(SourcePackagePublishingHistory.datecreated),
            Desc(SourcePackagePublishingHistory.id),
        )
        return DecoratedResultSet(res, itemgetter(0))

    def getReleasesAndPublishingHistory(self):
        """See `IDistributionSourcePackage`."""
        pub_constraints = (
            DistroSeries.distribution == self.distribution,
            SourcePackagePublishingHistory.distroseries == DistroSeries.id,
            SourcePackagePublishingHistory.archive_id.is_in(
                self.distribution.all_distro_archive_ids
            ),
            SourcePackagePublishingHistory.sourcepackagename
            == self.sourcepackagename,
        )

        # Find distinct SPRs for our SPN in our archives.
        spr_ids = (
            Store.of(self.distribution)
            .find(
                SourcePackagePublishingHistory.sourcepackagerelease_id,
                *pub_constraints,
            )
            .order_by(
                Desc(SourcePackagePublishingHistory.sourcepackagerelease_id)
            )
            .config(distinct=True)
        )

        def decorate(spr_ids):
            # Find the SPPHs for each SPR in our result.
            load(SourcePackageRelease, spr_ids)
            sprs = [
                IStore(SourcePackageRelease).get(SourcePackageRelease, spr_id)
                for spr_id in spr_ids
            ]
            pubs = DistributionSourcePackageRelease.getPublishingHistories(
                self.distribution, sprs
            )
            sprs_by_id = {
                spr: list(pubs)
                for (spr, pubs) in itertools.groupby(
                    pubs, attrgetter("sourcepackagerelease_id")
                )
            }
            return [
                (
                    DistributionSourcePackageRelease(
                        distribution=self.distribution,
                        sourcepackagerelease=spr,
                    ),
                    sprs_by_id[spr.id],
                )
                for spr in sprs
            ]

        return DecoratedResultSet(spr_ids, bulk_decorator=decorate)

    # XXX kiko 2006-08-16: Bad method name, no need to be a property.
    @property
    def releases(self):
        """See `IDistributionSourcePackage`."""
        return [
            dspr for (dspr, pubs) in self.getReleasesAndPublishingHistory()
        ]

    def __eq__(self, other):
        """See `IDistributionSourcePackage`."""
        return (
            (IDistributionSourcePackage.providedBy(other))
            and (self.distribution.id == other.distribution.id)
            and (self.sourcepackagename.id == other.sourcepackagename.id)
        )

    def __hash__(self):
        """Return the combined hash of distribution and package name."""
        # Combine two hashes, in order to try to get the hash somewhat
        # unique (it doesn't have to be unique). Use ^ instead of +, to
        # avoid the hash from being larger than sys.maxint.
        return hash(self.distribution) ^ hash(self.sourcepackagename)

    def __ne__(self, other):
        """See `IDistributionSourcePackage`."""
        return not self.__eq__(other)

    @property
    def pillar(self):
        """See `IBugTarget`."""
        return self.distribution

    def getBugSummaryContextWhereClause(self):
        """See `BugTargetBase`."""
        # Circular fail.
        from lp.bugs.model.bugsummary import BugSummary

        return (
            And(
                BugSummary.distribution == self.distribution,
                BugSummary.sourcepackagename == self.sourcepackagename,
            ),
        )

    def _customizeSearchParams(self, search_params):
        """Customize `search_params` for this distribution source package."""
        search_params.setSourcePackage(self)

    def _getOfficialTagClause(self):
        return self.distribution._getOfficialTagClause()

    @property
    def official_bug_tags(self):
        """See `IHasBugs`."""
        return self.distribution.official_bug_tags

    def composeCustomLanguageCodeMatch(self):
        """See `HasCustomLanguageCodesMixin`."""
        return And(
            CustomLanguageCode.distribution == self.distribution,
            CustomLanguageCode.sourcepackagename == self.sourcepackagename,
        )

    @classmethod
    def _get(cls, distribution, sourcepackagename):
        return DistributionSourcePackageInDatabase.get(
            distribution, sourcepackagename
        )

    @classmethod
    def _new(cls, distribution, sourcepackagename):
        return DistributionSourcePackageInDatabase.new(
            distribution, sourcepackagename
        )

    @classmethod
    def ensure(cls, spph=None, sourcepackage=None):
        """Create DistributionSourcePackage record, if necessary.

        Only create a record for primary archives (i.e. not for PPAs) or
        for official package branches. Requires either a SourcePackage
        or a SourcePackagePublishingHistory.

        :param spph: A SourcePackagePublishingHistory to create a DSP
            to represent an official uploaded/published package.
        :param sourcepackage: A SourcePackage to create a DSP to represent an
            official package branch.
        """
        if spph is None and sourcepackage is None:
            raise ValueError(
                "ensure() must be called with either a SPPH "
                "or a SourcePackage."
            )
        if spph is not None:
            if spph.archive.purpose != ArchivePurpose.PRIMARY:
                return
            distribution = spph.distroseries.distribution
            sourcepackagename = spph.sourcepackagerelease.sourcepackagename
        else:
            distribution = sourcepackage.distribution
            sourcepackagename = sourcepackage.sourcepackagename
        dsp = cls._get(distribution, sourcepackagename)
        if dsp is None:
            cls._new(distribution, sourcepackagename)

    @property
    def valid_webhook_event_types(self):
        return ["bug:0.1", "bug:comment:0.1"]


@implementer(transaction.interfaces.ISynchronizer)
class ThreadLocalLRUCache(LRUCache, local):
    """A per-thread LRU cache that can synchronize with a transaction."""

    def newTransaction(self, txn):
        pass

    def beforeCompletion(self, txn):
        pass

    def afterCompletion(self, txn):
        # Clear the cache when a transaction is committed or aborted.
        self.clear()


class DistributionSourcePackageInDatabase(StormBase):
    """Temporary class to allow access to the database."""

    # XXX: allenap 2008-11-13 bug=297736: This is a temporary measure
    # while DistributionSourcePackage is not yet hooked into the
    # database but we need access to some of the fields in the
    # database.

    __storm_table__ = "DistributionSourcePackage"

    id = Int(primary=True)

    distribution_id = Int(name="distribution")
    distribution = Reference(distribution_id, "Distribution.id")

    sourcepackagename_id = Int(name="sourcepackagename")
    sourcepackagename = Reference(sourcepackagename_id, "SourcePackageName.id")

    bug_reporting_guidelines = Unicode()
    content_templates = JSON()
    bug_reported_acknowledgement = Unicode()

    bug_count = Int()
    po_message_count = Int()
    enable_bugfiling_duplicate_search = Bool()

    @property
    def currentrelease(self):
        """See `IDistributionSourcePackage`."""
        releases = self.distribution.getCurrentSourceReleases(
            [self.sourcepackagename]
        )
        return releases.get(self)

    # This is a per-thread LRU cache of mappings from (distribution_id,
    # sourcepackagename_id)) to dsp_id. See get() for how this cache helps to
    # avoid database hits without causing consistency issues.
    _cache = ThreadLocalLRUCache(1000, 700)
    # Synchronize the mapping cache with transactions. The mapping is not
    # especially useful after a transaction completes because Storm invalidates
    # its caches, and leaving the mapping cache in place causes difficult to
    # understand test interactions.
    transaction.manager.registerSynch(_cache)

    @classmethod
    def get(cls, distribution, sourcepackagename):
        """Get a DSP given distribution and source package name.

        Attempts to use a cached `(distro_id, spn_id) --> dsp_id` mapping to
        avoid hitting the database.
        """
        # Check for a cached mapping from (distro_id, spn_id) to dsp_id.
        dsp_cache_key = distribution.id, sourcepackagename.id
        dsp_id = cls._cache.get(dsp_cache_key)
        # If not, fetch from the database.
        if dsp_id is None:
            return cls.getDirect(distribution, sourcepackagename)
        # Try store.get(), allowing Storm to answer from cache if it can.
        store = Store.of(distribution)
        dsp = store.get(DistributionSourcePackageInDatabase, dsp_id)
        # If it's not found, query the database; the mapping might be stale.
        if dsp is None:
            return cls.getDirect(distribution, sourcepackagename)
        # Check that the mapping in the cache was correct.
        if distribution.id != dsp.distribution_id:
            return cls.getDirect(distribution, sourcepackagename)
        if sourcepackagename.id != dsp.sourcepackagename_id:
            return cls.getDirect(distribution, sourcepackagename)
        # Cache hit, phew.
        return dsp

    @classmethod
    def getDirect(cls, distribution, sourcepackagename):
        """Get a DSP given distribution and source package name.

        Caches the `(distro_id, spn_id) --> dsp_id` mapping, but does not
        otherwise use the cache; it always goes to the database.
        """
        dsp = (
            Store.of(distribution)
            .find(
                DistributionSourcePackageInDatabase,
                DistributionSourcePackageInDatabase.sourcepackagename
                == sourcepackagename,
                DistributionSourcePackageInDatabase.distribution
                == distribution,
            )
            .one()
        )
        dsp_cache_key = distribution.id, sourcepackagename.id
        if dsp is None:
            pass  # No way to eject things from the cache!
        else:
            cls._cache[dsp_cache_key] = dsp.id
        return dsp

    @classmethod
    def new(cls, distribution, sourcepackagename):
        """Create a new DSP with the given parameters.

        Caches the `(distro_id, spn_id) --> dsp_id` mapping.
        """
        dsp = DistributionSourcePackageInDatabase()
        dsp.distribution = distribution
        dsp.sourcepackagename = sourcepackagename
        Store.of(distribution).add(dsp)
        Store.of(distribution).flush()
        dsp_cache_key = distribution.id, sourcepackagename.id
        cls._cache[dsp_cache_key] = dsp.id
        return dsp
