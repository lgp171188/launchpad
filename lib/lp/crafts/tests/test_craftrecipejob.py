# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for craft recipe jobs."""

import io
import json
import tarfile
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
    ICraftPublishingJob,
    ICraftPublishingJobSource,
    ICraftRecipeJob,
    ICraftRecipeRequestBuildsJob,
)
from lp.crafts.model.craftrecipejob import (
    CraftPublishingJob,
    CraftRecipeJob,
    CraftRecipeJobType,
    CraftRecipeRequestBuildsJob,
)
from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.librarian.interfaces import ILibraryFileAliasSet
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


class TestCraftPublishingJob(TestCaseWithFactory):
    """Test the CraftPublishingJob."""

    layer = CeleryJobLayer

    def setUp(self):
        super().setUp()
        self.useFixture(
            FeatureFixture(
                {"jobs.celery.enabled_classes": "CraftPublishingJob"}
            )
        )
        self.useFixture(FakeLogger())
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))
        self.recipe = self.factory.makeCraftRecipe()
        self.build = self.factory.makeCraftRecipeBuild(recipe=self.recipe)

    def test_provides_interface(self):
        # CraftPublishingJob provides ICraftPublishingJob.
        job = getUtility(ICraftPublishingJobSource).create(self.build)

        # Check that the instance provides the job interface
        self.assertProvides(job, ICraftPublishingJob)

        # Check that the class provides the source interface
        self.assertProvides(CraftPublishingJob, ICraftPublishingJobSource)

    def test_create(self):
        # CraftPublishingJob.create creates a CraftPublishingJob with the
        # correct attributes.
        job = getUtility(ICraftPublishingJobSource).create(self.build)

        job = removeSecurityProxy(job)

        self.assertThat(
            job,
            MatchesStructure(
                class_job_type=Equals(CraftRecipeJobType.PUBLISH_ARTIFACTS),
                recipe=Equals(self.recipe),
                build=Equals(self.build),
                error_message=Is(None),
            ),
        )

    def test_run_failure_cannot_determine_distribution(self):
        """Test failure when distribution cannot be determined."""
        job = getUtility(ICraftPublishingJobSource).create(self.build)

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

        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()
        job = removeSecurityProxy(job)

        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No configuration found for nonexistent",
            job.error_message,
        )

    def test_run_no_publishable_artifacts(self):
        """Test failure when no publishable artifacts are found."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with environment variables but no Cargo publishing info
        # We just need a config section for the distribution name
        self.pushConfig("craftbuild.soss")
        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        git_repository = self.factory.makeGitRepository(target=package)
        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a dummy file (but not a crate or jar)
        from io import BytesIO

        dummy_content = b"test content"

        # Create a LibraryFileAlias with the dummy content
        librarian = getUtility(ILibraryFileAliasSet)
        lfa = librarian.create(
            "test.txt",
            len(dummy_content),
            BytesIO(dummy_content),
            "text/plain",
        )

        # Add the file to the build
        removeSecurityProxy(self.build).addFile(lfa)

        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)

        self.assertEqual(
            "No publishable artifacts found in build",
            job.error_message,
        )

    def test_run_missing_cargo_config(self):
        """Test failure when a crate is found but Cargo config is missing."""
        distribution = self.factory.makeDistribution(name="soss")
        self.pushConfig("craftbuild.soss")
        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a BytesIO object to hold the tar data
        tar_data = io.BytesIO()

        # Create a tar archive
        with tarfile.open(fileobj=tar_data, mode="w") as tar:
            # Create a directory entry for the crate
            crate_dir_info = tarfile.TarInfo("test-0.1.0")
            crate_dir_info.type = tarfile.DIRTYPE
            tar.addfile(crate_dir_info)

            # Add a Cargo.toml file
            cargo_toml = """
[package]
name = "test"
version = "0.1.0"
authors = ["Test <test@example.com>"]
edition = "2018"
"""
            cargo_toml_info = tarfile.TarInfo("test-0.1.0/Cargo.toml")
            cargo_toml_bytes = cargo_toml.encode("utf-8")
            cargo_toml_info.size = len(cargo_toml_bytes)
            tar.addfile(cargo_toml_info, io.BytesIO(cargo_toml_bytes))

            # Add a src directory
            src_dir_info = tarfile.TarInfo("test-0.1.0/src")
            src_dir_info.type = tarfile.DIRTYPE
            tar.addfile(src_dir_info)

            # Add a main.rs file
            main_rs = 'fn main() { println!("Hello, world!"); }'
            main_rs_info = tarfile.TarInfo("test-0.1.0/src/main.rs")
            main_rs_bytes = main_rs.encode("utf-8")
            main_rs_info.size = len(main_rs_bytes)
            tar.addfile(main_rs_info, io.BytesIO(main_rs_bytes))

        # Get the tar data
        tar_data.seek(0)
        crate_content = tar_data.getvalue()

        # Create a LibraryFileAlias with the crate content
        librarian = getUtility(ILibraryFileAliasSet)
        lfa = librarian.create(
            "test-0.1.0.crate",
            len(crate_content),
            io.BytesIO(crate_content),
            "application/x-tar",
        )

        removeSecurityProxy(self.build).addFile(lfa)

        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()
        job = removeSecurityProxy(job)

        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "Missing Cargo publishing repository configuration",
            job.error_message,
        )

    def test_run_crate_extraction_failure(self):
        """Test failure when crate extraction fails."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with environment variables
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "CARGO_PUBLISH_URL": "https://example.com/registry",
                    "CARGO_PUBLISH_AUTH": "token123",
                }
            ),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create an invalid tar file (just some random bytes)
        invalid_crate_content = b"This is not a valid tar file"

        librarian = getUtility(ILibraryFileAliasSet)
        lfa = librarian.create(
            "invalid-0.1.0.crate",
            len(invalid_crate_content),
            io.BytesIO(invalid_crate_content),
            "application/x-tar",
        )

        removeSecurityProxy(self.build).addFile(lfa)

        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()
        job = removeSecurityProxy(job)

        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertIn(
            "Failed to extract crate",
            job.error_message,
        )

    def test_run_no_directory_in_crate(self):
        """Test failure when no directory is found in extracted crate."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with environment variables
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "CARGO_PUBLISH_URL": "https://example.com/registry",
                    "CARGO_PUBLISH_AUTH": "token123",
                }
            ),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        tar_data = io.BytesIO()

        # Create a tar archive with only files (no directories)
        with tarfile.open(fileobj=tar_data, mode="w") as tar:
            # Add a file at the root level (no directory)
            file_info = tarfile.TarInfo("file.txt")
            file_content = b"This is a file with no directory"
            file_info.size = len(file_content)
            tar.addfile(file_info, io.BytesIO(file_content))

        # Get the tar data
        tar_data.seek(0)
        crate_content = tar_data.getvalue()

        # Create a LibraryFileAlias with the crate content
        librarian = getUtility(ILibraryFileAliasSet)
        lfa = librarian.create(
            "nodirs-0.1.0.crate",
            len(crate_content),
            io.BytesIO(crate_content),
            "application/x-tar",
        )

        # Add the file to the build
        removeSecurityProxy(self.build).addFile(lfa)

        # Create and run the job
        job = getUtility(ICraftPublishingJobSource).create(self.build)

        JobRunner([job]).runAll()

        # Verify job failed with expected error message
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No directory found in extracted crate",
            job.error_message,
        )

    def test_run_missing_maven_config(self):
        """
        Test failure when Maven artifacts are found but Maven config is
        missing.
        """
        distribution = self.factory.makeDistribution(name="soss")

        self.pushConfig("craftbuild.soss")
        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        git_repository = self.factory.makeGitRepository(target=package)
        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a dummy jar file
        from io import BytesIO

        dummy_jar_content = b"dummy jar content"

        # Create a LibraryFileAlias with the jar content
        librarian = getUtility(ILibraryFileAliasSet)
        jar_lfa = librarian.create(
            "test-0.1.0.jar",
            len(dummy_jar_content),
            BytesIO(dummy_jar_content),
            "application/java-archive",
        )

        # Create a dummy pom file
        dummy_pom_content = b"<project>...</project>"

        # Create a LibraryFileAlias with the pom content
        pom_lfa = librarian.create(
            "pom.xml",
            len(dummy_pom_content),
            BytesIO(dummy_pom_content),
            "application/xml",
        )

        # Add the files to the build
        removeSecurityProxy(self.build).addFile(jar_lfa)
        removeSecurityProxy(self.build).addFile(pom_lfa)

        # Create and run the job
        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()
        job = removeSecurityProxy(job)

        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "Missing Maven publishing repository configuration",
            job.error_message,
        )
