# Copyright 2010-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.processor import (
    IProcessorSet,
    ProcessorNotFound,
)
from lp.registry.interfaces.distroseriesparent import IDistroSeriesParentSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.features.testing import FeatureFixture
from lp.services.job.tests import block_on_job
from lp.soyuz.enums import SourcePackageFormat
from lp.soyuz.interfaces.distributionjob import (
    IInitializeDistroSeriesJobSource,
    InitializationCompleted,
    InitializationPending,
)
from lp.soyuz.interfaces.packageset import IPackagesetSet
from lp.soyuz.interfaces.publishing import PackagePublishingStatus
from lp.soyuz.interfaces.sourcepackageformat import (
    ISourcePackageFormatSelectionSet,
)
from lp.soyuz.model.initializedistroseriesjob import InitializeDistroSeriesJob
from lp.soyuz.scripts.initialize_distroseries import InitializationError
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory, celebrity_logged_in
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import (
    CeleryJobLayer,
    DatabaseFunctionalLayer,
    DatabaseLayer,
    LaunchpadZopelessLayer,
)
from lp.testing.script import run_script


class InitializeDistroSeriesJobTests(TestCaseWithFactory):
    """Test case for InitializeDistroSeriesJob."""

    layer = DatabaseFunctionalLayer

    @property
    def job_source(self):
        return getUtility(IInitializeDistroSeriesJobSource)

    def test_getOopsVars(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        vars = job.getOopsVars()
        naked_job = removeSecurityProxy(job)
        self.assertIn(("distribution_id", distroseries.distribution.id), vars)
        self.assertIn(("distroseries_id", distroseries.id), vars)
        self.assertIn(("distribution_job_id", naked_job.context.id), vars)
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        self.assertIn(("parent_distroseries_ids", [str(parent.id)]), vars)

    def _getJobs(self):
        """Return the pending InitializeDistroSeriesJobs as a list."""
        return list(InitializeDistroSeriesJob.iterReady())

    def _getJobCount(self):
        """Return the number of InitializeDistroSeriesJobs in the
        queue."""
        return len(self._getJobs())

    def test___repr__(self):
        parent1 = self.factory.makeDistroSeries()
        parent2 = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        packageset1 = self.factory.makePackageset()
        packageset2 = self.factory.makePackageset()

        overlays = (True, False)
        overlay_pockets = ("Updates", "Release")
        overlay_components = ("main", "universe")
        arches = ("i386", "amd64")
        archindep_archtag = "amd64"
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        packagesets = (str(packageset1.id), str(packageset2.id))
        rebuild = False

        job = self.job_source.create(
            distroseries,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent1.id), str(parent2.id)],
            arches,
            archindep_archtag,
            packagesets,
            rebuild,
            overlays,
            overlay_pockets,
            overlay_components,
        )

        expected = (
            "<InitializeDistroSeriesJob for "
            "distribution: {distroseries.distribution.name}, "
            "distroseries: {distroseries.name}, "
            "parent[overlay?/pockets/components]: "
            "{parent1.name}[True/Updates/main],"
            "{parent2.name}[False/Release/universe], "
            "architectures: {architectures}, "
            "archindep_archtag: amd64, "
            "packagesets: {packagesets}, "
            "rebuild: False>".format(
                distroseries=distroseries,
                parent1=parent1,
                parent2=parent2,
                architectures=("i386", "amd64"),
                packagesets=[packageset1.name, packageset2.name],
            )
        )
        self.assertEqual(expected, repr(job))

    def test_create_with_existing_pending_job(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # If there's already a pending InitializeDistroSeriesJob for a
        # DistroSeries, InitializeDistroSeriesJob.create() raises an
        # exception.
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        exception = self.assertRaises(
            InitializationPending,
            self.job_source.create,
            distroseries,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
        )
        self.assertEqual(job, exception.job)

    def test_create_with_existing_completed_job(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # If there's already a completed InitializeDistroSeriesJob for a
        # DistroSeries, InitializeDistroSeriesJob.create() raises an
        # exception.
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        job.start()
        job.complete()
        exception = self.assertRaises(
            InitializationCompleted,
            self.job_source.create,
            distroseries,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
        )
        self.assertEqual(job, exception.job)

    def test_create_with_existing_failed_job(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # If there's already a failed InitializeDistroSeriesJob for a
        # DistroSeries, InitializeDistroSeriesJob.create() schedules a new
        # job.
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        job.start()
        job.fail()
        self.job_source.create(distroseries, [str(parent.id)])

    def test_run_with_previous_series_already_set(self):
        # InitializationError is raised if a parent series already exists
        # for this series.
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        getUtility(IDistroSeriesParentSet).new(
            distroseries, parent, initialized=True
        )

        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        expected_message = (
            "Series {child.name} has already been initialised" "."
        ).format(child=distroseries)
        self.assertRaisesWithContent(
            InitializationError, expected_message, job.run
        )

    def test_arguments(self):
        """Test that InitializeDistroSeriesJob specified with arguments can
        be gotten out again."""
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        arches = ("i386", "amd64")
        archindep_archtag = "amd64"
        packagesets = ("1", "2", "3")
        overlays = (True,)
        overlay_pockets = ("Updates",)
        overlay_components = ("restricted",)

        job = self.job_source.create(
            distroseries,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
            arches,
            archindep_archtag,
            packagesets,
            False,
            overlays,
            overlay_pockets,
            overlay_components,
        )

        naked_job = removeSecurityProxy(job)
        self.assertEqual(naked_job.distroseries, distroseries)
        self.assertEqual(naked_job.arches, arches)
        self.assertEqual(naked_job.archindep_archtag, archindep_archtag)
        self.assertEqual(naked_job.packagesets, packagesets)
        self.assertEqual(naked_job.rebuild, False)
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        self.assertEqual(naked_job.parents, (str(parent.id),))
        self.assertEqual(naked_job.overlays, overlays)
        self.assertEqual(naked_job.overlay_pockets, overlay_pockets)
        self.assertEqual(naked_job.overlay_components, overlay_components)

    def test_parent(self):
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        naked_job = removeSecurityProxy(job)
        self.assertEqual((str(parent.id),), naked_job.parents)

    def test_get(self):
        # InitializeDistroSeriesJob.get() returns the initialization job for
        # the given distroseries. There should only ever be one.
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        another_distroseries = self.factory.makeDistroSeries()
        self.assertIs(None, self.job_source.get(distroseries))
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        self.job_source.create(distroseries, [str(parent.id)])
        self.job_source.create(another_distroseries, [str(parent.id)])
        job = self.job_source.get(distroseries)
        self.assertIsInstance(job, InitializeDistroSeriesJob)
        self.assertEqual(job.distroseries, distroseries)

    def test_error_description_when_no_error(self):
        # The InitializeDistroSeriesJob.error_description property returns
        # None when no error description is recorded.
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        self.assertIs(None, removeSecurityProxy(job).error_description)

    def test_error_description_set_when_notifying_about_user_errors(self):
        # error_description is set by notifyUserError().
        parent = self.factory.makeDistroSeries()
        distroseries = self.factory.makeDistroSeries()
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(distroseries, [str(parent.id)])
        message = "This is an example message."
        job.notifyUserError(InitializationError(message))
        self.assertEqual(message, removeSecurityProxy(job).error_description)


def create_child(factory):
    processor = factory.makeProcessor(supports_virtualized=True)
    parent = factory.makeDistroSeries()
    parent_das = factory.makeDistroArchSeries(
        distroseries=parent, processor=processor
    )
    lf = factory.makeLibraryFileAlias()
    # Since the LFA needs to be in the librarian, commit.
    transaction.commit()
    parent_das.addOrUpdateChroot(lf)
    with celebrity_logged_in("admin"):
        parent.nominatedarchindep = parent_das
        publisher = SoyuzTestPublisher()
        publisher.prepareBreezyAutotest()
        packages = {"udev": "0.1-1", "libc6": "2.8-1"}
        for package in packages.keys():
            publisher.getPubBinaries(
                distroseries=parent,
                binaryname=package,
                version=packages[package],
                status=PackagePublishingStatus.PUBLISHED,
            )
        test1 = getUtility(IPackagesetSet).new(
            "test1", "test 1 packageset", parent.owner, distroseries=parent
        )
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        test1_packageset_id = str(test1.id)
        test1.addSources("udev")
    parent.updatePackageCount()
    child = factory.makeDistroSeries()
    getUtility(ISourcePackageFormatSelectionSet).add(
        child, SourcePackageFormat.FORMAT_1_0
    )
    # Make sure everything hits the database, switching db users aborts.
    transaction.commit()
    return parent, child, test1_packageset_id


class InitializeDistroSeriesJobTestsWithPackages(TestCaseWithFactory):
    """Test case for InitializeDistroSeriesJob."""

    layer = LaunchpadZopelessLayer

    @property
    def job_source(self):
        return getUtility(IInitializeDistroSeriesJobSource)

    def setupDas(self, parent, processor_name, arch_tag):
        try:
            processor = getUtility(IProcessorSet).getByName(processor_name)
        except ProcessorNotFound:
            processor = self.factory.makeProcessor(name=processor_name)
        processor.supports_virtualized = True
        parent_das = self.factory.makeDistroArchSeries(
            distroseries=parent, processor=processor, architecturetag=arch_tag
        )
        lf = self.factory.makeLibraryFileAlias()
        transaction.commit()
        parent_das.addOrUpdateChroot(lf)
        return parent_das

    def test_job(self):
        parent, child, test1_packageset_id = create_child(self.factory)
        # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
        job = self.job_source.create(child, [str(parent.id)])
        switch_dbuser("initializedistroseries")

        job.run()
        child.updatePackageCount()
        self.assertEqual(parent.sourcecount, child.sourcecount)
        self.assertEqual(parent.binarycount, child.binarycount)

    def test_job_with_arguments(self):
        parent, child, test1_packageset_id = create_child(self.factory)
        arch = parent.nominatedarchindep.architecturetag
        job = self.job_source.create(
            child,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
            packagesets=(test1_packageset_id,),
            arches=(arch,),
            rebuild=True,
        )
        switch_dbuser("initializedistroseries")

        job.run()
        child.updatePackageCount()
        builds = child.getBuildRecords(
            build_state=BuildStatus.NEEDSBUILD,
            pocket=PackagePublishingPocket.RELEASE,
        )
        self.assertEqual(child.sourcecount, 1)
        self.assertEqual(child.binarycount, 0)
        self.assertEqual(builds.count(), 1)

    def test_job_with_none_arguments(self):
        parent, child, test1_packageset_id = create_child(self.factory)
        job = self.job_source.create(
            child,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
            archindep_archtag=None,
            packagesets=None,
            arches=None,
            overlays=None,
            overlay_pockets=None,
            overlay_components=None,
            rebuild=True,
        )
        switch_dbuser("initializedistroseries")
        job.run()
        child.updatePackageCount()

        self.assertEqual(parent.sourcecount, child.sourcecount)

    def test_job_with_none_archindep_archtag_argument(self):
        parent, child, test1_packageset_id = create_child(self.factory)
        job = self.job_source.create(
            child,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
            archindep_archtag=None,
            packagesets=None,
            arches=None,
            overlays=None,
            overlay_pockets=None,
            overlay_components=None,
            rebuild=True,
        )
        switch_dbuser("initializedistroseries")
        job.run()

        self.assertEqual(
            parent.nominatedarchindep.architecturetag,
            child.nominatedarchindep.architecturetag,
        )

    def test_job_with_archindep_archtag_argument(self):
        parent, child, test1_packageset_id = create_child(self.factory)
        self.setupDas(parent, "amd64", "amd64")
        self.setupDas(parent, "powerpc", "hppa")
        job = self.job_source.create(
            child,
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            [str(parent.id)],
            archindep_archtag="amd64",
            packagesets=None,
            arches=None,
            overlays=None,
            overlay_pockets=None,
            overlay_components=None,
            rebuild=True,
        )
        switch_dbuser("initializedistroseries")
        job.run()

        self.assertEqual("amd64", child.nominatedarchindep.architecturetag)

    def test_cronscript(self):
        exit_code, _, _ = run_script(
            "cronscripts/process-job-source.py",
            args=["IInitializeDistroSeriesJobSource"],
        )
        self.assertEqual(0, exit_code)
        DatabaseLayer.force_dirty_database()


class TestViaCelery(TestCaseWithFactory):
    layer = CeleryJobLayer

    def test_job(self):
        """Job runs successfully via Celery."""
        fixture = FeatureFixture(
            {
                "jobs.celery.enabled_classes": "InitializeDistroSeriesJob",
            }
        )
        self.useFixture(fixture)
        parent, child, test1 = create_child(self.factory)
        job_source = getUtility(IInitializeDistroSeriesJobSource)
        with block_on_job():
            # XXX cjwatson 2023-09-11: Our JS code passes IDs as strings.
            job_source.create(child, [str(parent.id)])
            transaction.commit()
        child.updatePackageCount()
        self.assertEqual(parent.sourcecount, child.sourcecount)
        self.assertEqual(parent.binarycount, child.binarycount)
