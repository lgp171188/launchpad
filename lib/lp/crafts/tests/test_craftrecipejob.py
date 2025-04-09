# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for craft recipe jobs."""

import json
from textwrap import dedent

import six
from fixtures import FakeLogger
from testtools.matchers import (
    AfterPreprocessing,
    ContainsDict,
    Equals,
    GreaterThan,
    Is,
    LessThan,
    MatchesAll,
    MatchesSetwise,
    MatchesStructure,
)
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.code.tests.helpers import GitHostingFixture
from lp.crafts.interfaces.craftrecipe import (
    CRAFT_RECIPE_ALLOW_CREATE,
    CannotParseSourcecraftYaml,
)
from lp.crafts.interfaces.craftrecipejob import (
    ICraftRecipeJob,
    ICraftRecipeRequestBuildsJob,
    IRustCrateUploadJob,
    IRustCrateUploadJobSource,
)
from lp.crafts.model.craftrecipejob import (
    CraftRecipeJob,
    CraftRecipeJobType,
    CraftRecipeRequestBuildsJob,
    RustCrateUploadJob,
)
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.mail.sendmail import format_address_for_person
from lp.testing import TestCaseWithFactory
from lp.testing.dbuser import dbuser
from lp.testing.layers import CeleryJobLayer, ZopelessDatabaseLayer


class TestCraftRecipeJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CraftRecipeJob` objects provide `ICraftRecipeJob`.
        recipe = self.factory.makeCraftRecipe()
        self.assertProvides(
            CraftRecipeJob(recipe, CraftRecipeJobType.REQUEST_BUILDS, {}),
            ICraftRecipeJob,
        )


class TestCraftRecipeRequestBuildsJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # `CraftRecipeRequestBuildsJob` objects provide
        # `ICraftRecipeRequestBuildsJob`.
        recipe = self.factory.makeCraftRecipe()
        job = CraftRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertProvides(job, ICraftRecipeRequestBuildsJob)

    def test___repr__(self):
        # `CraftRecipeRequestBuildsJob` objects have an informative __repr__.
        recipe = self.factory.makeCraftRecipe()
        job = CraftRecipeRequestBuildsJob.create(recipe, recipe.registrant)
        self.assertEqual(
            "<CraftRecipeRequestBuildsJob for ~%s/%s/+craft/%s>"
            % (recipe.owner.name, recipe.project.name, recipe.name),
            repr(job),
        )

    def makeSeriesAndProcessors(self, distro_series_version, arch_tags):
        distroseries = self.factory.makeDistroSeries(
            distribution=getUtility(ILaunchpadCelebrities).ubuntu,
            version=distro_series_version,
        )
        processors = [
            self.factory.makeProcessor(
                name=arch_tag, supports_virtualized=True
            )
            for arch_tag in arch_tags
        ]
        for processor in processors:
            das = self.factory.makeDistroArchSeries(
                distroseries=distroseries,
                architecturetag=processor.name,
                processor=processor,
            )
            das.addOrUpdateChroot(
                self.factory.makeLibraryFileAlias(
                    filename="fake_chroot.tar.gz", db_only=True
                )
            )
        return distroseries, processors

    def test_run(self):
        # The job requests builds and records the result.
        distroseries, _ = self.makeSeriesAndProcessors(
            "20.04", ["avr2001", "sparc64", "x32"]
        )
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeCraftRecipe(git_ref=git_ref)
        expected_date_created = get_transaction_timestamp(IStore(recipe))
        job = CraftRecipeRequestBuildsJob.create(
            recipe, recipe.registrant, channels={"core": "stable"}
        )
        sourcecraft_yaml = dedent(
            """\
            base: ubuntu@20.04
            platforms:
                avr2001:
                x32:
            """
        )
        self.useFixture(GitHostingFixture(blob=sourcecraft_yaml))
        with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
            JobRunner([job]).runAll()
        now = get_transaction_timestamp(IStore(recipe))
        self.assertEmailQueueLength(0)
        self.assertThat(
            job,
            MatchesStructure(
                job=MatchesStructure.byEquality(status=JobStatus.COMPLETED),
                date_created=Equals(expected_date_created),
                date_finished=MatchesAll(
                    GreaterThan(expected_date_created), LessThan(now)
                ),
                error_message=Is(None),
                builds=AfterPreprocessing(
                    set,
                    MatchesSetwise(
                        *[
                            MatchesStructure(
                                build_request=MatchesStructure.byEquality(
                                    id=job.job.id
                                ),
                                requester=Equals(recipe.registrant),
                                recipe=Equals(recipe),
                                distro_arch_series=Equals(distroseries[arch]),
                                channels=Equals({"core": "stable"}),
                            )
                            for arch in ("avr2001", "x32")
                        ]
                    ),
                ),
            ),
        )

    def test_run_with_architectures(self):
        # If the user explicitly requested architectures, the job passes
        # those through when requesting builds, intersecting them with other
        # constraints.
        distroseries, _ = self.makeSeriesAndProcessors(
            "20.04", ["avr2001", "sparc64", "x32"]
        )
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeCraftRecipe(git_ref=git_ref)
        expected_date_created = get_transaction_timestamp(IStore(recipe))
        job = CraftRecipeRequestBuildsJob.create(
            recipe,
            recipe.registrant,
            channels={"core": "stable"},
            architectures=["sparc64", "x32"],
        )
        sourcecraft_yaml = dedent(
            """\
            base: ubuntu@20.04
            platforms:
                x32:
            """
        )
        self.useFixture(GitHostingFixture(blob=sourcecraft_yaml))
        with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
            JobRunner([job]).runAll()
        now = get_transaction_timestamp(IStore(recipe))
        self.assertEmailQueueLength(0)
        self.assertThat(
            job,
            MatchesStructure(
                job=MatchesStructure.byEquality(status=JobStatus.COMPLETED),
                date_created=Equals(expected_date_created),
                date_finished=MatchesAll(
                    GreaterThan(expected_date_created), LessThan(now)
                ),
                error_message=Is(None),
                builds=AfterPreprocessing(
                    set,
                    MatchesSetwise(
                        MatchesStructure(
                            build_request=MatchesStructure.byEquality(
                                id=job.job.id
                            ),
                            requester=Equals(recipe.registrant),
                            recipe=Equals(recipe),
                            distro_arch_series=Equals(distroseries["x32"]),
                            channels=Equals({"core": "stable"}),
                        )
                    ),
                ),
            ),
        )

    def test_run_failed(self):
        # A failed run sets the job status to FAILED and records the error
        # message.
        [git_ref] = self.factory.makeGitRefs()
        recipe = self.factory.makeCraftRecipe(git_ref=git_ref)
        expected_date_created = get_transaction_timestamp(IStore(recipe))
        job = CraftRecipeRequestBuildsJob.create(
            recipe, recipe.registrant, channels={"core": "stable"}
        )
        self.useFixture(GitHostingFixture()).getBlob.failure = (
            CannotParseSourcecraftYaml("Nonsense on stilts")
        )
        with dbuser(config.ICraftRecipeRequestBuildsJobSource.dbuser):
            JobRunner([job]).runAll()
        now = get_transaction_timestamp(IStore(recipe))
        [notification] = self.assertEmailQueueLength(1)
        self.assertThat(
            dict(notification),
            ContainsDict(
                {
                    "From": Equals(config.canonical.noreply_from_address),
                    "To": Equals(format_address_for_person(recipe.registrant)),
                    "Subject": Equals(
                        "Launchpad error while requesting builds of %s"
                        % recipe.name
                    ),
                }
            ),
        )
        self.assertEqual(
            "Launchpad encountered an error during the following operation: "
            "requesting builds of %s.  Nonsense on stilts" % recipe.name,
            six.ensure_text(notification.get_payload(decode=True)),
        )
        self.assertThat(
            job,
            MatchesStructure(
                job=MatchesStructure.byEquality(status=JobStatus.FAILED),
                date_created=Equals(expected_date_created),
                date_finished=MatchesAll(
                    GreaterThan(expected_date_created), LessThan(now)
                ),
                error_message=Equals("Nonsense on stilts"),
                builds=AfterPreprocessing(set, MatchesSetwise()),
            ),
        )


class TestRustCrateUploadJob(TestCaseWithFactory):
    """Test the RustCrateUploadJob."""

    layer = CeleryJobLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FakeLogger())
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))
        self.recipe = self.factory.makeCraftRecipe()
        self.build = self.factory.makeCraftRecipeBuild(recipe=self.recipe)

    def test_provides_interface(self):
        # RustCrateUploadJob provides IRustCrateUploadJob.
        job = getUtility(IRustCrateUploadJobSource).create(self.build)

        # Check that the instance provides the job interface
        self.assertProvides(job, IRustCrateUploadJob)

        # Check that the class provides the source interface
        self.assertProvides(RustCrateUploadJob, IRustCrateUploadJobSource)

    def test_create(self):
        # RustCrateUploadJob.create creates a RustCrateUploadJob with the
        # correct attributes.
        job = getUtility(IRustCrateUploadJobSource).create(self.build)

        job = removeSecurityProxy(job)

        self.assertThat(
            job,
            MatchesStructure(
                class_job_type=Equals(CraftRecipeJobType.RUST_CRATE_UPLOAD),
                recipe=Equals(self.recipe),
                build=Equals(self.build),
                error_message=Is(None),
            ),
        )

    def test_run_failure_no_archive_file(self):
        """Test failure when no archive file is found in the build."""
        job = getUtility(IRustCrateUploadJobSource).create(self.build)

        # Create a mock that returns files without .tar.xz extension
        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.txt", db_only=True
        )

        # Patch the build's getFiles method to return a non-tar.xz file
        self.patch(
            removeSecurityProxy(self.build),
            "getFiles",
            lambda: [(None, mock_lfa, None)],
        )

        # Run the job
        JobRunner([job]).runAll()

        # Verify job failed with error message
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No archive file found in build",
            job.error_message,
        )

    def test_run_failure_cannot_determine_distribution(self):
        """Test failure when distribution cannot be determined."""
        job = getUtility(IRustCrateUploadJobSource).create(self.build)

        # Create a mock for getFiles that returns a tar.xz file
        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.tar.xz", db_only=True
        )

        # Patch the build's getFiles method to return a tar.xz file
        self.patch(
            removeSecurityProxy(self.build),
            "getFiles",
            lambda: [(None, mock_lfa, None)],
        )

        # Create a mock git repository with a non-distribution target
        git_repo = self.factory.makeGitRepository()
        self.patch(
            removeSecurityProxy(self.recipe), "git_repository", git_repo
        )

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "Could not determine distribution for build",
            job.error_message,
        )

    def test_run_failure_no_configuration(self):
        """Test failure when no configuration is found for the distribution."""
        # Create a distribution with a name that won't have a configuration
        distribution = self.factory.makeDistribution(name="nonexistent")

        # Create a distribution source package for our distribution
        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        # Create a git repository targeting that package
        git_repository = self.factory.makeGitRepository(target=package)

        # Update our recipe to use this git repository
        removeSecurityProxy(self.recipe).git_repository = git_repository

        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.tar.xz", db_only=True
        )

        self.patch(
            removeSecurityProxy(self.build),
            "getFiles",
            lambda: [(None, mock_lfa, None)],
        )

        job = getUtility(IRustCrateUploadJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No configuration found for nonexistent",
            job.error_message,
        )

    def test_run_failure_missing_cargo_config(self):
        """Test failure when the cargo configuration is missing."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with environment variables but no Cargo publishing info
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps({"OTHER_VAR": "value"}),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.tar.xz", db_only=True
        )

        self.patch(
            removeSecurityProxy(self.build),
            "getFiles",
            lambda: [(None, mock_lfa, None)],
        )

        job = getUtility(IRustCrateUploadJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "Missing Cargo publishing repository configuration",
            job.error_message,
        )
