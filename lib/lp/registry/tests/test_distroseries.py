# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for distroseries."""

__all__ = [
    "CurrentSourceReleasesMixin",
]

import json

import transaction
from testtools.matchers import Equals
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.errors import NoSuchDistroSeries
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.registry.interfaces.externalpackage import ExternalPackageType
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.database.interfaces import IStore
from lp.services.webapp.interfaces import OAuthPermission
from lp.soyuz.enums import (
    ArchivePurpose,
    IndexCompressionType,
    PackagePublishingStatus,
)
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.component import IComponentSet
from lp.soyuz.interfaces.distributionjob import (
    IInitializeDistroSeriesJobSource,
)
from lp.soyuz.interfaces.distributionsourcepackagerelease import (
    IDistributionSourcePackageRelease,
)
from lp.soyuz.interfaces.publishing import active_publishing_status
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import (
    ANONYMOUS,
    StormStatementRecorder,
    TestCase,
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    login,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadFunctionalLayer
from lp.testing.matchers import HasQueryCount
from lp.testing.pages import webservice_for_person
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode,
)


class CurrentSourceReleasesMixin:
    """Mixin class for current source release tests.

    Used by tests of DistroSeries and Distribution.  The mixin must not extend
    TestCase or it will be run by other modules when imported.
    """

    def setUp(self):
        # Log in as an admin, so that we can create distributions.
        super().setUp()
        login("foo.bar@canonical.com")
        self.publisher = SoyuzTestPublisher()
        self.factory = self.publisher.factory
        self.development_series = self.publisher.setUpDefaultDistroSeries()
        self.distribution = self.development_series.distribution
        self.published_package = self.target.getSourcePackage(
            self.publisher.default_package_name
        )
        login(ANONYMOUS)

    def assertCurrentVersion(self, expected_version, package_name=None):
        """Assert the current version of a package is the expected one.

        It uses getCurrentSourceReleases() to get the version.

        If package_name isn't specified, the test publisher's default
        name is used.
        """
        if package_name is None:
            package_name = self.publisher.default_package_name
        package = self.target.getSourcePackage(package_name)
        releases = self.target.getCurrentSourceReleases(
            [package.sourcepackagename]
        )
        self.assertEqual(releases[package].version, expected_version)

    def test_one_release(self):
        # If there is one published version, that one will be returned.
        self.publisher.getPubSource(version="0.9")
        self.assertCurrentVersion("0.9")

    def test_return_value(self):
        # getCurrentSourceReleases() returns a dict. The corresponding
        # source package is used as the key, with
        # a DistributionSourcePackageRelease as the values.
        self.publisher.getPubSource(version="0.9")
        releases = self.target.getCurrentSourceReleases(
            [self.published_package.sourcepackagename]
        )
        self.assertTrue(self.published_package in releases)
        self.assertTrue(
            self.release_interface.providedBy(releases[self.published_package])
        )

    def test_latest_version(self):
        # If more than one version is published, the latest one is
        # returned.
        self.publisher.getPubSource(version="0.9")
        self.publisher.getPubSource(version="1.0")
        self.assertCurrentVersion("1.0")

    def test_active_publishing_status(self):
        # Every status defined in active_publishing_status is considered
        # when checking for the current release.
        self.publisher.getPubSource(version="0.9")
        for minor_version, status in enumerate(active_publishing_status):
            latest_version = "1.%s" % minor_version
            self.publisher.getPubSource(version=latest_version, status=status)
            self.assertCurrentVersion(latest_version)

    def test_not_active_publishing_status(self):
        # Every status not defined in active_publishing_status is
        # ignored when checking for the current release.
        self.publisher.getPubSource(version="0.9")
        for minor_version, status in enumerate(PackagePublishingStatus.items):
            if status in active_publishing_status:
                continue
            self.publisher.getPubSource(
                version="1.%s" % minor_version, status=status
            )
            self.assertCurrentVersion("0.9")

    def test_ignore_other_package_names(self):
        # Packages with different names don't affect the returned
        # version.
        self.publisher.getPubSource(version="0.9", sourcename="foo")
        self.publisher.getPubSource(version="1.0", sourcename="bar")
        self.assertCurrentVersion("0.9", package_name="foo")

    def ignore_other_distributions(self):
        # Packages with the same name in other distributions don't
        # affect the returned version.
        series_in_other_distribution = self.factory.makeDistroSeries()
        self.publisher.getPubSource(version="0.9")
        self.publisher.getPubSource(
            version="1.0", distroseries=series_in_other_distribution
        )
        self.assertCurrentVersion("0.9")

    def test_ignore_ppa(self):
        # PPA packages having the same name don't affect the returned
        # version.
        ppa_uploader = self.factory.makePerson()
        ppa_archive = getUtility(IArchiveSet).new(
            purpose=ArchivePurpose.PPA,
            owner=ppa_uploader,
            distribution=self.distribution,
        )
        self.publisher.getPubSource(version="0.9")
        self.publisher.getPubSource(version="1.0", archive=ppa_archive)
        self.assertCurrentVersion("0.9")

    def test_get_multiple(self):
        # getCurrentSourceReleases() allows you to get information about
        # the current release for multiple packages at the same time.
        # This is done using a single DB query, making it more efficient
        # than using IDistributionSource.currentrelease.
        self.publisher.getPubSource(version="0.9", sourcename="foo")
        self.publisher.getPubSource(version="1.0", sourcename="bar")
        foo_package = self.distribution.getSourcePackage("foo")
        bar_package = self.distribution.getSourcePackage("bar")
        releases = self.distribution.getCurrentSourceReleases(
            [foo_package.sourcepackagename, bar_package.sourcepackagename]
        )
        self.assertEqual(releases[foo_package].version, "0.9")
        self.assertEqual(releases[bar_package].version, "1.0")


class TestDistroSeriesCurrentSourceReleases(
    CurrentSourceReleasesMixin, TestCase
):
    """Test for DistroSeries.getCurrentSourceReleases()."""

    layer = LaunchpadFunctionalLayer
    release_interface = IDistributionSourcePackageRelease

    @property
    def target(self):
        return self.development_series


class TestDistroSeries(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_getSuite_release_pocket(self):
        # The suite of a distro series and the release pocket is the name of
        # the distroseries.
        distroseries = self.factory.makeDistroSeries()
        self.assertEqual(
            distroseries.name,
            distroseries.getSuite(PackagePublishingPocket.RELEASE),
        )

    def test_getSuite_non_release_pocket(self):
        # The suite of a distro series and a non-release pocket is the name of
        # the distroseries followed by a hyphen and the name of the pocket in
        # lower case.
        distroseries = self.factory.makeDistroSeries()
        pocket = PackagePublishingPocket.PROPOSED
        suite = "%s-%s" % (distroseries.name, pocket.name.lower())
        self.assertEqual(suite, distroseries.getSuite(pocket))

    def test_getDistroArchSeriesByProcessor(self):
        # A IDistroArchSeries can be retrieved by processor.
        distroseries = self.factory.makeDistroSeries()
        processor = self.factory.makeProcessor()
        distroarchseries = self.factory.makeDistroArchSeries(
            distroseries=distroseries,
            architecturetag="i386",
            processor=processor,
        )
        self.assertEqual(
            distroarchseries,
            distroseries.getDistroArchSeriesByProcessor(processor),
        )

    def test_getDistroArchSeriesByProcessor_none(self):
        # getDistroArchSeriesByProcessor returns None when no distroarchseries
        # is found
        distroseries = self.factory.makeDistroSeries()
        processor = self.factory.makeProcessor()
        self.assertIs(
            None, distroseries.getDistroArchSeriesByProcessor(processor)
        )

    def test_getDerivedSeries(self):
        dsp = self.factory.makeDistroSeriesParent()
        self.assertEqual(
            [dsp.derived_series], dsp.parent_series.getDerivedSeries()
        )

    def test_registrant_owner_differ(self):
        # The registrant is the creator whereas the owner is the
        # distribution's owner.
        registrant = self.factory.makePerson()
        distroseries = self.factory.makeDistroSeries(registrant=registrant)
        self.assertEqual(distroseries.distribution.owner, distroseries.owner)
        self.assertEqual(registrant, distroseries.registrant)
        self.assertNotEqual(distroseries.registrant, distroseries.owner)

    def test_isDerivedSeries(self):
        # The series method isInitializing() returns True only if the series
        # has one or more parent series.
        distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.isDerivedSeries())
        self.factory.makeDistroSeriesParent(derived_series=distroseries)
        self.assertTrue(distroseries.isDerivedSeries())

    def test_inherit_overrides_from_parents(self):
        # inherit_overrides_from_parents is an accessor which maps to
        # all of the series' DistroSeriesParent.inherit_overrides, for
        # UI simplicity for now.
        distroseries = self.factory.makeDistroSeries()
        dsp1 = self.factory.makeDistroSeriesParent(
            derived_series=distroseries, inherit_overrides=True
        )
        dsp2 = self.factory.makeDistroSeriesParent(
            derived_series=distroseries, inherit_overrides=False
        )
        self.assertEqual(True, distroseries.inherit_overrides_from_parents)
        with person_logged_in(distroseries.distribution.owner):
            distroseries.inherit_overrides_from_parents = False
        self.assertEqual(False, dsp1.inherit_overrides)
        self.assertEqual(False, dsp2.inherit_overrides)
        self.assertEqual(False, distroseries.inherit_overrides_from_parents)
        with person_logged_in(distroseries.distribution.owner):
            distroseries.inherit_overrides_from_parents = True
        self.assertEqual(True, dsp1.inherit_overrides)
        self.assertEqual(True, dsp2.inherit_overrides)
        self.assertEqual(True, distroseries.inherit_overrides_from_parents)

    def test_isInitializing(self):
        # The series method isInitializing() returns True only if there is an
        # initialization job with a pending status attached to this series.
        distroseries = self.factory.makeDistroSeries()
        parent_distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.isInitializing())
        job_source = getUtility(IInitializeDistroSeriesJobSource)
        job = job_source.create(distroseries, [parent_distroseries.id])
        self.assertTrue(distroseries.isInitializing())
        job.start()
        self.assertTrue(distroseries.isInitializing())
        job.queue()
        self.assertTrue(distroseries.isInitializing())
        job.start()
        job.complete()
        self.assertFalse(distroseries.isInitializing())

    def test_isInitialized(self):
        # The series method isInitialized() returns True once the series has
        # been initialized.
        distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.isInitialized())
        self.factory.makeSourcePackagePublishingHistory(
            distroseries=distroseries, archive=distroseries.main_archive
        )
        self.assertTrue(distroseries.isInitialized())

    def test_getInitializationJob(self):
        # getInitializationJob() returns the most recent
        # `IInitializeDistroSeriesJob` for the given series.
        distroseries = self.factory.makeDistroSeries()
        parent_distroseries = self.factory.makeDistroSeries()
        self.assertIs(None, distroseries.getInitializationJob())
        job_source = getUtility(IInitializeDistroSeriesJobSource)
        job = job_source.create(distroseries, [parent_distroseries.id])
        self.assertEqual(job, distroseries.getInitializationJob())

    def test_getDifferenceComments_gets_DistroSeriesDifferenceComments(self):
        distroseries = self.factory.makeDistroSeries()
        dsd = self.factory.makeDistroSeriesDifference(
            derived_series=distroseries
        )
        comment = self.factory.makeDistroSeriesDifferenceComment(dsd)
        self.assertContentEqual(
            [comment], distroseries.getDifferenceComments()
        )

    def test_valid_specifications_query_count(self):
        distroseries = self.factory.makeDistroSeries()
        distribution = distroseries.distribution
        spec1 = self.factory.makeSpecification(
            distribution=distribution, goal=distroseries
        )
        spec2 = self.factory.makeSpecification(
            distribution=distribution, goal=distroseries
        )
        for _ in range(5):
            self.factory.makeSpecificationWorkItem(specification=spec1)
            self.factory.makeSpecificationWorkItem(specification=spec2)
        IStore(spec1.__class__).flush()
        IStore(spec1.__class__).invalidate()
        with StormStatementRecorder() as recorder:
            for spec in distroseries.api_valid_specifications:
                spec.workitems_text
        self.assertThat(recorder, HasQueryCount(Equals(3)))

    def test_valid_specifications_preloading_excludes_deleted_workitems(self):
        distroseries = self.factory.makeDistroSeries()
        spec = self.factory.makeSpecification(
            distribution=distroseries.distribution, goal=distroseries
        )
        self.factory.makeSpecificationWorkItem(
            specification=spec, deleted=True
        )
        self.factory.makeSpecificationWorkItem(specification=spec)
        workitems = [
            s.workitems_text for s in distroseries.api_valid_specifications
        ]
        self.assertContentEqual([spec.workitems_text], workitems)

    def test_backports_not_automatic(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.backports_not_automatic)
        with admin_logged_in():
            distroseries.backports_not_automatic = True
        self.assertTrue(distroseries.backports_not_automatic)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertTrue(
            naked_distroseries.publishing_options["backports_not_automatic"]
        )

    def test_proposed_not_automatic(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.proposed_not_automatic)
        with admin_logged_in():
            distroseries.proposed_not_automatic = True
        self.assertTrue(distroseries.proposed_not_automatic)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertTrue(
            naked_distroseries.publishing_options["proposed_not_automatic"]
        )

    def test_include_long_descriptions(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertTrue(distroseries.include_long_descriptions)
        with admin_logged_in():
            distroseries.include_long_descriptions = False
        self.assertFalse(distroseries.include_long_descriptions)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertFalse(
            naked_distroseries.publishing_options["include_long_descriptions"]
        )

    def test_index_compressors(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertEqual(
            [IndexCompressionType.GZIP, IndexCompressionType.BZIP2],
            distroseries.index_compressors,
        )
        with admin_logged_in():
            distroseries.index_compressors = [IndexCompressionType.XZ]
        self.assertEqual(
            [IndexCompressionType.XZ], distroseries.index_compressors
        )
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertEqual(
            ["xz"], naked_distroseries.publishing_options["index_compressors"]
        )

    def test_publish_by_hash(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.publish_by_hash)
        with admin_logged_in():
            distroseries.publish_by_hash = True
        self.assertTrue(distroseries.publish_by_hash)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertTrue(
            naked_distroseries.publishing_options["publish_by_hash"]
        )

    def test_advertise_by_hash(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertFalse(distroseries.advertise_by_hash)
        with admin_logged_in():
            distroseries.advertise_by_hash = True
        self.assertTrue(distroseries.advertise_by_hash)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertTrue(
            naked_distroseries.publishing_options["advertise_by_hash"]
        )

    def test_strict_supported_component_dependencies(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertTrue(distroseries.strict_supported_component_dependencies)
        with admin_logged_in():
            distroseries.strict_supported_component_dependencies = False
        self.assertFalse(distroseries.strict_supported_component_dependencies)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertFalse(
            naked_distroseries.publishing_options[
                "strict_supported_component_dependencies"
            ]
        )

    def test_publish_i18n_index(self):
        distroseries = self.factory.makeDistroSeries()
        self.assertTrue(distroseries.publish_i18n_index)
        with admin_logged_in():
            distroseries.publish_i18n_index = False
        self.assertFalse(distroseries.publish_i18n_index)
        naked_distroseries = removeSecurityProxy(distroseries)
        self.assertFalse(
            naked_distroseries.publishing_options["publish_i18n_index"]
        )

    def test_getExternalPackageSeries(self):
        # Test that we get the ExternalPackageSeries that belongs to the
        # distribution with the proper attributes
        distroseries = self.factory.makeDistroSeries()
        sourcepackagename = self.factory.getOrMakeSourcePackageName(
            "my-package"
        )
        channel = ("22.04", "candidate", "staging")
        externalpackageseries = distroseries.getExternalPackageSeries(
            name=sourcepackagename,
            packagetype=ExternalPackageType.ROCK,
            channel=channel,
        )
        self.assertEqual(externalpackageseries.distroseries, distroseries)
        self.assertEqual(externalpackageseries.name, "my-package")
        self.assertEqual(
            externalpackageseries.packagetype, ExternalPackageType.ROCK
        )
        self.assertEqual(externalpackageseries.channel, channel)

        # We can have external package series without channel
        externalpackageseries = distroseries.getExternalPackageSeries(
            name=sourcepackagename,
            packagetype=ExternalPackageType.SNAP,
            channel=None,
        )
        self.assertEqual(externalpackageseries.distroseries, distroseries)
        self.assertEqual(externalpackageseries.name, "my-package")
        self.assertEqual(
            externalpackageseries.packagetype, ExternalPackageType.SNAP
        )
        self.assertEqual(externalpackageseries.channel, None)


class TestDistroSeriesPackaging(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.series = self.factory.makeDistroSeries()
        self.user = self.series.distribution.owner
        login("admin@canonical.com")
        component_set = getUtility(IComponentSet)
        self.packages = {}
        self.main_component = component_set["main"]
        self.universe_component = component_set["universe"]
        self.makeSeriesPackage("normal")
        self.makeSeriesPackage("translatable", messages=800)
        hot_package = self.makeSeriesPackage("hot", bugs=50)
        # Create a second SPPH for 'hot', to verify that duplicates are
        # eliminated in the queries.
        self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=hot_package.sourcepackagename,
            distroseries=self.series,
            component=self.universe_component,
            section_name="web",
        )
        self.makeSeriesPackage("hot-translatable", bugs=25, messages=1000)
        self.makeSeriesPackage("main", is_main=True)
        self.makeSeriesPackage("linked")
        self.linkPackage("linked")
        transaction.commit()
        login(ANONYMOUS)

    def makeSeriesPackage(
        self,
        name=None,
        is_main=False,
        bugs=None,
        messages=None,
        is_translations=False,
        pocket=None,
        status=None,
    ):
        # Make a published source package.
        if name is None:
            name = self.factory.getUniqueString()
        if is_main:
            component = self.main_component
        else:
            component = self.universe_component
        if is_translations:
            section = "translations"
        else:
            section = "web"
        sourcepackagename = self.factory.makeSourcePackageName(name)
        spph = self.factory.makeSourcePackagePublishingHistory(
            sourcepackagename=sourcepackagename,
            distroseries=self.series,
            component=component,
            section_name=section,
            pocket=pocket,
            status=status,
        )
        source_package = self.factory.makeSourcePackage(
            sourcepackagename=sourcepackagename, distroseries=self.series
        )
        if bugs is not None:
            dsp = removeSecurityProxy(
                source_package.distribution_sourcepackage
            )
            dsp.bug_count = bugs
        if messages is not None:
            template = self.factory.makePOTemplate(
                distroseries=self.series,
                sourcepackagename=sourcepackagename,
                owner=self.user,
            )
            removeSecurityProxy(template).messagecount = messages
        spr = spph.sourcepackagerelease
        for extension in ("dsc", "tar.gz"):
            filename = "%s_%s.%s" % (spr.name, spr.version, extension)
            spr.addFile(
                self.factory.makeLibraryFileAlias(
                    filename=filename, db_only=True
                )
            )
        self.packages[name] = source_package
        return source_package

    def makeSeriesBinaryPackage(
        self,
        name=None,
        is_main=False,
        is_translations=False,
        das=None,
        pocket=None,
        status=None,
    ):
        # Make a published binary package.
        if name is None:
            name = self.factory.getUniqueString()
        source = self.makeSeriesPackage(
            name=name,
            is_main=is_main,
            is_translations=is_translations,
            pocket=pocket,
            status=status,
        )
        spr = source.distinctreleases[0]
        binarypackagename = self.factory.makeBinaryPackageName(name)
        bpph = self.factory.makeBinaryPackagePublishingHistory(
            binarypackagename=binarypackagename,
            distroarchseries=das,
            component=spr.component,
            section_name=spr.section.name,
            status=status,
            pocket=pocket,
            source_package_release=spr,
        )
        bpr = bpph.binarypackagerelease
        filename = "%s_%s_%s.deb" % (
            bpr.name,
            bpr.version,
            das.architecturetag,
        )
        bpr.addFile(
            self.factory.makeLibraryFileAlias(filename=filename, db_only=True)
        )
        return bpph

    def linkPackage(self, name):
        product_series = self.factory.makeProductSeries()
        removeSecurityProxy(product_series).setPackaging(
            self.series, self.packages[name].sourcepackagename, self.user
        )
        return product_series

    def test_getPrioritizedUnlinkedSourcePackages(self):
        # Verify the ordering of source packages that need linking.
        package_summaries = self.series.getPrioritizedUnlinkedSourcePackages()
        names = [summary["package"].name for summary in package_summaries]
        expected = [
            "main",
            "hot-translatable",
            "hot",
            "translatable",
            "normal",
        ]
        self.assertEqual(expected, names)

    def test_getPrioritizedUnlinkedSourcePackages_no_language_packs(self):
        # Verify that translations packages are not listed.
        self.makeSeriesPackage("language-pack-vi", is_translations=True)
        package_summaries = self.series.getPrioritizedUnlinkedSourcePackages()
        names = [summary["package"].name for summary in package_summaries]
        expected = [
            "main",
            "hot-translatable",
            "hot",
            "translatable",
            "normal",
        ]
        self.assertEqual(expected, names)

    def test_getPrioritizedPackagings(self):
        # Verify the ordering of packagings that need more upstream info.
        for name in ["main", "hot-translatable", "hot", "translatable"]:
            self.linkPackage(name)
        packagings = self.series.getPrioritizedPackagings()
        names = [packaging.sourcepackagename.name for packaging in packagings]
        expected = [
            "main",
            "hot-translatable",
            "hot",
            "translatable",
            "linked",
        ]
        self.assertEqual(expected, names)

    def test_getPrioritizedPackagings_bug_tracker(self):
        # Verify the ordering of packagings with and without a bug tracker.
        self.linkPackage("hot")
        self.makeSeriesPackage("cold")
        product_series = self.linkPackage("cold")
        with person_logged_in(product_series.product.owner):
            product_series.product.bugtracker = self.factory.makeBugTracker()
        packagings = self.series.getPrioritizedPackagings()
        names = [packaging.sourcepackagename.name for packaging in packagings]
        expected = ["hot", "linked", "cold"]
        self.assertEqual(expected, names)

    def test_getPrioritizedPackagings_branch(self):
        # Verify the ordering of packagings with and without a branch.
        self.linkPackage("translatable")
        self.makeSeriesPackage("withbranch")
        product_series = self.linkPackage("withbranch")
        with person_logged_in(product_series.product.owner):
            product_series.branch = self.factory.makeBranch()
        packagings = self.series.getPrioritizedPackagings()
        names = [packaging.sourcepackagename.name for packaging in packagings]
        expected = ["translatable", "linked", "withbranch"]
        self.assertEqual(expected, names)

    def test_getPrioritizedPackagings_translation(self):
        # Verify the ordering of translatable packagings that are and are not
        # configured to import.
        self.linkPackage("translatable")
        self.makeSeriesPackage("importabletranslatable")
        product_series = self.linkPackage("importabletranslatable")
        with person_logged_in(product_series.product.owner):
            product_series.branch = self.factory.makeBranch()
            product_series.translations_autoimport_mode = (
                TranslationsBranchImportMode.IMPORT_TEMPLATES
            )
        packagings = self.series.getPrioritizedPackagings()
        names = [packaging.sourcepackagename.name for packaging in packagings]
        expected = ["translatable", "linked", "importabletranslatable"]
        self.assertEqual(expected, names)


class TestDistroSeriesWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_language_pack_full_export_requested_not_translations_admin(self):
        # Somebody with only launchpad.TranslationsAdmin cannot request full
        # language pack exports.
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        self.assertFalse(distroseries.language_pack_full_export_requested)
        group = self.factory.makeTranslationGroup()
        with admin_logged_in():
            distroseries.distribution.translationgroup = group
        webservice = webservice_for_person(
            group.owner, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.patch(
            distroseries_url,
            "application/json",
            json.dumps({"language_pack_full_export_requested": True}),
        )
        self.assertEqual(401, response.status)
        self.assertFalse(distroseries.language_pack_full_export_requested)

    def test_language_pack_full_export_requested_langpacks_admin(self):
        # Somebody with launchpad.LanguagePacksAdmin can request full
        # language pack exports.
        distroseries = self.factory.makeDistroSeries()
        distroseries_url = api_url(distroseries)
        self.assertFalse(distroseries.language_pack_full_export_requested)
        person = self.factory.makePerson(
            member_of=[getUtility(ILaunchpadCelebrities).rosetta_experts]
        )
        webservice = webservice_for_person(
            person, permission=OAuthPermission.WRITE_PRIVATE
        )
        response = webservice.patch(
            distroseries_url,
            "application/json",
            json.dumps({"language_pack_full_export_requested": True}),
        )
        self.assertEqual(209, response.status)
        self.assertTrue(distroseries.language_pack_full_export_requested)

    def test_translation_template_statistics(self):
        distroseries = self.factory.makeDistroSeries()
        templates = [
            self.factory.makePOTemplate(distroseries=distroseries)
            for _ in range(3)
        ]
        removeSecurityProxy(templates[0]).messagecount = 100
        removeSecurityProxy(templates[0]).priority = 10
        removeSecurityProxy(templates[1]).iscurrent = False
        removeSecurityProxy(templates[2]).languagepack = True
        self.factory.makePOTemplate()
        distroseries_url = api_url(distroseries)
        webservice = webservice_for_person(None, default_api_version="devel")
        response = webservice.named_get(
            distroseries_url, "getTranslationTemplateStatistics"
        )
        self.assertEqual(200, response.status)
        self.assertEqual(
            [
                {
                    "sourcepackage": template.sourcepackage.name,
                    "translation_domain": template.translation_domain,
                    "template_name": template.name,
                    "total": template.messagecount,
                    "enabled": template.iscurrent,
                    "languagepack": template.languagepack,
                    "priority": template.priority,
                    "date_last_updated": (
                        template.date_last_updated.isoformat()
                    ),
                }
                for template in templates
            ],
            response.jsonBody(),
        )


class TestDistroSeriesSet(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def _get_translatables(self):
        distro_series_set = getUtility(IDistroSeriesSet)
        # Get translatables as a sequence of names of the series.
        return sorted(
            series.name for series in distro_series_set.translatables()
        )

    def _ref_translatables(self, expected=None):
        # Return the reference value, merged with expected data.
        if expected is None:
            return self.ref_translatables
        if isinstance(expected, list):
            return sorted(self.ref_translatables + expected)
        return sorted(self.ref_translatables + [expected])

    def test_translatables(self):
        # translatables() returns all distroseries that have potemplates
        # and are not set to "hide all translations".
        # See whatever distroseries sample data already has.
        self.ref_translatables = self._get_translatables()

        new_distroseries = self.factory.makeDistroSeries(name="sampleseries")
        with person_logged_in(new_distroseries.distribution.owner):
            new_distroseries.hide_all_translations = False
        transaction.commit()
        translatables = self._get_translatables()
        self.assertEqual(
            translatables,
            self._ref_translatables(),
            "A newly created distroseries should not be translatable but "
            "translatables() returns %r instead of %r."
            % (translatables, self._ref_translatables()),
        )

        new_sourcepackagename = self.factory.makeSourcePackageName()
        self.factory.makePOTemplate(
            distroseries=new_distroseries,
            sourcepackagename=new_sourcepackagename,
        )
        transaction.commit()
        translatables = self._get_translatables()
        self.assertEqual(
            translatables,
            self._ref_translatables("sampleseries"),
            "After assigning a PO template, a distroseries should be "
            "translatable but translatables() returns %r instead of %r."
            % (translatables, self._ref_translatables("sampleseries")),
        )

        with person_logged_in(new_distroseries.distribution.owner):
            new_distroseries.hide_all_translations = True
        transaction.commit()
        translatables = self._get_translatables()
        self.assertEqual(
            translatables,
            self._ref_translatables(),
            "After hiding all translation, a distroseries should not be "
            "translatable but translatables() returns %r instead of %r."
            % (translatables, self._ref_translatables()),
        )

    def test_fromSuite_release_pocket(self):
        series = self.factory.makeDistroSeries()
        result = getUtility(IDistroSeriesSet).fromSuite(
            series.distribution, series.name
        )
        self.assertEqual((series, PackagePublishingPocket.RELEASE), result)

    def test_fromSuite_non_release_pocket(self):
        series = self.factory.makeDistroSeries()
        suite = "%s-backports" % series.name
        result = getUtility(IDistroSeriesSet).fromSuite(
            series.distribution, suite
        )
        self.assertEqual((series, PackagePublishingPocket.BACKPORTS), result)

    def test_fromSuite_no_such_series(self):
        distribution = self.factory.makeDistribution()
        self.assertRaises(
            NoSuchDistroSeries,
            getUtility(IDistroSeriesSet).fromSuite,
            distribution,
            "doesntexist",
        )
