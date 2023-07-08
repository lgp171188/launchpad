# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test Builder features."""

from fixtures import FakeLogger
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuilderCleanStatus, BuildStatus
from lp.buildmaster.interfaces.builder import IBuilder, IBuilderSet
from lp.buildmaster.interfaces.buildqueue import IBuildQueueSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.tests.mock_workers import make_publisher
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import flush_database_updates
from lp.services.features.testing import FeatureFixture
from lp.soyuz.enums import ArchivePurpose, PackagePublishingStatus
from lp.soyuz.interfaces.binarypackagebuild import IBinaryPackageBuildSet
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    celebrity_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer, LaunchpadZopelessLayer


class TestBuilder(TestCaseWithFactory):
    """Basic unit tests for `Builder`."""

    layer = DatabaseFunctionalLayer

    def test_providesInterface(self):
        # Builder provides IBuilder
        builder = self.factory.makeBuilder()
        with celebrity_logged_in("buildd_admin"):
            self.assertProvides(builder, IBuilder)

    def test_default_values(self):
        builder = self.factory.makeBuilder()
        # Make sure the Storm cache gets the values that the database
        # initializes.
        flush_database_updates()
        self.assertEqual(0, builder.failure_count)

    def test_setting_builderok_resets_failure_count(self):
        builder = removeSecurityProxy(self.factory.makeBuilder())
        builder.failure_count = 1
        builder.builderok = False
        self.assertEqual(1, builder.failure_count)
        builder.builderok = True
        self.assertEqual(0, builder.failure_count)

    def test_setting_builderok_dirties(self):
        builder = removeSecurityProxy(self.factory.makeBuilder())
        builder.builderok = False
        builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        builder.builderok = True
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)

    def test_setCleanStatus(self):
        builder = self.factory.makeBuilder()
        self.assertEqual(BuilderCleanStatus.DIRTY, builder.clean_status)
        with celebrity_logged_in("buildd_admin"):
            builder.setCleanStatus(BuilderCleanStatus.CLEAN)
        self.assertEqual(BuilderCleanStatus.CLEAN, builder.clean_status)

    def test_set_processors(self):
        builder = self.factory.makeBuilder()
        proc1 = self.factory.makeProcessor()
        proc2 = self.factory.makeProcessor()
        with admin_logged_in():
            builder.processors = [proc1, proc2]
        self.assertEqual(proc1, builder.processor)
        self.assertEqual([proc1, proc2], builder.processors)

    def test_set_processor(self):
        builder = self.factory.makeBuilder()
        proc = self.factory.makeProcessor()
        with admin_logged_in():
            builder.processor = proc
        self.assertEqual(proc, builder.processor)
        self.assertEqual([proc], builder.processors)

    def test_region_empty(self):
        builder = self.factory.makeBuilder(name="some-builder-name")
        self.assertEqual("", builder.region)

    def test_region(self):
        builder = self.factory.makeBuilder(name="some-region-001")
        self.assertEqual("some-region", builder.region)


# XXX cjwatson 2020-05-18: All these tests would now make more sense in
# lp.buildmaster.tests.test_buildqueue, and should be moved there when
# convenient.
class TestFindBuildCandidatesBase(TestCaseWithFactory):
    """Setup the test publisher and some builders."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.publisher = make_publisher()
        self.publisher.prepareBreezyAutotest()

        self.proc_386 = getUtility(IProcessorSet).getByName("386")

        # Create some i386 builders ready to build PPA builds.  Two
        # already exist in sampledata so we'll use those first.
        self.builder1 = getUtility(IBuilderSet)["bob"]
        self.frog_builder = getUtility(IBuilderSet)["frog"]
        self.builder3 = self.factory.makeBuilder(name="builder3")
        self.builder4 = self.factory.makeBuilder(name="builder4")
        self.builder5 = self.factory.makeBuilder(name="builder5")
        self.builders = [
            self.builder1,
            self.frog_builder,
            self.builder3,
            self.builder4,
            self.builder5,
        ]

        # Ensure all builders are operational.
        for builder in self.builders:
            builder.builderok = True
            builder.manual = False

        self.bq_set = getUtility(IBuildQueueSet)


class TestFindBuildCandidatesGeneralCases(TestFindBuildCandidatesBase):
    # Test usage of findBuildCandidates not specific to any archive type.

    def test_findBuildCandidates_matches_processor(self):
        # BuildQueueSet.findBuildCandidates returns the highest scored build
        # for the given processor and the given virtualization setting.
        bq1 = self.factory.makeBinaryPackageBuild().queueBuild()
        bq2 = self.factory.makeBinaryPackageBuild().queueBuild()
        bq3 = self.factory.makeBinaryPackageBuild(
            processor=bq2.processor
        ).queueBuild()

        # No job is returned for a fresh processor.
        proc = self.factory.makeProcessor()
        self.assertEqual(
            [],
            self.bq_set.findBuildCandidates(
                processor=proc, virtualized=True, limit=3
            ),
        )

        # bq1 is the best candidate for its processor.
        self.assertEqual(
            [bq1],
            self.bq_set.findBuildCandidates(
                processor=bq1.processor, virtualized=True, limit=3
            ),
        )

        # bq2's score doesn't matter when finding candidates for bq1's
        # processor.
        bq2.manualScore(3000)
        self.assertEqual(
            [],
            self.bq_set.findBuildCandidates(
                processor=proc, virtualized=True, limit=3
            ),
        )
        self.assertEqual(
            [bq1],
            self.bq_set.findBuildCandidates(
                processor=bq1.processor, virtualized=True, limit=3
            ),
        )

        # When looking at bq2's processor, the build with the higher score
        # wins.
        self.assertEqual(
            [bq2, bq3],
            self.bq_set.findBuildCandidates(
                processor=bq2.processor, virtualized=True, limit=3
            ),
        )
        bq3.manualScore(4000)
        self.assertEqual(
            [bq3, bq2],
            self.bq_set.findBuildCandidates(
                processor=bq2.processor, virtualized=True, limit=3
            ),
        )

    def test_findBuildCandidates_honours_virtualized(self):
        proc = self.factory.makeProcessor(supports_virtualized=True)
        bq_nonvirt = self.factory.makeBinaryPackageBuild(
            archive=self.factory.makeArchive(virtualized=False), processor=proc
        ).queueBuild()
        bq_virt = self.factory.makeBinaryPackageBuild(
            archive=self.factory.makeArchive(virtualized=True), processor=proc
        ).queueBuild()

        self.assertEqual(
            [bq_nonvirt],
            self.bq_set.findBuildCandidates(
                processor=proc, virtualized=False, limit=3
            ),
        )
        self.assertEqual(
            [bq_virt],
            self.bq_set.findBuildCandidates(
                processor=proc, virtualized=True, limit=3
            ),
        )

    def test_findBuildCandidates_honours_resources(self):
        (
            repository_plain,
            repository_large,
            repository_gpu,
            repository_gpu_large,
        ) = (
            self.factory.makeGitRepository(builder_constraints=constraints)
            for constraints in (None, ["large"], ["gpu"], ["gpu", "large"])
        )
        das = self.factory.makeDistroArchSeries()
        bq_plain, bq_large, bq_gpu, bq_gpu_large = (
            self.factory.makeCIBuild(
                git_repository=repository, distro_arch_series=das
            ).queueBuild()
            for repository in (
                repository_plain,
                repository_large,
                repository_gpu,
                repository_gpu_large,
            )
        )

        self.assertEqual(
            [bq_plain],
            self.bq_set.findBuildCandidates(
                processor=das.processor, virtualized=True, limit=5
            ),
        )
        self.assertContentEqual(
            [bq_plain, bq_large],
            self.bq_set.findBuildCandidates(
                processor=das.processor,
                virtualized=True,
                limit=5,
                open_resources=("large",),
            ),
        )
        self.assertContentEqual(
            [bq_plain, bq_large, bq_gpu, bq_gpu_large],
            self.bq_set.findBuildCandidates(
                processor=das.processor,
                virtualized=True,
                limit=5,
                open_resources=("large", "gpu"),
            ),
        )
        self.assertEqual(
            [bq_gpu],
            self.bq_set.findBuildCandidates(
                processor=das.processor,
                virtualized=True,
                limit=5,
                restricted_resources=("gpu",),
            ),
        )
        self.assertEqual(
            [bq_gpu, bq_gpu_large],
            self.bq_set.findBuildCandidates(
                processor=das.processor,
                virtualized=True,
                limit=5,
                open_resources=("large",),
                restricted_resources=("gpu",),
            ),
        )

    def test_findBuildCandidates_honours_limit(self):
        # BuildQueueSet.findBuildCandidates returns no more than the number
        # of candidates requested.
        processor = self.factory.makeProcessor()
        bqs = [
            self.factory.makeBinaryPackageBuild(
                processor=processor
            ).queueBuild()
            for _ in range(10)
        ]

        self.assertEqual(
            bqs[:5],
            self.bq_set.findBuildCandidates(
                processor=processor, virtualized=True, limit=5
            ),
        )
        self.assertEqual(
            bqs,
            self.bq_set.findBuildCandidates(
                processor=processor, virtualized=True, limit=10
            ),
        )
        self.assertEqual(
            bqs,
            self.bq_set.findBuildCandidates(
                processor=processor, virtualized=True, limit=11
            ),
        )

    def test_findBuildCandidates_honours_minimum_score(self):
        # Sometimes there's an emergency that requires us to lock down the
        # build farm except for certain whitelisted builds.  We do this by
        # way of a feature flag to set a minimum score; if this is set,
        # BuildQueueSet.findBuildCandidates will ignore any build with a
        # lower score.
        processors = []
        bqs = []
        for _ in range(2):
            processors.append(self.factory.makeProcessor())
            bqs.append([])
            for score in (100000, 99999):
                bq = self.factory.makeBinaryPackageBuild(
                    processor=processors[-1]
                ).queueBuild()
                bq.manualScore(score)
                bqs[-1].append(bq)
        processors.append(self.factory.makeProcessor())

        # By default, each processor has the two builds we just created for
        # it as candidates, with the highest score first.
        self.assertEqual(
            bqs[0],
            self.bq_set.findBuildCandidates(
                processor=processors[0], virtualized=True, limit=3
            ),
        )
        self.assertEqual(
            bqs[1],
            self.bq_set.findBuildCandidates(
                processor=processors[1], virtualized=True, limit=3
            ),
        )

        # If we set a minimum score, then only builds above that threshold
        # are candidates.
        with FeatureFixture({"buildmaster.minimum_score": "100000"}):
            self.assertEqual(
                [bqs[0][0]],
                self.bq_set.findBuildCandidates(
                    processor=processors[0],
                    virtualized=True,
                    limit=3,
                ),
            )
            self.assertEqual(
                [bqs[1][0]],
                self.bq_set.findBuildCandidates(
                    processor=processors[1],
                    virtualized=True,
                    limit=3,
                ),
            )

        # We can similarly set a minimum score for individual processors.
        cases = [
            ({0: "99999"}, [bqs[0], bqs[1], []]),
            ({1: "99999"}, [bqs[0], bqs[1], []]),
            ({2: "99999"}, [bqs[0], bqs[1], []]),
            ({0: "100000"}, [[bqs[0][0]], bqs[1], []]),
            ({1: "100000"}, [bqs[0], [bqs[1][0]], []]),
            ({2: "100000"}, [bqs[0], bqs[1], []]),
        ]
        for feature_spec, expected_bqs in cases:
            features = {
                "buildmaster.minimum_score.%s" % processors[i].name: score
                for i, score in feature_spec.items()
            }
            with FeatureFixture(features):
                for i, processor in enumerate(processors):
                    self.assertEqual(
                        expected_bqs[i],
                        self.bq_set.findBuildCandidates(
                            processor=processor,
                            virtualized=True,
                            limit=3,
                        ),
                    )

        # If we set an invalid minimum score, buildd-manager doesn't
        # explode.
        with FakeLogger() as logger:
            with FeatureFixture({"buildmaster.minimum_score": "nonsense"}):
                self.assertEqual(
                    bqs[0],
                    self.bq_set.findBuildCandidates(
                        processor=processors[0],
                        virtualized=True,
                        limit=3,
                    ),
                )
                self.assertEqual(
                    bqs[1],
                    self.bq_set.findBuildCandidates(
                        processor=processors[1],
                        virtualized=True,
                        limit=3,
                    ),
                )
            self.assertEqual(
                "invalid buildmaster.minimum_score: nonsense\n"
                "invalid buildmaster.minimum_score: nonsense\n",
                logger.output,
            )


class TestFindBuildCandidatesPPABase(TestFindBuildCandidatesBase):
    ppa_joe_private = False
    ppa_jim_private = False

    def _setBuildsBuildingForArch(
        self, builds_list, num_builds, archtag="i386"
    ):
        """Helper function.

        Set the first `num_builds` in `builds_list` with `archtag` as
        BUILDING.
        """
        count = 0
        for build in builds_list[:num_builds]:
            if build.distro_arch_series.architecturetag == archtag:
                build.updateStatus(
                    BuildStatus.BUILDING, builder=self.builders[count]
                )
            count += 1

    def setUp(self):
        """Publish some builds for the test archive."""
        super().setUp()

        # Create two PPAs and add some builds to each.
        self.ppa_joe = self.factory.makeArchive(
            name="joesppa", private=self.ppa_joe_private
        )
        self.ppa_jim = self.factory.makeArchive(
            name="jimsppa", private=self.ppa_jim_private
        )

        self.joe_builds = []
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe,
            ).createMissingBuilds()
        )
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe,
            ).createMissingBuilds()
        )
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="cobblers",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe,
            ).createMissingBuilds()
        )
        self.joe_builds.extend(
            self.publisher.getPubSource(
                sourcename="thunderpants",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_joe,
            ).createMissingBuilds()
        )

        self.jim_builds = []
        self.jim_builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_jim,
            ).createMissingBuilds()
        )
        self.jim_builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.ppa_jim,
            ).createMissingBuilds()
        )

        # Set the first three builds in joe's PPA as building, which
        # leaves two builders free.
        self._setBuildsBuildingForArch(self.joe_builds, 3)
        num_active_builders = len(
            [build for build in self.joe_builds if build.builder is not None]
        )
        num_free_builders = len(self.builders) - num_active_builders
        self.assertEqual(num_free_builders, 2)


class TestFindBuildCandidatesPPA(TestFindBuildCandidatesPPABase):
    def test_findBuildCandidate(self):
        # joe's fourth i386 build will be the next build candidate.
        [next_job] = self.bq_set.findBuildCandidates(
            processor=self.proc_386, virtualized=True, limit=1
        )
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.assertEqual("joesppa", build.archive.name)

    def test_findBuildCandidate_with_disabled_archive(self):
        # Disabled archives should not be considered for dispatching
        # builds.
        [disabled_job] = self.bq_set.findBuildCandidates(
            processor=self.proc_386, virtualized=True, limit=1
        )
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(
            disabled_job
        )
        build.archive.disable()
        [next_job] = self.bq_set.findBuildCandidates(
            processor=self.proc_386, virtualized=True, limit=1
        )
        self.assertNotEqual(disabled_job, next_job)


class TestFindBuildCandidatesPrivatePPA(TestFindBuildCandidatesPPABase):
    ppa_joe_private = True

    def test_findBuildCandidate_for_private_ppa(self):
        # joe's fourth i386 build will be the next build candidate.
        [next_job] = self.bq_set.findBuildCandidates(
            processor=self.proc_386, virtualized=True, limit=1
        )
        build = getUtility(IBinaryPackageBuildSet).getByQueueEntry(next_job)
        self.assertEqual("joesppa", build.archive.name)

        # If the source for the build is still pending, it will still be
        # dispatched: the builder will use macaroon authentication to fetch
        # the source files from the librarian.
        pub = build.current_source_publication
        pub.status = PackagePublishingStatus.PENDING
        [candidate] = self.bq_set.findBuildCandidates(
            processor=self.proc_386, virtualized=True, limit=1
        )
        self.assertEqual(next_job.id, candidate.id)


class TestFindBuildCandidatesDistroArchive(TestFindBuildCandidatesBase):
    def setUp(self):
        """Publish some builds for the test archive."""
        super().setUp()
        # Create a primary archive and publish some builds for the
        # queue.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY
        )

        self.gedit_build = self.publisher.getPubSource(
            sourcename="gedit",
            status=PackagePublishingStatus.PUBLISHED,
            archive=self.non_ppa,
        ).createMissingBuilds()[0]
        self.firefox_build = self.publisher.getPubSource(
            sourcename="firefox",
            status=PackagePublishingStatus.PUBLISHED,
            archive=self.non_ppa,
        ).createMissingBuilds()[0]

    def test_findBuildCandidate_for_non_ppa(self):
        # Normal archives are not restricted to serial builds per
        # arch.
        self.assertEqual(
            [
                self.gedit_build.buildqueue_record,
                self.firefox_build.buildqueue_record,
            ],
            self.bq_set.findBuildCandidates(
                processor=self.proc_386, virtualized=True, limit=3
            ),
        )

        # Now even if we set the build building, we'll still get the
        # second non-ppa build for the same archive as the next candidate.
        self.gedit_build.updateStatus(
            BuildStatus.BUILDING, builder=self.frog_builder
        )
        self.assertEqual(
            [self.firefox_build.buildqueue_record],
            self.bq_set.findBuildCandidates(
                processor=self.proc_386, virtualized=True, limit=3
            ),
        )

    def test_findBuildCandidate_for_recipe_build(self):
        # Recipe builds with a higher score are selected first.
        # This test is run in a context with mixed recipe and binary builds.
        self.assertEqual(self.gedit_build.buildqueue_record.lastscore, 2505)
        self.assertEqual(self.firefox_build.buildqueue_record.lastscore, 2505)

        das = self.factory.makeDistroArchSeries(
            processor=getUtility(IProcessorSet).getByName("386")
        )
        das.distroseries.nominatedarchindep = das
        recipe_build_job = self.factory.makeSourcePackageRecipeBuild(
            distroseries=das.distroseries
        ).queueBuild()
        recipe_build_job.manualScore(9999)

        self.assertEqual(recipe_build_job.lastscore, 9999)

        self.assertEqual(
            [
                recipe_build_job,
                self.gedit_build.buildqueue_record,
                self.firefox_build.buildqueue_record,
            ],
            self.bq_set.findBuildCandidates(
                processor=self.proc_386, virtualized=True, limit=3
            ),
        )


class TestFindRecipeBuildCandidates(TestFindBuildCandidatesBase):
    # These tests operate in a "recipe builds only" setting.
    # Please see also bug #507782.

    def clearBuildQueue(self):
        """Delete all `BuildQueue`, XXXJOb and `Job` instances."""
        for bq in IStore(BuildQueue).find(BuildQueue):
            bq.destroySelf()

    def setUp(self):
        """Publish some builds for the test archive."""
        super().setUp()
        # Create a primary archive and publish some builds for the
        # queue.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY
        )

        das = self.factory.makeDistroArchSeries(
            processor=getUtility(IProcessorSet).getByName("386")
        )
        das.distroseries.nominatedarchindep = das
        self.clearBuildQueue()
        self.bq1 = self.factory.makeSourcePackageRecipeBuild(
            distroseries=das.distroseries
        ).queueBuild()
        self.bq1.manualScore(3333)
        self.bq2 = self.factory.makeSourcePackageRecipeBuild(
            distroseries=das.distroseries
        ).queueBuild()
        self.bq2.manualScore(4333)

    def test_findBuildCandidate_with_highest_score(self):
        # The recipe build with the highest score is selected first.
        # This test is run in a "recipe builds only" context.
        self.assertEqual(
            [self.bq2, self.bq1],
            self.bq_set.findBuildCandidates(
                processor=self.proc_386, virtualized=True, limit=2
            ),
        )
