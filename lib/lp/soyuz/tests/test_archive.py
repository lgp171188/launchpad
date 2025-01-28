# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Archive features."""

import doctest
import http.client
import os.path
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePath
from urllib.parse import urlsplit

import responses
import transaction
from aptsources.sourceslist import SourceEntry
from storm.store import Store
from testtools.matchers import (
    AfterPreprocessing,
    AllMatch,
    DocTestMatches,
    Equals,
    LessThan,
    MatchesListwise,
    MatchesPredicate,
    MatchesStructure,
)
from testtools.testcase import ExpectedException
from testtools.twistedsupport import (
    AsynchronousDeferredRunTest,
    AsynchronousDeferredRunTestForBrokenTwisted,
)
from twisted.internet import defer
from zope.component import getUtility
from zope.security.interfaces import Unauthorized
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.archivepublisher.interfaces.archivegpgsigningkey import (
    IArchiveGPGSigningKey,
)
from lp.buildmaster.enums import BuildQueueStatus, BuildStatus
from lp.buildmaster.interfaces.buildfarmjobbehaviour import (
    IBuildFarmJobBehaviour,
)
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.registry.enums import PersonVisibility, TeamMembershipPolicy
from lp.registry.interfaces.distribution import IDistributionSet
from lp.registry.interfaces.person import IPersonSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.teammembership import TeamMembershipStatus
from lp.services.authserver.testing import InProcessAuthServerFixture
from lp.services.database.interfaces import IStore
from lp.services.features import getFeatureFlag
from lp.services.features.testing import FeatureFixture
from lp.services.gpg.interfaces import (
    GPGKeyDoesNotExistOnServer,
    GPGKeyTemporarilyNotFoundError,
    IGPGHandler,
)
from lp.services.job.interfaces.job import JobStatus
from lp.services.macaroons.testing import MacaroonVerifies
from lp.services.propertycache import clear_property_cache, get_property_cache
from lp.services.signing.enums import SigningKeyType
from lp.services.signing.interfaces.signingkey import IArchiveSigningKeySet
from lp.services.timeout import default_timeout
from lp.services.webapp.authorization import check_permission
from lp.services.webapp.interfaces import OAuthPermission
from lp.services.worlddata.interfaces.country import ICountrySet
from lp.soyuz.adapters.archivedependencies import get_sources_list_for_building
from lp.soyuz.adapters.overrides import BinaryOverride, SourceOverride
from lp.soyuz.enums import (
    ArchivePermissionType,
    ArchivePublishingMethod,
    ArchivePurpose,
    ArchiveRepositoryFormat,
    ArchiveStatus,
    PackageCopyPolicy,
    PackagePublishingStatus,
)
from lp.soyuz.interfaces.archive import (
    NAMED_AUTH_TOKEN_FEATURE_FLAG,
    ArchiveDependencyError,
    ArchiveDisabled,
    ArchiveNotPrivate,
    CannotCopy,
    CannotModifyArchiveProcessor,
    CannotUploadToPocket,
    CannotUploadToPPA,
    CannotUploadToSeries,
    DuplicateTokenName,
    IArchiveSet,
    InsufficientUploadRights,
    InvalidExternalDependencies,
    InvalidPocketForPartnerArchive,
    InvalidPocketForPPA,
    NamedAuthTokenFeatureDisabled,
    NoRightsForArchive,
    NoRightsForComponent,
    NoSuchPPA,
    RedirectedPocket,
    VersionRequiresName,
)
from lp.soyuz.interfaces.archivejob import ICIBuildUploadJobSource
from lp.soyuz.interfaces.archivepermission import IArchivePermissionSet
from lp.soyuz.interfaces.binarypackagebuild import BuildSetStatus
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.packagecopyjob import IPlainPackageCopyJobSource
from lp.soyuz.interfaces.publishing import (
    active_publishing_status,
    inactive_publishing_status,
)
from lp.soyuz.model.archive import (
    Archive,
    CannotSetMetadataOverrides,
    validate_ppa,
)
from lp.soyuz.model.archivepermission import (
    ArchivePermission,
    ArchivePermissionSet,
)
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.model.binarypackagerelease import (
    BinaryPackageReleaseDownloadCount,
)
from lp.soyuz.model.component import ComponentSelection
from lp.soyuz.tests.soyuz import Base64KeyMatches
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import (
    ANONYMOUS,
    RequestTimelineCollector,
    StormStatementRecorder,
    TestCaseWithFactory,
    admin_logged_in,
    celebrity_logged_in,
    login,
    login_celebrity,
    login_person,
    person_logged_in,
)
from lp.testing.gpgkeys import gpgkeysdir
from lp.testing.keyserver import InProcessKeyServerFixture
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
)
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person
from lp.testing.views import create_webservice_error_view


class TestGetPublicationsInArchive(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def makeArchivesForOneDistribution(self, count=3):
        distribution = self.factory.makeDistribution()
        archives = []
        for _ in range(count):
            archives.append(
                self.factory.makeArchive(distribution=distribution)
            )
        return archives

    def makeArchivesWithPublications(self, count=3):
        archives = self.makeArchivesForOneDistribution(count=count)
        sourcepackagename = self.factory.makeSourcePackageName()
        for archive in archives:
            self.factory.makeSourcePackagePublishingHistory(
                sourcepackagename=sourcepackagename,
                archive=archive,
                status=PackagePublishingStatus.PUBLISHED,
            )
        return archives, sourcepackagename

    def getPublications(
        self, sourcepackagename, archives, distribution=None, distroseries=None
    ):
        return getUtility(IArchiveSet).getPublicationsInArchives(
            sourcepackagename,
            archives,
            distribution=distribution,
            distroseries=distroseries,
        )

    def test_getPublications_returns_all_published_publications(self):
        # Returns all currently published publications for archives
        archives, sourcepackagename = self.makeArchivesWithPublications()
        results = self.getPublications(
            sourcepackagename, archives, distribution=archives[0].distribution
        )
        self.assertEqual(3, results.count())

    def test_getPublications_empty_list_of_archives(self):
        # Passing an empty list of archives will result in an empty
        # resultset.
        archives, sourcepackagename = self.makeArchivesWithPublications()
        results = self.getPublications(
            sourcepackagename, [], distribution=archives[0].distribution
        )
        self.assertEqual([], list(results))

    def assertPublicationsFromArchives(self, publications, archives):
        self.assertEqual(len(archives), publications.count())
        for publication, archive in zip(publications, archives):
            self.assertEqual(archive, publication.archive)

    def test_getPublications_returns_only_for_given_archives(self):
        # Returns only publications for the specified archives
        archives, sourcepackagename = self.makeArchivesWithPublications()
        results = self.getPublications(
            sourcepackagename,
            [archives[0]],
            distribution=archives[0].distribution,
        )
        self.assertPublicationsFromArchives(results, [archives[0]])

    def test_getPublications_returns_only_published_publications(self):
        # Publications that are not published will not be returned.
        archive = self.factory.makeArchive()
        sourcepackagename = self.factory.makeSourcePackageName()
        self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            sourcepackagename=sourcepackagename,
            status=PackagePublishingStatus.PENDING,
        )
        results = self.getPublications(
            sourcepackagename, [archive], distribution=archive.distribution
        )
        self.assertEqual([], list(results))

    def publishSourceInNewArchive(self, sourcepackagename):
        distribution = self.factory.makeDistribution()
        distroseries = self.factory.makeDistroSeries(distribution=distribution)
        archive = self.factory.makeArchive(distribution=distribution)
        self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
            status=PackagePublishingStatus.PUBLISHED,
        )
        return archive

    def test_getPublications_for_specific_distro(self):
        # Results can be filtered for specific distributions.
        sourcepackagename = self.factory.makeSourcePackageName()
        archive = self.publishSourceInNewArchive(sourcepackagename)
        other_archive = self.publishSourceInNewArchive(sourcepackagename)
        # We don't get the results for other_distribution
        results = self.getPublications(
            sourcepackagename,
            [archive, other_archive],
            distribution=archive.distribution,
        )
        self.assertPublicationsFromArchives(results, [archive])

    def test_getPublications_for_specific_distroseries(self):
        # Results can be filtered for specific distroseries.
        archives = self.makeArchivesForOneDistribution()
        sourcepackagename = self.factory.makeSourcePackageName()
        distroseries_list = [
            self.factory.makeDistroSeries(
                distribution=archives[0].distribution
            )
            for _ in range(3)
        ]
        for archive in archives:
            for distroseries in distroseries_list:
                self.factory.makeSourcePackagePublishingHistory(
                    sourcepackagename=sourcepackagename,
                    distroseries=distroseries,
                    archive=archive,
                    status=PackagePublishingStatus.PUBLISHED,
                )
        for distroseries in distroseries_list:
            results = self.getPublications(
                sourcepackagename, archives, distroseries=distroseries
            )
            self.assertPublicationsFromArchives(results, archives)
            for publication in results:
                self.assertEqual(distroseries, publication.distroseries)


class TestArchiveRepositorySize(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def test_empty_ppa_has_zero_binaries_size(self):
        # An empty PPA has no binaries so has zero binaries_size.
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertEqual(0, ppa.binaries_size)

    def test_sources_size_on_empty_archive(self):
        # Zero is returned for an archive without sources.
        archive = self.factory.makeArchive()
        self.assertEqual(0, archive.sources_size)

    def publishSourceFile(self, archive, library_file):
        """Publish a source package with the given content to the archive.

        :param archive: the IArchive to publish to.
        :param library_file: a LibraryFileAlias for the content of the
            source file.
        """
        sourcepackagerelease = self.factory.makeSourcePackageRelease()
        self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            distroseries=archive.distribution.currentseries,
            sourcepackagerelease=sourcepackagerelease,
            status=PackagePublishingStatus.PUBLISHED,
        )
        self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=sourcepackagerelease,
            library_file=library_file,
        )

    def test_sources_size_does_not_count_duplicated_files(self):
        # If there are multiple copies of the same file name/size
        # only one will be counted.
        archive = self.factory.makeArchive()
        library_file = self.factory.makeLibraryFileAlias()
        self.publishSourceFile(archive, library_file)
        self.assertEqual(library_file.content.filesize, archive.sources_size)

        self.publishSourceFile(archive, library_file)
        self.assertEqual(library_file.content.filesize, archive.sources_size)


class TestSeriesWithSources(TestCaseWithFactory):
    """Create some sources in different series."""

    layer = DatabaseFunctionalLayer

    def test_series_with_sources_returns_all_series(self):
        # Calling series_with_sources returns all series with publishings.
        distribution = self.factory.makeDistribution()
        archive = self.factory.makeArchive(distribution=distribution)
        self.factory.makeDistroSeries(distribution=distribution, version="0.5")
        series_with_sources1 = self.factory.makeDistroSeries(
            distribution=distribution, version="1"
        )
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series_with_sources1,
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        series_with_sources2 = self.factory.makeDistroSeries(
            distribution=distribution, version="2"
        )
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series_with_sources2,
            archive=archive,
            status=PackagePublishingStatus.PENDING,
        )
        self.assertEqual(
            [series_with_sources2, series_with_sources1],
            archive.series_with_sources,
        )

    def test_series_with_sources_ignore_non_published_records(self):
        # If all publishings in a series are deleted or superseded
        # the series will not be returned.
        series = self.factory.makeDistroSeries()
        archive = self.factory.makeArchive(distribution=series.distribution)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series,
            archive=archive,
            status=PackagePublishingStatus.DELETED,
        )
        self.assertEqual([], archive.series_with_sources)

    def test_series_with_sources_ordered_by_version(self):
        # The returned series are ordered by the distroseries version.
        distribution = self.factory.makeDistribution()
        archive = self.factory.makeArchive(distribution=distribution)
        series1 = self.factory.makeDistroSeries(
            version="1", distribution=distribution
        )
        series2 = self.factory.makeDistroSeries(
            version="2", distribution=distribution
        )
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series1,
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=series2,
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        self.assertEqual([series2, series1], archive.series_with_sources)
        # Change the version such that they should order differently
        removeSecurityProxy(series2).version = "0.5"
        # ... and check that they do
        self.assertEqual([series1, series2], archive.series_with_sources)


class TestArchiveEnableDisable(TestCaseWithFactory):
    """Test the enable and disable methods of Archive."""

    layer = DatabaseFunctionalLayer

    def _getBuildQueuesByStatus(self, archive, status):
        # Return the count for archive build jobs with the given status.
        return (
            IStore(BuildQueue)
            .find(
                BuildQueue.id,
                BinaryPackageBuild.build_farm_job_id
                == BuildQueue._build_farm_job_id,
                BinaryPackageBuild.archive == archive,
                BinaryPackageBuild.status == BuildStatus.NEEDSBUILD,
                BuildQueue.status == status,
            )
            .count()
        )

    def assertNoBuildQueuesHaveStatus(self, archive, status):
        # Check that that the jobs attached to this archive do not have this
        # status.
        self.assertEqual(self._getBuildQueuesByStatus(archive, status), 0)

    def assertHasBuildQueuesWithStatus(self, archive, status, count):
        # Check that that there are jobs attached to this archive that have
        # the specified status.
        self.assertEqual(self._getBuildQueuesByStatus(archive, status), count)

    def test_enableArchive(self):
        # Enabling an archive should set all the Archive's suspended builds to
        # WAITING.
        archive = self.factory.makeArchive(enabled=True)
        build = self.factory.makeBinaryPackageBuild(
            archive=archive, status=BuildStatus.NEEDSBUILD
        )
        build.queueBuild()
        # disable the archive, as it is currently enabled
        removeSecurityProxy(archive).disable()
        self.assertHasBuildQueuesWithStatus(
            archive, BuildQueueStatus.SUSPENDED, 1
        )
        removeSecurityProxy(archive).enable()
        self.assertNoBuildQueuesHaveStatus(archive, BuildQueueStatus.SUSPENDED)
        self.assertTrue(archive.enabled)

    def test_enableArchive_virt_sets_virtualized(self):
        # Enabling an archive that requires virtualized builds changes all
        # its pending builds to be virtualized.
        archive = self.factory.makeArchive(virtualized=False)
        other_archive = self.factory.makeArchive(virtualized=False)
        pending_builds = [
            self.factory.makeBinaryPackageBuild(
                archive=archive, status=BuildStatus.NEEDSBUILD
            )
            for _ in range(2)
        ]
        completed_build = self.factory.makeBinaryPackageBuild(
            archive=archive, status=BuildStatus.FULLYBUILT
        )
        other_build = self.factory.makeBinaryPackageBuild(
            archive=other_archive, status=BuildStatus.NEEDSBUILD
        )
        for build in pending_builds + [completed_build, other_build]:
            self.assertFalse(build.virtualized)
            build.queueBuild()
            self.assertFalse(build.buildqueue_record.virtualized)
        removeSecurityProxy(archive).disable()
        removeSecurityProxy(archive).require_virtualized = True
        removeSecurityProxy(archive).enable()
        # Pending builds in the just-enabled archive are now virtualized.
        for build in pending_builds:
            self.assertTrue(build.virtualized)
            self.assertTrue(build.buildqueue_record.virtualized)
        # Completed builds and builds in other archives are untouched.
        for build in completed_build, other_build:
            self.assertFalse(build.virtualized)
            self.assertFalse(build.buildqueue_record.virtualized)

    def test_enableArchive_nonvirt_sets_virtualized(self):
        # Enabling an archive that does not require virtualized builds
        # changes its pending builds to be virtualized or not depending on
        # whether their processor supports non-virtualized builds.
        distroseries = self.factory.makeDistroSeries()
        archive = self.factory.makeArchive(
            distribution=distroseries.distribution, virtualized=False
        )
        other_archive = self.factory.makeArchive(
            distribution=distroseries.distribution, virtualized=False
        )
        procs = [self.factory.makeProcessor() for _ in range(2)]
        dases = [
            self.factory.makeDistroArchSeries(
                distroseries=distroseries, processor=procs[i]
            )
            for i in range(2)
        ]
        pending_builds = [
            self.factory.makeBinaryPackageBuild(
                distroarchseries=dases[i],
                archive=archive,
                status=BuildStatus.NEEDSBUILD,
                processor=procs[i],
            )
            for i in range(2)
        ]
        completed_build = self.factory.makeBinaryPackageBuild(
            distroarchseries=dases[0],
            archive=archive,
            status=BuildStatus.FULLYBUILT,
            processor=procs[0],
        )
        other_build = self.factory.makeBinaryPackageBuild(
            distroarchseries=dases[0],
            archive=other_archive,
            status=BuildStatus.NEEDSBUILD,
            processor=procs[0],
        )
        for build in pending_builds + [completed_build, other_build]:
            self.assertFalse(build.virtualized)
            build.queueBuild()
            self.assertFalse(build.buildqueue_record.virtualized)
        removeSecurityProxy(archive).disable()
        procs[0].supports_nonvirtualized = False
        removeSecurityProxy(archive).enable()
        # Pending builds in the just-enabled archive are now virtualized iff
        # their processor does not support non-virtualized builds.
        self.assertTrue(pending_builds[0].virtualized)
        self.assertTrue(pending_builds[0].buildqueue_record.virtualized)
        self.assertFalse(pending_builds[1].virtualized)
        self.assertFalse(pending_builds[1].buildqueue_record.virtualized)
        # Completed builds and builds in other archives are untouched.
        for build in completed_build, other_build:
            self.assertFalse(build.virtualized)
            self.assertFalse(build.buildqueue_record.virtualized)

    def test_enableArchiveAlreadyEnabled(self):
        # Enabling an already enabled Archive should raise an AssertionError.
        archive = self.factory.makeArchive(enabled=True)
        self.assertRaises(AssertionError, removeSecurityProxy(archive).enable)

    def test_disableArchive(self):
        # Disabling an archive should set all the Archive's pending builds to
        # SUSPENDED.
        archive = self.factory.makeArchive(enabled=True)
        build = self.factory.makeBinaryPackageBuild(
            archive=archive, status=BuildStatus.NEEDSBUILD
        )
        build.queueBuild()
        self.assertHasBuildQueuesWithStatus(
            archive, BuildQueueStatus.WAITING, 1
        )
        removeSecurityProxy(archive).disable()
        self.assertNoBuildQueuesHaveStatus(archive, BuildQueueStatus.WAITING)
        self.assertFalse(archive.enabled)

    def test_disableArchiveAlreadyDisabled(self):
        # Disabling an already disabled Archive should raise an
        # AssertionError.
        archive = self.factory.makeArchive(enabled=False)
        self.assertRaises(AssertionError, removeSecurityProxy(archive).disable)


class TestCollectLatestPublishedSources(TestCaseWithFactory):
    """Ensure that the private helper method works as expected."""

    layer = DatabaseFunctionalLayer

    def makePublishedSources(self, archive, statuses, versions, names):
        for status, version, name in zip(statuses, versions, names):
            self.factory.makeSourcePackagePublishingHistory(
                sourcepackagename=name,
                archive=archive,
                version=version,
                status=status,
            )

    def test_collectLatestPublishedSources_returns_latest(self):
        sourcepackagename = self.factory.makeSourcePackageName(name="foo")
        other_spn = self.factory.makeSourcePackageName(name="bar")
        archive = self.factory.makeArchive()
        self.makePublishedSources(
            archive,
            [PackagePublishingStatus.PUBLISHED] * 3,
            ["1.0", "1.1", "2.0"],
            [sourcepackagename, sourcepackagename, other_spn],
        )
        pubs = removeSecurityProxy(archive)._collectLatestPublishedSources(
            archive, None, ["foo"]
        )
        self.assertEqual(1, len(pubs))
        self.assertEqual("1.1", pubs[0].source_package_version)

    def test_collectLatestPublishedSources_returns_published_only(self):
        # Set the status of the latest pub to DELETED and ensure that it
        # is not returned.
        sourcepackagename = self.factory.makeSourcePackageName(name="foo")
        other_spn = self.factory.makeSourcePackageName(name="bar")
        archive = self.factory.makeArchive()
        self.makePublishedSources(
            archive,
            [
                PackagePublishingStatus.PUBLISHED,
                PackagePublishingStatus.DELETED,
                PackagePublishingStatus.PUBLISHED,
            ],
            ["1.0", "1.1", "2.0"],
            [sourcepackagename, sourcepackagename, other_spn],
        )
        pubs = removeSecurityProxy(archive)._collectLatestPublishedSources(
            archive, None, ["foo"]
        )
        self.assertEqual(1, len(pubs))
        self.assertEqual("1.0", pubs[0].source_package_version)

    def test_collectLatestPublishedSources_multiple_distroseries(self):
        # The helper method selects the correct publication from multiple
        # distroseries.
        sourcepackagename = self.factory.makeSourcePackageName(name="foo")
        archive = self.factory.makeArchive()
        distroseries_one = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        distroseries_two = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=sourcepackagename,
            archive=archive,
            distroseries=distroseries_one,
            version="1.0",
            status=PackagePublishingStatus.PUBLISHED,
        )
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=sourcepackagename,
            archive=archive,
            distroseries=distroseries_two,
            version="1.1",
            status=PackagePublishingStatus.PUBLISHED,
        )
        pubs = removeSecurityProxy(archive)._collectLatestPublishedSources(
            archive, distroseries_one.name, ["foo"]
        )
        self.assertEqual(1, len(pubs))
        self.assertEqual("1.0", pubs[0].source_package_version)


class TestArchiveCanUpload(TestCaseWithFactory):
    """Test the various methods that verify whether uploads are allowed to
    happen."""

    layer = DatabaseFunctionalLayer

    def test_checkArchivePermission_by_PPA_owner(self):
        # Uploading to a PPA should be allowed for a user that is the owner
        owner = self.factory.makePerson(name="somebody")
        archive = self.factory.makeArchive(owner=owner)
        self.assertTrue(archive.checkArchivePermission(owner))
        someone_unrelated = self.factory.makePerson(name="somebody-unrelated")
        self.assertFalse(archive.checkArchivePermission(someone_unrelated))

    def test_checkArchivePermission_distro_archive(self):
        # Regular users can not upload to ubuntu
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        # The factory sets the archive owner the same as the distro owner,
        # change that here to ensure the security adapter checks are right.
        removeSecurityProxy(archive).owner = self.factory.makePerson()
        main = getUtility(IComponentSet)["main"]
        # A regular user doesn't have access
        somebody = self.factory.makePerson()
        self.assertFalse(archive.checkArchivePermission(somebody, main))
        # An ubuntu core developer does have access
        coredev = self.factory.makePerson()
        with person_logged_in(archive.distribution.owner):
            archive.newComponentUploader(coredev, main.name)
        self.assertTrue(archive.checkArchivePermission(coredev, main))

    def test_checkArchivePermission_ppa(self):
        owner = self.factory.makePerson()
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.PPA, owner=owner
        )
        somebody = self.factory.makePerson()
        # The owner has access
        self.assertTrue(archive.checkArchivePermission(owner))
        # Somebody unrelated does not
        self.assertFalse(archive.checkArchivePermission(somebody))

    def makeArchiveAndActiveDistroSeries(
        self, purpose=ArchivePurpose.PRIMARY, status=SeriesStatus.DEVELOPMENT
    ):
        archive = self.factory.makeArchive(purpose=purpose)
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution, status=status
        )
        return archive, distroseries

    def makePersonWithComponentPermission(self, archive):
        person = self.factory.makePerson()
        component = self.factory.makeComponent()
        removeSecurityProxy(archive).newComponentUploader(person, component)
        return person, component

    def checkUpload(
        self,
        archive,
        person,
        sourcepackagename,
        distroseries=None,
        component=None,
        pocket=None,
        strict_component=False,
    ):
        if distroseries is None:
            distroseries = self.factory.makeDistroSeries()
        if component is None:
            component = self.factory.makeComponent()
        if pocket is None:
            pocket = PackagePublishingPocket.RELEASE
        return archive.checkUpload(
            person,
            distroseries,
            sourcepackagename,
            component,
            pocket,
            strict_component=strict_component,
        )

    def assertCanUpload(
        self,
        archive,
        person,
        sourcepackagename,
        distroseries=None,
        component=None,
        pocket=None,
        strict_component=False,
    ):
        """Assert an upload to 'archive' will be accepted."""
        self.assertIsNone(
            self.checkUpload(
                archive,
                person,
                sourcepackagename,
                distroseries=distroseries,
                component=component,
                pocket=pocket,
                strict_component=strict_component,
            )
        )

    def assertCannotUpload(
        self,
        reason,
        archive,
        person,
        sourcepackagename,
        distroseries=None,
        component=None,
        pocket=None,
        strict_component=False,
    ):
        """Assert that upload to 'archive' will be rejected.

        :param reason: The expected reason for not being able to upload. A
            class.
        """
        self.assertIsInstance(
            self.checkUpload(
                archive,
                person,
                sourcepackagename,
                distroseries=distroseries,
                component=component,
                pocket=pocket,
                strict_component=strict_component,
            ),
            reason,
        )

    def test_checkUpload_partner_invalid_pocket(self):
        # Partner archives only have release and proposed pockets
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PARTNER
        )
        self.assertCannotUpload(
            InvalidPocketForPartnerArchive,
            archive,
            self.factory.makePerson(),
            self.factory.makeSourcePackageName(),
            pocket=PackagePublishingPocket.UPDATES,
            distroseries=distroseries,
        )

    def test_checkUpload_ppa_invalid_pocket(self):
        # PPA archives only have release pockets
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PPA
        )
        self.assertCannotUpload(
            InvalidPocketForPPA,
            archive,
            self.factory.makePerson(),
            self.factory.makeSourcePackageName(),
            pocket=PackagePublishingPocket.PROPOSED,
            distroseries=distroseries,
        )

    def test_checkUpload_invalid_pocket_for_series_state(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        self.assertCannotUpload(
            CannotUploadToPocket,
            archive,
            self.factory.makePerson(),
            self.factory.makeSourcePackageName(),
            pocket=PackagePublishingPocket.UPDATES,
            distroseries=distroseries,
        )

    def test_checkUpload_primary_proposed_development(self):
        # It should be possible to upload to the PROPOSED pocket while the
        # distroseries is in the DEVELOPMENT status.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newPackageUploader(
            person, sourcepackagename
        )
        self.assertCanUpload(
            archive,
            person,
            sourcepackagename,
            pocket=PackagePublishingPocket.PROPOSED,
            distroseries=distroseries,
        )

    def test_checkUpload_backports_development(self):
        # It should be possible to upload to the BACKPORTS pocket while the
        # distroseries is in the DEVELOPMENT status.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newPackageUploader(
            person, sourcepackagename
        )
        self.assertCanUpload(
            archive,
            person,
            sourcepackagename,
            pocket=PackagePublishingPocket.BACKPORTS,
            distroseries=distroseries,
        )

    def test_checkUpload_disabled_archive(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        archive = removeSecurityProxy(archive)
        archive.disable()
        self.assertCannotUpload(
            ArchiveDisabled,
            archive,
            self.factory.makePerson(),
            self.factory.makeSourcePackageName(),
            distroseries=distroseries,
        )

    def test_checkUpload_ppa_owner(self):
        person = self.factory.makePerson()
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.PPA, owner=person
        )
        self.assertCanUpload(
            archive, person, self.factory.makeSourcePackageName()
        )

    def test_checkUpload_ppa_with_permission(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newComponentUploader(person, "main")
        # component is ignored
        self.assertCanUpload(
            archive,
            person,
            self.factory.makeSourcePackageName(),
            component=self.factory.makeComponent(name="universe"),
        )

    def test_checkUpload_ppa_with_no_permission(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        person = self.factory.makePerson()
        self.assertCannotUpload(
            CannotUploadToPPA,
            archive,
            person,
            self.factory.makeSourcePackageName(),
        )

    def test_owner_can_upload_to_ppa_no_sourcepackage(self):
        # The owner can upload to PPAs even if the source package doesn't
        # exist yet.
        team = self.factory.makeTeam()
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.PPA, owner=team
        )
        person = self.factory.makePerson()
        removeSecurityProxy(team).addMember(person, team.teamowner)
        self.assertCanUpload(archive, person, None)

    def test_can_upload_to_ppa_for_old_series(self):
        # You can upload whatever you want to a PPA, regardless of the upload
        # policy.
        person = self.factory.makePerson()
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.PPA, owner=person
        )
        spn = self.factory.makeSourcePackageName()
        distroseries = self.factory.makeDistroSeries(
            status=SeriesStatus.CURRENT
        )
        self.assertCanUpload(archive, person, spn, distroseries=distroseries)

    def test_checkUpload_copy_archive_no_permission(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.COPY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newPackageUploader(
            person, sourcepackagename
        )
        self.assertCannotUpload(
            NoRightsForArchive,
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
        )

    def test_checkUploadToPocket_for_released_distroseries_copy_archive(self):
        # Uploading to the release pocket in a released COPY archive
        # should be allowed.  This is mainly so that rebuilds that are
        # running during the release process don't suddenly cause
        # exceptions in the buildd-manager.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.COPY)
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution, status=SeriesStatus.CURRENT
        )
        self.assertIsNone(
            archive.checkUploadToPocket(
                distroseries, PackagePublishingPocket.RELEASE
            )
        )

    def test_checkUploadToPocket_handles_redirects(self):
        # Uploading to the release pocket is disallowed if
        # Distribution.redirect_release_uploads is set.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        with person_logged_in(archive.distribution.owner):
            archive.distribution.redirect_release_uploads = True
        person = self.factory.makePerson()
        self.assertIsInstance(
            archive.checkUploadToPocket(
                distroseries, PackagePublishingPocket.RELEASE, person=person
            ),
            RedirectedPocket,
        )
        # The proposed pocket is unaffected.
        self.assertIsNone(
            archive.checkUploadToPocket(
                distroseries, PackagePublishingPocket.PROPOSED, person=person
            )
        )
        # Queue admins bypass this check.
        with person_logged_in(archive.distribution.owner):
            archive.newQueueAdmin(person, "main")
        self.assertIsNone(
            archive.checkUploadToPocket(
                distroseries, PackagePublishingPocket.RELEASE, person=person
            )
        )

    def test_checkUpload_package_permission(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newPackageUploader(
            person, sourcepackagename
        )
        self.assertCanUpload(
            archive, person, sourcepackagename, distroseries=distroseries
        )

    def makePersonWithPocketPermission(self, archive, pocket):
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newPocketUploader(person, pocket)
        return person

    def test_checkUpload_pocket_permission(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY, status=SeriesStatus.CURRENT
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        pocket = PackagePublishingPocket.SECURITY
        person = self.makePersonWithPocketPermission(archive, pocket)
        self.assertCanUpload(
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
            pocket=pocket,
        )

    def make_person_with_packageset_permission(
        self, archive, distroseries, packages=()
    ):
        packageset = self.factory.makePackageset(
            distroseries=distroseries, packages=packages
        )
        person = self.factory.makePerson()
        with person_logged_in(archive.distribution.owner):
            archive.newPackagesetUploader(person, packageset)
        return person, packageset

    def test_checkUpload_packageset_permission(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person, packageset = self.make_person_with_packageset_permission(
            archive, distroseries, packages=[sourcepackagename]
        )
        self.assertCanUpload(
            archive, person, sourcepackagename, distroseries=distroseries
        )

    def test_checkUpload_packageset_wrong_distroseries(self):
        # A person with rights to upload to the package set in distro
        # series K may not upload with these same rights to a different
        # distro series L.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person, packageset = self.make_person_with_packageset_permission(
            archive, distroseries, packages=[sourcepackagename]
        )
        other_distroseries = self.factory.makeDistroSeries()
        self.assertCannotUpload(
            InsufficientUploadRights,
            archive,
            person,
            sourcepackagename,
            distroseries=other_distroseries,
        )

    def test_checkUpload_component_permission(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person, component = self.makePersonWithComponentPermission(archive)
        self.assertCanUpload(
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
            component=component,
        )

    def test_checkUpload_no_permissions(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person = self.factory.makePerson()
        self.assertCannotUpload(
            NoRightsForArchive,
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
        )

    def test_checkUpload_insufficient_permissions(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person, packageset = self.make_person_with_packageset_permission(
            archive, distroseries
        )
        self.assertCannotUpload(
            InsufficientUploadRights,
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
        )

    def test_checkUpload_without_strict_component(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person, component = self.makePersonWithComponentPermission(archive)
        other_component = self.factory.makeComponent()
        self.assertCanUpload(
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
            component=other_component,
            strict_component=False,
        )

    def test_checkUpload_with_strict_component(self):
        archive, distroseries = self.makeArchiveAndActiveDistroSeries(
            purpose=ArchivePurpose.PRIMARY
        )
        sourcepackagename = self.factory.makeSourcePackageName()
        person, component = self.makePersonWithComponentPermission(archive)
        other_component = self.factory.makeComponent()
        self.assertCannotUpload(
            NoRightsForComponent,
            archive,
            person,
            sourcepackagename,
            distroseries=distroseries,
            component=other_component,
            strict_component=True,
        )

    def test_checkUpload_component_rights_no_package(self):
        # A person allowed to upload to a particular component of an archive
        # can upload basically whatever they want to that component, even if
        # the package doesn't exist yet.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        person, component = self.makePersonWithComponentPermission(archive)
        self.assertCanUpload(archive, person, None, component=component)

    def test_checkUpload_ppa_obsolete_series(self):
        distroseries = self.factory.makeDistroSeries(
            status=SeriesStatus.OBSOLETE
        )
        ppa = self.factory.makeArchive(
            distribution=distroseries.distribution, purpose=ArchivePurpose.PPA
        )
        self.assertCannotUpload(
            CannotUploadToSeries,
            ppa,
            ppa.owner,
            None,
            distroseries=distroseries,
        )
        removeSecurityProxy(ppa).permit_obsolete_series_uploads = True
        self.assertCanUpload(ppa, ppa.owner, None, distroseries=distroseries)

    def makePackageToUpload(self, distroseries):
        sourcepackagename = self.factory.makeSourcePackageName()
        return self.factory.makeSuiteSourcePackage(
            pocket=PackagePublishingPocket.RELEASE,
            sourcepackagename=sourcepackagename,
            distroseries=distroseries,
        )

    def test_canUploadSuiteSourcePackage_invalid_pocket(self):
        # Test that canUploadSuiteSourcePackage calls checkUpload for
        # the pocket checks.
        person = self.factory.makePerson()
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.PPA, owner=person
        )
        suitesourcepackage = self.factory.makeSuiteSourcePackage(
            pocket=PackagePublishingPocket.PROPOSED
        )
        self.assertFalse(
            archive.canUploadSuiteSourcePackage(person, suitesourcepackage)
        )

    def test_canUploadSuiteSourcePackage_no_permission(self):
        # Test that canUploadSuiteSourcePackage calls verifyUpload for
        # the permission checks.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        suitesourcepackage = self.factory.makeSuiteSourcePackage(
            pocket=PackagePublishingPocket.RELEASE
        )
        person = self.factory.makePerson()
        self.assertFalse(
            archive.canUploadSuiteSourcePackage(person, suitesourcepackage)
        )

    def test_canUploadSuiteSourcePackage_package_permission(self):
        # Test that a package permission is enough to upload a new
        # package.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries()
        suitesourcepackage = self.makePackageToUpload(distroseries)
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newPackageUploader(
            person, suitesourcepackage.sourcepackagename
        )
        self.assertTrue(
            archive.canUploadSuiteSourcePackage(person, suitesourcepackage)
        )

    def test_canUploadSuiteSourcePackage_component_permission(self):
        # Test that component upload permission is enough to be
        # allowed to upload a new package.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries()
        suitesourcepackage = self.makePackageToUpload(distroseries)
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newComponentUploader(person, "universe")
        self.assertTrue(
            archive.canUploadSuiteSourcePackage(person, suitesourcepackage)
        )

    def test_canUploadSuiteSourcePackage_strict_component(self):
        # Test that canUploadSuiteSourcePackage uses strict component
        # checking.
        archive, distroseries = self.makeArchiveAndActiveDistroSeries()
        suitesourcepackage = self.makePackageToUpload(distroseries)
        main_component = self.factory.makeComponent(name="main")
        self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            distroseries=distroseries,
            sourcepackagename=suitesourcepackage.sourcepackagename,
            status=PackagePublishingStatus.PUBLISHED,
            pocket=PackagePublishingPocket.RELEASE,
            component=main_component,
        )
        person = self.factory.makePerson()
        removeSecurityProxy(archive).newComponentUploader(person, "universe")
        # This time the user can't upload as there has been a
        # publication and they don't have permission for the component
        # the package is published in.
        self.assertFalse(
            archive.canUploadSuiteSourcePackage(person, suitesourcepackage)
        )

    def test_hasAnyPermission(self):
        # hasAnyPermission returns true if the person is the member of a
        # team with any kind of permission on the archive.
        archive = self.factory.makeArchive()
        person = self.factory.makePerson()
        team = self.factory.makeTeam()
        main = getUtility(IComponentSet)["main"]
        ArchivePermission(
            archive=archive,
            person=team,
            component=main,
            permission=ArchivePermissionType.UPLOAD,
        )

        self.assertFalse(archive.hasAnyPermission(person))
        with celebrity_logged_in("admin"):
            team.addMember(person, team.teamowner)
        self.assertTrue(archive.hasAnyPermission(person))


class TestUpdatePackageDownloadCount(TestCaseWithFactory):
    """Ensure that updatePackageDownloadCount works as expected."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        self.store = IStore(Archive)

        self.archive = self.factory.makeArchive()
        self.bpr_1 = self.publisher.getPubBinaries(archive=self.archive)[
            0
        ].binarypackagerelease
        self.bpr_2 = self.publisher.getPubBinaries(archive=self.archive)[
            0
        ].binarypackagerelease

        country_set = getUtility(ICountrySet)
        self.australia = country_set["AU"]
        self.new_zealand = country_set["NZ"]

    def assertCount(self, count, archive, bpr, day, country):
        self.assertEqual(
            count,
            self.store.find(
                BinaryPackageReleaseDownloadCount,
                archive=archive,
                binary_package_release=bpr,
                day=day,
                country=country,
            )
            .one()
            .count,
        )

    def test_creates_new_entry(self):
        # The first update for a particular archive, package, day and
        # country will create a new BinaryPackageReleaseDownloadCount
        # entry.
        day = date(2010, 2, 20)
        self.assertIsNone(
            self.store.find(
                BinaryPackageReleaseDownloadCount,
                archive=self.archive,
                binary_package_release=self.bpr_1,
                day=day,
                country=self.australia,
            ).one()
        )
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 10
        )
        self.assertCount(10, self.archive, self.bpr_1, day, self.australia)
        self.assertEqual(10, self.archive.getPackageDownloadTotal(self.bpr_1))

    def test_reuses_existing_entry(self):
        # A second update will simply add to the count on the existing
        # BPRDC.
        day = date(2010, 2, 20)
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 10
        )
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 3
        )
        self.assertCount(13, self.archive, self.bpr_1, day, self.australia)
        self.assertEqual(13, self.archive.getPackageDownloadTotal(self.bpr_1))

    def test_differentiates_between_countries(self):
        # A different country will cause a new entry to be created.
        day = date(2010, 2, 20)
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 10
        )
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.new_zealand, 3
        )

        self.assertCount(10, self.archive, self.bpr_1, day, self.australia)
        self.assertCount(3, self.archive, self.bpr_1, day, self.new_zealand)
        self.assertEqual(13, self.archive.getPackageDownloadTotal(self.bpr_1))

    def test_country_can_be_none(self):
        # The country can be None, indicating that it is unknown.
        day = date(2010, 2, 20)
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 10
        )
        self.archive.updatePackageDownloadCount(self.bpr_1, day, None, 3)

        self.assertCount(10, self.archive, self.bpr_1, day, self.australia)
        self.assertCount(3, self.archive, self.bpr_1, day, None)
        self.assertEqual(13, self.archive.getPackageDownloadTotal(self.bpr_1))

    def test_differentiates_between_days(self):
        # A different date will also cause a new entry to be created.
        day = date(2010, 2, 20)
        another_day = date(2010, 2, 21)
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 10
        )
        self.archive.updatePackageDownloadCount(
            self.bpr_1, another_day, self.australia, 3
        )

        self.assertCount(10, self.archive, self.bpr_1, day, self.australia)
        self.assertCount(
            3, self.archive, self.bpr_1, another_day, self.australia
        )
        self.assertEqual(13, self.archive.getPackageDownloadTotal(self.bpr_1))

    def test_differentiates_between_bprs(self):
        # And even a different package will create a new entry.
        day = date(2010, 2, 20)
        self.archive.updatePackageDownloadCount(
            self.bpr_1, day, self.australia, 10
        )
        self.archive.updatePackageDownloadCount(
            self.bpr_2, day, self.australia, 3
        )

        self.assertCount(10, self.archive, self.bpr_1, day, self.australia)
        self.assertCount(3, self.archive, self.bpr_2, day, self.australia)
        self.assertEqual(10, self.archive.getPackageDownloadTotal(self.bpr_1))
        self.assertEqual(3, self.archive.getPackageDownloadTotal(self.bpr_2))


class TestProcessors(TestCaseWithFactory):
    """Ensure that restricted architectures builds can be allowed and
    disallowed correctly."""

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        """Setup an archive with relevant publications."""
        super().setUp(user="foo.bar@canonical.com")
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()
        self.archive = self.factory.makeArchive()
        self.default_procs = [
            getUtility(IProcessorSet).getByName("386"),
            getUtility(IProcessorSet).getByName("amd64"),
        ]
        self.unrestricted_procs = self.default_procs + [
            getUtility(IProcessorSet).getByName("hppa")
        ]
        self.arm = self.factory.makeProcessor(
            name="arm", restricted=True, build_by_default=False
        )

    def test_new_default_processors(self):
        # ArchiveSet.new creates an ArchiveArch for each Processor with
        # build_by_default set.
        self.factory.makeProcessor(name="default", build_by_default=True)
        self.factory.makeProcessor(name="nondefault", build_by_default=False)
        archive = getUtility(IArchiveSet).new(
            owner=self.factory.makePerson(),
            purpose=ArchivePurpose.PPA,
            distribution=self.factory.makeDistribution(),
            name="ppa",
        )
        self.assertContentEqual(
            ["386", "amd64", "hppa", "default"],
            [processor.name for processor in archive.processors],
        )

    def test_new_override_processors(self):
        # ArchiveSet.new can be given a custom set of processors.
        archive = getUtility(IArchiveSet).new(
            owner=self.factory.makePerson(),
            purpose=ArchivePurpose.PPA,
            distribution=self.factory.makeDistribution(),
            name="ppa",
            processors=[self.arm],
        )
        self.assertContentEqual(
            ["arm"], [processor.name for processor in archive.processors]
        )

    def test_get_returns_restricted_only(self):
        """enabled_restricted_processors shows only restricted processors."""
        self.assertContentEqual(
            self.unrestricted_procs, self.archive.processors
        )
        self.assertContentEqual([], self.archive.enabled_restricted_processors)
        uproc = self.factory.makeProcessor(
            restricted=False, build_by_default=True
        )
        rproc = self.factory.makeProcessor(
            restricted=True, build_by_default=False
        )
        self.archive.setProcessors([uproc, rproc])
        self.assertContentEqual([uproc, rproc], self.archive.processors)
        self.assertContentEqual(
            [rproc], self.archive.enabled_restricted_processors
        )

    def test_set(self):
        """The property remembers its value correctly."""
        self.archive.setProcessors([self.arm])
        self.assertContentEqual([self.arm], self.archive.processors)
        self.archive.setProcessors(self.unrestricted_procs + [self.arm])
        self.assertContentEqual(
            self.unrestricted_procs + [self.arm], self.archive.processors
        )
        self.archive.setProcessors([])
        self.assertContentEqual([], self.archive.processors)

    def test_set_non_admin(self):
        """Non-admins can only enable or disable unrestricted processors."""
        self.archive.setProcessors(self.default_procs)
        self.assertContentEqual(self.default_procs, self.archive.processors)
        with person_logged_in(self.archive.owner) as owner:
            # Adding arm is forbidden ...
            self.assertRaises(
                CannotModifyArchiveProcessor,
                self.archive.setProcessors,
                [self.default_procs[0], self.arm],
                check_permissions=True,
                user=owner,
            )
            # ... but removing amd64 is OK.
            self.archive.setProcessors(
                [self.default_procs[0]], check_permissions=True, user=owner
            )
            self.assertContentEqual(
                [self.default_procs[0]], self.archive.processors
            )
        with admin_logged_in() as admin:
            self.archive.setProcessors(
                [self.default_procs[0], self.arm],
                check_permissions=True,
                user=admin,
            )
            self.assertContentEqual(
                [self.default_procs[0], self.arm], self.archive.processors
            )
        with person_logged_in(self.archive.owner) as owner:
            hppa = getUtility(IProcessorSet).getByName("hppa")
            self.assertFalse(hppa.restricted)
            # Adding hppa while removing arm is forbidden ...
            self.assertRaises(
                CannotModifyArchiveProcessor,
                self.archive.setProcessors,
                [self.default_procs[0], hppa],
                check_permissions=True,
                user=owner,
            )
            # ... but adding hppa while retaining arm is OK.
            self.archive.setProcessors(
                [self.default_procs[0], self.arm, hppa],
                check_permissions=True,
                user=owner,
            )
            self.assertContentEqual(
                [self.default_procs[0], self.arm, hppa],
                self.archive.processors,
            )

    def test_set_enabled_restricted_processors(self):
        """The deprecated enabled_restricted_processors property still works.

        It's like processors, but only including those that are restricted.
        """
        self.archive.enabled_restricted_processors = [self.arm]
        self.assertContentEqual(
            self.unrestricted_procs + [self.arm], self.archive.processors
        )
        self.assertContentEqual(
            [self.arm], self.archive.enabled_restricted_processors
        )
        self.archive.enabled_restricted_processors = []
        self.assertContentEqual(
            self.unrestricted_procs, self.archive.processors
        )
        self.assertContentEqual([], self.archive.enabled_restricted_processors)


class TestNamedAuthTokenFeatureFlag(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def test_feature_flag_disabled(self):
        # With feature flag disabled, we will not create new named auth tokens.
        private_ppa = self.factory.makeArchive(private=True)
        with FeatureFixture({NAMED_AUTH_TOKEN_FEATURE_FLAG: ""}):
            self.assertRaises(
                NamedAuthTokenFeatureDisabled,
                private_ppa.newNamedAuthToken,
                "tokenname",
            )

    def test_feature_flag_disabled_by_default(self):
        # Without a feature flag, we will not create new named auth tokens.
        private_ppa = self.factory.makeArchive(private=True)
        self.assertRaises(
            NamedAuthTokenFeatureDisabled,
            private_ppa.newNamedAuthToken,
            "tokenname",
        )


class TestArchiveTokens(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        owner = self.factory.makePerson()
        self.private_ppa = self.factory.makeArchive(owner=owner, private=True)
        self.joe = self.factory.makePerson(name="joe")
        self.private_ppa.newSubscription(self.joe, owner)
        self.useFixture(FeatureFixture({NAMED_AUTH_TOKEN_FEATURE_FLAG: "on"}))

    def test_getAuthToken_with_no_token(self):
        self.assertIsNone(self.private_ppa.getAuthToken(self.joe))

    def test_getAuthToken_with_token(self):
        token = self.private_ppa.newAuthToken(self.joe)
        self.assertIsNone(token.name)
        self.assertEqual(self.private_ppa.getAuthToken(self.joe), token)

    def test_getArchiveSubscriptionURL(self):
        url = self.joe.getArchiveSubscriptionURL(self.joe, self.private_ppa)
        token = self.private_ppa.getAuthToken(self.joe)
        self.assertEqual(token.archive_url, url)

    def test_newNamedAuthToken_private_archive(self):
        res = self.private_ppa.newNamedAuthToken("tokenname", as_dict=True)
        token = self.private_ppa.getNamedAuthToken("tokenname")
        self.assertIsNotNone(token)
        self.assertIsNone(token.person)
        self.assertEqual("tokenname", token.name)
        self.assertIsNotNone(token.token)
        self.assertEqual(self.private_ppa, token.archive)
        self.assertIn(
            "://+%s:%s@" % (token.name, token.token), token.archive_url
        )
        self.assertDictEqual(
            {"token": token.token, "archive_url": token.archive_url}, res
        )

    def test_newNamedAuthToken_public_archive(self):
        public_ppa = self.factory.makeArchive(private=False)
        self.assertRaises(
            ArchiveNotPrivate, public_ppa.newNamedAuthToken, "tokenname"
        )

    def test_newNamedAuthToken_duplicate_name(self):
        self.private_ppa.newNamedAuthToken("tokenname")
        self.assertRaises(
            DuplicateTokenName, self.private_ppa.newNamedAuthToken, "tokenname"
        )

    def test_newNamedAuthToken_with_custom_secret(self):
        token = self.private_ppa.newNamedAuthToken("tokenname", "secret")
        self.assertEqual("secret", token.token)

    def test_newNamedAuthTokens_private_archive(self):
        res = self.private_ppa.newNamedAuthTokens(
            ("name1", "name2"), as_dict=True
        )
        tokens = self.private_ppa.getNamedAuthTokens()
        self.assertDictEqual({tok.name: tok.asDict() for tok in tokens}, res)

    def test_newNamedAuthTokens_public_archive(self):
        public_ppa = self.factory.makeArchive(private=False)
        self.assertRaises(
            ArchiveNotPrivate,
            public_ppa.newNamedAuthTokens,
            ("name1", "name2"),
        )

    def test_newNamedAuthTokens_duplicate_name(self):
        self.private_ppa.newNamedAuthToken("tok1")
        res = self.private_ppa.newNamedAuthTokens(
            ("tok1", "tok2", "tok3"), as_dict=True
        )
        tokens = self.private_ppa.getNamedAuthTokens()
        self.assertDictEqual({tok.name: tok.asDict() for tok in tokens}, res)

    def test_newNamedAuthTokens_idempotent(self):
        names = ("name1", "name2", "name3", "name4", "name5")
        res1 = self.private_ppa.newNamedAuthTokens(names, as_dict=True)
        res2 = self.private_ppa.newNamedAuthTokens(names, as_dict=True)
        self.assertEqual(res1, res2)

    def test_newNamedAuthTokens_query_count(self):
        # Preload feature flag so it is cached.
        getFeatureFlag(NAMED_AUTH_TOKEN_FEATURE_FLAG)
        with StormStatementRecorder() as recorder1:
            self.private_ppa.newNamedAuthTokens("tok1")
        with StormStatementRecorder() as recorder2:
            self.private_ppa.newNamedAuthTokens(("tok1", "tok2", "tok3"))
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))

    def test_getNamedAuthToken_with_no_token(self):
        self.assertRaises(
            NotFoundError, self.private_ppa.getNamedAuthToken, "tokenname"
        )

    def test_getNamedAuthToken_with_token(self):
        res = self.private_ppa.newNamedAuthToken("tokenname", as_dict=True)
        self.assertEqual(
            self.private_ppa.getNamedAuthToken("tokenname", as_dict=True), res
        )

    def test_revokeNamedAuthToken_with_token(self):
        token = self.private_ppa.newNamedAuthToken("tokenname")
        self.private_ppa.revokeNamedAuthToken("tokenname")
        self.assertIsNotNone(token.date_deactivated)

    def test_revokeNamedAuthToken_with_no_token(self):
        self.assertRaises(
            NotFoundError, self.private_ppa.revokeNamedAuthToken, "tokenname"
        )

    def test_revokeNamedAuthTokens(self):
        names = ("name1", "name2", "name3", "name4", "name5")
        tokens = self.private_ppa.newNamedAuthTokens(names)
        self.assertThat(
            tokens,
            AllMatch(
                MatchesPredicate(
                    lambda x: not x.date_deactivated, "%s is not active."
                )
            ),
        )
        self.private_ppa.revokeNamedAuthTokens(names)
        self.assertThat(
            tokens,
            AllMatch(
                MatchesPredicate(lambda x: x.date_deactivated, "%s is active.")
            ),
        )

    def test_revokeNamedAuthTokens_with_previously_revoked_token(self):
        names = ("name1", "name2", "name3", "name4", "name5")
        self.private_ppa.newNamedAuthTokens(names)
        token1 = self.private_ppa.getNamedAuthToken("name1")
        token2 = self.private_ppa.getNamedAuthToken("name2")

        # Revoke token1.
        deactivation_time_1 = datetime.now(timezone.utc) - timedelta(
            seconds=90
        )
        token1.date_deactivated = deactivation_time_1

        # Revoke all tokens, including token1.
        self.private_ppa.revokeNamedAuthTokens(names)

        # Check that token1.date_deactivated has not changed.
        self.assertEqual(deactivation_time_1, token1.date_deactivated)
        self.assertLess(token1.date_deactivated, token2.date_deactivated)

    def test_revokeNamedAuthTokens_idempotent(self):
        names = ("name1", "name2", "name3", "name4", "name5")
        res1 = self.private_ppa.revokeNamedAuthTokens(names)
        res2 = self.private_ppa.revokeNamedAuthTokens(names)
        self.assertEqual(res1, res2)

    def test_getNamedAuthToken_with_revoked_token(self):
        self.private_ppa.newNamedAuthToken("tokenname")
        self.private_ppa.revokeNamedAuthToken("tokenname")
        self.assertRaises(
            NotFoundError, self.private_ppa.getNamedAuthToken, "tokenname"
        )

    def test_getNamedAuthTokens(self):
        res1 = self.private_ppa.newNamedAuthToken("tokenname1", as_dict=True)
        res2 = self.private_ppa.newNamedAuthToken("tokenname2", as_dict=True)
        self.private_ppa.newNamedAuthToken("tokenname3")
        self.private_ppa.revokeNamedAuthToken("tokenname3")
        self.assertContentEqual(
            [res1, res2], self.private_ppa.getNamedAuthTokens(as_dict=True)
        )

    def test_getNamedAuthTokens_with_names(self):
        res1 = self.private_ppa.newNamedAuthToken("tokenname1", as_dict=True)
        res2 = self.private_ppa.newNamedAuthToken("tokenname2", as_dict=True)
        self.private_ppa.newNamedAuthToken("tokenname3")
        self.assertContentEqual(
            [res1, res2],
            self.private_ppa.getNamedAuthTokens(
                ("tokenname1", "tokenname2"), as_dict=True
            ),
        )


class TestGetBinaryPackageRelease(TestCaseWithFactory):
    """Ensure that getBinaryPackageRelease works as expected."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Setup an archive with relevant publications."""
        super().setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        self.archive = self.factory.makeArchive()
        self.archive.require_virtualized = False

        self.i386_pub, self.hppa_pub = self.publisher.getPubBinaries(
            version="1.2.3-4",
            archive=self.archive,
            binaryname="foo-bin",
            status=PackagePublishingStatus.PUBLISHED,
            architecturespecific=True,
        )

        (
            self.i386_indep_pub,
            self.hppa_indep_pub,
        ) = self.publisher.getPubBinaries(
            version="1.2.3-4",
            archive=self.archive,
            binaryname="bar-bin",
            status=PackagePublishingStatus.PUBLISHED,
        )

        self.bpns = getUtility(IBinaryPackageNameSet)

    def test_returns_matching_binarypackagerelease(self):
        # The BPR with a file by the given name should be returned.
        self.assertEqual(
            self.i386_pub.binarypackagerelease,
            self.archive.getBinaryPackageRelease(
                self.bpns["foo-bin"], "1.2.3-4", "i386"
            ),
        )

    def test_returns_correct_architecture(self):
        # The architecture is taken into account correctly.
        self.assertEqual(
            self.hppa_pub.binarypackagerelease,
            self.archive.getBinaryPackageRelease(
                self.bpns["foo-bin"], "1.2.3-4", "hppa"
            ),
        )

    def test_works_with_architecture_independent_binaries(self):
        # Architecture independent binaries with multiple publishings
        # are found properly.
        # We use 'i386' as the arch tag here, since what we have in the DB
        # is the *build* arch tag, not the one in the filename ('all').
        self.assertEqual(
            self.i386_indep_pub.binarypackagerelease,
            self.archive.getBinaryPackageRelease(
                self.bpns["bar-bin"], "1.2.3-4", "i386"
            ),
        )

    def test_returns_none_for_nonexistent_binary(self):
        # Non-existent files return None.
        self.assertIsNone(
            self.archive.getBinaryPackageRelease(
                self.bpns["cdrkit"], "1.2.3-4", "i386"
            )
        )

    def test_returns_none_for_duplicate_file(self):
        # In the unlikely case of multiple BPRs in this archive with the same
        # name (hopefully impossible, but it still happens occasionally due
        # to bugs), None is returned.

        # Publish the same binaries again. Evil.
        self.publisher.getPubBinaries(
            version="1.2.3-4",
            archive=self.archive,
            binaryname="foo-bin",
            status=PackagePublishingStatus.PUBLISHED,
            architecturespecific=True,
        )

        self.assertIsNone(
            self.archive.getBinaryPackageRelease(
                self.bpns["foo-bin"], "1.2.3-4", "i386"
            )
        )

    def test_returns_none_from_another_archive(self):
        # Cross-archive searches are not performed.
        self.assertIsNone(
            self.factory.makeArchive().getBinaryPackageRelease(
                self.bpns["foo-bin"], "1.2.3-4", "i386"
            )
        )

    def test_matches_version_as_text(self):
        # Versions such as 1.2.3-4 and 1.02.003-4 are equal according to the
        # "debversion" type, but for lookup purposes we compare the text of
        # the version strings exactly.
        other_i386_pub, other_hppa_pub = self.publisher.getPubBinaries(
            version="1.02.003-4",
            archive=self.archive,
            binaryname="foo-bin",
            status=PackagePublishingStatus.PUBLISHED,
            architecturespecific=True,
        )
        self.assertEqual(
            self.i386_pub.binarypackagerelease,
            self.archive.getBinaryPackageRelease(
                self.bpns["foo-bin"], "1.2.3-4", "i386"
            ),
        )
        self.assertEqual(
            other_i386_pub.binarypackagerelease,
            self.archive.getBinaryPackageRelease(
                self.bpns["foo-bin"], "1.02.003-4", "i386"
            ),
        )


class TestGetBinaryPackageReleaseByFileName(TestCaseWithFactory):
    """Ensure that getBinaryPackageReleaseByFileName works as expected."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        """Setup an archive with relevant publications."""
        super().setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        self.archive = self.factory.makeArchive()
        self.archive.require_virtualized = False

        self.i386_pub, self.hppa_pub = self.publisher.getPubBinaries(
            version="1.2.3-4",
            archive=self.archive,
            binaryname="foo-bin",
            status=PackagePublishingStatus.PUBLISHED,
            architecturespecific=True,
        )

        (
            self.i386_indep_pub,
            self.hppa_indep_pub,
        ) = self.publisher.getPubBinaries(
            version="1.2.3-4",
            archive=self.archive,
            binaryname="bar-bin",
            status=PackagePublishingStatus.PUBLISHED,
        )

    def test_returns_matching_binarypackagerelease(self):
        # The BPR with a file by the given name should be returned.
        self.assertEqual(
            self.i386_pub.binarypackagerelease,
            self.archive.getBinaryPackageReleaseByFileName(
                "foo-bin_1.2.3-4_i386.deb"
            ),
        )

    def test_returns_correct_architecture(self):
        # The architecture is taken into account correctly.
        self.assertEqual(
            self.hppa_pub.binarypackagerelease,
            self.archive.getBinaryPackageReleaseByFileName(
                "foo-bin_1.2.3-4_hppa.deb"
            ),
        )

    def test_works_with_architecture_independent_binaries(self):
        # Architecture independent binaries with multiple publishings
        # are found properly.
        self.assertEqual(
            self.i386_indep_pub.binarypackagerelease,
            self.archive.getBinaryPackageReleaseByFileName(
                "bar-bin_1.2.3-4_all.deb"
            ),
        )

    def test_returns_none_for_source_file(self):
        # None is returned if the file is a source component instead.
        self.assertIsNone(
            self.archive.getBinaryPackageReleaseByFileName("foo_1.2.3-4.dsc")
        )

    def test_returns_none_for_nonexistent_file(self):
        # Non-existent files return None.
        self.assertIsNone(
            self.archive.getBinaryPackageReleaseByFileName(
                "this-is-not-real_1.2.3-4_all.deb"
            )
        )

    def test_returns_latest_for_duplicate_file(self):
        # In the unlikely case of multiple BPRs in this archive with the same
        # name (hopefully impossible, but it still happens occasionally due
        # to bugs), the latest is returned.

        # Publish the same binaries again. Evil.
        new_pubs = self.publisher.getPubBinaries(
            version="1.2.3-4",
            archive=self.archive,
            binaryname="foo-bin",
            status=PackagePublishingStatus.PUBLISHED,
            architecturespecific=True,
        )

        self.assertEqual(
            new_pubs[0].binarypackagerelease,
            self.archive.getBinaryPackageReleaseByFileName(
                "foo-bin_1.2.3-4_i386.deb"
            ),
        )

    def test_returns_none_from_another_archive(self):
        # Cross-archive searches are not performed.
        self.assertIsNone(
            self.factory.makeArchive().getBinaryPackageReleaseByFileName(
                "foo-bin_1.2.3-4_i386.deb"
            )
        )


class TestArchiveDelete(TestCaseWithFactory):
    """Test PPA deletion."""

    layer = LaunchpadFunctionalLayer

    def makePopulatedArchive(self):
        archive = self.factory.makeArchive()
        self.assertActive(archive)
        publisher = SoyuzTestPublisher()
        with admin_logged_in():
            publisher.prepareBreezyAutotest()
            publisher.getPubBinaries(
                archive=archive,
                binaryname="foo-bin1",
                status=PackagePublishingStatus.PENDING,
            )
            publisher.getPubBinaries(
                archive=archive,
                binaryname="foo-bin2",
                status=PackagePublishingStatus.PUBLISHED,
            )
        Store.of(archive).flush()
        return archive

    def assertActive(self, archive):
        self.assertTrue(archive.enabled)
        self.assertEqual(ArchiveStatus.ACTIVE, archive.status)

    def assertDeleting(self, archive):
        # Deleting an archive sets the status to DELETING.  This tells the
        # publisher to set the publications to DELETED and delete the
        # published archive from disk, after which the status of the archive
        # itself is set to DELETED.
        self.assertFalse(archive.enabled)
        self.assertEqual(ArchiveStatus.DELETING, archive.status)

    def test_delete_unprivileged(self):
        # An unprivileged user cannot delete an archive.
        archive = self.factory.makeArchive()
        self.assertActive(archive)
        person = self.factory.makePerson()
        with person_logged_in(person):
            self.assertRaises(Unauthorized, getattr, archive, "delete")
            self.assertActive(archive)

    def test_delete_archive_owner(self):
        # The owner of an archive can delete it.
        archive = self.makePopulatedArchive()
        with person_logged_in(archive.owner):
            archive.delete(deleted_by=archive.owner)
            self.assertDeleting(archive)

    def test_delete_registry_expert(self):
        # A registry expert can delete an archive.
        archive = self.makePopulatedArchive()
        with celebrity_logged_in("registry_experts"):
            archive.delete(deleted_by=archive.owner)
            self.assertDeleting(archive)

    def test_delete_when_disabled(self):
        # A disabled archive can also be deleted (bug 574246).
        archive = self.makePopulatedArchive()
        with person_logged_in(archive.owner):
            archive.disable()
            archive.delete(deleted_by=archive.owner)
            self.assertDeleting(archive)

    def test_cannot_reenable(self):
        # A deleted archive cannot be re-enabled.
        archive = self.factory.makeArchive()
        with person_logged_in(archive.owner):
            archive.delete(deleted_by=archive.owner)
            self.assertDeleting(archive)
            self.assertRaisesWithContent(
                AssertionError,
                "Deleted archives can't be enabled.",
                archive.enable,
            )
            self.assertDeleting(archive)


class TestSuppressSubscription(TestCaseWithFactory):
    """Tests relating to suppressing subscription."""

    layer = DatabaseFunctionalLayer

    def test_set_and_get_suppress(self):
        # Basic set and get of the suppress_subscription_notifications
        # property.  Anyone can read it and it defaults to False.
        archive = self.factory.makeArchive()
        with person_logged_in(archive.owner):
            self.assertFalse(archive.suppress_subscription_notifications)

            # The archive owner can change the value.
            archive.suppress_subscription_notifications = True
            self.assertTrue(archive.suppress_subscription_notifications)

    def test_most_users_cant_set_suppress(self):
        # Basic set and get of the suppress_subscription_notifications
        # property.  Anyone can read it and it defaults to False.
        archive = self.factory.makeArchive()
        with person_logged_in(self.factory.makePerson()):
            self.assertFalse(archive.suppress_subscription_notifications)
            self.assertRaises(
                Unauthorized,
                setattr,
                archive,
                "suppress_subscription_notifications",
                True,
            )


class TestBuildDebugSymbols(TestCaseWithFactory):
    """Tests relating to the build_debug_symbols flag."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.archive = self.factory.makeArchive()

    def test_build_debug_symbols_is_public(self):
        # Anyone can see the attribute.
        login(ANONYMOUS)
        self.assertFalse(self.archive.build_debug_symbols)

    def test_non_owner_cannot_set_build_debug_symbols(self):
        # A non-owner cannot set it.
        login_person(self.factory.makePerson())
        self.assertRaises(
            Unauthorized, setattr, self.archive, "build_debug_symbols", True
        )

    def test_owner_can_set_build_debug_symbols(self):
        # The archive owner can set it.
        login_person(self.archive.owner)
        self.archive.build_debug_symbols = True
        self.assertTrue(self.archive.build_debug_symbols)

    def test_commercial_admin_cannot_set_build_debug_symbols(self):
        # A commercial admin cannot set it.
        with celebrity_logged_in("commercial_admin"):
            self.assertRaises(
                Unauthorized,
                setattr,
                self.archive,
                "build_debug_symbols",
                True,
            )


class TestAddArchiveDependencies(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_add_hidden_dependency(self):
        # The user cannot add a dependency on an archive they cannot see.
        archive = self.factory.makeArchive(private=True)
        dependency = self.factory.makeArchive(private=True)
        with person_logged_in(archive.owner):
            with ExpectedException(
                ArchiveDependencyError,
                "You don't have permission to use this dependency.",
            ):
                archive.addArchiveDependency(dependency, "foo")

    def test_private_dependency_public_archive(self):
        # A public archive may not depend on a private archive.
        archive = self.factory.makeArchive()
        dependency = self.factory.makeArchive(
            private=True, owner=archive.owner
        )
        with person_logged_in(archive.owner):
            with ExpectedException(
                ArchiveDependencyError,
                "Public PPAs cannot depend on private ones.",
            ):
                archive.addArchiveDependency(dependency, "foo")

    def test_add_private_dependency(self):
        # The user can add a dependency on private archive they can see.
        archive = self.factory.makeArchive(private=True)
        dependency = self.factory.makeArchive(
            private=True, owner=archive.owner
        )
        with person_logged_in(archive.owner):
            archive_dependency = archive.addArchiveDependency(
                dependency, PackagePublishingPocket.RELEASE
            )
            self.assertContentEqual(archive.dependencies, [archive_dependency])

    def test_dependency_has_different_distribution(self):
        # A public archive may not depend on a private archive.
        archive = self.factory.makeArchive()
        distro = self.factory.makeDistribution()
        dependency = self.factory.makeArchive(
            distribution=distro, owner=archive.owner
        )
        with person_logged_in(archive.owner):
            with ExpectedException(
                ArchiveDependencyError,
                "Dependencies must be for the same distribution.",
            ):
                archive.addArchiveDependency(
                    dependency, PackagePublishingPocket.RELEASE
                )

    def test_dependency_is_disabled(self):
        # A public archive may not depend on a private archive.
        archive = self.factory.makeArchive()
        dependency = self.factory.makeArchive(
            owner=archive.owner, enabled=False
        )
        with person_logged_in(archive.owner):
            with ExpectedException(
                ArchiveDependencyError, "Dependencies must not be disabled."
            ):
                archive.addArchiveDependency(
                    dependency, PackagePublishingPocket.RELEASE
                )


class TestArchiveDependencies(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer
    run_tests_with = AsynchronousDeferredRunTestForBrokenTwisted.make_factory(
        timeout=30
    )

    @defer.inlineCallbacks
    def test_private_sources_list(self):
        """Entries for private dependencies include credentials."""
        self.useFixture(InProcessAuthServerFixture())
        self.pushConfig(
            "launchpad", internal_macaroon_secret_key="some-secret"
        )
        p3a = self.factory.makeArchive(name="p3a", private=True)
        yield self.useFixture(InProcessKeyServerFixture()).start()
        key_path = os.path.join(gpgkeysdir, "ppa-sample@canonical.com.sec")
        yield IArchiveGPGSigningKey(p3a).setSigningKey(
            key_path, async_keyserver=True
        )
        dependency = self.factory.makeArchive(
            name="dependency", private=True, owner=p3a.owner
        )
        with person_logged_in(p3a.owner):
            bpph = self.factory.makeBinaryPackagePublishingHistory(
                archive=dependency,
                status=PackagePublishingStatus.PUBLISHED,
                pocket=PackagePublishingPocket.RELEASE,
            )
            p3a.addArchiveDependency(
                dependency, PackagePublishingPocket.RELEASE
            )
            build = self.factory.makeBinaryPackageBuild(
                archive=p3a, distroarchseries=bpph.distroarchseries
            )
            behaviour = IBuildFarmJobBehaviour(build)
            sources_list, trusted_keys = yield get_sources_list_for_building(
                behaviour,
                build.distro_arch_series,
                build.source_package_release.name,
            )
            # Mark the build as building so that we can verify its macaroons.
            build.updateStatus(BuildStatus.BUILDING)
            self.assertThat(
                SourceEntry(sources_list[0]),
                MatchesStructure(
                    type=Equals("deb"),
                    uri=AfterPreprocessing(
                        urlsplit,
                        MatchesStructure(
                            scheme=Equals("http"),
                            username=Equals("buildd"),
                            password=MacaroonVerifies(
                                "binary-package-build", p3a
                            ),
                            hostname=Equals("private-ppa.launchpad.test"),
                            path=Equals(
                                "/%s/dependency/ubuntu" % p3a.owner.name
                            ),
                        ),
                    ),
                    dist=Equals(build.distro_series.getSuite(build.pocket)),
                    comps=Equals(["main"]),
                ),
            )
            self.assertThat(
                trusted_keys,
                MatchesListwise(
                    [
                        Base64KeyMatches(
                            "0D57E99656BEFB0897606EE9A022DD1F5001B46D"
                        ),
                    ]
                ),
            )

    def test_invalid_external_dependencies(self):
        """Trying to set invalid external dependencies raises an exception."""
        ppa = self.factory.makeArchive()
        self.assertRaisesWithContent(
            InvalidExternalDependencies,
            "Invalid external dependencies:\n"
            "Malformed format string here --> %(series): "
            "Must start with 'deb'\n"
            "Malformed format string here --> %(series): Invalid URL\n",
            setattr,
            ppa,
            "external_dependencies",
            "Malformed format string here --> %(series)",
        )


class TestFindDepCandidates(TestCaseWithFactory):
    """Tests for Archive.findDepCandidates."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.archive = self.factory.makeArchive()
        self.publisher = SoyuzTestPublisher()
        login("admin@canonical.com")
        self.publisher.prepareBreezyAutotest()

    def assertDep(
        self,
        arch_tag,
        name,
        expected,
        archive=None,
        pocket=PackagePublishingPocket.RELEASE,
        component=None,
        source_package_name="something-new",
    ):
        """Helper to check that findDepCandidates works.

        Searches for the given dependency name in the given architecture and
        archive, and compares it to the given expected value.
        The archive defaults to self.archive.

        Also commits, since findDepCandidates uses the standby store.
        """
        transaction.commit()

        if component is None:
            component = getUtility(IComponentSet)["main"]
        if archive is None:
            archive = self.archive

        self.assertEqual(
            expected,
            list(
                archive.findDepCandidates(
                    self.publisher.distroseries[arch_tag],
                    pocket,
                    component,
                    source_package_name,
                    name,
                )
            ),
        )

    def test_finds_candidate_in_same_archive(self):
        # A published candidate in the same archive should be found.
        bins = self.publisher.getPubBinaries(
            binaryname="foo",
            archive=self.archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        self.assertDep("i386", "foo", [bins[0]])
        self.assertDep("hppa", "foo", [bins[1]])

    def test_does_not_find_pending_publication(self):
        # A pending candidate in the same archive should not be found.
        self.publisher.getPubBinaries(binaryname="foo", archive=self.archive)
        self.assertDep("i386", "foo", [])

    def test_ppa_searches_primary_archive(self):
        # PPA searches implicitly look in the primary archive too.
        self.assertEqual(self.archive.purpose, ArchivePurpose.PPA)
        self.assertDep("i386", "foo", [])

        bins = self.publisher.getPubBinaries(
            binaryname="foo",
            archive=self.archive.distribution.main_archive,
            status=PackagePublishingStatus.PUBLISHED,
        )

        self.assertDep("i386", "foo", [bins[0]])

    def test_searches_dependencies(self):
        # Candidates from archives on which the target explicitly depends
        # should be found.
        bins = self.publisher.getPubBinaries(
            binaryname="foo",
            archive=self.archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        other_archive = self.factory.makeArchive()
        self.assertDep("i386", "foo", [], archive=other_archive)

        other_archive.addArchiveDependency(
            self.archive, PackagePublishingPocket.RELEASE
        )
        self.assertDep("i386", "foo", [bins[0]], archive=other_archive)

    def test_obeys_dependency_pockets(self):
        # Only packages published in a pocket matching the dependency should
        # be found.
        release_bins = self.publisher.getPubBinaries(
            binaryname="foo-release",
            archive=self.archive,
            status=PackagePublishingStatus.PUBLISHED,
        )
        updates_bins = self.publisher.getPubBinaries(
            binaryname="foo-updates",
            archive=self.archive,
            status=PackagePublishingStatus.PUBLISHED,
            pocket=PackagePublishingPocket.UPDATES,
        )
        proposed_bins = self.publisher.getPubBinaries(
            binaryname="foo-proposed",
            archive=self.archive,
            status=PackagePublishingStatus.PUBLISHED,
            pocket=PackagePublishingPocket.PROPOSED,
        )

        # Temporarily turn our test PPA into a copy archive, so we can
        # add non-RELEASE dependencies on it.
        removeSecurityProxy(self.archive).purpose = ArchivePurpose.COPY

        other_archive = self.factory.makeArchive()
        other_archive.addArchiveDependency(
            self.archive, PackagePublishingPocket.UPDATES
        )
        self.assertDep(
            "i386", "foo-release", [release_bins[0]], archive=other_archive
        )
        self.assertDep(
            "i386", "foo-updates", [updates_bins[0]], archive=other_archive
        )
        self.assertDep("i386", "foo-proposed", [], archive=other_archive)

        other_archive.removeArchiveDependency(self.archive)
        other_archive.addArchiveDependency(
            self.archive, PackagePublishingPocket.PROPOSED
        )
        self.assertDep(
            "i386", "foo-proposed", [proposed_bins[0]], archive=other_archive
        )

    def test_obeys_dependency_components(self):
        # Only packages published in a component matching the dependency
        # should be found.
        primary = self.archive.distribution.main_archive
        main_bins = self.publisher.getPubBinaries(
            binaryname="foo-main",
            archive=primary,
            component="main",
            status=PackagePublishingStatus.PUBLISHED,
        )
        universe_bins = self.publisher.getPubBinaries(
            binaryname="foo-universe",
            archive=primary,
            component="universe",
            status=PackagePublishingStatus.PUBLISHED,
        )

        self.archive.addArchiveDependency(
            primary,
            PackagePublishingPocket.RELEASE,
            component=getUtility(IComponentSet)["main"],
        )
        self.assertDep("i386", "foo-main", [main_bins[0]])
        self.assertDep("i386", "foo-universe", [])

        self.archive.removeArchiveDependency(primary)
        self.archive.addArchiveDependency(
            primary,
            PackagePublishingPocket.RELEASE,
            component=getUtility(IComponentSet)["universe"],
        )
        self.assertDep("i386", "foo-main", [main_bins[0]])
        self.assertDep("i386", "foo-universe", [universe_bins[0]])

    def test_obeys_dependency_components_with_primary_ancestry(self):
        # When the dependency component is undefined, only packages
        # published in a component matching the primary archive ancestry
        # should be found.
        primary = self.archive.distribution.main_archive
        self.publisher.getPubSource(
            sourcename="something-new",
            version="1",
            archive=primary,
            component="main",
            status=PackagePublishingStatus.PUBLISHED,
        )
        main_bins = self.publisher.getPubBinaries(
            binaryname="foo-main",
            archive=primary,
            component="main",
            status=PackagePublishingStatus.PUBLISHED,
        )
        universe_bins = self.publisher.getPubBinaries(
            binaryname="foo-universe",
            archive=primary,
            component="universe",
            status=PackagePublishingStatus.PUBLISHED,
        )

        self.archive.addArchiveDependency(
            primary, PackagePublishingPocket.RELEASE
        )
        self.assertDep("i386", "foo-main", [main_bins[0]])
        self.assertDep("i386", "foo-universe", [])

        self.publisher.getPubSource(
            sourcename="something-new",
            version="2",
            archive=primary,
            component="universe",
            status=PackagePublishingStatus.PUBLISHED,
        )
        self.assertDep("i386", "foo-main", [main_bins[0]])
        self.assertDep("i386", "foo-universe", [universe_bins[0]])


class TestOverlays(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=30)

    def _createDep(
        self,
        test_publisher,
        derived_series,
        parent_series,
        parent_distro,
        component_name=None,
        pocket=None,
        overlay=True,
        arch_tag="i386",
        publish_base_url="http://archive.launchpad.test/",
    ):
        # Helper to create a parent/child relationship.
        if isinstance(parent_distro, str):
            depdistro = self.factory.makeDistribution(
                parent_distro, publish_base_url=publish_base_url
            )
        else:
            depdistro = parent_distro
        if isinstance(parent_series, str):
            depseries = self.factory.makeDistroSeries(
                name=parent_series, distribution=depdistro
            )
            self.factory.makeDistroArchSeries(
                distroseries=depseries, architecturetag=arch_tag
            )
        else:
            depseries = parent_series
        test_publisher.addFakeChroots(depseries)
        if component_name is not None:
            component = getUtility(IComponentSet)[component_name]
        else:
            component = None
        for name in ("main", "restricted", "universe", "multiverse"):
            self.factory.makeComponentSelection(
                depseries, getUtility(IComponentSet)[name]
            )

        self.factory.makeDistroSeriesParent(
            derived_series=derived_series,
            parent_series=depseries,
            initialized=True,
            is_overlay=overlay,
            pocket=pocket,
            component=component,
        )
        return depseries, depdistro

    @defer.inlineCallbacks
    def test_overlay_dependencies(self):
        # sources.list is properly generated for a complex overlay structure.
        # Pocket dependencies and component dependencies are taken into
        # account when generating sources.list.
        #
        #            breezy               type of relation:
        #               |                    |           |
        #    -----------------------         |           o
        #    |          |          |         |           |
        #    o          o          |      no overlay  overlay
        #    |          |          |
        # series11  series21   series31
        #    |
        #    o
        #    |
        # series12
        #
        test_publisher = SoyuzTestPublisher()
        test_publisher.prepareBreezyAutotest()
        breezy = test_publisher.breezy_autotest
        pub_source = test_publisher.getPubSource(
            version="1.1", archive=breezy.main_archive
        )
        [build] = pub_source.createMissingBuilds()
        series11, depdistro = self._createDep(
            test_publisher,
            breezy,
            "series11",
            "depdistro",
            "universe",
            PackagePublishingPocket.SECURITY,
        )
        self._createDep(
            test_publisher,
            breezy,
            "series21",
            "depdistro2",
            "multiverse",
            PackagePublishingPocket.UPDATES,
        )
        self._createDep(
            test_publisher, breezy, "series31", "depdistro3", overlay=False
        )
        self._createDep(
            test_publisher,
            series11,
            "series12",
            "depdistro4",
            "multiverse",
            PackagePublishingPocket.UPDATES,
        )
        behaviour = IBuildFarmJobBehaviour(build)
        sources_list, trusted_keys = yield get_sources_list_for_building(
            behaviour,
            build.distro_arch_series,
            build.source_package_release.name,
        )

        self.assertThat(
            "\n".join(sources_list),
            DocTestMatches(
                ".../ubuntutest breezy-autotest main\n"
                ".../depdistro series11 main universe\n"
                ".../depdistro series11-security main universe\n"
                ".../depdistro2 series21 "
                "main restricted universe multiverse\n"
                ".../depdistro2 series21-security "
                "main restricted universe multiverse\n"
                ".../depdistro2 series21-updates "
                "main restricted universe multiverse\n"
                ".../depdistro4 series12 main restricted "
                "universe multiverse\n"
                ".../depdistro4 series12-security main "
                "restricted universe multiverse\n"
                ".../depdistro4 series12-updates "
                "main restricted universe multiverse\n",
                doctest.ELLIPSIS,
            ),
        )
        self.assertEqual([], trusted_keys)


class TestComponents(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_no_components_for_arbitrary_person(self):
        # By default, a person cannot upload to any component of an archive.
        archive = self.factory.makeArchive()
        person = self.factory.makePerson()
        self.assertFalse(set(archive.getComponentsForUploader(person)))

    def test_components_for_person_with_permissions(self):
        # If a person has been explicitly granted upload permissions to a
        # particular component, then those components are included in
        # IArchive.getComponentsForUploader.
        archive = self.factory.makeArchive()
        component = self.factory.makeComponent()
        person = self.factory.makePerson()
        # Only admins or techboard members can add permissions normally. That
        # restriction isn't relevant to this test.
        ap_set = removeSecurityProxy(getUtility(IArchivePermissionSet))
        ap = ap_set.newComponentUploader(archive, person, component)
        self.assertEqual({ap}, set(archive.getComponentsForUploader(person)))


class TestPockets(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_no_pockets_for_arbitrary_person(self):
        # By default, a person cannot upload to any pocket of an archive.
        archive = self.factory.makeArchive()
        person = self.factory.makePerson()
        self.assertEqual(set(), set(archive.getPocketsForUploader(person)))

    def test_pockets_for_person_with_permissions(self):
        # If a person has been explicitly granted upload permissions to a
        # particular pocket, then those pockets are included in
        # IArchive.getPocketsForUploader.
        archive = self.factory.makeArchive()
        person = self.factory.makePerson()
        # Only admins or techboard members can add permissions normally. That
        # restriction isn't relevant to this test.
        ap_set = removeSecurityProxy(getUtility(IArchivePermissionSet))
        ap = ap_set.newPocketUploader(
            archive, person, PackagePublishingPocket.SECURITY
        )
        self.assertEqual({ap}, set(archive.getPocketsForUploader(person)))


class TestValidatePPA(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.ubuntu = getUtility(IDistributionSet)["ubuntu"]
        self.ubuntutest = getUtility(IDistributionSet)["ubuntutest"]
        with admin_logged_in():
            self.ubuntutest.supports_ppas = True

    def test_open_teams(self):
        team = self.factory.makeTeam()
        self.assertEqual(
            "Open teams cannot have PPAs.",
            validate_ppa(team, self.ubuntu, "ppa"),
        )

    def test_distribution_name(self):
        ppa_owner = self.factory.makePerson()
        self.assertEqual(
            "A PPA cannot have the same name as its distribution.",
            validate_ppa(ppa_owner, self.ubuntu, "ubuntu"),
        )

    def test_ubuntu_name(self):
        # Disambiguating old-style URLs relies on there never being a
        # PPA named "ubuntu".
        ppa_owner = self.factory.makePerson()
        self.assertEqual(
            'A PPA cannot be named "ubuntu".',
            validate_ppa(ppa_owner, self.ubuntutest, "ubuntu"),
        )

    def test_distro_unsupported(self):
        ppa_owner = self.factory.makePerson()
        distro = self.factory.makeDistribution(displayname="Unbuntu")
        self.assertEqual(
            "Unbuntu does not support PPAs.",
            validate_ppa(ppa_owner, distro, "ppa"),
        )
        with admin_logged_in():
            distro.supports_ppas = True
        self.assertIs(None, validate_ppa(ppa_owner, distro, "ppa"))

    def test_private_ppa_standard_user(self):
        ppa_owner = self.factory.makePerson()
        with person_logged_in(ppa_owner):
            errors = validate_ppa(
                ppa_owner,
                self.ubuntu,
                self.factory.getUniqueString(),
                private=True,
            )
        self.assertEqual(
            "%s is not allowed to make private PPAs" % (ppa_owner.name,),
            errors,
        )

    def test_private_ppa_commercial_subscription(self):
        owner = self.factory.makePerson()
        self.factory.grantCommercialSubscription(owner)
        with person_logged_in(owner):
            errors = validate_ppa(owner, self.ubuntu, "ppa", private=True)
        self.assertIsNone(errors)

    def test_private_ppa_commercial_admin(self):
        ppa_owner = self.factory.makePerson()
        with celebrity_logged_in("admin"):
            comm = getUtility(ILaunchpadCelebrities).commercial_admin
            comm.addMember(ppa_owner, comm.teamowner)
        with person_logged_in(ppa_owner):
            self.assertIsNone(
                validate_ppa(
                    ppa_owner,
                    self.ubuntu,
                    self.factory.getUniqueString(),
                    private=True,
                )
            )

    def test_private_ppa_admin(self):
        ppa_owner = self.factory.makeAdministrator()
        with person_logged_in(ppa_owner):
            self.assertIsNone(
                validate_ppa(
                    ppa_owner,
                    self.ubuntu,
                    self.factory.getUniqueString(),
                    private=True,
                )
            )

    def test_two_ppas(self):
        ppa = self.factory.makeArchive(name="ppa")
        self.assertEqual(
            "You already have a PPA for Ubuntu named 'ppa'.",
            validate_ppa(ppa.owner, self.ubuntu, "ppa"),
        )

    def test_two_ppas_with_team(self):
        team = self.factory.makeTeam(
            membership_policy=TeamMembershipPolicy.MODERATED
        )
        self.factory.makeArchive(owner=team, name="ppa")
        self.assertEqual(
            "%s already has a PPA for Ubuntu named 'ppa'." % team.displayname,
            validate_ppa(team, self.ubuntu, "ppa"),
        )

    def test_valid_ppa(self):
        ppa_owner = self.factory.makePerson()
        self.assertIsNone(validate_ppa(ppa_owner, self.ubuntu, "ppa"))

    def test_private_team_private_ppa(self):
        # Folk with launchpad.Edit on a private team can make private PPAs for
        # that team, regardless of whether they have super-powers.a
        team_owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=team_owner,
            visibility=PersonVisibility.PRIVATE,
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        team_admin = self.factory.makePerson()
        with person_logged_in(team_owner):
            private_team.addMember(
                team_admin, team_owner, status=TeamMembershipStatus.ADMIN
            )
        with person_logged_in(team_admin):
            result = validate_ppa(
                private_team, self.ubuntu, "ppa", private=True
            )
        self.assertIsNone(result)

    def test_private_team_public_ppa(self):
        # No one can make a public PPA for a private team.
        team_owner = self.factory.makePerson()
        private_team = self.factory.makeTeam(
            owner=team_owner,
            visibility=PersonVisibility.PRIVATE,
            membership_policy=TeamMembershipPolicy.RESTRICTED,
        )
        team_admin = self.factory.makePerson()
        with person_logged_in(team_owner):
            private_team.addMember(
                team_admin, team_owner, status=TeamMembershipStatus.ADMIN
            )
        with person_logged_in(team_admin):
            result = validate_ppa(
                private_team, self.ubuntu, "ppa", private=False
            )
        self.assertEqual("Private teams may not have public archives.", result)


class TestGetComponentsForSeries(TestCaseWithFactory):
    """Tests for Archive.getComponentsForSeries."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.series = self.factory.makeDistroSeries()
        self.comp1 = self.factory.makeComponent()
        self.comp2 = self.factory.makeComponent()

    def test_series_components_for_primary_archive(self):
        # The primary archive uses the series' defined components.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        self.assertEqual(0, len(archive.getComponentsForSeries(self.series)))

        ComponentSelection(distroseries=self.series, component=self.comp1)
        ComponentSelection(distroseries=self.series, component=self.comp2)
        clear_property_cache(self.series)

        self.assertEqual(
            {self.comp1, self.comp2},
            set(archive.getComponentsForSeries(self.series)),
        )

    def test_partner_component_for_partner_archive(self):
        # The partner archive always uses only the 'partner' component.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PARTNER)
        ComponentSelection(distroseries=self.series, component=self.comp1)
        partner_comp = getUtility(IComponentSet)["partner"]
        self.assertEqual(
            [partner_comp], list(archive.getComponentsForSeries(self.series))
        )

    def test_component_for_ppas(self):
        # PPAs only use 'main'.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        ComponentSelection(distroseries=self.series, component=self.comp1)
        main_comp = getUtility(IComponentSet)["main"]
        self.assertEqual(
            [main_comp], list(archive.getComponentsForSeries(self.series))
        )


class TestDefaultComponent(TestCaseWithFactory):
    """Tests for Archive.default_component."""

    layer = DatabaseFunctionalLayer

    def test_default_component_for_other_archives(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        self.assertIsNone(archive.default_component)

    def test_default_component_for_partner(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PARTNER)
        self.assertEqual(
            getUtility(IComponentSet)["partner"], archive.default_component
        )

    def test_default_component_for_ppas(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertEqual(
            getUtility(IComponentSet)["main"], archive.default_component
        )


class TestGetPockets(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_getPockets_for_other_archives(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        self.assertEqual(
            list(PackagePublishingPocket.items), archive.getPockets()
        )

    def test_getPockets_for_PPAs(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertEqual(
            [PackagePublishingPocket.RELEASE], archive.getPockets()
        )


class TestGetFileByName(TestCaseWithFactory):
    """Tests for Archive.getFileByName."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.archive = self.factory.makeArchive()

    def test_unknown_file_is_not_found(self):
        # A file with an unsupported extension is not found.
        self.assertRaises(NotFoundError, self.archive.getFileByName, "a.bar")

    def test_source_file_is_found(self):
        # A file from a published source package can be retrieved.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        dsc = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, dsc.filename
        )
        pub.sourcepackagerelease.addFile(dsc)
        self.assertEqual(dsc, self.archive.getFileByName(dsc.filename))

    def test_nonexistent_source_file_is_not_found(self):
        # Something that looks like a source file but isn't is not
        # found.
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, "foo_1.0.dsc"
        )

    def test_binary_file_is_found(self):
        # A file from a published binary package can be retrieved.
        pub = self.factory.makeBinaryPackagePublishingHistory(
            archive=self.archive
        )
        deb = self.factory.makeLibraryFileAlias(filename="foo_1.0_all.deb")
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, deb.filename
        )
        pub.binarypackagerelease.addFile(deb)
        self.assertEqual(deb, self.archive.getFileByName(deb.filename))

    def test_nonexistent_binary_file_is_not_found(self):
        # Something that looks like a binary file but isn't is not
        # found.
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, "foo_1.0_all.deb"
        )

    def test_source_changes_file_is_found(self):
        # A .changes file from a published source can be retrieved.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        pu = self.factory.makePackageUpload(
            changes_filename="foo_1.0_source.changes"
        )
        pu.setDone()
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, pu.changesfile.filename
        )
        pu.addSource(pub.sourcepackagerelease)
        self.assertEqual(
            pu.changesfile, self.archive.getFileByName(pu.changesfile.filename)
        )

    def test_nonexistent_source_changes_file_is_not_found(self):
        # Something that looks like a source .changes file but isn't is not
        # found.
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, "foo_1.0_source.changes"
        )

    def test_package_diff_is_found(self):
        # A .diff.gz from a package diff can be retrieved.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        diff = self.factory.makePackageDiff(
            to_source=pub.sourcepackagerelease, diff_filename="foo_1.0.diff.gz"
        )
        self.assertEqual(
            diff.diff_content,
            self.archive.getFileByName(diff.diff_content.filename),
        )

    def test_expired_files_are_skipped(self):
        # Expired files are ignored.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        dsc = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        pub.sourcepackagerelease.addFile(dsc)

        # The file is initially found without trouble.
        self.assertEqual(dsc, self.archive.getFileByName(dsc.filename))

        # But after expiry it is not.
        removeSecurityProxy(dsc).content = None
        self.assertRaises(
            NotFoundError, self.archive.getFileByName, dsc.filename
        )

        # It reappears if we create a new one.
        new_dsc = self.factory.makeLibraryFileAlias(filename=dsc.filename)
        pub.sourcepackagerelease.addFile(new_dsc)
        self.assertEqual(new_dsc, self.archive.getFileByName(dsc.filename))

    def test_oddly_named_files_are_found(self):
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        pu = self.factory.makePackageUpload(
            changes_filename="foo-bar-baz_amd64.changes"
        )
        pu.setDone()
        pu.addSource(pub.sourcepackagerelease)
        self.assertEqual(
            pu.changesfile, self.archive.getFileByName(pu.changesfile.filename)
        )


class TestGetSourceFileByName(TestCaseWithFactory):
    """Tests for Archive.getSourceFileByName."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.archive = self.factory.makeArchive()

    def test_source_file_is_found(self):
        # A file from a published source package can be retrieved.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        dsc = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        self.assertRaises(
            NotFoundError,
            self.archive.getSourceFileByName,
            pub.source_package_name,
            pub.source_package_version,
            dsc.filename,
        )
        pub.sourcepackagerelease.addFile(dsc)
        self.assertEqual(
            dsc,
            self.archive.getSourceFileByName(
                pub.source_package_name,
                pub.source_package_version,
                dsc.filename,
            ),
        )

    def test_nonexistent_source_file_is_not_found(self):
        # Something that looks like a source file but isn't is not
        # found.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        self.assertRaises(
            NotFoundError,
            self.archive.getSourceFileByName,
            pub.source_package_name,
            pub.source_package_version,
            "foo_1.0.dsc",
        )

    def test_nonexistent_source_package_version_is_not_found(self):
        # The source package version must match exactly.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        pub2 = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive, sourcepackagename=pub.source_package_name
        )
        dsc = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        pub2.sourcepackagerelease.addFile(dsc)
        self.assertRaises(
            NotFoundError,
            self.archive.getSourceFileByName,
            pub.source_package_name,
            pub.source_package_version,
            "foo_1.0.dsc",
        )

    def test_nonexistent_source_package_name_is_not_found(self):
        # The source package name must match exactly.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        pub2 = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive
        )
        dsc = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        pub2.sourcepackagerelease.addFile(dsc)
        self.assertRaises(
            NotFoundError,
            self.archive.getSourceFileByName,
            pub.source_package_name,
            pub.source_package_version,
            "foo_1.0.dsc",
        )

    def test_epoch_stripping_collision(self):
        # Even if the archive contains two source packages with identical
        # names and versions apart from epochs which have the same filenames
        # with different contents (the worst case), getSourceFileByName
        # returns the correct files.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive, version="1.0-1"
        )
        dsc = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        pub.sourcepackagerelease.addFile(dsc)
        pub2 = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive,
            sourcepackagename=pub.source_package_name,
            version="1:1.0-1",
        )
        dsc2 = self.factory.makeLibraryFileAlias(filename="foo_1.0.dsc")
        pub2.sourcepackagerelease.addFile(dsc2)
        self.assertEqual(
            dsc,
            self.archive.getSourceFileByName(
                pub.source_package_name,
                pub.source_package_version,
                dsc.filename,
            ),
        )
        self.assertEqual(
            dsc2,
            self.archive.getSourceFileByName(
                pub2.source_package_name,
                pub2.source_package_version,
                dsc2.filename,
            ),
        )

    def test_matches_version_as_text(self):
        # Versions such as 0.7-4 and 0.7-04 are equal according to the
        # "debversion" type, but for lookup purposes we compare the text of
        # the version strings exactly.
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive, version="0.7-4"
        )
        orig = self.factory.makeLibraryFileAlias(
            filename="foo_0.7.orig.tar.gz"
        )
        pub.sourcepackagerelease.addFile(orig)
        pub2 = self.factory.makeSourcePackagePublishingHistory(
            archive=self.archive,
            sourcepackagename=pub.sourcepackagename.name,
            version="0.7-04",
        )
        orig2 = self.factory.makeLibraryFileAlias(
            filename="foo_0.7.orig.tar.gz"
        )
        pub2.sourcepackagerelease.addFile(orig2)
        self.assertEqual(
            orig,
            self.archive.getSourceFileByName(
                pub.sourcepackagename.name, "0.7-4", orig.filename
            ),
        )
        self.assertEqual(
            orig2,
            self.archive.getSourceFileByName(
                pub.sourcepackagename.name, "0.7-04", orig2.filename
            ),
        )


class TestGetPoolFileByPath(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_file_name_too_short(self):
        archive = self.factory.makeArchive()
        self.assertIsNone(
            archive.getPoolFileByPath(PurePath("pool/nonexistent"))
        )

    def test_file_name_too_long(self):
        archive = self.factory.makeArchive()
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath("pool/main/p/package/nonexistent/path")
            )
        )

    def test_mismatched_source_prefix(self):
        archive = self.factory.makeArchive()
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1.dsc", db_only=True
            ),
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath("pool/main/q/test-package/test-package_1.dsc")
            )
        )

    def test_source_not_found(self):
        archive = self.factory.makeArchive()
        self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath("pool/main/t/test-package/test-package_1.dsc")
            )
        )

    def test_source_wrong_component(self):
        archive = self.factory.makeArchive()
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1.dsc", db_only=True
            ),
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath("pool/universe/t/test-package/test-package_1.dsc")
            )
        )

    def test_source_wrong_source_package_name(self):
        archive = self.factory.makeArchive()
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1.dsc", db_only=True
            ),
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath("pool/main/o/other-package/test-package_1.dsc")
            )
        )

    def test_source_found(self):
        archive = self.factory.makeArchive()
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        sprf = self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1.dsc", db_only=True
            ),
        )
        self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1.tar.xz", db_only=True
            ),
        )
        IStore(sprf).flush()
        self.assertEqual(
            sprf.libraryfile,
            archive.getPoolFileByPath(
                PurePath("pool/main/t/test-package/test-package_1.dsc")
            ),
        )

    def test_source_found_multiple(self):
        # Source uploads that share files are initially uploaded as separate
        # LFAs, relying on the librarian's garbage-collection job to
        # deduplicate them later.
        archive = self.factory.makeArchive()
        orig_content = b"An original source tarball"
        orig_lfas = []
        for i in range(2):
            spph = self.factory.makeSourcePackagePublishingHistory(
                archive=archive,
                status=PackagePublishingStatus.PUBLISHED,
                sourcepackagename="test-package",
                component="main",
            )
            version = "1-%d" % (i + 1)
            self.factory.makeSourcePackageReleaseFile(
                sourcepackagerelease=spph.sourcepackagerelease,
                library_file=self.factory.makeLibraryFileAlias(
                    filename="test-package_%s.dsc" % version, db_only=True
                ),
            )
            self.factory.makeSourcePackageReleaseFile(
                sourcepackagerelease=spph.sourcepackagerelease,
                library_file=self.factory.makeLibraryFileAlias(
                    filename="test-package_%s.debian.tar.xz" % version,
                    db_only=True,
                ),
            )
            orig_lfas.append(
                self.factory.makeLibraryFileAlias(
                    filename="test-package_1.orig.tar.xz",
                    content=orig_content,
                    db_only=True,
                )
            )
            self.factory.makeSourcePackageReleaseFile(
                sourcepackagerelease=spph.sourcepackagerelease,
                library_file=orig_lfas[-1],
            )
        self.assertEqual(
            orig_lfas[-1],
            archive.getPoolFileByPath(
                PurePath("pool/main/t/test-package/test-package_1.orig.tar.xz")
            ),
        )

    def test_source_live_at(self):
        now = datetime.now(timezone.utc)
        archive = self.factory.makeArchive()
        spph_1 = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.DELETED,
            sourcepackagename="test-package",
            component="main",
            version="1",
        )
        removeSecurityProxy(spph_1).datepublished = now - timedelta(days=3)
        removeSecurityProxy(spph_1).dateremoved = now - timedelta(days=1)
        sprf_1 = self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph_1.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1.dsc", db_only=True
            ),
        )
        spph_2 = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
            version="2",
        )
        removeSecurityProxy(spph_2).datepublished = now - timedelta(days=2)
        sprf_2 = self.factory.makeSourcePackageReleaseFile(
            sourcepackagerelease=spph_2.sourcepackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_2.dsc", db_only=True
            ),
        )
        IStore(archive).flush()
        for days, expected_file in (
            (4, None),
            (3, sprf_1.libraryfile),
            (2, sprf_1.libraryfile),
            (1, None),
        ):
            self.assertEqual(
                expected_file,
                archive.getPoolFileByPath(
                    PurePath("pool/main/t/test-package/test-package_1.dsc"),
                    live_at=now - timedelta(days=days),
                ),
            )
        for days, expected_file in (
            (3, None),
            (2, sprf_2.libraryfile),
            (1, sprf_2.libraryfile),
        ):
            self.assertEqual(
                expected_file,
                archive.getPoolFileByPath(
                    PurePath("pool/main/t/test-package/test-package_2.dsc"),
                    live_at=now - timedelta(days=days),
                ),
            )

    def test_binary_not_found(self):
        archive = self.factory.makeArchive()
        self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath("pool/main/t/test-package/test-package_1_amd64.deb")
            )
        )

    def test_binary_wrong_component(self):
        archive = self.factory.makeArchive()
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpph.binarypackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1_amd64.deb", db_only=True
            ),
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath(
                    "pool/universe/t/test-package/test-package_1_amd64.deb"
                )
            )
        )

    def test_binary_wrong_source_package_name(self):
        archive = self.factory.makeArchive()
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpph.binarypackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1_amd64.deb", db_only=True
            ),
        )
        self.assertIsNone(
            archive.getPoolFileByPath(
                PurePath(
                    "pool/universe/o/other-package/test-package_1_amd64.deb"
                )
            )
        )

    def test_binary_found(self):
        archive = self.factory.makeArchive()
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        bpf = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpph.binarypackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1_amd64.deb", db_only=True
            ),
        )
        bpph2 = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
        )
        self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpph2.binarypackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1_i386.deb", db_only=True
            ),
        )
        IStore(bpf).flush()
        self.assertEqual(
            bpf.libraryfile,
            archive.getPoolFileByPath(
                PurePath("pool/main/t/test-package/test-package_1_amd64.deb")
            ),
        )

    def test_binary_live_at(self):
        now = datetime.now(timezone.utc)
        archive = self.factory.makeArchive()
        bpph_1 = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.DELETED,
            sourcepackagename="test-package",
            component="main",
            version="1",
        )
        removeSecurityProxy(bpph_1).datepublished = now - timedelta(days=3)
        removeSecurityProxy(bpph_1).dateremoved = now - timedelta(days=1)
        bpf_1 = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpph_1.binarypackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_1_amd64.deb", db_only=True
            ),
        )
        bpph_2 = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename="test-package",
            component="main",
            version="2",
        )
        removeSecurityProxy(bpph_2).datepublished = now - timedelta(days=2)
        bpf_2 = self.factory.makeBinaryPackageFile(
            binarypackagerelease=bpph_2.binarypackagerelease,
            library_file=self.factory.makeLibraryFileAlias(
                filename="test-package_2_amd64.deb", db_only=True
            ),
        )
        IStore(archive).flush()
        for days, expected_file in (
            (4, None),
            (3, bpf_1.libraryfile),
            (2, bpf_1.libraryfile),
            (1, None),
        ):
            self.assertEqual(
                expected_file,
                archive.getPoolFileByPath(
                    PurePath(
                        "pool/main/t/test-package/test-package_1_amd64.deb"
                    ),
                    live_at=now - timedelta(days=days),
                ),
            )
        for days, expected_file in (
            (3, None),
            (2, bpf_2.libraryfile),
            (1, bpf_2.libraryfile),
        ):
            self.assertEqual(
                expected_file,
                archive.getPoolFileByPath(
                    PurePath(
                        "pool/main/t/test-package/test-package_2_amd64.deb"
                    ),
                    live_at=now - timedelta(days=days),
                ),
            )


class TestGetPublishedSources(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_getPublishedSources_comprehensive(self):
        # The doctests for getPublishedSources migrated from a doctest for
        # better testing.
        cprov = getUtility(IPersonSet).getByName("cprov")
        cprov_archive = cprov.archive
        # There are three published sources by default - no args returns all
        # publications.
        self.assertEqual(3, cprov_archive.getPublishedSources().count())
        # Various filters.
        warty = cprov_archive.distribution["warty"]
        hoary = cprov_archive.distribution["hoary"]
        breezy_autotest = cprov_archive.distribution["breezy-autotest"]
        all_sources = cprov_archive.getPublishedSources()
        expected = [
            ("cdrkit - 1.0", "breezy-autotest"),
            ("iceweasel - 1.0", "warty"),
            ("pmount - 0.1-1", "warty"),
        ]
        found = []
        for pub in all_sources:
            title = pub.sourcepackagerelease.title
            pub_ds = pub.distroseries.name
            found.append((title, pub_ds))
        self.assertEqual(expected, found)
        self.assertEqual(
            1, cprov_archive.getPublishedSources(name="cd").count()
        )
        self.assertEqual(
            1, cprov_archive.getPublishedSources(name="ice").count()
        )
        self.assertEqual(
            1,
            cprov_archive.getPublishedSources(
                name="iceweasel", exact_match=True
            ).count(),
        )
        self.assertEqual(
            0,
            cprov_archive.getPublishedSources(
                name="ice", exact_match=True
            ).count(),
        )
        self.assertRaises(
            VersionRequiresName,
            cprov_archive.getPublishedSources,
            version="1.0",
        )
        self.assertEqual(
            1,
            cprov_archive.getPublishedSources(
                name="ice", version="1.0"
            ).count(),
        )
        self.assertEqual(
            0,
            cprov_archive.getPublishedSources(
                name="ice", version="666"
            ).count(),
        )
        self.assertEqual(
            3,
            cprov_archive.getPublishedSources(
                status=PackagePublishingStatus.PUBLISHED
            ).count(),
        )
        self.assertEqual(
            3,
            cprov_archive.getPublishedSources(
                status=active_publishing_status
            ).count(),
        )
        self.assertEqual(
            0,
            cprov_archive.getPublishedSources(
                status=inactive_publishing_status
            ).count(),
        )
        self.assertEqual(
            2, cprov_archive.getPublishedSources(distroseries=warty).count()
        )
        self.assertEqual(
            0, cprov_archive.getPublishedSources(distroseries=hoary).count()
        )
        self.assertEqual(
            1,
            cprov_archive.getPublishedSources(
                distroseries=breezy_autotest
            ).count(),
        )
        self.assertEqual(
            2,
            cprov_archive.getPublishedSources(
                distroseries=warty, pocket=PackagePublishingPocket.RELEASE
            ).count(),
        )
        self.assertEqual(
            0,
            cprov_archive.getPublishedSources(
                distroseries=warty, pocket=PackagePublishingPocket.UPDATES
            ).count(),
        )
        self.assertEqual(
            1,
            cprov_archive.getPublishedSources(
                name="ice", distroseries=warty
            ).count(),
        )
        self.assertEqual(
            0,
            cprov_archive.getPublishedSources(
                name="ice", distroseries=breezy_autotest
            ).count(),
        )
        mid_2007 = datetime(
            year=2007, month=7, day=9, hour=14, tzinfo=timezone.utc
        )
        self.assertEqual(
            0,
            cprov_archive.getPublishedSources(
                created_since_date=mid_2007
            ).count(),
        )
        one_hour_step = timedelta(hours=1)
        one_hour_earlier = mid_2007 - one_hour_step
        self.assertEqual(
            1,
            cprov_archive.getPublishedSources(
                created_since_date=one_hour_earlier
            ).count(),
        )
        two_hours_earlier = one_hour_earlier - one_hour_step
        self.assertEqual(
            3,
            cprov_archive.getPublishedSources(
                created_since_date=two_hours_earlier
            ).count(),
        )

    def test_getPublishedSources_name(self):
        # The name parameter allows filtering with a list of
        # names.
        distroseries = self.factory.makeDistroSeries()
        # Create some SourcePackagePublishingHistory.
        for package_name in ["package1", "package2", "package3"]:
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=distroseries,
                archive=distroseries.main_archive,
                sourcepackagename=self.factory.makeSourcePackageName(
                    package_name
                ),
            )
        filtered_sources = distroseries.main_archive.getPublishedSources(
            name=["package1", "package2"]
        )

        self.assertEqual(
            3, distroseries.main_archive.getPublishedSources().count()
        )
        self.assertEqual(2, filtered_sources.count())
        self.assertContentEqual(
            ["package1", "package2"],
            [
                filtered_source.sourcepackagerelease.name
                for filtered_source in filtered_sources
            ],
        )

    def test_getPublishedSources_multi_pockets(self):
        # Passing an iterable of pockets should return publications
        # with any of them in.
        distroseries = self.factory.makeDistroSeries()
        pockets = [
            PackagePublishingPocket.RELEASE,
            PackagePublishingPocket.UPDATES,
            PackagePublishingPocket.BACKPORTS,
        ]
        for pocket in pockets:
            self.factory.makeSourcePackagePublishingHistory(
                sourcepackagename=pocket.name.lower(),
                distroseries=distroseries,
                archive=distroseries.main_archive,
                pocket=pocket,
            )
        required_pockets = [
            PackagePublishingPocket.RELEASE,
            PackagePublishingPocket.UPDATES,
        ]
        filtered = distroseries.main_archive.getPublishedSources(
            pocket=required_pockets
        )

        self.assertContentEqual(
            [PackagePublishingPocket.RELEASE, PackagePublishingPocket.UPDATES],
            [source.pocket for source in filtered],
        )

    def test_filter_by_component_name(self):
        # getPublishedSources() can be filtered by component name.
        distroseries = self.factory.makeDistroSeries()
        for component in getUtility(IComponentSet):
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=distroseries,
                component=component,
            )
        [filtered] = distroseries.main_archive.getPublishedSources(
            component_name="universe"
        )
        self.assertEqual("universe", filtered.component.name)

    def test_order_by_date(self):
        archive = self.factory.makeArchive()
        dates = [self.factory.getUniqueDate() for _ in range(5)]
        # Make sure the ID ordering and date ordering don't match so that we
        # can spot a date-ordered result.
        pubs = [
            self.factory.makeSourcePackagePublishingHistory(
                archive=archive, date_uploaded=dates[(i + 1) % 5]
            )
            for i in range(5)
        ]
        self.assertEqual(
            [pubs[i] for i in (3, 2, 1, 0, 4)],
            list(archive.getPublishedSources(order_by_date=True)),
        )

    def test_order_by_date_ascending(self):
        archive = self.factory.makeArchive()
        middle_spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            date_uploaded=datetime(2009, 1, 1, tzinfo=timezone.utc),
        )
        newest_spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            date_uploaded=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        oldest_spph = self.factory.makeSourcePackagePublishingHistory(
            archive=archive,
            date_uploaded=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
        expected_order = [oldest_spph, middle_spph, newest_spph]

        self.assertEqual(
            expected_order,
            list(
                archive.api_getPublishedSources(order_by_date_ascending=True)
            ),
        )

    def test_matches_version_as_text(self):
        # Versions such as 0.7-4 and 0.07-4 are equal according to the
        # "debversion" type, but for lookup purposes we compare the text of
        # the version strings exactly.
        archive = self.factory.makeArchive()
        pub = self.factory.makeSourcePackagePublishingHistory(
            archive=archive, version="0.7-4"
        )
        self.assertEqual(
            [pub],
            list(
                archive.getPublishedSources(
                    name=pub.sourcepackagename.name,
                    version="0.7-4",
                    exact_match=True,
                )
            ),
        )
        self.assertEqual(
            [],
            list(
                archive.getPublishedSources(
                    name=pub.sourcepackagename.name,
                    version="0.07-4",
                    exact_match=True,
                )
            ),
        )


class TestGetPublishedSourcesWebService(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def createTestingPPA(self):
        """Creates and populates a PPA for API performance tests.

        Creates a public PPA and populates it with 5 distinct source
        publications with corresponding `PackageUpload` records.
        """
        ppa = self.factory.makeArchive(name="ppa", purpose=ArchivePurpose.PPA)
        distroseries = self.factory.makeDistroSeries(
            distribution=ppa.distribution
        )
        # XXX cprov 2014-04-22: currently the target archive owner cannot
        # 'addSource' to a `PackageUpload` ('launchpad.Edit'). It seems
        # too restrive to me.
        with person_logged_in(ppa.owner):
            for _ in range(5):
                upload = self.factory.makePackageUpload(
                    distroseries=distroseries, archive=ppa
                )
                pub = self.factory.makeSourcePackagePublishingHistory(
                    archive=ppa,
                    distroseries=distroseries,
                    creator=ppa.owner,
                    spr_creator=ppa.owner,
                    maintainer=ppa.owner,
                    packageupload=upload,
                )
                naked_upload = removeSecurityProxy(upload)
                naked_upload.addSource(pub.sourcepackagerelease)
        return ppa

    def test_query_count(self):
        # IArchive.getPublishedSources() webservice is exposed
        # via a wrapper to improving performance (by reducing the
        # number of queries issued)
        ppa = self.createTestingPPA()
        ppa_url = f"/~{ppa.owner.name}/+archive/ubuntu/ppa"
        webservice = webservice_for_person(
            ppa.owner, permission=OAuthPermission.READ_PRIVATE
        )

        collector = RequestTimelineCollector()
        collector.register()
        self.addCleanup(collector.unregister)

        response = webservice.named_get(ppa_url, "getPublishedSources")

        self.assertEqual(200, response.status)
        self.assertEqual(5, response.jsonBody()["total_size"])
        self.assertThat(collector, HasQueryCount(LessThan(28)))


class TestCopyPackage(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def _setup_copy_data(
        self,
        source_distribution=None,
        source_purpose=None,
        source_private=False,
        source_pocket=None,
        target_purpose=None,
        target_status=SeriesStatus.DEVELOPMENT,
        same_distribution=False,
    ):
        if target_purpose is None:
            target_purpose = ArchivePurpose.PPA
        source_archive = self.factory.makeArchive(
            distribution=source_distribution,
            purpose=source_purpose,
            private=source_private,
        )
        target_distribution = (
            source_archive.distribution if same_distribution else None
        )
        target_archive = self.factory.makeArchive(
            distribution=target_distribution, purpose=target_purpose
        )
        source = self.factory.makeSourcePackagePublishingHistory(
            archive=source_archive,
            pocket=source_pocket,
            status=PackagePublishingStatus.PUBLISHED,
        )
        with person_logged_in(source_archive.owner):
            source_name = source.source_package_name
            version = source.source_package_version
        to_pocket = PackagePublishingPocket.RELEASE
        to_series = self.factory.makeDistroSeries(
            distribution=target_archive.distribution, status=target_status
        )
        return (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        )

    def test_copyPackage_creates_packagecopyjob(self):
        # The copyPackage method should create a PCJ with the appropriate
        # parameters.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        sponsored = self.factory.makePerson()
        with person_logged_in(target_archive.owner):
            target_archive.copyPackage(
                source_name,
                version,
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=False,
                person=target_archive.owner,
                sponsored=sponsored,
                phased_update_percentage=30,
            )

        # The source should not be published yet in the target_archive.
        published = target_archive.getPublishedSources(
            name=source.source_package_name
        ).any()
        self.assertIsNone(published)

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()

        # Its data should reflect the requested copy.
        self.assertThat(
            copy_job,
            MatchesStructure.byEquality(
                package_name=source_name,
                package_version=version,
                target_archive=target_archive,
                source_archive=source_archive,
                target_distroseries=to_series,
                target_pocket=to_pocket,
                include_binaries=False,
                sponsored=sponsored,
                copy_policy=PackageCopyPolicy.INSECURE,
                phased_update_percentage=30,
                move=False,
            ),
        )

    def test_copyPackage_disallows_non_primary_archive_uploaders(self):
        # If copying to a primary archive and you're not an uploader for
        # the package then you can't copy.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        self.assertRaises(
            CannotCopy,
            target_archive.copyPackage,
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

    def test_copyPackage_allows_primary_archive_uploaders(self):
        # Copying to a primary archive if you're already an uploader is OK.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newComponentUploader(person, "universe")
        target_archive.copyPackage(
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(target_archive, copy_job.target_archive)

    def test_copyPackage_disallows_non_PPA_owners(self):
        # Only people with launchpad.Append are allowed to call copyPackage.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        person = self.factory.makePerson()
        self.assertTrue(target_archive.is_ppa)
        self.assertRaises(
            CannotCopy,
            target_archive.copyPackage,
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

    def test_copyPackage_allows_queue_admins_for_new_packages(self):
        # If a package does not exist in the target archive and series,
        # people with queue admin permissions to any component may copy it.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newQueueAdmin(person, "universe")
        target_archive.copyPackage(
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(target_archive, copy_job.target_archive)

    def test_copyPackage_allows_queue_admins_for_correct_component(self):
        # If a package already exists in the target archive and series,
        # queue admins of its component may copy it.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=to_series,
            archive=target_archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename=source_name,
            version="%s~" % version,
            component="main",
        )
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newQueueAdmin(person, "main")
        target_archive.copyPackage(
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(target_archive, copy_job.target_archive)

    def test_copyPackage_disallows_queue_admins_for_incorrect_component(self):
        # If a package already exists in the target archive and series,
        # people who only have queue admin permissions to some other
        # component may not copy it.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=to_series,
            archive=target_archive,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename=source_name,
            version="%s~" % version,
            component="main",
        )
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newQueueAdmin(person, "universe")
        self.assertRaises(
            CannotCopy,
            target_archive.copyPackage,
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

    def test_copyPackage_disallows_non_release_target_pocket_for_PPA(self):
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        to_pocket = PackagePublishingPocket.UPDATES
        self.assertTrue(target_archive.is_ppa)
        self.assertRaises(
            CannotCopy,
            target_archive.copyPackage,
            source_name,
            version,
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=target_archive.owner,
        )

    def test_copyPackage_unembargo_creates_unembargo_job(self):
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_private=True,
            target_purpose=ArchivePurpose.PRIMARY,
            target_status=SeriesStatus.CURRENT,
        )
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newComponentUploader(
                source_archive.owner, "universe"
            )
        to_pocket = PackagePublishingPocket.SECURITY
        with person_logged_in(source_archive.owner):
            target_archive.copyPackage(
                source_name,
                version,
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=False,
                person=source_archive.owner,
                unembargo=True,
            )

        # There should be one copy job, with the unembargo flag set.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(target_archive, copy_job.target_archive)
        self.assertTrue(copy_job.unembargo)

    def test_copyPackage_with_default_distroseries(self):
        # If to_series is None, copyPackage copies into the same series as
        # the source in the target archive.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        with person_logged_in(target_archive.owner):
            target_archive.copyPackage(
                source_name,
                version,
                source_archive,
                to_pocket.name,
                include_binaries=False,
                person=target_archive.owner,
            )

        # There should be one copy job with the correct target series.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_jobs = job_source.getActiveJobs(target_archive)
        self.assertEqual(1, copy_jobs.count())
        self.assertEqual(source.distroseries, copy_jobs[0].target_distroseries)

    def test_copyPackage_unpublished_source(self):
        # If the given source name is not published in the source archive,
        # we get a CannotCopy exception.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        with person_logged_in(target_archive.owner):
            expected_error = "%s is not published in %s." % (
                source_name,
                target_archive.displayname,
            )
            self.assertRaisesWithContent(
                CannotCopy,
                expected_error,
                target_archive.copyPackage,
                source_name,
                version,
                target_archive,
                to_pocket.name,
                target_archive.owner,
            )

    def test_copyPackage_with_source_series_and_pocket(self):
        # The from_series and from_pocket parameters cause copyPackage to
        # select a matching source publication.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution()
        )
        other_series = self.factory.makeDistroSeries(
            distribution=source_archive.distribution,
            status=SeriesStatus.DEVELOPMENT,
        )
        with person_logged_in(source_archive.owner):
            source.copyTo(
                other_series, PackagePublishingPocket.UPDATES, source_archive
            )
            source.requestDeletion(source_archive.owner)
        with person_logged_in(target_archive.owner):
            target_archive.copyPackage(
                source_name,
                version,
                source_archive,
                to_pocket.name,
                include_binaries=False,
                person=target_archive.owner,
                from_series=source.distroseries.name,
                from_pocket=source.pocket.name,
            )

        # There should be one copy job, with the source distroseries and
        # pocket set.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(source.distroseries, copy_job.source_distroseries)
        self.assertEqual(source.pocket, copy_job.source_pocket)

    def test_copyPackage_move(self):
        # Passing move=True causes copyPackage to create a copy job that
        # will delete the source publication after copying.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution()
        )
        with person_logged_in(target_archive.owner):
            target_archive.newComponentUploader(source_archive.owner, "main")
        with person_logged_in(source_archive.owner):
            target_archive.copyPackage(
                source_name,
                version,
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=True,
                person=source_archive.owner,
                move=True,
            )

        # There should be one copy job, with move=True set.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertTrue(copy_job.move)

    def test_copyPackage_move_without_permission(self):
        # Passing move=True checks that the user is permitted to delete the
        # source publication.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution()
        )
        with person_logged_in(target_archive.owner):
            expected_error = (
                "%s is not permitted to delete publications from %s."
                % (
                    target_archive.owner.display_name,
                    source_archive.displayname,
                )
            )
            self.assertRaisesWithContent(
                CannotCopy,
                expected_error,
                target_archive.copyPackage,
                source_name,
                version,
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=True,
                person=target_archive.owner,
                move=True,
            )

    def test_copyPackage_move_from_immutable_suite(self):
        # Passing move=True checks that the source suite can be modified.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution(),
            source_purpose=ArchivePurpose.PRIMARY,
            source_pocket=PackagePublishingPocket.RELEASE,
        )
        with person_logged_in(target_archive.owner):
            target_archive.newComponentUploader(source_archive.owner, "main")
        removeSecurityProxy(source.distroseries).status = (
            SeriesStatus.SUPPORTED
        )
        with person_logged_in(source_archive.owner):
            expected_error = "Cannot delete publications from suite '%s'" % (
                source.distroseries.getSuite(source.pocket)
            )
            self.assertRaisesWithContent(
                CannotCopy,
                expected_error,
                target_archive.copyPackage,
                source_name,
                version,
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=True,
                person=source_archive.owner,
                move=True,
            )

    def test_copyPackages_with_single_package(self):
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()

        sponsored = self.factory.makePerson()
        with person_logged_in(target_archive.owner):
            target_archive.copyPackages(
                [source_name],
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=False,
                person=target_archive.owner,
                sponsored=sponsored,
            )

        # The source should not be published yet in the target_archive.
        published = target_archive.getPublishedSources(
            name=source.source_package_name
        ).any()
        self.assertIsNone(published)

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertThat(
            copy_job,
            MatchesStructure.byEquality(
                package_name=source_name,
                package_version=version,
                target_archive=target_archive,
                source_archive=source_archive,
                target_distroseries=to_series,
                target_pocket=to_pocket,
                include_binaries=False,
                sponsored=sponsored,
                copy_policy=PackageCopyPolicy.MASS_SYNC,
                move=False,
            ),
        )

    def test_copyPackages_with_multiple_packages(self):
        # PENDING and PUBLISHED packages should both be copied.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        sources = [source]
        sources.append(
            self.factory.makeSourcePackagePublishingHistory(
                archive=source_archive, status=PackagePublishingStatus.PENDING
            )
        )
        sources.append(
            self.factory.makeSourcePackagePublishingHistory(
                archive=source_archive,
                status=PackagePublishingStatus.PUBLISHED,
            )
        )
        names = [
            source.sourcepackagerelease.sourcepackagename.name
            for source in sources
        ]

        with person_logged_in(target_archive.owner):
            target_archive.copyPackages(
                names,
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=False,
                person=target_archive.owner,
            )

        # Make sure three copy jobs exist.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_jobs = job_source.getActiveJobs(target_archive)
        self.assertEqual(3, copy_jobs.count())

    def test_copyPackages_disallows_non_primary_archive_uploaders(self):
        # If copying to a primary archive and you're not an uploader for
        # the package then you can't copy.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        self.assertRaises(
            CannotCopy,
            target_archive.copyPackages,
            [source_name],
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

    def test_copyPackages_allows_primary_archive_uploaders(self):
        # Copying to a primary archive if you're already an uploader is OK.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newComponentUploader(person, "universe")
        target_archive.copyPackages(
            [source_name],
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(target_archive, copy_job.target_archive)

    def test_copyPackages_disallows_non_PPA_owners(self):
        # Only people with launchpad.Append are allowed to call copyPackages.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        person = self.factory.makePerson()
        self.assertTrue(target_archive.is_ppa)
        self.assertRaises(
            CannotCopy,
            target_archive.copyPackages,
            [source_name],
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

    def test_copyPackages_allows_queue_admins(self):
        # Queue admins without upload permissions may still copy packages.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newQueueAdmin(person, "universe")
        target_archive.copyPackages(
            [source_name],
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )

        # There should be one copy job.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(target_archive, copy_job.target_archive)

    def test_copyPackages_with_multiple_distroseries(self):
        # The from_series parameter selects a source distroseries.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        new_distroseries = self.factory.makeDistroSeries(
            distribution=source_archive.distribution
        )
        new_version = "%s.1" % version
        new_spr = self.factory.makeSourcePackageRelease(
            archive=source_archive,
            distroseries=new_distroseries,
            sourcepackagename=source_name,
            version=new_version,
        )
        self.factory.makeSourcePackagePublishingHistory(
            archive=source_archive,
            distroseries=new_distroseries,
            sourcepackagerelease=new_spr,
        )

        with person_logged_in(target_archive.owner):
            target_archive.copyPackages(
                [source_name],
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                from_series=source.distroseries.name,
                include_binaries=False,
                person=target_archive.owner,
            )

        # There should be one copy job with the correct version.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(version, copy_job.package_version)

        # If we now do another copy without the from_series parameter, it
        # selects the newest version in the source archive.
        with person_logged_in(target_archive.owner):
            target_archive.copyPackages(
                [source_name],
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=False,
                person=target_archive.owner,
            )

        copy_jobs = job_source.getActiveJobs(target_archive)
        self.assertEqual(2, copy_jobs.count())
        self.assertEqual(copy_job, copy_jobs[0])
        self.assertEqual(new_version, copy_jobs[1].package_version)

    def test_copyPackages_with_default_distroseries(self):
        # If to_series is None, copyPackages copies into the same series as
        # each source in the target archive.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        sources = [source]
        other_series = self.factory.makeDistroSeries(
            distribution=target_archive.distribution
        )
        sources.append(
            self.factory.makeSourcePackagePublishingHistory(
                distroseries=other_series,
                archive=source_archive,
                status=PackagePublishingStatus.PUBLISHED,
            )
        )
        names = [
            source.sourcepackagerelease.sourcepackagename.name
            for source in sources
        ]

        with person_logged_in(target_archive.owner):
            target_archive.copyPackages(
                names,
                source_archive,
                to_pocket.name,
                include_binaries=False,
                person=target_archive.owner,
            )

        # There should be two copy jobs with the correct target series.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_jobs = job_source.getActiveJobs(target_archive)
        self.assertEqual(2, copy_jobs.count())
        self.assertContentEqual(
            [source.distroseries for source in sources],
            [copy_job.target_distroseries for copy_job in copy_jobs],
        )

    def test_copyPackages_with_default_distroseries_and_override(self):
        # If to_series is None, copyPackages checks permissions based on the
        # component in the target archive, not the component in the source
        # archive.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            target_purpose=ArchivePurpose.PRIMARY, same_distribution=True
        )
        sources = [source]
        uploader = self.factory.makePerson()
        main = self.factory.makeComponent(name="main")
        universe = self.factory.makeComponent(name="universe")
        ComponentSelection(distroseries=to_series, component=main)
        ComponentSelection(distroseries=to_series, component=universe)
        with person_logged_in(target_archive.owner):
            target_archive.newComponentUploader(uploader, universe)
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=source.distroseries,
            archive=target_archive,
            pocket=to_pocket,
            status=PackagePublishingStatus.PUBLISHED,
            sourcepackagename=source_name,
            version="%s~1" % version,
            component=universe,
        )
        names = [
            source.sourcepackagerelease.sourcepackagename.name
            for source in sources
        ]

        with person_logged_in(uploader):
            target_archive.copyPackages(
                names,
                source_archive,
                to_pocket.name,
                include_binaries=False,
                person=uploader,
            )

        # There should be a copy job with the correct target series.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(source.distroseries, copy_job.target_distroseries)

    def test_copyPackages_unpublished_source(self):
        # If none of the given source names are published in the source
        # archive, we get a CannotCopy exception.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data()
        with person_logged_in(target_archive.owner):
            expected_error = (
                "None of the supplied package names are published in %s."
                % target_archive.displayname
            )
            self.assertRaisesWithContent(
                CannotCopy,
                expected_error,
                target_archive.copyPackages,
                [source_name],
                target_archive,
                to_pocket.name,
                target_archive.owner,
            )

    def test_copyPackages_to_pocket(self):
        # copyPackages respects the to_pocket parameter.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(target_purpose=ArchivePurpose.PRIMARY)
        to_pocket = PackagePublishingPocket.PROPOSED
        person = self.factory.makePerson()
        with person_logged_in(target_archive.distribution.owner):
            target_archive.newComponentUploader(person, "universe")
        target_archive.copyPackages(
            [source_name],
            source_archive,
            to_pocket.name,
            to_series=to_series.name,
            include_binaries=False,
            person=person,
        )
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertEqual(to_pocket, copy_job.target_pocket)

    def test_copyPackages_move(self):
        # Passing move=True causes copyPackages to create copy jobs that
        # will delete the source publication after copying.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution()
        )
        with person_logged_in(target_archive.owner):
            target_archive.newComponentUploader(source_archive.owner, "main")
        with person_logged_in(source_archive.owner):
            target_archive.copyPackages(
                [source_name],
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=True,
                person=source_archive.owner,
                move=True,
            )

        # There should be one copy job, with move=True set.
        job_source = getUtility(IPlainPackageCopyJobSource)
        copy_job = job_source.getActiveJobs(target_archive).one()
        self.assertTrue(copy_job.move)

    def test_copyPackages_move_without_permission(self):
        # Passing move=True checks that the user is permitted to delete the
        # source publication.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution()
        )
        with person_logged_in(target_archive.owner):
            expected_error = (
                "%s is not permitted to delete publications from %s."
                % (
                    target_archive.owner.display_name,
                    source_archive.displayname,
                )
            )
            self.assertRaisesWithContent(
                CannotCopy,
                expected_error,
                target_archive.copyPackages,
                [source_name],
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=True,
                person=target_archive.owner,
                move=True,
            )

    def test_copyPackages_move_from_immutable_suite(self):
        # Passing move=True checks that the source suite can be modified.
        (
            source,
            source_archive,
            source_name,
            target_archive,
            to_pocket,
            to_series,
            version,
        ) = self._setup_copy_data(
            source_distribution=self.factory.makeDistribution(),
            source_purpose=ArchivePurpose.PRIMARY,
            source_pocket=PackagePublishingPocket.RELEASE,
        )
        with person_logged_in(target_archive.owner):
            target_archive.newComponentUploader(source_archive.owner, "main")
        removeSecurityProxy(source.distroseries).status = (
            SeriesStatus.SUPPORTED
        )
        with person_logged_in(source_archive.owner):
            expected_error = "Cannot delete publications from suite '%s'" % (
                source.distroseries.getSuite(source.pocket)
            )
            self.assertRaisesWithContent(
                CannotCopy,
                expected_error,
                target_archive.copyPackages,
                [source_name],
                source_archive,
                to_pocket.name,
                to_series=to_series.name,
                include_binaries=True,
                person=source_archive.owner,
                move=True,
            )


class TestUploadCIBuild(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def makeCIBuild(self, distribution, **kwargs):
        # CIBuilds must be in a package namespace in order to be uploaded to
        # an archive.
        dsp = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        repository = self.factory.makeGitRepository(target=dsp)
        return self.factory.makeCIBuild(git_repository=repository, **kwargs)

    def test_creates_job(self):
        # The uploadCIBuild method creates a CIBuildUploadJob with the
        # appropriate parameters.
        archive = self.factory.makeArchive(
            publishing_method=ArchivePublishingMethod.ARTIFACTORY
        )
        series = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        build = self.makeCIBuild(
            archive.distribution, status=BuildStatus.FULLYBUILT
        )
        with person_logged_in(archive.owner):
            archive.uploadCIBuild(
                build, archive.owner, series.name, "Release", to_channel="edge"
            )
        [job] = getUtility(ICIBuildUploadJobSource).iterReady()
        self.assertThat(
            job,
            MatchesStructure.byEquality(
                ci_build=build,
                target_distroseries=series,
                target_pocket=PackagePublishingPocket.RELEASE,
                target_channel="edge",
            ),
        )

    def test_disallows_non_artifactory_publishing(self):
        # CI builds may only be copied into archives published using
        # Artifactory.
        archive = self.factory.makeArchive()
        series = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        build = self.makeCIBuild(
            archive.distribution, status=BuildStatus.FULLYBUILT
        )
        with person_logged_in(archive.owner):
            self.assertRaisesWithContent(
                CannotCopy,
                "CI builds may only be uploaded to archives published using "
                "Artifactory.",
                archive.uploadCIBuild,
                build,
                archive.owner,
                series.name,
                "Release",
            )

    def test_disallows_non_package_namespace(self):
        # Only CI builds for repositories in package namespaces may be
        # copied into archives.
        archive = self.factory.makeArchive(
            publishing_method=ArchivePublishingMethod.ARTIFACTORY
        )
        series = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        build = self.factory.makeCIBuild(status=BuildStatus.FULLYBUILT)
        with person_logged_in(archive.owner):
            self.assertRaisesWithContent(
                CannotCopy,
                "Only CI builds for repositories in package namespaces may be "
                "uploaded to archives.",
                archive.uploadCIBuild,
                build,
                archive.owner,
                series.name,
                "Release",
            )

    def test_disallows_incomplete_builds(self):
        # CI builds with statuses other than FULLYBUILT may not be copied.
        archive = self.factory.makeArchive(
            publishing_method=ArchivePublishingMethod.ARTIFACTORY
        )
        series = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        build = self.makeCIBuild(
            archive.distribution, status=BuildStatus.FAILEDTOBUILD
        )
        person = self.factory.makePerson()
        self.assertRaisesWithContent(
            CannotCopy,
            "%r has status 'Failed to build', not 'Successfully built'."
            % (build),
            archive.uploadCIBuild,
            build,
            person,
            series.name,
            "Release",
        )

    def test_disallows_non_uploaders(self):
        # Only people with upload permission may call uploadCIBuild.
        archive = self.factory.makeArchive(
            publishing_method=ArchivePublishingMethod.ARTIFACTORY
        )
        series = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        build = self.makeCIBuild(
            archive.distribution, status=BuildStatus.FULLYBUILT
        )
        person = self.factory.makePerson()
        self.assertRaisesWithContent(
            CannotCopy,
            "Signer has no upload rights to this PPA.",
            archive.uploadCIBuild,
            build,
            person,
            series.name,
            "Release",
        )


class TestgetAllPublishedBinaries(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_returns_publication(self):
        archive = self.factory.makeArchive()
        publication = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive
        )
        publications = archive.getAllPublishedBinaries()
        self.assertEqual(1, publications.count())
        self.assertEqual(publication, publications[0])

    def test_created_since_date_newer(self):
        archive = self.factory.makeArchive()
        datecreated = self.factory.getUniqueDate()
        self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=datecreated
        )
        later_date = datecreated + timedelta(minutes=1)
        publications = archive.getAllPublishedBinaries(
            created_since_date=later_date
        )
        self.assertEqual(0, publications.count())

    def test_created_since_date_older(self):
        archive = self.factory.makeArchive()
        datecreated = self.factory.getUniqueDate()
        publication = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=datecreated
        )
        earlier_date = datecreated - timedelta(minutes=1)
        publications = archive.getAllPublishedBinaries(
            created_since_date=earlier_date
        )
        self.assertEqual(1, publications.count())
        self.assertEqual(publication, publications[0])

    def test_created_since_date_middle(self):
        archive = self.factory.makeArchive()
        datecreated = self.factory.getUniqueDate()
        self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=datecreated
        )
        middle_date = datecreated + timedelta(minutes=1)
        later_date = middle_date + timedelta(minutes=1)
        later_publication = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=later_date
        )
        publications = archive.getAllPublishedBinaries(
            created_since_date=middle_date
        )
        self.assertEqual(1, publications.count())
        self.assertEqual(later_publication, publications[0])

    def test_unordered_results(self):
        archive = self.factory.makeArchive()
        datecreated = self.factory.getUniqueDate()
        middle_date = datecreated + timedelta(minutes=1)
        later_date = middle_date + timedelta(minutes=1)

        # Create three publications whose ID ordering doesn't match the
        # date ordering.
        first_publication = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=datecreated
        )
        middle_publication = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=later_date
        )
        later_publication = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, datecreated=middle_date
        )

        # We can't test for no ordering as it's not deterministic; but
        # we can make sure that all the publications are returned.
        publications = archive.getAllPublishedBinaries(ordered=False)
        self.assertContentEqual(
            publications,
            [first_publication, middle_publication, later_publication],
        )

    def test_order_by_date(self):
        archive = self.factory.makeArchive()
        dates = [self.factory.getUniqueDate() for _ in range(5)]
        # Make sure the ID ordering and date ordering don't match so that we
        # can spot a date-ordered result.
        pubs = [
            self.factory.makeBinaryPackagePublishingHistory(
                archive=archive, datecreated=dates[(i + 1) % 5]
            )
            for i in range(5)
        ]
        self.assertEqual(
            [pubs[i] for i in (3, 2, 1, 0, 4)],
            list(archive.getAllPublishedBinaries(order_by_date=True)),
        )

    def test_order_by_date_ascending(self):
        archive = self.factory.makeArchive()
        middle_bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            datecreated=datetime(2009, 1, 1, tzinfo=timezone.utc),
        )
        newest_bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            datecreated=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        oldest_bpph = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive,
            datecreated=datetime(2000, 1, 1, tzinfo=timezone.utc),
        )
        expected_order = [oldest_bpph, middle_bpph, newest_bpph]

        self.assertEqual(
            expected_order,
            list(
                archive.getAllPublishedBinaries(order_by_date_ascending=True)
            ),
        )

    def test_matches_version_as_text(self):
        # Versions such as 0.7-4 and 0.07-4 are equal according to the
        # "debversion" type, but for lookup purposes we compare the text of
        # the version strings exactly.
        archive = self.factory.makeArchive()
        pub = self.factory.makeBinaryPackagePublishingHistory(
            archive=archive, version="0.7-4"
        )
        self.assertEqual(
            [pub],
            list(
                archive.getAllPublishedBinaries(
                    name=pub.binarypackagename.name,
                    version="0.7-4",
                    exact_match=True,
                )
            ),
        )
        self.assertEqual(
            [],
            list(
                archive.getAllPublishedBinaries(
                    name=pub.binarypackagename.name,
                    version="0.07-4",
                    exact_match=True,
                )
            ),
        )


class TestRemovingPermissions(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_remove_permission_is_none(self):
        # Several API functions remove permissions if they are not already
        # removed.  This verifies that the underlying utility function does
        # not generate an error if the permission is None.
        ap_set = ArchivePermissionSet()
        ap_set._remove_permission(None)


class TestRemovingCopyNotifications(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def makeJob(self):
        distroseries = self.factory.makeDistroSeries()
        archive1 = self.factory.makeArchive(distroseries.distribution)
        archive2 = self.factory.makeArchive(distroseries.distribution)
        requester = self.factory.makePerson()
        source = getUtility(IPlainPackageCopyJobSource)
        job = source.create(
            package_name="foo",
            source_archive=archive1,
            target_archive=archive2,
            target_distroseries=distroseries,
            target_pocket=PackagePublishingPocket.RELEASE,
            package_version="1.0-1",
            include_binaries=True,
            requester=requester,
        )
        return (distroseries, archive1, archive2, requester, job)

    def test_removeCopyNotification(self):
        distroseries, archive1, archive2, requester, job = self.makeJob()
        job.start()
        job.fail()

        with person_logged_in(archive2.owner):
            archive2.removeCopyNotification(job.id)

        source = getUtility(IPlainPackageCopyJobSource)
        found_jobs = source.getIncompleteJobsForArchive(archive2)
        self.assertIsNone(found_jobs.any())

    def test_removeCopyNotification_raises_for_not_failed(self):
        distroseries, archive1, archive2, requester, job = self.makeJob()

        self.assertNotEqual(JobStatus.FAILED, job.status)
        with person_logged_in(archive2.owner):
            self.assertRaises(
                AssertionError, archive2.removeCopyNotification, job.id
            )

    def test_removeCopyNotification_raises_for_wrong_archive(self):
        # If the job ID supplied is not for the context archive, an
        # error should be raised.
        distroseries, archive1, archive2, requester, job = self.makeJob()
        job.start()
        job.fail()

        # Set up a second job in the other archive.
        source = getUtility(IPlainPackageCopyJobSource)
        job2 = source.create(
            package_name="foo",
            source_archive=archive2,
            target_archive=archive1,
            target_distroseries=distroseries,
            target_pocket=PackagePublishingPocket.RELEASE,
            package_version="1.0-1",
            include_binaries=True,
            requester=requester,
        )

        with person_logged_in(archive2.owner):
            self.assertRaises(
                AssertionError, archive2.removeCopyNotification, job2.id
            )


class TestPublishFlag(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_primary_archive_published_by_default(self):
        distribution = self.factory.makeDistribution()
        self.assertTrue(distribution.main_archive.publish)

    def test_partner_archive_published_by_default(self):
        partner = self.factory.makeArchive(purpose=ArchivePurpose.PARTNER)
        self.assertTrue(partner.publish)

    def test_ppa_published_by_default(self):
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertTrue(ppa.publish)

    def test_copy_archive_not_published_by_default(self):
        copy = self.factory.makeArchive(purpose=ArchivePurpose.COPY)
        self.assertFalse(copy.publish)


class TestPPANaming(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_unique_copy_archive_name(self):
        # Non-PPA archive names must be unique for a given distribution.
        uber = self.factory.makeDistribution()
        self.factory.makeArchive(
            purpose=ArchivePurpose.COPY, distribution=uber, name="uber-copy"
        )
        self.assertRaises(
            AssertionError,
            self.factory.makeArchive,
            purpose=ArchivePurpose.COPY,
            distribution=uber,
            name="uber-copy",
        )

    def test_unique_partner_archive_name(self):
        # Partner archive names must be unique for a given distribution.
        uber = self.factory.makeDistribution()
        self.factory.makeArchive(
            purpose=ArchivePurpose.PARTNER,
            distribution=uber,
            name="uber-partner",
        )
        self.assertRaises(
            AssertionError,
            self.factory.makeArchive,
            purpose=ArchivePurpose.PARTNER,
            distribution=uber,
            name="uber-partner",
        )

    def test_unique_ppa_name_per_owner_and_distribution(self):
        person = self.factory.makePerson()
        self.factory.makeArchive(owner=person, name="ppa")
        self.assertEqual(
            "PPA for %s" % person.displayname, person.archive.displayname
        )
        self.assertEqual("ppa", person.archive.name)
        self.assertRaises(
            AssertionError, self.factory.makeArchive, owner=person, name="ppa"
        )

    def test_default_archive(self):
        # Creating multiple PPAs does not affect the existing traversal from
        # IPerson to a single IArchive.
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(owner=person, name="ppa")
        self.factory.makeArchive(owner=person, name="nightly")
        self.assertEqual(ppa, person.archive)

    def test_non_default_ppas_have_different_displayname(self):
        person = self.factory.makePerson()
        another_ppa = self.factory.makeArchive(owner=person, name="nightly")
        self.assertEqual(
            "PPA named nightly for %s" % person.displayname,
            another_ppa.displayname,
        )

    def test_archives_cannot_have_same_name_as_distribution(self):
        boingolinux = self.factory.makeDistribution(name="boingolinux")
        self.assertRaises(
            AssertionError,
            getUtility(IArchiveSet).new,
            owner=self.factory.makePerson(),
            purpose=ArchivePurpose.PRIMARY,
            distribution=boingolinux,
            name=boingolinux.name,
        )


class TestGetPPAOwnedByPerson(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.set = getUtility(IArchiveSet)

    def test_person(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        random = self.factory.makePerson()
        self.assertEqual(archive, self.set.getPPAOwnedByPerson(archive.owner))
        self.assertIs(None, self.set.getPPAOwnedByPerson(random))

    def test_distribution_and_name(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertEqual(
            archive,
            self.set.getPPAOwnedByPerson(
                archive.owner, archive.distribution, archive.name
            ),
        )
        self.assertIs(
            None,
            self.set.getPPAOwnedByPerson(
                archive.owner, archive.distribution, archive.name + "lol"
            ),
        )
        self.assertIs(
            None,
            self.set.getPPAOwnedByPerson(
                archive.owner, self.factory.makeDistribution(), archive.name
            ),
        )

    def test_statuses(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertEqual(
            archive,
            self.set.getPPAOwnedByPerson(
                archive.owner, statuses=(ArchiveStatus.ACTIVE,)
            ),
        )
        self.assertIs(
            None,
            self.set.getPPAOwnedByPerson(
                archive.owner, statuses=(ArchiveStatus.DELETING,)
            ),
        )
        with person_logged_in(archive.owner):
            archive.delete(archive.owner)
        self.assertEqual(
            archive,
            self.set.getPPAOwnedByPerson(
                archive.owner, statuses=(ArchiveStatus.DELETING,)
            ),
        )

    def test_has_packages(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertIs(
            None,
            self.set.getPPAOwnedByPerson(archive.owner, has_packages=True),
        )
        self.factory.makeSourcePackagePublishingHistory(archive=archive)
        self.assertEqual(
            archive,
            self.set.getPPAOwnedByPerson(archive.owner, has_packages=True),
        )


class TestPPALookup(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        self.notbuntu = self.factory.makeDistribution()
        self.person = self.factory.makePerson()
        self.factory.makeArchive(owner=self.person, name="ppa")
        self.nightly = self.factory.makeArchive(
            owner=self.person, name="nightly"
        )
        self.other_ppa = self.factory.makeArchive(
            owner=self.person, distribution=self.notbuntu, name="ppa"
        )
        self.third_ppa = self.factory.makeArchive(
            owner=self.person, distribution=self.notbuntu, name="aap"
        )

    def test_ppas(self):
        # IPerson.ppas returns all owned PPAs ordered by name.
        self.assertEqual(
            ["aap", "nightly", "ppa", "ppa"],
            [ppa.name for ppa in self.person.ppas],
        )

    def test_getPPAByName(self):
        default_ppa = self.person.getPPAByName(self.ubuntu, "ppa")
        self.assertEqual(self.person.archive, default_ppa)
        nightly_ppa = self.person.getPPAByName(self.ubuntu, "nightly")
        self.assertEqual(self.nightly, nightly_ppa)
        other_ppa = self.person.getPPAByName(self.notbuntu, "ppa")
        self.assertEqual(self.other_ppa, other_ppa)
        third_ppa = self.person.getPPAByName(self.notbuntu, "aap")
        self.assertEqual(self.third_ppa, third_ppa)

    def test_getPPAByName_defaults_to_ubuntu(self):
        default_ppa = self.person.getPPAByName(None, "ppa")
        self.assertEqual(self.person.archive, default_ppa)

    def test_NoSuchPPA(self):
        self.assertRaises(
            NoSuchPPA, self.person.getPPAByName, self.ubuntu, "not-found"
        )

    def test_NoSuchPPA_default_distro(self):
        self.assertRaises(NoSuchPPA, self.person.getPPAByName, None, "aap")


class TestArchiveReference(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def assertReferenceIntegrity(self, reference, archive):
        """Assert that the archive's reference matches in both directions."""
        self.assertEqual(reference, archive.reference)
        self.assertEqual(
            archive, getUtility(IArchiveSet).getByReference(reference)
        )

    def test_primary(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        self.assertReferenceIntegrity(archive.distribution.name, archive)

    def test_partner(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PARTNER)
        self.assertReferenceIntegrity(
            "%s/%s" % (archive.distribution.name, archive.name), archive
        )

    def test_copy(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.COPY)
        self.assertReferenceIntegrity(
            "%s/%s" % (archive.distribution.name, archive.name), archive
        )

    def test_ppa(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertReferenceIntegrity(
            "~%s/%s/%s"
            % (archive.owner.name, archive.distribution.name, archive.name),
            archive,
        )

    def test_ppa_alias(self):
        # ppa:OWNER/DISTRO/ARCHIVE is accepted as a convenience to make it
        # easier to avoid tilde-expansion in shells.
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        reference = "ppa:%s/%s/%s" % (
            archive.owner.name,
            archive.distribution.name,
            archive.name,
        )
        self.assertEqual(
            archive, getUtility(IArchiveSet).getByReference(reference)
        )


class TestArchiveSetGetByReference(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.set = getUtility(IArchiveSet)

    def test_ppa(self):
        owner = self.factory.makePerson(name="pwner")
        twoner = self.factory.makePerson(name="twoner")
        twobuntu = self.factory.makeDistribution(name="two")
        threebuntu = self.factory.makeDistribution(name="three")
        ppa1 = self.factory.makeArchive(
            owner=owner,
            distribution=twobuntu,
            name="ppa",
            purpose=ArchivePurpose.PPA,
        )
        ppa2 = self.factory.makeArchive(
            owner=owner,
            distribution=twobuntu,
            name="qpa",
            purpose=ArchivePurpose.PPA,
        )
        ppa3 = self.factory.makeArchive(
            owner=owner,
            distribution=threebuntu,
            name="ppa",
            purpose=ArchivePurpose.PPA,
        )
        ppa4 = self.factory.makeArchive(
            owner=twoner,
            distribution=twobuntu,
            name="ppa",
            purpose=ArchivePurpose.PPA,
        )

        self.assertEqual(ppa1, self.set.getByReference("~pwner/two/ppa"))
        self.assertEqual(ppa2, self.set.getByReference("~pwner/two/qpa"))
        self.assertEqual(ppa3, self.set.getByReference("~pwner/three/ppa"))
        self.assertEqual(ppa4, self.set.getByReference("~twoner/two/ppa"))

        # Bad combinations give None.
        self.assertIs(None, self.set.getByReference("~pwner/three/qpa"))
        self.assertIs(None, self.set.getByReference("~twoner/two/qpa"))
        self.assertIs(None, self.set.getByReference("~pwner/two/rpa"))

        # Nonexistent names give None.
        self.assertIs(None, self.set.getByReference("~pwner/enoent/ppa"))
        self.assertIs(None, self.set.getByReference("~whoisthis/two/ppa"))

        # Invalid formats give None.
        self.assertIs(None, self.set.getByReference("~whoisthis/two/w/t"))
        self.assertIs(None, self.set.getByReference("~whoisthis/two"))
        self.assertIs(None, self.set.getByReference("~whoisthis"))

    def test_distro(self):
        twobuntu = self.factory.makeDistribution(name="two")
        threebuntu = self.factory.makeDistribution(name="three")
        two_primary = self.factory.makeArchive(
            distribution=twobuntu, purpose=ArchivePurpose.PRIMARY
        )
        two_partner = self.factory.makeArchive(
            distribution=twobuntu, purpose=ArchivePurpose.PARTNER
        )
        three_primary = self.factory.makeArchive(
            distribution=threebuntu, purpose=ArchivePurpose.PRIMARY
        )
        three_copy = self.factory.makeArchive(
            distribution=threebuntu,
            purpose=ArchivePurpose.COPY,
            name="rebuild",
        )

        self.assertEqual(two_primary, self.set.getByReference("two"))
        self.assertEqual(two_partner, self.set.getByReference("two/partner"))
        self.assertEqual(three_primary, self.set.getByReference("three"))
        self.assertEqual(three_copy, self.set.getByReference("three/rebuild"))

        # Bad combinations give None.
        self.assertIs(None, self.set.getByReference("three/partner"))
        self.assertIs(None, self.set.getByReference("two/rebuild"))

        # Nonexistent names give None.
        self.assertIs(None, self.set.getByReference("three/enoent"))
        self.assertIs(None, self.set.getByReference("enodist"))
        self.assertIs(None, self.set.getByReference("enodist/partner"))

        # Invalid formats give None.
        self.assertIs(None, self.set.getByReference("two/partner/idonteven"))

    def test_nonsense(self):
        self.assertIs(None, getUtility(IArchiveSet).getByReference(""))
        self.assertIs(
            None,
            getUtility(IArchiveSet).getByReference("that/does/not/make/sense"),
        )

    def test_check_permissions_private(self):
        private_owner = self.factory.makeTeam(
            visibility=PersonVisibility.PRIVATE
        )
        private = self.factory.makeArchive(owner=private_owner, private=True)
        with admin_logged_in():
            private_reference = private.reference
        self.assertEqual(
            private,
            getUtility(IArchiveSet).getByReference(
                private_reference, check_permissions=False
            ),
        )
        self.assertIs(
            None,
            getUtility(IArchiveSet).getByReference(
                private_reference, check_permissions=True
            ),
        )
        self.assertEqual(
            private,
            getUtility(IArchiveSet).getByReference(
                private_reference, check_permissions=True, user=private_owner
            ),
        )
        self.assertIs(
            None,
            getUtility(IArchiveSet).getByReference(
                private_reference,
                check_permissions=True,
                user=self.factory.makePerson(),
            ),
        )

    def test_check_permissions_public(self):
        public = self.factory.makeArchive(private=False)
        self.assertEqual(
            public,
            getUtility(IArchiveSet).getByReference(
                public.reference, check_permissions=False
            ),
        )
        self.assertEqual(
            public,
            getUtility(IArchiveSet).getByReference(
                public.reference, check_permissions=True
            ),
        )
        self.assertEqual(
            public,
            getUtility(IArchiveSet).getByReference(
                public.reference,
                check_permissions=True,
                user=self.factory.makePerson(),
            ),
        )

    def assertLookupFails(self, reference):
        self.assertIs(
            None,
            getUtility(IArchiveSet).getByReference(
                reference, check_permissions=True
            ),
        )

    def test_check_permissions_nonexistent(self):
        self.assertLookupFails("")
        self.assertLookupFails("enoent")
        self.assertLookupFails("ubuntu/enoent")
        self.assertLookupFails("ubuntu/partner/enoent")
        self.assertLookupFails("~enoent/ubuntu/ppa")
        self.assertLookupFails("~cprov/enoent/ppa")
        self.assertLookupFails("~cprov/ubuntu/enoent")
        self.assertLookupFails("~enoent/twonoent")
        self.assertLookupFails("~enoent/twonoent/threenoent")
        self.assertLookupFails("~enoent/twonoent/threenoent/fournoent")


class TestArchiveSetGetBy1024BitRSASigningKey(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.set = getUtility(IArchiveSet)

    def makeArchivesWithRSAKey(self, key_size, archives_number=1):
        archives = []

        def fingerprintGenerator(prefix="4096"):
            letters = ["A", "B", "C", "D", "E", "F"]
            return prefix + "".join(
                random.choice(letters) for _ in range(40 - len(prefix))
            )

        key_fingerprint = fingerprintGenerator(str(key_size))
        owner = self.factory.makePerson()
        self.factory.makeGPGKey(
            owner=owner,
            keyid=key_fingerprint[-8:],
            fingerprint=key_fingerprint,
            keysize=key_size,
        )
        signing_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=key_fingerprint
        )
        for _ in range(archives_number):
            ppa = self.factory.makeArchive(
                owner=owner,
                distribution=getUtility(IDistributionSet).getByName(
                    "ubuntutest"
                ),
                purpose=ArchivePurpose.PPA,
            )
            ppa.signing_key_fingerprint = key_fingerprint
            self.factory.makeArchiveSigningKey(ppa, None, signing_key)
            archives.append(ppa)
        return archives

    def test_no_PPAs_with_1024_bit_key(self):
        archives = list(
            self.set.getArchivesWith1024BitRSASigningKey(limit=None)
        )
        self.assertEqual(0, len(archives))

    def test_PPAs_with_1024_bit_key(self):
        archives_number = 10
        # Create archives with 1024-bit RSA key.
        archives = self.makeArchivesWithRSAKey(
            key_size=1024, archives_number=archives_number
        )

        actual_archives = list(
            getUtility(IArchiveSet).getArchivesWith1024BitRSASigningKey(
                limit=None
            )
        )
        self.assertEqual(archives_number, len(actual_archives))
        self.assertEqual(archives, actual_archives)

    def test_PPAs_with_1024_bit_key_PPAs_have_4096_bit_key(self):
        archives_number = 10
        # Create archives with 1024-bit RSA key.
        archives = self.makeArchivesWithRSAKey(
            key_size=1024, archives_number=archives_number
        )

        # Create archives with 4096-bit RSA key.
        noise_archives = self.makeArchivesWithRSAKey(
            key_size=4096, archives_number=5
        )

        actual_archives = list(
            getUtility(IArchiveSet).getArchivesWith1024BitRSASigningKey(
                limit=None
            )
        )
        self.assertEqual(archives_number, len(actual_archives))
        self.assertEqual(archives, actual_archives)
        self.assertNotIn(noise_archives, actual_archives)

    def test_PPAs_with_1024_bit_key_mixed(self):
        archives_number = 10

        owner = self.factory.makePerson()

        # Create archives with 1024-bit RSA key.
        archives = self.makeArchivesWithRSAKey(
            key_size=1024, archives_number=archives_number
        )

        # Add a 4096-bit RSA key to the archives.
        gpg_key = self.factory.makeGPGKey(
            owner=owner,
            keysize=4096,
        )
        signing_key = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=gpg_key.fingerprint
        )
        for archive in archives:
            self.factory.makeArchiveSigningKey(archive, None, signing_key)

        # Create archives with 4096-bit RSA key.
        self.makeArchivesWithRSAKey(key_size=4096, archives_number=5)

        actual_archives = list(
            getUtility(IArchiveSet).getArchivesWith1024BitRSASigningKey(
                limit=None
            )
        )
        self.assertEqual(0, len(actual_archives))


class TestArchiveSetCheckViewPermission(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.archive_set = getUtility(IArchiveSet)
        self.public_archive = self.factory.makeArchive(private=False)
        self.public_disabled_archive = self.factory.makeArchive(
            private=False, enabled=False
        )
        self.private_archive = self.factory.makeArchive(private=True)

    def test_public_enabled_archives(self):
        somebody = self.factory.makePerson()
        with person_logged_in(somebody):
            results = self.archive_set.checkViewPermission(
                [
                    self.public_archive,
                    self.public_disabled_archive,
                    self.private_archive,
                ],
                somebody,
            )
        self.assertDictEqual(
            results,
            {
                self.public_archive: True,
                self.public_disabled_archive: False,
                self.private_archive: False,
            },
        )

    def test_admin_can_view(self):
        admin = self.factory.makeAdministrator()
        with person_logged_in(admin):
            results = self.archive_set.checkViewPermission(
                [
                    self.public_archive,
                    self.public_disabled_archive,
                    self.private_archive,
                ],
                admin,
            )
        self.assertDictEqual(
            results,
            {
                self.public_archive: True,
                self.public_disabled_archive: True,
                self.private_archive: True,
            },
        )
        comm_admin = self.factory.makeCommercialAdmin()
        with person_logged_in(comm_admin):
            results = self.archive_set.checkViewPermission(
                [
                    self.public_archive,
                    self.public_disabled_archive,
                    self.private_archive,
                ],
                comm_admin,
            )
        self.assertDictEqual(
            results,
            {
                self.public_archive: True,
                self.public_disabled_archive: True,
                self.private_archive: True,
            },
        )

    def test_registry_experts(self):
        registry_expert = self.factory.makeRegistryExpert()
        with person_logged_in(registry_expert):
            results = self.archive_set.checkViewPermission(
                [
                    self.public_archive,
                    self.public_disabled_archive,
                    self.private_archive,
                ],
                registry_expert,
            )
        self.assertDictEqual(
            results,
            {
                self.public_archive: True,
                self.public_disabled_archive: True,
                self.private_archive: False,
            },
        )

    def test_owner(self):
        owner = self.factory.makePerson()
        enabled_archive = self.factory.makeArchive(
            owner=owner, private=False, enabled=True
        )
        disabled_archive = self.factory.makeArchive(
            owner=owner, private=False, enabled=False
        )
        with person_logged_in(owner):
            results = self.archive_set.checkViewPermission(
                [
                    enabled_archive,
                    disabled_archive,
                ],
                owner,
            )
        self.assertDictEqual(
            results,
            {
                enabled_archive: True,
                disabled_archive: True,
            },
        )

    def test_team_owner(self):
        team_member = self.factory.makePerson()
        team = self.factory.makeTeam(members=[team_member])
        enabled_archive = self.factory.makeArchive(
            owner=team, private=False, enabled=True
        )
        disabled_archive = self.factory.makeArchive(
            owner=team, private=False, enabled=False
        )
        with person_logged_in(team_member):
            results = self.archive_set.checkViewPermission(
                [
                    enabled_archive,
                    disabled_archive,
                ],
                team_member,
            )
        self.assertDictEqual(
            results,
            {
                enabled_archive: True,
                disabled_archive: True,
            },
        )

    def test_query_count(self):
        archives = [self.factory.makeArchive(private=False) for _ in range(10)]
        somebody = self.factory.makePerson()
        with StormStatementRecorder() as recorder1:
            self.archive_set.checkViewPermission(archives[:5], somebody)
        with StormStatementRecorder() as recorder2:
            self.archive_set.checkViewPermission(archives, somebody)
        self.assertThat(recorder2, HasQueryCount.byEquality(recorder1))


class TestDisplayName(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_default(self):
        # If 'displayname' is omitted when creating the archive, there is a
        # sensible default.
        archive = self.factory.makeArchive(name="test-ppa")
        self.assertEqual(
            "PPA named test-ppa for %s" % archive.owner.displayname,
            archive.displayname,
        )

    def test_provided(self):
        # If 'displayname' is provided, it is used.
        archive = self.factory.makeArchive(
            purpose=ArchivePurpose.COPY,
            displayname="Rock and roll with rebuilds!",
            name="test-rebuild",
        )
        self.assertEqual("Rock and roll with rebuilds!", archive.displayname)

    def test_editable(self):
        # Anyone with edit permission on the archive can change displayname.
        archive = self.factory.makeArchive(name="test-ppa")
        login("no-priv@canonical.com")
        e = self.assertRaises(
            Unauthorized, setattr, archive, "displayname", "No-way!"
        )
        self.assertEqual("launchpad.Edit", e.args[2])
        with person_logged_in(archive.owner):
            archive.displayname = "My testing packages"


class TestAuthorizedSize(TestCaseWithFactory):
    """Tests for Archive.authorized_size"""

    layer = DatabaseFunctionalLayer

    def test_editable(self):
        archive = self.factory.makeArchive(name="test-ppa")
        self.assertEqual(8192, archive.authorized_size)

        # unprivileged person cannot edit `authorized_size`
        login("no-priv@canonical.com")
        self.assertRaises(
            Unauthorized, setattr, archive, "authorized_size", 1234
        )

        # launchpad developers can edit `authorized_size`
        with celebrity_logged_in("launchpad_developers"):
            archive.authorized_size *= 2
        self.assertEqual(16384, archive.authorized_size)


class TestPrivate(TestCaseWithFactory):
    """Tests for Archive.private"""

    layer = DatabaseFunctionalLayer

    def test_editable(self):
        archive = self.factory.makeArchive(name="test-ppa")
        self.assertEqual(False, archive.private)

        # unprivileged person cannot edit `private`
        login("no-priv@canonical.com")
        self.assertRaises(Unauthorized, setattr, archive, "private", True)

        # launchpad developers can edit `private`
        with celebrity_logged_in("launchpad_developers"):
            archive.private = True
        self.assertEqual(True, archive.private)


class TestPublishingMethod(TestCaseWithFactory):
    """Tests for Archive.publishing_method"""

    layer = DatabaseFunctionalLayer

    def test_editable(self):
        archive = self.factory.makeArchive(name="test-ppa")
        self.assertEqual(
            ArchivePublishingMethod.LOCAL, archive.publishing_method
        )

        # unprivileged person cannot edit `publishing_method`
        login("no-priv@canonical.com")
        self.assertRaises(
            Unauthorized,
            setattr,
            archive,
            "publishing_method",
            ArchivePublishingMethod.ARTIFACTORY,
        )

        # launchpad developers can edit `publishing_method`
        with celebrity_logged_in("launchpad_developers"):
            archive.publishing_method = ArchivePublishingMethod.ARTIFACTORY
        self.assertEqual(
            ArchivePublishingMethod.ARTIFACTORY, archive.publishing_method
        )


class TestRepositoryFormat(TestCaseWithFactory):
    """Tests for Archive.repository_format"""

    layer = DatabaseFunctionalLayer

    def test_editable(self):
        archive = self.factory.makeArchive(name="test-ppa")
        self.assertEqual(
            ArchiveRepositoryFormat.DEBIAN, archive.repository_format
        )

        # unprivileged person cannot edit `repository_format`
        login("no-priv@canonical.com")
        self.assertRaises(
            Unauthorized,
            setattr,
            archive,
            "repository_format",
            ArchiveRepositoryFormat.PYTHON,
        )

        # launchpad developers can edit `repository_format`
        with celebrity_logged_in("launchpad_developers"):
            archive.repository_format = ArchiveRepositoryFormat.PYTHON
        self.assertEqual(
            ArchiveRepositoryFormat.PYTHON, archive.repository_format
        )


class TestSigningKeyPropagation(TestCaseWithFactory):
    """Signing keys are shared between PPAs owned by the same person/team."""

    layer = DatabaseFunctionalLayer

    def test_ppa_created_with_no_signing_key(self):
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertIsNone(ppa.signing_key_fingerprint)

    def test_default_signing_key_propagated_to_new_ppa(self):
        person = self.factory.makePerson()
        ppa = self.factory.makeArchive(
            owner=person, purpose=ArchivePurpose.PPA, name="ppa"
        )
        self.assertEqual(ppa, person.archive)
        self.factory.makeGPGKey(person)
        key = person.gpg_keys[0]
        removeSecurityProxy(person.archive).signing_key_owner = key.owner
        removeSecurityProxy(person.archive).signing_key_fingerprint = (
            key.fingerprint
        )
        del get_property_cache(person.archive).signing_key
        ppa_with_key = self.factory.makeArchive(
            owner=person, purpose=ArchivePurpose.PPA
        )
        self.assertEqual(person.gpg_keys[0], ppa_with_key.signing_key)

    def test_secure_default_signing_key_propagated_to_new_ppa(self):
        # When a default PPA has more than one signing key, for example during
        # the 1024-bit RSA signing key to 4096-bit RSA signing key migration,
        # only the secure key is propagated to the new PPAs of the same
        # person.
        person = self.factory.makePerson()
        default_ppa = self.factory.makeArchive(
            owner=person, purpose=ArchivePurpose.PPA, name="ppa"
        )
        self.assertEqual(default_ppa, person.archive)
        fingerprint_1024R = self.factory.getUniqueHexString(digits=40).upper()
        signing_key_1024R = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=fingerprint_1024R
        )
        self.factory.makeGPGKey(
            owner=person,
            keyid=fingerprint_1024R[-8:],
            fingerprint=fingerprint_1024R,
            keysize=1024,
        )
        removeSecurityProxy(person.archive).signing_key_owner = person
        removeSecurityProxy(person.archive).signing_key_fingerprint = (
            fingerprint_1024R
        )
        del get_property_cache(person.archive).signing_key
        getUtility(IArchiveSigningKeySet).create(
            default_ppa,
            None,
            signing_key_1024R,
        )
        fingerprint_4096R = self.factory.getUniqueHexString(digits=40).upper()
        signing_key_4096R = self.factory.makeSigningKey(
            key_type=SigningKeyType.OPENPGP, fingerprint=fingerprint_4096R
        )
        self.factory.makeGPGKey(
            owner=person,
            keyid=fingerprint_4096R[-8:],
            fingerprint=fingerprint_4096R,
            keysize=4096,
        )
        getUtility(IArchiveSigningKeySet).create(
            default_ppa,
            None,
            signing_key_4096R,
        )
        another_ppa = self.factory.makeArchive(
            owner=person, purpose=ArchivePurpose.PPA
        )
        self.assertEqual(
            another_ppa.signing_key_fingerprint, fingerprint_4096R
        )


class TestGetSigningKeyData(TestCaseWithFactory):
    """Test `Archive.getSigningKeyData`.

    We just use `responses` to mock the keyserver here; the details of its
    implementation aren't especially important, we can't use
    `InProcessKeyServerFixture` because the keyserver operations are
    synchronous, and `responses` is much faster than `KeyServerTac`.
    """

    layer = DatabaseFunctionalLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=30)

    def test_getSigningKeyData_no_fingerprint(self):
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        self.assertIsNone(ppa.getSigningKeyData())

    @responses.activate
    def test_getSigningKeyData_keyserver_success(self):
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        key_path = os.path.join(gpgkeysdir, "ppa-sample@canonical.com.sec")
        gpghandler = getUtility(IGPGHandler)
        with open(key_path, "rb") as key_file:
            secret_key = gpghandler.importSecretKey(key_file.read())
        public_key = gpghandler.retrieveKey(secret_key.fingerprint)
        public_key_data = public_key.export()
        removeSecurityProxy(ppa).signing_key_fingerprint = (
            public_key.fingerprint
        )
        key_url = gpghandler.getURLForKeyInServer(
            public_key.fingerprint, action="get"
        )
        responses.add("GET", key_url, body=public_key_data)
        gpghandler.resetLocalState()
        with default_timeout(5.0):
            self.assertEqual(
                public_key_data.decode("UTF-8"), ppa.getSigningKeyData()
            )

    @responses.activate
    def test_getSigningKeyData_not_found_on_keyserver(self):
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        gpghandler = getUtility(IGPGHandler)
        removeSecurityProxy(ppa).signing_key_fingerprint = "dummy-fp"
        key_url = gpghandler.getURLForKeyInServer("dummy-fp", action="get")
        responses.add(
            "GET", key_url, status=404, body="No results found: No keys found"
        )
        with default_timeout(5.0):
            error = self.assertRaises(
                GPGKeyDoesNotExistOnServer, ppa.getSigningKeyData
            )
        error_view = create_webservice_error_view(error)
        self.assertEqual(http.client.NOT_FOUND, error_view.status)

    @responses.activate
    def test_getSigningKeyData_keyserver_failure(self):
        ppa = self.factory.makeArchive(purpose=ArchivePurpose.PPA)
        gpghandler = getUtility(IGPGHandler)
        removeSecurityProxy(ppa).signing_key_fingerprint = "dummy-fp"
        key_url = gpghandler.getURLForKeyInServer("dummy-fp", action="get")
        responses.add("GET", key_url, status=500)
        with default_timeout(5.0):
            error = self.assertRaises(
                GPGKeyTemporarilyNotFoundError, ppa.getSigningKeyData
            )
        error_view = create_webservice_error_view(error)
        self.assertEqual(http.client.INTERNAL_SERVER_ERROR, error_view.status)


class TestCountersAndSummaries(TestCaseWithFactory):
    layer = LaunchpadFunctionalLayer

    def test_cprov_build_counters_in_sampledata(self):
        cprov_archive = getUtility(IPersonSet).getByName("cprov").archive
        expected_counters = {
            "failed": 1,
            "pending": 0,
            "succeeded": 3,
            "superseded": 0,
            "total": 4,
        }
        self.assertDictEqual(
            expected_counters, cprov_archive.getBuildCounters()
        )

    def test_ubuntu_build_counters_in_sampledata(self):
        ubuntu_archive = getUtility(IDistributionSet)["ubuntu"].main_archive
        expected_counters = {
            "failed": 5,
            "pending": 2,
            "succeeded": 8,
            "superseded": 3,
            "total": 18,
        }
        self.assertDictEqual(
            expected_counters, ubuntu_archive.getBuildCounters()
        )
        # include_needsbuild=False excludes builds in status NEEDSBUILD.
        expected_counters["pending"] -= 1
        expected_counters["total"] -= 1
        self.assertDictEqual(
            expected_counters,
            ubuntu_archive.getBuildCounters(include_needsbuild=False),
        )

    def assertBuildSummaryMatches(self, status, builds, summary):
        self.assertEqual(status, summary["status"])
        self.assertContentEqual(
            builds, [build.title for build in summary["builds"]]
        )

    def test_build_summaries_in_sampledata(self):
        ubuntu = getUtility(IDistributionSet)["ubuntu"]
        firefox_source = ubuntu.getSourcePackage("mozilla-firefox")
        firefox_source_pub = firefox_source.publishing_history[0]
        foobar = ubuntu.getSourcePackage("foobar")
        foobar_pub = foobar.publishing_history[0]
        build_summaries = ubuntu.main_archive.getBuildSummariesForSourceIds(
            [firefox_source_pub.id, foobar_pub.id]
        )
        self.assertEqual(2, len(build_summaries))
        expected_firefox_builds = [
            "hppa build of mozilla-firefox 0.9 in ubuntu warty RELEASE",
            "i386 build of mozilla-firefox 0.9 in ubuntu warty RELEASE",
        ]
        self.assertBuildSummaryMatches(
            BuildSetStatus.FULLYBUILT,
            expected_firefox_builds,
            build_summaries[firefox_source_pub.id],
        )
        expected_foobar_builds = [
            "i386 build of foobar 1.0 in ubuntu warty RELEASE",
        ]
        self.assertBuildSummaryMatches(
            BuildSetStatus.FAILEDTOBUILD,
            expected_foobar_builds,
            build_summaries[foobar_pub.id],
        )

    def test_private_archives_have_private_counters_and_summaries(self):
        archive = self.factory.makeArchive()
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        with celebrity_logged_in("admin"):
            archive.private = True
            publisher = SoyuzTestPublisher()
            publisher.setUpDefaultDistroSeries(distroseries)
            publisher.addFakeChroots(distroseries)
            publisher.getPubBinaries(archive=archive)
            source_id = archive.getPublishedSources()[0].id

            # An admin can see the counters and build summaries.
            archive.getBuildCounters()["total"]
            archive.getBuildSummariesForSourceIds([source_id])

        # The archive owner can see the counters and build summaries.
        with person_logged_in(archive.owner):
            archive.getBuildCounters()["total"]
            archive.getBuildSummariesForSourceIds([source_id])

        # The public cannot.
        login("no-priv@canonical.com")
        e = self.assertRaises(
            Unauthorized, getattr, archive, "getBuildCounters"
        )
        self.assertEqual("launchpad.View", e.args[2])
        e = self.assertRaises(
            Unauthorized, getattr, archive, "getBuildSummariesForSourceIds"
        )
        self.assertEqual("launchpad.View", e.args[2])


class TestArchiveGetOverridePolicy(TestCaseWithFactory):
    """Tests for Archive.getOverridePolicy.

    These are just integration tests. The underlying policies are tested
    in lp.soyuz.adapters.tests.test_overrides.
    """

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.series = self.factory.makeDistroSeries()
        with admin_logged_in():
            self.series.nominatedarchindep = self.amd64 = (
                self.factory.makeDistroArchSeries(
                    distroseries=self.series, architecturetag="amd64"
                )
            )
            self.armhf = self.factory.makeDistroArchSeries(
                distroseries=self.series, architecturetag="armhf"
            )
        self.main = getUtility(IComponentSet)["main"]
        self.restricted = getUtility(IComponentSet)["restricted"]
        self.universe = getUtility(IComponentSet)["universe"]
        self.multiverse = getUtility(IComponentSet)["multiverse"]
        self.non_free = getUtility(IComponentSet).ensure("non-free")
        self.partner = getUtility(IComponentSet)["partner"]

    def prepareBinaries(self, archive, bpn):
        amd64_bpph = self.factory.makeBinaryPackagePublishingHistory(
            binarypackagename=bpn,
            archive=archive,
            distroarchseries=self.amd64,
            pocket=PackagePublishingPocket.PROPOSED,
            architecturespecific=True,
        )
        armhf_bpph = self.factory.makeBinaryPackagePublishingHistory(
            binarypackagename=bpn,
            archive=archive,
            distroarchseries=self.armhf,
            pocket=PackagePublishingPocket.PROPOSED,
            architecturespecific=True,
        )
        amd64_override = BinaryOverride(
            component=amd64_bpph.component,
            section=amd64_bpph.section,
            priority=amd64_bpph.priority,
            version=amd64_bpph.binarypackagerelease.version,
            new=False,
        )
        armhf_override = BinaryOverride(
            component=armhf_bpph.component,
            section=armhf_bpph.section,
            priority=armhf_bpph.priority,
            version=armhf_bpph.binarypackagerelease.version,
            new=False,
        )
        return (amd64_override, armhf_override, amd64_bpph, armhf_bpph)

    def test_primary_sources(self):
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=self.series.main_archive,
            distroseries=self.series,
            pocket=PackagePublishingPocket.UPDATES,
        )
        policy = self.series.main_archive.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        existing_spn = spph.sourcepackagerelease.sourcepackagename
        main_spn = self.factory.makeSourcePackageName()
        non_free_spn = self.factory.makeSourcePackageName()

        # Packages with an existing publication in any pocket return
        # that publication's overrides. Otherwise they're new, with a
        # default component mapped from their original component.
        self.assertEqual(
            {
                existing_spn: SourceOverride(
                    component=spph.component,
                    section=spph.section,
                    version=spph.sourcepackagerelease.version,
                    new=False,
                ),
                main_spn: SourceOverride(component=self.universe, new=True),
                non_free_spn: SourceOverride(
                    component=self.multiverse, new=True
                ),
            },
            policy.calculateSourceOverrides(
                {
                    existing_spn: SourceOverride(component=self.non_free),
                    main_spn: SourceOverride(component=self.main),
                    non_free_spn: SourceOverride(component=self.non_free),
                }
            ),
        )

    def test_primary_sources_deleted(self):
        person = self.series.main_archive.owner
        spn = self.factory.makeSourcePackageName()
        spph1 = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=spn,
            archive=self.series.main_archive,
            distroseries=self.series,
            pocket=PackagePublishingPocket.PROPOSED,
        )
        spph2 = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=spn,
            archive=self.series.main_archive,
            distroseries=self.series,
            pocket=PackagePublishingPocket.PROPOSED,
        )
        policy = self.series.main_archive.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        # The latest of the active publications is taken.
        self.assertEqual(
            {
                spn: SourceOverride(
                    component=spph2.component,
                    section=spph2.section,
                    version=spph2.sourcepackagerelease.version,
                    new=False,
                )
            },
            policy.calculateSourceOverrides({spn: SourceOverride()}),
        )

        # If we set the latest to Deleted, the next most recent active
        # one is used.
        with person_logged_in(person):
            spph2.requestDeletion(person)
        self.assertEqual(
            {
                spn: SourceOverride(
                    component=spph1.component,
                    section=spph1.section,
                    version=spph1.sourcepackagerelease.version,
                    new=False,
                )
            },
            policy.calculateSourceOverrides({spn: SourceOverride()}),
        )

        # But if they're all Deleted, we use the most recent Deleted one
        # and throw the package into NEW. Resurrections should default
        # to the old overrides but still require manual approval.
        with person_logged_in(person):
            spph1.requestDeletion(person)
        self.assertEqual(
            {
                spn: SourceOverride(
                    component=spph2.component,
                    section=spph2.section,
                    version=spph2.sourcepackagerelease.version,
                    new=True,
                )
            },
            policy.calculateSourceOverrides({spn: SourceOverride()}),
        )

    def test_primary_binaries(self):
        existing_bpn = self.factory.makeBinaryPackageName()
        other_bpn = self.factory.makeBinaryPackageName()
        amd64_override, armhf_override, _, _ = self.prepareBinaries(
            self.series.main_archive, existing_bpn
        )
        policy = self.series.main_archive.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        # Packages with an existing publication in any pocket of any DAS
        # with a matching archtag, or nominatedarchindep if the archtag
        # is None, return that publication's overrides. Otherwise
        # they're new, with a default component mapped from their
        # original component.
        self.assertEqual(
            {
                (existing_bpn, "amd64"): amd64_override,
                (existing_bpn, None): amd64_override,
                (existing_bpn, "i386"): armhf_override,
                (other_bpn, "amd64"): BinaryOverride(
                    component=self.universe, new=True
                ),
                (other_bpn, "i386"): BinaryOverride(
                    component=self.restricted, new=True
                ),
            },
            policy.calculateBinaryOverrides(
                {
                    (existing_bpn, "amd64"): BinaryOverride(
                        component=self.main
                    ),
                    (existing_bpn, None): BinaryOverride(component=self.main),
                    (existing_bpn, "i386"): BinaryOverride(
                        component=self.main
                    ),
                    (other_bpn, "amd64"): BinaryOverride(component=self.main),
                    (other_bpn, "i386"): BinaryOverride(
                        component=self.non_free,
                        source_override=SourceOverride(
                            component=self.restricted
                        ),
                    ),
                }
            ),
        )

    def test_primary_binaries_deleted(self):
        person = self.series.main_archive.owner
        bpn = self.factory.makeBinaryPackageName()
        amd64_over, armhf_over, amd64_pub, armhf_pub = self.prepareBinaries(
            self.series.main_archive, bpn
        )
        policy = self.series.main_archive.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        # The latest of the active publications for the architecture is
        # taken.
        self.assertEqual(
            {
                (bpn, "armhf"): BinaryOverride(
                    component=armhf_pub.component,
                    section=armhf_pub.section,
                    priority=armhf_pub.priority,
                    version=armhf_pub.binarypackagerelease.version,
                    new=False,
                )
            },
            policy.calculateBinaryOverrides(
                {(bpn, "armhf"): BinaryOverride()}
            ),
        )

        # If there are no active publications for the architecture,
        # another architecture's most recent active is used.
        with person_logged_in(person):
            armhf_pub.requestDeletion(person)
        self.assertEqual(
            {
                (bpn, "armhf"): BinaryOverride(
                    component=amd64_pub.component,
                    section=amd64_pub.section,
                    priority=amd64_pub.priority,
                    version=amd64_pub.binarypackagerelease.version,
                    new=False,
                )
            },
            policy.calculateBinaryOverrides(
                {(bpn, "armhf"): BinaryOverride()}
            ),
        )

        # But once there are no active publications for any
        # architecture, a Deleted one in a matching arch is used and the
        # package is thrown into NEW.
        with person_logged_in(person):
            amd64_pub.requestDeletion(person)
        self.assertEqual(
            {
                (bpn, "armhf"): BinaryOverride(
                    component=armhf_pub.component,
                    section=armhf_pub.section,
                    priority=armhf_pub.priority,
                    version=armhf_pub.binarypackagerelease.version,
                    new=True,
                )
            },
            policy.calculateBinaryOverrides(
                {(bpn, "armhf"): BinaryOverride()}
            ),
        )

    def test_primary_inherit_from_parent(self):
        dsp = self.factory.makeDistroSeriesParent(inherit_overrides=False)
        child = dsp.derived_series
        parent = dsp.parent_series
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=parent.main_archive, distroseries=parent
        )

        overrides = child.main_archive.getOverridePolicy(
            child, None
        ).calculateSourceOverrides({spph.sourcepackagename: SourceOverride()})
        self.assertNotEqual(
            spph.component, overrides[spph.sourcepackagename].component
        )

        with admin_logged_in():
            child.inherit_overrides_from_parents = True
        overrides = child.main_archive.getOverridePolicy(
            child, None
        ).calculateSourceOverrides({spph.sourcepackagename: SourceOverride()})
        self.assertEqual(
            spph.component, overrides[spph.sourcepackagename].component
        )

    def test_ppa_sources(self):
        ppa = self.factory.makeArchive(
            distribution=self.series.distribution, purpose=ArchivePurpose.PPA
        )
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=ppa, distroseries=self.series
        )
        policy = ppa.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        existing_spn = spph.sourcepackagerelease.sourcepackagename
        main_spn = self.factory.makeSourcePackageName()
        non_free_spn = self.factory.makeSourcePackageName()

        # PPA packages are always overridden to main, with no
        # examination of existing publications or assertions about
        # newness.
        self.assertEqual(
            {
                existing_spn: SourceOverride(component=self.main),
                main_spn: SourceOverride(component=self.main),
                non_free_spn: SourceOverride(component=self.main),
            },
            policy.calculateSourceOverrides(
                {
                    existing_spn: SourceOverride(component=self.non_free),
                    main_spn: SourceOverride(component=self.main),
                    non_free_spn: SourceOverride(component=self.non_free),
                }
            ),
        )

    def test_ppa_binaries(self):
        ppa = self.factory.makeArchive(
            distribution=self.series.distribution, purpose=ArchivePurpose.PPA
        )
        existing_bpn = self.factory.makeBinaryPackageName()
        other_bpn = self.factory.makeBinaryPackageName()
        amd64_override, armhf_override, _, _ = self.prepareBinaries(
            ppa, existing_bpn
        )
        policy = ppa.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        # PPA packages are always overridden to main, with no
        # examination of existing publications or assertions about
        # newness.
        self.assertEqual(
            {
                (existing_bpn, "amd64"): BinaryOverride(component=self.main),
                (existing_bpn, None): BinaryOverride(component=self.main),
                (existing_bpn, "i386"): BinaryOverride(component=self.main),
                (other_bpn, "amd64"): BinaryOverride(component=self.main),
            },
            policy.calculateBinaryOverrides(
                {
                    (existing_bpn, "amd64"): BinaryOverride(
                        component=self.main
                    ),
                    (existing_bpn, None): BinaryOverride(component=self.main),
                    (existing_bpn, "i386"): BinaryOverride(
                        component=self.main
                    ),
                    (other_bpn, "amd64"): BinaryOverride(
                        component=self.non_free
                    ),
                }
            ),
        )

    def test_partner_sources(self):
        partner = self.factory.makeArchive(
            distribution=self.series.distribution,
            purpose=ArchivePurpose.PARTNER,
        )
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=partner,
            distroseries=self.series,
            pocket=PackagePublishingPocket.RELEASE,
        )
        policy = partner.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        existing_spn = spph.sourcepackagerelease.sourcepackagename
        universe_spn = self.factory.makeSourcePackageName()

        # Packages with an existing publication in any pocket return
        # that publication's overrides. Otherwise they're new, with a
        # default component of partner.
        self.assertEqual(
            {
                existing_spn: SourceOverride(
                    component=spph.component,
                    section=spph.section,
                    version=spph.sourcepackagerelease.version,
                    new=False,
                ),
                universe_spn: SourceOverride(component=self.partner, new=True),
            },
            policy.calculateSourceOverrides(
                {
                    existing_spn: SourceOverride(component=self.non_free),
                    universe_spn: SourceOverride(component=self.universe),
                }
            ),
        )

    def test_partner_binaries(self):
        partner = self.factory.makeArchive(
            distribution=self.series.distribution,
            purpose=ArchivePurpose.PARTNER,
        )
        existing_bpn = self.factory.makeBinaryPackageName()
        other_bpn = self.factory.makeBinaryPackageName()
        amd64_override, armhf_override, _, _ = self.prepareBinaries(
            partner, existing_bpn
        )
        policy = partner.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        # Packages with an existing publication in any pocket of any DAS
        # with a matching archtag, or nominatedarchindep if the archtag
        # is None, return that publication's overrides. Otherwise
        # they're new, with a default component of partner.
        self.assertEqual(
            {
                (existing_bpn, "amd64"): amd64_override,
                (existing_bpn, None): amd64_override,
                (existing_bpn, "i386"): armhf_override,
                (other_bpn, "amd64"): BinaryOverride(
                    component=self.partner, new=True
                ),
            },
            policy.calculateBinaryOverrides(
                {
                    (existing_bpn, "amd64"): BinaryOverride(
                        component=self.main
                    ),
                    (existing_bpn, None): BinaryOverride(component=self.main),
                    (existing_bpn, "i386"): BinaryOverride(
                        component=self.main
                    ),
                    (other_bpn, "amd64"): BinaryOverride(
                        component=self.non_free
                    ),
                }
            ),
        )

    def test_copy_sources(self):
        copy = self.factory.makeArchive(
            distribution=self.series.distribution, purpose=ArchivePurpose.COPY
        )
        spph = self.factory.makeSourcePackagePublishingHistory(
            archive=self.series.main_archive,
            distroseries=self.series,
            pocket=PackagePublishingPocket.UPDATES,
        )
        policy = copy.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        existing_spn = spph.sourcepackagerelease.sourcepackagename
        main_spn = self.factory.makeSourcePackageName()
        non_free_spn = self.factory.makeSourcePackageName()

        # Packages with an existing publication in any pocket in the
        # copy archive's distribution's primary archive return that
        # publication's overrides. Otherwise they're new, with a default
        # component mapped from their original component.
        self.assertEqual(
            {
                existing_spn: SourceOverride(
                    component=spph.component,
                    section=spph.section,
                    version=spph.sourcepackagerelease.version,
                    new=False,
                ),
                main_spn: SourceOverride(component=self.universe, new=True),
                non_free_spn: SourceOverride(
                    component=self.multiverse, new=True
                ),
            },
            policy.calculateSourceOverrides(
                {
                    existing_spn: SourceOverride(component=self.non_free),
                    main_spn: SourceOverride(component=self.main),
                    non_free_spn: SourceOverride(component=self.non_free),
                }
            ),
        )

    def test_copy_binaries(self):
        existing_bpn = self.factory.makeBinaryPackageName()
        other_bpn = self.factory.makeBinaryPackageName()
        amd64_override, armhf_override, _, _ = self.prepareBinaries(
            self.series.main_archive, existing_bpn
        )
        copy = self.factory.makeArchive(
            distribution=self.series.distribution, purpose=ArchivePurpose.COPY
        )
        policy = copy.getOverridePolicy(
            self.series, PackagePublishingPocket.RELEASE
        )

        # Packages with an existing publication in any pocket of any DAS
        # with a matching archtag, or nominatedarchindep if the archtag
        # is None, in the copy archive's distribution's main archive
        # return that publication's overrides. Otherwise they're new,
        # with a default component mapped from their original component.
        self.assertEqual(
            {
                (existing_bpn, "amd64"): amd64_override,
                (existing_bpn, None): amd64_override,
                (existing_bpn, "i386"): armhf_override,
                (other_bpn, "amd64"): BinaryOverride(
                    component=self.universe, new=True
                ),
            },
            policy.calculateBinaryOverrides(
                {
                    (existing_bpn, "amd64"): BinaryOverride(
                        component=self.main
                    ),
                    (existing_bpn, None): BinaryOverride(component=self.main),
                    (existing_bpn, "i386"): BinaryOverride(
                        component=self.main
                    ),
                    (other_bpn, "amd64"): BinaryOverride(component=self.main),
                }
            ),
        )


class TestMarkSuiteDirty(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_default_is_none(self):
        archive = self.factory.makeArchive()
        self.assertIsNone(archive.dirty_suites)

    def test_unprivileged_disallowed(self):
        archive = self.factory.makeArchive()
        self.assertRaises(Unauthorized, getattr, archive, "markSuiteDirty")

    def test_primary_archive_uploader_disallowed(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        person = self.factory.makePerson()
        with person_logged_in(archive.distribution.owner):
            archive.newComponentUploader(person, "main")
        with person_logged_in(person):
            self.assertRaises(Unauthorized, getattr, archive, "markSuiteDirty")

    def test_primary_archive_owner_allowed(self):
        archive = self.factory.makeArchive(purpose=ArchivePurpose.PRIMARY)
        # Simulate Ubuntu's situation where the primary archive is owned by
        # an archive admin team while the distribution is owned by the
        # technical board, allowing us to tell the difference between
        # permissions granted to the archive owner vs. the distribution
        # owner.
        with person_logged_in(archive.distribution.owner):
            archive.distribution.owner = getUtility(
                ILaunchpadCelebrities
            ).ubuntu_techboard
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        with person_logged_in(archive.owner):
            archive.markSuiteDirty(
                distroseries, PackagePublishingPocket.UPDATES
            )
        self.assertEqual(
            ["%s-updates" % distroseries.name], archive.dirty_suites
        )

    def test_first_suite(self):
        archive = self.factory.makeArchive()
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        with person_logged_in(archive.owner):
            archive.markSuiteDirty(
                distroseries, PackagePublishingPocket.UPDATES
            )
        self.assertEqual(
            ["%s-updates" % distroseries.name], archive.dirty_suites
        )

    def test_already_dirty(self):
        archive = self.factory.makeArchive()
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        with person_logged_in(archive.owner):
            archive.markSuiteDirty(
                distroseries, PackagePublishingPocket.UPDATES
            )
            archive.markSuiteDirty(
                distroseries, PackagePublishingPocket.UPDATES
            )
        self.assertEqual(
            ["%s-updates" % distroseries.name], archive.dirty_suites
        )

    def test_second_suite(self):
        archive = self.factory.makeArchive()
        distroseries = self.factory.makeDistroSeries(
            distribution=archive.distribution
        )
        with person_logged_in(archive.owner):
            archive.markSuiteDirty(
                distroseries, PackagePublishingPocket.UPDATES
            )
            archive.markSuiteDirty(
                distroseries, PackagePublishingPocket.RELEASE
            )
        self.assertContentEqual(
            ["%s-updates" % distroseries.name, distroseries.name],
            archive.dirty_suites,
        )


class TestArchivePermissions(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_archive_owner_does_not_have_admin(self):
        archive = self.factory.makeArchive()
        login_person(archive.owner)
        self.assertFalse(check_permission("launchpad.Admin", archive))

    def test_archive_launchpad_ppa_admins_have_admin(self):
        archive = self.factory.makeArchive()
        login_celebrity("ppa_admin")
        self.assertTrue(check_permission("launchpad.Admin", archive))

    def test_archive_commercial_admin_have_admin(self):
        archive = self.factory.makeArchive()
        login_celebrity("commercial_admin")
        self.assertTrue(check_permission("launchpad.Admin", archive))

    def test_launchpad_ppa_self_admins_no_admin_for_other_archives(self):
        archive = self.factory.makeArchive()
        # archive owner is not part of `ppa_self_admins`
        login_celebrity("ppa_self_admins")
        self.assertFalse(check_permission("launchpad.Admin", archive))

    def test_launchpad_ppa_self_admins_have_admin_for_own_archives(self):
        celeb = getUtility(ILaunchpadCelebrities).ppa_self_admins
        owner = self.factory.makePerson(member_of=[celeb])
        archive = self.factory.makeArchive(owner=owner)
        login_person(archive.owner)
        self.assertTrue(check_permission("launchpad.Admin", archive))


class TestArchiveMetadataOverrides(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.default_metadata_overrides = {
            "Origin": "default_origin",
            "Label": "default_label",
            "Suite": "default_suite",
            "Snapshots": "default_snapshots",
        }

    def create_archive(self, owner=None, private=False, primary=False):
        if primary:
            distribution = self.factory.makeDistribution(owner=owner)
            archive = self.factory.makeArchive(
                owner=owner,
                distribution=distribution,
                purpose=ArchivePurpose.PRIMARY,
            )
            with celebrity_logged_in("admin"):
                archive.setMetadataOverrides(self.default_metadata_overrides)
            return archive

        return self.factory.makeArchive(
            owner=owner,
            private=private,
            metadata_overrides=self.default_metadata_overrides,
        )

    def test_cannot_set_invalid_metadata_keys(self):
        owner = self.factory.makePerson()
        archive = self.create_archive(owner=owner)
        login_person(owner)
        self.assertRaises(
            CannotSetMetadataOverrides,
            archive.setMetadataOverrides,
            {"Invalid": "test_invalid"},
        )

    def test_cannot_set_non_string_values_for_metadata(self):
        owner = self.factory.makePerson()
        archive = self.create_archive(owner=owner)
        login_person(owner)
        invalid_values = ["", None, True, 1, [], {}]
        for value in invalid_values:
            self.assertRaises(
                CannotSetMetadataOverrides,
                archive.setMetadataOverrides,
                {"Origin": value},
            )

    def test_anonymous_can_view_public_archive_metadata_overrides(self):
        archive = self.create_archive()
        login(ANONYMOUS)
        self.assertEqual(
            archive.metadata_overrides,
            self.default_metadata_overrides,
        )

    def test_non_owner_can_view_public_archive_metadata_overrides(self):
        user = self.factory.makePerson()
        archive = self.create_archive()
        login_person(user)
        self.assertEqual(
            archive.metadata_overrides,
            self.default_metadata_overrides,
        )

    def test_owner_can_view_own_public_archive_metadata_overrides(self):
        owner = self.factory.makePerson()
        archive = self.create_archive(owner=owner)
        login_person(owner)
        self.assertEqual(
            archive.metadata_overrides,
            self.default_metadata_overrides,
        )

    def test_admin_can_view_metadata_overrides_of_any_public_archive(self):
        archive = self.create_archive()
        login_celebrity("admin")
        self.assertEqual(
            archive.metadata_overrides,
            self.default_metadata_overrides,
        )

    def test_owner_can_view_own_private_archive_metadata_overrides(self):
        owner = self.factory.makePerson()
        private_archive = self.create_archive(owner=owner, private=True)
        login_person(owner)
        self.assertEqual(
            private_archive.metadata_overrides,
            self.default_metadata_overrides,
        )

    def test_admin_can_view_metadata_overrides_of_any_private_archive(self):
        private_archive = self.create_archive(private=True)
        login_celebrity("admin")
        self.assertEqual(
            private_archive.metadata_overrides,
            self.default_metadata_overrides,
        )

    def test_anonymous_cannot_view_private_archive_metadata_overrides(self):
        private_archive = self.create_archive(private=True)
        login(ANONYMOUS)
        self.assertRaises(
            Unauthorized, getattr, private_archive, "metadata_overrides"
        )

    def test_non_owner_cannot_view_private_archive_metadata_overrides(self):
        owner = self.factory.makePerson()
        user = self.factory.makePerson()
        private_archive = self.create_archive(owner=owner, private=True)
        login_person(user)
        self.assertRaises(
            Unauthorized, getattr, private_archive, "metadata_overrides"
        )

    def test_subscriber_cannot_view_private_archive_metadata_overrides(self):
        owner = self.factory.makePerson()
        user = self.factory.makePerson()
        private_archive = self.create_archive(owner=owner, private=True)
        with person_logged_in(owner):
            private_archive.newSubscription(user, owner)
        login_person(user)
        self.assertRaises(
            Unauthorized, getattr, private_archive, "metadata_overrides"
        )

    def test_owner_can_set_metadata_overrides_on_own_public_archive(self):
        owner = self.factory.makePerson()
        login_person(owner)
        archive = self.create_archive(owner=owner)
        self.assertEqual(
            archive.metadata_overrides, self.default_metadata_overrides
        )
        overrides = {"Origin": "test_origin"}
        archive.setMetadataOverrides(overrides)
        self.assertEqual(archive.metadata_overrides, overrides)

    def test_admin_can_set_metadata_overrides_on_any_public_archive(self):
        archive = self.create_archive()
        login_celebrity("admin")
        self.assertEqual(
            archive.metadata_overrides, self.default_metadata_overrides
        )
        overrides = {"Origin": "test_origin"}
        archive.setMetadataOverrides(overrides)
        self.assertEqual(archive.metadata_overrides, overrides)

    def test_anonymous_cannot_set_metadata_overrides_on_public_archive(self):
        archive = self.create_archive()
        login(ANONYMOUS)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized, lambda: archive.setMetadataOverrides(overrides)
        )

    def test_non_owner_cannot_set_metadata_overrides_on_public_archive(self):
        user = self.factory.makePerson()
        archive = self.create_archive()
        login_person(user)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized, lambda: archive.setMetadataOverrides(overrides)
        )

    def test_owner_can_set_metadata_overrides_on_private_archive(self):
        owner = self.factory.makePerson()
        login_person(owner)
        private_archive = self.create_archive(owner=owner, private=True)
        self.assertEqual(
            private_archive.metadata_overrides, self.default_metadata_overrides
        )
        overrides = {"Origin": "test_origin"}
        private_archive.setMetadataOverrides(overrides)
        self.assertEqual(private_archive.metadata_overrides, overrides)

    def test_admin_can_set_metadata_overrides_on_any_private_archive(self):
        private_archive = self.create_archive(private=True)
        login_celebrity("admin")
        self.assertEqual(
            private_archive.metadata_overrides, self.default_metadata_overrides
        )
        overrides = {"Origin": "test_origin"}
        private_archive.setMetadataOverrides(overrides)
        self.assertEqual(private_archive.metadata_overrides, overrides)

    def test_anonymous_cannot_set_metadata_overrides_on_private_archive(self):
        private_archive = self.create_archive(private=True)
        login(ANONYMOUS)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized,
            lambda: private_archive.setMetadataOverrides(overrides),
        )

    def test_non_owner_cannot_set_metadata_overrides_on_private_archive(self):
        user = self.factory.makePerson()
        private_archive = self.create_archive(private=True)
        login_person(user)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized,
            lambda: private_archive.setMetadataOverrides(overrides),
        )

    def test_subscriber_cannot_set_metadata_overrides_on_private_archive(self):
        owner = self.factory.makePerson()
        user = self.factory.makePerson()
        private_archive = self.create_archive(owner=owner, private=True)
        with person_logged_in(owner):
            private_archive.newSubscription(user, owner)
        login_person(user)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized,
            lambda: private_archive.setMetadataOverrides(overrides),
        )

    def test_owner_can_set_metadata_overrides_on_own_primary_archive(self):
        owner = self.factory.makePerson()
        primary_archive = self.create_archive(owner=owner, primary=True)
        login_person(owner)
        self.assertEqual(
            primary_archive.metadata_overrides, self.default_metadata_overrides
        )
        overrides = {"Origin": "test_origin"}
        primary_archive.setMetadataOverrides(overrides)
        self.assertEqual(primary_archive.metadata_overrides, overrides)

    def test_admin_can_set_metadata_overrides_on_any_primary_archive(self):
        primary_archive = self.create_archive(primary=True)
        login_celebrity("admin")
        self.assertEqual(
            primary_archive.metadata_overrides, self.default_metadata_overrides
        )
        overrides = {"Origin": "test_origin"}
        primary_archive.setMetadataOverrides(overrides)
        self.assertEqual(primary_archive.metadata_overrides, overrides)

    def test_anonymous_cannot_set_metadata_overrides_on_primary_archive(self):
        primary_archive = self.create_archive(primary=True)
        login(ANONYMOUS)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized,
            lambda: primary_archive.setMetadataOverrides(overrides),
        )

    def test_non_owner_cannot_set_metadata_overrides_on_primary_archive(self):
        user = self.factory.makePerson()
        primary_archive = self.create_archive(primary=True)
        login_person(user)
        overrides = {"Origin": "test_origin"}
        self.assertRaises(
            Unauthorized,
            lambda: primary_archive.setMetadataOverrides(overrides),
        )
