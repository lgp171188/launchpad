# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
"""Test BuildQueue start time estimation."""

from datetime import datetime, timedelta, timezone

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import BuildStatus
from lp.buildmaster.interfaces.builder import IBuilderSet
from lp.buildmaster.interfaces.processor import IProcessorSet
from lp.buildmaster.model.buildqueue import BuildQueue
from lp.buildmaster.queuedepth import (
    estimate_job_delay,
    estimate_time_to_next_builder,
    get_builder_data,
    get_free_builders_count,
)
from lp.buildmaster.tests.test_buildqueue import find_job
from lp.services.database.interfaces import IStore
from lp.soyuz.enums import ArchivePurpose, PackagePublishingStatus
from lp.soyuz.model.binarypackagebuild import BinaryPackageBuild
from lp.soyuz.tests.test_publishing import SoyuzTestPublisher
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


def check_mintime_to_builder(test, bq, min_time):
    """Test the estimated time until a builder becomes available."""
    time_stamp = bq.date_started or datetime.now(timezone.utc)
    delay = estimate_time_to_next_builder(
        removeSecurityProxy(bq), now=time_stamp
    )
    test.assertTrue(
        delay <= min_time,
        "Wrong min time to next available builder (%s > %s)"
        % (delay, min_time),
    )


def set_remaining_time_for_running_job(bq, remainder):
    """Set remaining running time for job."""
    offset = bq.estimated_duration.seconds - remainder
    removeSecurityProxy(bq).date_started = datetime.now(
        timezone.utc
    ) - timedelta(seconds=offset)


def check_delay_for_job(test, the_job, delay):
    # Obtain the builder statistics pertaining to this job.
    builder_data = get_builder_data()
    estimated_delay = estimate_job_delay(
        removeSecurityProxy(the_job), builder_data
    )
    test.assertEqual(delay, estimated_delay)


def total_builders():
    """How many available builders do we have in total?"""
    builder_data = get_builder_data()
    return builder_data[(None, False)] + builder_data[(None, True)]


def builders_for_job(job):
    """How many available builders can run the given job?"""
    builder_data = get_builder_data()
    return builder_data[(getattr(job.processor, "id", None), job.virtualized)]


def check_estimate(test, job, delay_in_seconds):
    time_stamp = job.date_started or datetime.now(timezone.utc)
    estimate = job.getEstimatedJobStartTime(now=time_stamp)
    if delay_in_seconds is None:
        test.assertEqual(
            delay_in_seconds,
            estimate,
            "An estimate should not be possible at present but one was "
            "returned (%s) nevertheless." % estimate,
        )
    else:
        estimate -= time_stamp
        test.assertTrue(
            estimate.seconds <= delay_in_seconds,
            "The estimated delay deviates from the expected one (%s > %s)"
            % (estimate.seconds, delay_in_seconds),
        )


def disable_builders(test, processor_name, virtualized):
    """Disable bulders with the given processor and virtualization setting."""
    if processor_name is not None:
        processor = getUtility(IProcessorSet).getByName(processor_name)
    for builder in test.builders[(processor.id, virtualized)]:
        builder.builderok = False


def nth_builder(test, bq, n):
    """Find nth builder that can execute the given build."""

    def builder_key(job):
        """Access key for builders capable of running the given job."""
        return (getattr(job.processor, "id", None), job.virtualized)

    builder = None
    builders = test.builders.get(builder_key(bq), [])
    try:
        for builder in builders[n - 1 :]:
            if builder.builderok:
                break
    except IndexError:
        pass
    return builder


def assign_to_builder(test, job_name, builder_number, processor="386"):
    """Simulate assigning a build to a builder."""
    build, bq = find_job(test, job_name, processor)
    builder = nth_builder(test, bq, builder_number)
    bq.markAsBuilding(builder)


class TestBuildQueueBase(TestCaseWithFactory):
    """Setup the test publisher and some builders."""

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.publisher = SoyuzTestPublisher()
        self.publisher.prepareBreezyAutotest()

        # First make nine 'i386' builders.
        self.i1 = self.factory.makeBuilder(name="i386-v-1")
        self.i2 = self.factory.makeBuilder(name="i386-v-2")
        self.i3 = self.factory.makeBuilder(name="i386-v-3")
        self.i4 = self.factory.makeBuilder(name="i386-v-4")
        self.i5 = self.factory.makeBuilder(name="i386-v-5")
        self.i6 = self.factory.makeBuilder(name="i386-n-6", virtualized=False)
        self.i7 = self.factory.makeBuilder(name="i386-n-7", virtualized=False)
        self.i8 = self.factory.makeBuilder(name="i386-n-8", virtualized=False)
        self.i9 = self.factory.makeBuilder(name="i386-n-9", virtualized=False)

        # Next make seven 'hppa' builders.
        self.hppa_proc = getUtility(IProcessorSet).getByName("hppa")
        self.h1 = self.factory.makeBuilder(
            name="hppa-v-1", processors=[self.hppa_proc]
        )
        self.h2 = self.factory.makeBuilder(
            name="hppa-v-2", processors=[self.hppa_proc]
        )
        self.h3 = self.factory.makeBuilder(
            name="hppa-v-3", processors=[self.hppa_proc]
        )
        self.h4 = self.factory.makeBuilder(
            name="hppa-v-4", processors=[self.hppa_proc]
        )
        self.h5 = self.factory.makeBuilder(
            name="hppa-n-5", processors=[self.hppa_proc], virtualized=False
        )
        self.h6 = self.factory.makeBuilder(
            name="hppa-n-6", processors=[self.hppa_proc], virtualized=False
        )
        self.h7 = self.factory.makeBuilder(
            name="hppa-n-7", processors=[self.hppa_proc], virtualized=False
        )

        # Finally make five 'amd64' builders.
        self.amd_proc = getUtility(IProcessorSet).getByName("amd64")
        self.a1 = self.factory.makeBuilder(
            name="amd64-v-1", processors=[self.amd_proc]
        )
        self.a2 = self.factory.makeBuilder(
            name="amd64-v-2", processors=[self.amd_proc]
        )
        self.a3 = self.factory.makeBuilder(
            name="amd64-v-3", processors=[self.amd_proc]
        )
        self.a4 = self.factory.makeBuilder(
            name="amd64-n-4", processors=[self.amd_proc], virtualized=False
        )
        self.a5 = self.factory.makeBuilder(
            name="amd64-n-5", processors=[self.amd_proc], virtualized=False
        )

        self.builders = dict()
        self.x86_proc = getUtility(IProcessorSet).getByName("386")
        # x86 native
        self.builders[(self.x86_proc.id, False)] = [
            self.i6,
            self.i7,
            self.i8,
            self.i9,
        ]
        # x86 virtual
        self.builders[(self.x86_proc.id, True)] = [
            self.i1,
            self.i2,
            self.i3,
            self.i4,
            self.i5,
        ]

        # amd64 native
        self.builders[(self.amd_proc.id, False)] = [self.a4, self.a5]
        # amd64 virtual
        self.builders[(self.amd_proc.id, True)] = [self.a1, self.a2, self.a3]

        # hppa native
        self.builders[(self.hppa_proc.id, False)] = [
            self.h5,
            self.h6,
            self.h7,
        ]
        # hppa virtual
        self.builders[(self.hppa_proc.id, True)] = [
            self.h1,
            self.h2,
            self.h3,
            self.h4,
        ]

        # Ensure all builders are operational.
        for builders in self.builders.values():
            for builder in builders:
                builder.builderok = True
                builder.manual = False

        # Native builders irrespective of processor.
        self.builders[(None, False)] = []
        self.builders[(None, False)].extend(
            self.builders[(self.x86_proc.id, False)]
        )
        self.builders[(None, False)].extend(
            self.builders[(self.amd_proc.id, False)]
        )
        self.builders[(None, False)].extend(
            self.builders[(self.hppa_proc.id, False)]
        )

        # Virtual builders irrespective of processor.
        self.builders[(None, True)] = []
        self.builders[(None, True)].extend(
            self.builders[(self.x86_proc.id, True)]
        )
        self.builders[(None, True)].extend(
            self.builders[(self.amd_proc.id, True)]
        )
        self.builders[(None, True)].extend(
            self.builders[(self.hppa_proc.id, True)]
        )

        # Disable the sample data builders.
        getUtility(IBuilderSet)["bob"].builderok = False
        getUtility(IBuilderSet)["frog"].builderok = False

    def makeCustomBuildQueue(
        self,
        score=9876,
        virtualized=True,
        estimated_duration=64,
        sourcename=None,
        recipe_build=None,
    ):
        """Create a `SourcePackageRecipeBuild` and a `BuildQueue` for
        testing."""
        if recipe_build is None:
            recipe_build = self.factory.makeSourcePackageRecipeBuild(
                sourcename=sourcename
            )
        bq = BuildQueue(
            build_farm_job=recipe_build.build_farm_job,
            lastscore=score,
            estimated_duration=timedelta(seconds=estimated_duration),
            virtualized=virtualized,
        )
        IStore(BuildQueue).add(bq)
        return bq


class SingleArchBuildsBase(TestBuildQueueBase):
    """Set up a test environment with builds that target a single
    processor."""

    def setUp(self):
        """Set up some native x86 builds for the test archive."""
        super().setUp()
        # The builds will be set up as follows:
        #
        #      gedit, p:  386, v:False e:0:01:00 *** s: 1001
        #    firefox, p:  386, v:False e:0:02:00 *** s: 1002
        #        apg, p:  386, v:False e:0:03:00 *** s: 1003
        #        vim, p:  386, v:False e:0:04:00 *** s: 1004
        #        gcc, p:  386, v:False e:0:05:00 *** s: 1005
        #      bison, p:  386, v:False e:0:06:00 *** s: 1006
        #       flex, p:  386, v:False e:0:07:00 *** s: 1007
        #   postgres, p:  386, v:False e:0:08:00 *** s: 1008
        #
        # p=processor, v=virtualized, e=estimated_duration, s=score

        # First mark all builds in the sample data as already built.
        sample_data = IStore(BinaryPackageBuild).find(BinaryPackageBuild)
        for build in sample_data:
            build.buildstate = BuildStatus.FULLYBUILT
        IStore(BinaryPackageBuild).flush()

        # We test builds that target a primary archive.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY
        )
        self.non_ppa.require_virtualized = False

        self.builds = []
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="apg",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="vim",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gcc",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="bison",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="flex",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="postgres",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
            ).createMissingBuilds()
        )
        # Set up the builds for test.
        score = 1000
        duration = 0
        for build in self.builds:
            score += 1
            duration += 60
            bq = build.buildqueue_record
            bq.lastscore = score
            bq.estimated_duration = timedelta(seconds=duration)


class TestBuilderData(SingleArchBuildsBase):
    """Test the retrieval of builder related data. The latter is required
    for job dispatch time estimations irrespective of job processor
    architecture and virtualization setting."""

    def test_builder_data(self):
        # Make sure the builder numbers are correct. The builder data will
        # be the same for all of our builds.
        bq = self.builds[0].buildqueue_record
        self.assertEqual(
            21, total_builders(), "The total number of builders is wrong."
        )
        self.assertEqual(
            4,
            builders_for_job(bq),
            "[1] The total number of builders that can build the job in "
            "question is wrong.",
        )
        builder_stats = get_builder_data()
        self.assertEqual(
            4,
            builder_stats[(self.x86_proc.id, False)],
            "The number of native x86 builders is wrong",
        )
        self.assertEqual(
            5,
            builder_stats[(self.x86_proc.id, True)],
            "The number of virtual x86 builders is wrong",
        )
        self.assertEqual(
            2,
            builder_stats[(self.amd_proc.id, False)],
            "The number of native amd64 builders is wrong",
        )
        self.assertEqual(
            3,
            builder_stats[(self.amd_proc.id, True)],
            "The number of virtual amd64 builders is wrong",
        )
        self.assertEqual(
            3,
            builder_stats[(self.hppa_proc.id, False)],
            "The number of native hppa builders is wrong",
        )
        self.assertEqual(
            4,
            builder_stats[(self.hppa_proc.id, True)],
            "The number of virtual hppa builders is wrong",
        )
        self.assertEqual(
            9,
            builder_stats[(None, False)],
            "The number of *virtual* builders across all processors is wrong",
        )
        self.assertEqual(
            12,
            builder_stats[(None, True)],
            "The number of *native* builders across all processors is wrong",
        )
        # Disable the native x86 builders.
        for builder in self.builders[(self.x86_proc.id, False)]:
            builder.builderok = False
        # Since all native x86 builders were disabled there are none left
        # to build the job.
        self.assertEqual(
            0,
            builders_for_job(bq),
            "[2] The total number of builders that can build the job in "
            "question is wrong.",
        )
        # Re-enable one of them.
        for builder in self.builders[(self.x86_proc.id, False)]:
            builder.builderok = True
            break
        # Now there should be one builder available to build the job.
        self.assertEqual(
            1,
            builders_for_job(bq),
            "[3] The total number of builders that can build the job in "
            "question is wrong.",
        )
        # Disable the *virtual* x86 builders -- should not make any
        # difference.
        for builder in self.builders[(self.x86_proc.id, True)]:
            builder.builderok = False
        # There should still be one builder available to build the job.
        self.assertEqual(
            1,
            builders_for_job(bq),
            "[4] The total number of builders that can build the job in "
            "question is wrong.",
        )

    def test_free_builder_counts(self):
        # Make sure the builder numbers are correct. The builder data will
        # be the same for all of our builds.
        build = self.builds[0]
        # The build in question is an x86/native one.
        self.assertEqual(self.x86_proc.id, build.processor.id)
        self.assertEqual(False, build.virtualized)

        # To test this non-interface method, we need to remove the
        # security proxy.
        bq = removeSecurityProxy(build.buildqueue_record)
        builder_stats = get_builder_data()
        # We have 4 x86 native builders.
        self.assertEqual(
            4,
            builder_stats[(self.x86_proc.id, False)],
            "The number of native x86 builders is wrong",
        )
        # Initially all 4 builders are free.
        free_count = get_free_builders_count(
            build.processor, build.virtualized
        )
        self.assertEqual(4, free_count)
        # Once we assign a build to one of them we should see the free
        # builders count drop by one.
        assign_to_builder(self, "postgres", 1)
        free_count = get_free_builders_count(
            build.processor, build.virtualized
        )
        self.assertEqual(3, free_count)
        # When we assign another build to one of them we should see the free
        # builders count drop by one again.
        assign_to_builder(self, "gcc", 2)
        free_count = get_free_builders_count(
            build.processor, build.virtualized
        )
        self.assertEqual(2, free_count)
        # Let's use up another builder.
        assign_to_builder(self, "apg", 3)
        free_count = get_free_builders_count(
            build.processor, build.virtualized
        )
        self.assertEqual(1, free_count)
        # And now for the last one.
        assign_to_builder(self, "flex", 4)
        free_count = get_free_builders_count(
            build.processor, build.virtualized
        )
        self.assertEqual(0, free_count)
        # If we reset the 'flex' build the builder that was assigned to it
        # will be free again.
        build, bq = find_job(self, "flex")
        bq.reset()
        free_count = get_free_builders_count(
            build.processor, build.virtualized
        )
        self.assertEqual(1, free_count)


class TestMinTimeToNextBuilder(SingleArchBuildsBase):
    """Test estimated time-to-builder with builds targeting a single
    processor."""

    def test_min_time_to_next_builder(self):
        """When is the next builder capable of running the job at the head of
        the queue becoming available?"""
        # Test the estimation of the minimum time until a builder becomes
        # available.

        # The builds will be set up as follows:
        #
        #      gedit, p:  386, v:False e:0:01:00 *** s: 1001
        #    firefox, p:  386, v:False e:0:02:00 *** s: 1002
        #        apg, p:  386, v:False e:0:03:00 *** s: 1003
        #        vim, p:  386, v:False e:0:04:00 *** s: 1004
        #        gcc, p:  386, v:False e:0:05:00 *** s: 1005
        #      bison, p:  386, v:False e:0:06:00 *** s: 1006
        #       flex, p:  386, v:False e:0:07:00 *** s: 1007
        #   postgres, p:  386, v:False e:0:08:00 *** s: 1008
        #
        # p=processor, v=virtualized, e=estimated_duration, s=score

        # This will be the job of interest.
        apg_build, apg_job = find_job(self, "apg")
        # One of four builders for the 'apg' build is immediately available.
        check_mintime_to_builder(self, apg_job, 0)

        # Assign the postgres job to a builder.
        assign_to_builder(self, "postgres", 1)
        # Now one builder is gone. But there should still be a builder
        # immediately available.
        check_mintime_to_builder(self, apg_job, 0)

        assign_to_builder(self, "flex", 2)
        check_mintime_to_builder(self, apg_job, 0)

        assign_to_builder(self, "bison", 3)
        check_mintime_to_builder(self, apg_job, 0)

        assign_to_builder(self, "gcc", 4)
        # Now that no builder is immediately available, the shortest
        # remaining build time (based on the estimated duration) is returned:
        #   300 seconds
        # This is equivalent to the 'gcc' job's estimated duration.
        check_mintime_to_builder(self, apg_job, 300)

        # Now we pretend that the 'postgres' started 6 minutes ago. Its
        # remaining execution time should be 2 minutes = 120 seconds and
        # it now becomes the job whose builder becomes available next.
        build, bq = find_job(self, "postgres")
        set_remaining_time_for_running_job(bq, 120)
        check_mintime_to_builder(self, apg_job, 120)

        # What happens when jobs overdraw the estimated duration? Let's
        # pretend the 'flex' job started 8 minutes ago.
        build, bq = find_job(self, "flex")
        set_remaining_time_for_running_job(bq, -60)
        # In such a case we assume that the job will complete within 2
        # minutes, this is a guess that has worked well so far.
        check_mintime_to_builder(self, apg_job, 120)

        # If there's a job that will complete within a shorter time then
        # we expect to be given that time frame.
        build, bq = find_job(self, "postgres")
        set_remaining_time_for_running_job(bq, 30)
        check_mintime_to_builder(self, apg_job, 30)

        # Disable the native x86 builders.
        for builder in self.builders[(self.x86_proc.id, False)]:
            builder.builderok = False

        # No builders capable of running the job at hand are available now.
        self.assertEqual(0, builders_for_job(apg_job))
        # The "minimum time to builder" estimation logic is not aware of this
        # though.
        check_mintime_to_builder(self, apg_job, 0)

        # The following job can only run on a native builder.
        job = self.makeCustomBuildQueue(
            estimated_duration=111,
            sourcename="xxr-gftp",
            score=1055,
            virtualized=False,
        )
        self.builds.append(job.specific_build)

        # Disable all native builders.
        for builder in self.builders[(None, False)]:
            builder.builderok = False

        # All native builders are disabled now.  No builders capable of
        # running the job at hand are available.
        self.assertEqual(0, builders_for_job(job))
        # The "minimum time to builder" estimation logic is not aware of the
        # fact that no builders capable of running the job are available.
        check_mintime_to_builder(self, job, 0)


class MultiArchBuildsBase(TestBuildQueueBase):
    """Set up a test environment with builds and multiple processors."""

    def setUp(self):
        """Set up some native x86 builds for the test archive."""
        super().setUp()
        # The builds will be set up as follows:
        #
        #      gedit, p: hppa, v:False e:0:01:00 *** s: 1001
        #      gedit, p:  386, v:False e:0:02:00 *** s: 1002
        #    firefox, p: hppa, v:False e:0:03:00 *** s: 1003
        #    firefox, p:  386, v:False e:0:04:00 *** s: 1004
        #        apg, p: hppa, v:False e:0:05:00 *** s: 1005
        #        apg, p:  386, v:False e:0:06:00 *** s: 1006
        #        vim, p: hppa, v:False e:0:07:00 *** s: 1007
        #        vim, p:  386, v:False e:0:08:00 *** s: 1008
        #        gcc, p: hppa, v:False e:0:09:00 *** s: 1009
        #        gcc, p:  386, v:False e:0:10:00 *** s: 1010
        #      bison, p: hppa, v:False e:0:11:00 *** s: 1011
        #      bison, p:  386, v:False e:0:12:00 *** s: 1012
        #       flex, p: hppa, v:False e:0:13:00 *** s: 1013
        #       flex, p:  386, v:False e:0:14:00 *** s: 1014
        #   postgres, p: hppa, v:False e:0:15:00 *** s: 1015
        #   postgres, p:  386, v:False e:0:16:00 *** s: 1016
        #
        # p=processor, v=virtualized, e=estimated_duration, s=score

        # First mark all builds in the sample data as already built.
        sample_data = IStore(BinaryPackageBuild).find(BinaryPackageBuild)
        for build in sample_data:
            build.buildstate = BuildStatus.FULLYBUILT
        IStore(BinaryPackageBuild).flush()

        # We test builds that target a primary archive.
        self.non_ppa = self.factory.makeArchive(
            name="primary", purpose=ArchivePurpose.PRIMARY
        )
        self.non_ppa.require_virtualized = False

        self.builds = []
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gedit",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="firefox",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="apg",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="vim",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="gcc",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="bison",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="flex",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        self.builds.extend(
            self.publisher.getPubSource(
                sourcename="postgres",
                status=PackagePublishingStatus.PUBLISHED,
                archive=self.non_ppa,
                architecturehintlist="any",
            ).createMissingBuilds()
        )
        # Set up the builds for test.
        score = 1000
        duration = 0
        for build in self.builds:
            score += getattr(self, "score_increment", 1)
            score += 1
            duration += 60
            bq = build.buildqueue_record
            bq.lastscore = score
            bq.estimated_duration = timedelta(seconds=duration)


class TestMinTimeToNextBuilderMulti(MultiArchBuildsBase):
    """Test estimated time-to-builder with builds and multiple processors."""

    def disabled_test_min_time_to_next_builder(self):
        """When is the next builder capable of running the job at the head of
        the queue becoming available?"""
        # XXX AaronBentley 2010-03-19 bug=541914: Fails spuriously
        # One of four builders for the 'apg' build is immediately available.
        apg_build, apg_job = find_job(self, "apg", "hppa")
        check_mintime_to_builder(self, apg_job, 0)

        # Assign the postgres job to a builder.
        assign_to_builder(self, "postgres", 1, "hppa")
        # Now one builder is gone. But there should still be a builder
        # immediately available.
        check_mintime_to_builder(self, apg_job, 0)

        assign_to_builder(self, "flex", 2, "hppa")
        check_mintime_to_builder(self, apg_job, 0)

        assign_to_builder(self, "bison", 3, "hppa")
        # Now that no builder is immediately available, the shortest
        # remaining build time (based on the estimated duration) is returned:
        #   660 seconds
        # This is equivalent to the 'bison' job's estimated duration.
        check_mintime_to_builder(self, apg_job, 660)

        # Now we pretend that the 'postgres' started 13 minutes ago. Its
        # remaining execution time should be 2 minutes = 120 seconds and
        # it now becomes the job whose builder becomes available next.
        build, bq = find_job(self, "postgres", "hppa")
        set_remaining_time_for_running_job(bq, 120)
        check_mintime_to_builder(self, apg_job, 120)

        # What happens when jobs overdraw the estimated duration? Let's
        # pretend the 'flex' job started 14 minutes ago.
        build, bq = find_job(self, "flex", "hppa")
        set_remaining_time_for_running_job(bq, -60)
        # In such a case we assume that the job will complete within 2
        # minutes, this is a guess that has worked well so far.
        check_mintime_to_builder(self, apg_job, 120)

        # If there's a job that will complete within a shorter time then
        # we expect to be given that time frame.
        build, bq = find_job(self, "postgres", "hppa")
        set_remaining_time_for_running_job(bq, 30)
        check_mintime_to_builder(self, apg_job, 30)

        # Disable the native hppa builders.
        for builder in self.builders[(self.hppa_proc.id, False)]:
            builder.builderok = False

        # No builders capable of running the job at hand are available now.
        self.assertEqual(0, builders_for_job(apg_job))
        check_mintime_to_builder(self, apg_job, 0)

        # Let's add a processor-independent job to the mix.
        job = self.makeCustomBuildQueue(
            virtualized=False,
            estimated_duration=22,
            sourcename="my-recipe-digikam",
            score=9999,
        )
        # There are still builders available for the processor-independent
        # job.
        self.assertEqual(6, builders_for_job(job))
        # Even free ones.
        self.assertTrue(
            bq._getFreeBuildersCount(job.processor, job.virtualized) > 0,
            "Builders are immediately available for processor-independent "
            "jobs.",
        )
        check_mintime_to_builder(self, job, 0)

        # Let's disable all builders.
        for builders in self.builders.values():
            for builder in builders:
                builder.builderok = False

        # There are no builders capable of running even the processor
        # independent jobs now.
        self.assertEqual(0, builders_for_job(job))
        check_mintime_to_builder(self, job, 0)

        # Re-enable the native hppa builders.
        for builder in self.builders[(self.hppa_proc.id, False)]:
            builder.builderok = True

        # The builder that's becoming available next is the one that's
        # running the 'postgres' build.
        check_mintime_to_builder(self, apg_job, 30)

        # Make sure we'll find an x86 builder as well.
        builder = self.builders[(self.x86_proc.id, False)][0]
        builder.builderok = True

        # Now this builder is the one that becomes available next (29 minutes
        # remaining build time).
        assign_to_builder(self, "gcc", 1, "386")
        build, bq = find_job(self, "gcc", "386")
        set_remaining_time_for_running_job(bq, 29)

        check_mintime_to_builder(self, apg_job, 29)

        # Make a second, idle x86 builder available.
        builder = self.builders[(self.x86_proc.id, False)][1]
        builder.builderok = True

        # That builder should be available immediately since it's idle.
        check_mintime_to_builder(self, apg_job, 0)


class TestMultiArchJobDelayEstimation(MultiArchBuildsBase):
    """Test estimated job delays with various processors."""

    score_increment = 2

    def setUp(self):
        """Add 2 'build source package from recipe' builds to the mix.

        The two platform-independent jobs will have a score of 1025 and 1053
        respectively.
        In case of jobs with equal scores the one with the lesser 'job' value
        (i.e. the older one wins).

              3,              gedit, p: hppa, v:False e:0:01:00 *** s: 1003
              4,              gedit, p:  386, v:False e:0:02:00 *** s: 1006
              5,            firefox, p: hppa, v:False e:0:03:00 *** s: 1009
              6,            firefox, p:  386, v:False e:0:04:00 *** s: 1012
              7,                apg, p: hppa, v:False e:0:05:00 *** s: 1015
              9,                vim, p: hppa, v:False e:0:07:00 *** s: 1021
             10,                vim, p:  386, v:False e:0:08:00 *** s: 1024
              8,                apg, p:  386, v:False e:0:06:00 *** s: 1024
        -->  19,     xx-recipe-bash, p: None, v:False e:0:00:22 *** s: 1025
             11,                gcc, p: hppa, v:False e:0:09:00 *** s: 1027
             12,                gcc, p:  386, v:False e:0:10:00 *** s: 1030
             13,              bison, p: hppa, v:False e:0:11:00 *** s: 1033
             14,              bison, p:  386, v:False e:0:12:00 *** s: 1036
             15,               flex, p: hppa, v:False e:0:13:00 *** s: 1039
             16,               flex, p:  386, v:False e:0:14:00 *** s: 1042
             17,           postgres, p: hppa, v:False e:0:15:00 *** s: 1045
             18,           postgres, p:  386, v:False e:0:16:00 *** s: 1048
        -->  20,      xx-recipe-zsh, p: None, v:False e:0:03:42 *** s: 1053

        p=processor, v=virtualized, e=estimated_duration, s=score
        """
        super().setUp()

        job = self.makeCustomBuildQueue(
            virtualized=False,
            estimated_duration=22,
            sourcename="xx-recipe-bash",
            score=1025,
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            virtualized=False,
            estimated_duration=222,
            sourcename="xx-recipe-zsh",
            score=1053,
        )
        self.builds.append(job.specific_build)

        # Assign the same score to the '386' vim and apg build jobs.
        _apg_build, apg_job = find_job(self, "apg", "386")
        apg_job.lastscore = 1024

    def disabled_test_job_delay_for_binary_builds(self):
        # One of four builders for the 'flex' build is immediately available.
        flex_build, flex_job = find_job(self, "flex", "hppa")
        check_mintime_to_builder(self, flex_job, 0)

        # The delay will be 900 (= 15*60) + 222 seconds
        check_delay_for_job(self, flex_job, 1122)

        # Assign the postgres job to a builder.
        assign_to_builder(self, "postgres", 1, "hppa")
        # The 'postgres' job is not pending any more.  Now only the 222
        # seconds (the estimated duration of the platform-independent job)
        # should be returned.
        check_delay_for_job(self, flex_job, 222)

        # How about some estimates for x86 builds?
        _bison_build, bison_job = find_job(self, "bison", "386")
        check_mintime_to_builder(self, bison_job, 0)
        # The delay will be 900 (= (14+16)*60/2) + 222 seconds.
        check_delay_for_job(self, bison_job, 1122)

        # The 2 tests that follow exercise the estimation in conjunction with
        # longer pending job queues. Please note that the sum of estimates for
        # the '386' jobs is divided by 4 which is the number of native '386'
        # builders.

        # Also, this tests that jobs with equal score but a lower 'job' value
        # (i.e. older jobs) are queued ahead of the job of interest (JOI).
        _vim_build, vim_job = find_job(self, "vim", "386")
        check_mintime_to_builder(self, vim_job, 0)
        # The delay will be 870 (= (6+10+12+14+16)*60/4) + 122 (= (222+22)/2)
        # seconds.
        check_delay_for_job(self, vim_job, 992)

        _gedit_build, gedit_job = find_job(self, "gedit", "386")
        check_mintime_to_builder(self, gedit_job, 0)
        # The delay will be
        #   1080 (= (4+6+8+10+12+14+16)*60/4) + 122 (= (222+22)/2)
        # seconds.
        check_delay_for_job(self, gedit_job, 1172)

    def disabled_test_job_delay_for_recipe_builds(self):
        # One of the 9 builders for the 'bash' build is immediately available.
        bash_build, bash_job = find_job(self, "xx-recipe-bash", None)
        check_mintime_to_builder(self, bash_job, 0)

        # The delay will be 960 + 780 + 222 = 1962, where
        #   hppa job delays: 960 = (9+11+13+15)*60/3
        #    386 job delays: 780 = (10+12+14+16)*60/4
        check_delay_for_job(self, bash_job, 1962)

        # One of the 9 builders for the 'zsh' build is immediately available.
        zsh_build, zsh_job = find_job(self, "xx-recipe-zsh", None)
        check_mintime_to_builder(self, zsh_job, 0)

        # The delay will be 0 since this is the head job.
        check_delay_for_job(self, zsh_job, 0)

        # Assign the zsh job to a builder.
        self.assertEqual((None, False), bash_job._getHeadJobPlatform())
        assign_to_builder(self, "xx-recipe-zsh", 1, None)
        self.assertEqual((1, False), bash_job._getHeadJobPlatform())

        # Now that the highest-scored job is out of the way, the estimation
        # for the 'bash' recipe build is 222 seconds shorter.

        # The delay will be 960 + 780 = 1740, where
        #   hppa job delays: 960 = (9+11+13+15)*60/3
        #    386 job delays: 780 = (10+12+14+16)*60/4
        check_delay_for_job(self, bash_job, 1740)

        _postgres_build, postgres_job = find_job(self, "postgres", "386")
        # The delay will be 0 since this is the head job now.
        check_delay_for_job(self, postgres_job, 0)
        # Also, the platform of the postgres job is returned since it *is*
        # the head job now.
        pg_platform = (postgres_job.processor.id, postgres_job.virtualized)
        self.assertEqual(pg_platform, postgres_job._getHeadJobPlatform())


class TestJobDispatchTimeEstimation(MultiArchBuildsBase):
    """Test estimated job delays with various processors."""

    score_increment = 2

    def setUp(self):
        """Add more processor-independent jobs to the mix, make the '386' jobs
        virtual.

            3,              gedit, p: hppa, v:False e:0:01:00 *** s: 1003
            4,              gedit, p:  386, v: True e:0:02:00 *** s: 1006
            5,            firefox, p: hppa, v:False e:0:03:00 *** s: 1009
            6,            firefox, p:  386, v: True e:0:04:00 *** s: 1012
            7,                apg, p: hppa, v:False e:0:05:00 *** s: 1015
            9,                vim, p: hppa, v:False e:0:07:00 *** s: 1021
           10,                vim, p:  386, v: True e:0:08:00 *** s: 1024
            8,                apg, p:  386, v: True e:0:06:00 *** s: 1024
           19,       xxr-aptitude, p: None, v:False e:0:05:32 *** s: 1025
           11,                gcc, p: hppa, v:False e:0:09:00 *** s: 1027
           12,                gcc, p:  386, v: True e:0:10:00 *** s: 1030
           13,              bison, p: hppa, v:False e:0:11:00 *** s: 1033
           14,              bison, p:  386, v: True e:0:12:00 *** s: 1036
           15,               flex, p: hppa, v:False e:0:13:00 *** s: 1039
           16,               flex, p:  386, v: True e:0:14:00 *** s: 1042
           23,      xxr-apt-build, p: None, v: True e:0:12:56 *** s: 1043
           22,       xxr-cron-apt, p: None, v: True e:0:11:05 *** s: 1043
           26,           xxr-cupt, p: None, v: True e:0:18:30 *** s: 1044
           25,            xxr-apt, p: None, v: True e:0:16:38 *** s: 1044
           24,       xxr-debdelta, p: None, v: True e:0:14:47 *** s: 1044
           17,           postgres, p: hppa, v:False e:0:15:00 *** s: 1045
           18,           postgres, p:  386, v: True e:0:16:00 *** s: 1048
           21,         xxr-daptup, p: None, v: True e:0:09:14 *** s: 1051
           20,       xxr-auto-apt, p: None, v:False e:0:07:23 *** s: 1053

         p=processor, v=virtualized, e=estimated_duration, s=score
        """
        super().setUp()

        job = self.makeCustomBuildQueue(
            virtualized=False,
            estimated_duration=332,
            sourcename="xxr-aptitude",
            score=1025,
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            virtualized=False,
            estimated_duration=443,
            sourcename="xxr-auto-apt",
            score=1053,
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            estimated_duration=554, sourcename="xxr-daptup", score=1051
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            estimated_duration=665, sourcename="xxr-cron-apt", score=1043
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            estimated_duration=776, sourcename="xxr-apt-build", score=1043
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            estimated_duration=887, sourcename="xxr-debdelta", score=1044
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            estimated_duration=998, sourcename="xxr-apt", score=1044
        )
        self.builds.append(job.specific_build)
        job = self.makeCustomBuildQueue(
            estimated_duration=1110, sourcename="xxr-cupt", score=1044
        )
        self.builds.append(job.specific_build)

        # Assign the same score to the '386' vim and apg build jobs.
        _apg_build, apg_job = find_job(self, "apg", "386")
        apg_job.lastscore = 1024

        # Also, toggle the 'virtualized' flag for all '386' jobs.
        for build in self.builds:
            bq = build.buildqueue_record
            if bq.processor == self.x86_proc:
                removeSecurityProxy(bq).virtualized = True

    def test_pending_jobs_only(self):
        # Let's see the assertion fail for a job that's not pending any more.
        assign_to_builder(self, "gedit", 1, "hppa")
        gedit_build, gedit_job = find_job(self, "gedit", "hppa")
        self.assertRaises(AssertionError, gedit_job.getEstimatedJobStartTime)

    def test_estimation_binary_virtual(self):
        gcc_build, gcc_job = find_job(self, "gcc", "386")
        # The delay of 1671 seconds is calculated as follows:
        #                     386 jobs: (12+14+16)*60/3           = 840
        #   processor-independent jobs:
        #       (12:56 + 11:05 + 18:30 + 16:38 + 14:47 + 9:14)/6  = 831
        check_estimate(self, gcc_job, 1671)
        self.assertEqual(5, builders_for_job(gcc_job))

    def test_proc_indep_virtual_true(self):
        xxr_build, xxr_job = find_job(self, "xxr-apt-build", None)
        # The delay of 1802 seconds is calculated as follows:
        #                     386 jobs: 16*60                    = 960
        #   processor-independent jobs:
        #       (11:05 + 18:30 + 16:38 + 14:47 + 9:14)/5         = 842
        check_estimate(self, xxr_job, 1802)

    def test_estimation_binary_virtual_long_queue(self):
        gedit_build, gedit_job = find_job(self, "gedit", "386")
        # The delay of 1671 seconds is calculated as follows:
        #                     386 jobs:
        #       (4+6+8+10+12+14+16)*60/5                          = 840
        #   processor-independent jobs:
        #       (12:56 + 11:05 + 18:30 + 16:38 + 14:47 + 9:14)/6  = 831
        check_estimate(self, gedit_job, 1671)

    def test_proc_indep_virtual_null_headjob(self):
        xxr_build, xxr_job = find_job(self, "xxr-daptup", None)
        # This job is at the head of the queue for virtualized builders and
        # will get dispatched within the next 5 seconds.
        check_estimate(self, xxr_job, 5)

    def test_proc_indep_virtual_false(self):
        xxr_build, xxr_job = find_job(self, "xxr-aptitude", None)
        # The delay of 1403 seconds is calculated as follows:
        #                    hppa jobs: (9+11+13+15)*60/3        = 960
        #   processor-independent jobs: 7:23                     = 443
        check_estimate(self, xxr_job, 1403)

    def test_proc_indep_virtual_false_headjob(self):
        xxr_build, xxr_job = find_job(self, "xxr-auto-apt", None)
        # This job is at the head of the queue for native builders and
        # will get dispatched within the next 5 seconds.
        check_estimate(self, xxr_job, 5)

    def test_estimation_binary_virtual_same_score(self):
        vim_build, vim_job = find_job(self, "vim", "386")
        # The apg job is ahead of the vim job.
        # The delay of 1527 seconds is calculated as follows:
        #                     386 jobs: (6+10+12+14+16)*60/5      = 696
        #   processor-independent jobs:
        #       (12:56 + 11:05 + 18:30 + 16:38 + 14:47 + 9:14)/6  = 831
        check_estimate(self, vim_job, 1527)

    def test_no_builder_no_estimate(self):
        # No dispatch estimate is provided in the absence of builders that
        # can run the job of interest (JOI).
        disable_builders(self, "386", True)
        vim_build, vim_job = find_job(self, "vim", "386")
        check_estimate(self, vim_job, None)

    def disabled_test_estimates_with_small_builder_pool(self):
        # Test that a reduced builder pool results in longer dispatch time
        # estimates.
        vim_build, vim_job = find_job(self, "vim", "386")
        disable_builders(self, "386", True)
        # Re-enable one builder.
        builder = self.builders[(self.x86_proc.id, True)][0]
        builder.builderok = True
        # Dispatch the firefox job to it.
        assign_to_builder(self, "firefox", 1, "386")
        # Dispatch the head job, making postgres/386 the new head job and
        # resulting in a 240 seconds head job dispatch delay.
        assign_to_builder(self, "xxr-daptup", 1, None)
        check_mintime_to_builder(self, vim_job, 240)
        # Re-enable another builder.
        builder = self.builders[(self.x86_proc.id, True)][1]
        builder.builderok = True
        # Assign a job to it.
        assign_to_builder(self, "gedit", 2, "386")
        check_mintime_to_builder(self, vim_job, 120)

        xxr_build, xxr_job = find_job(self, "xxr-apt", None)
        # The delay of 2627+120 seconds is calculated as follows:
        #                     386 jobs : (6+10+12+14+16)*60/2     = 1740
        #   processor-independent jobs :
        #       (12:56 + 11:05 + 18:30 + 16:38 + 14:47)/5         =  887
        # waiting time for next builder:                          =  120
        self.assertEqual(2, builders_for_job(vim_job))
        self.assertEqual(9, builders_for_job(xxr_job))
        check_estimate(self, vim_job, 2747)

    def test_estimation_binary_virtual_headjob(self):
        # The head job only waits for the next builder to become available.
        disable_builders(self, "386", True)
        # Re-enable one builder.
        builder = self.builders[(self.x86_proc.id, True)][0]
        builder.builderok = True
        # Assign a job to it.
        assign_to_builder(self, "gedit", 1, "386")
        # Dispatch the head job, making postgres/386 the new head job.
        assign_to_builder(self, "xxr-daptup", 2, None)
        postgres_build, postgres_job = find_job(self, "postgres", "386")
        check_estimate(self, postgres_job, 120)
