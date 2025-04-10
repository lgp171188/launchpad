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

    def test_run_failure_no_archive_file(self):
        """Test failure when no archive file is found in the build."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with environment variables but no Cargo publishing info
        # We just need a config section for the distribution name
        self.pushConfig("craftbuild.soss")
        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        git_repository = self.factory.makeGitRepository(target=package)
        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a job without adding any files to the build
        job = getUtility(ICraftPublishingJobSource).create(self.build)

        # Run the job - it should fail because there are no files
        JobRunner([job]).runAll()

        # Verify job failed with error message
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No archive file found in build",
            job.error_message,
        )

    def test_run_no_publishable_artifacts(self):
        """Test failure when no publishable artifacts are found."""
        distribution = self.factory.makeDistribution(name="soss")
        self.pushConfig("craftbuild.soss")
        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        git_repository = self.factory.makeGitRepository(target=package)
        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a tar.xz file with a dummy file (but no artifacts)
        import lzma
        import os
        import tarfile
        import tempfile
        from io import BytesIO

        # Create a temporary directory to work in
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a dummy file
            dummy_file_path = os.path.join(tmpdir, "test.txt")
            with open(dummy_file_path, "w") as f:
                f.write("test content")

            # Create a tar file
            tar_path = os.path.join(tmpdir, "archive.tar")
            with tarfile.open(tar_path, "w") as tar:
                tar.add(dummy_file_path, arcname="test.txt")

            # Compress the tar file with lzma
            tar_xz_path = os.path.join(tmpdir, "archive.tar.xz")
            with open(tar_path, "rb") as f_in:
                with lzma.open(tar_xz_path, "wb") as f_out:
                    f_out.write(f_in.read())

            # Read the compressed file
            with open(tar_xz_path, "rb") as f:
                tar_xz_content = f.read()

        librarian = getUtility(ILibraryFileAliasSet)
        lfa = librarian.create(
            "archive.tar.xz",
            len(tar_xz_content),
            BytesIO(tar_xz_content),
            "application/x-xz",
        )

        # Add the file to the build
        removeSecurityProxy(self.build).addFile(lfa)

        job = getUtility(ICraftPublishingJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No publishable artifacts found in archive",
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

        job = getUtility(ICraftPublishingJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "Missing Cargo publishing repository configuration",
            job.error_message,
        )

    def test_run_failure_no_crate_file(self):
        """Test failure when no crate files are found in the archive."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with proper Cargo publishing info
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "CARGO_PUBLISH_URL": "https://example.com/cargo",
                    "CARGO_PUBLISH_AUTH": "user:pass",
                }
            ),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a tar.xz file with a dummy file (but no crate files)
        import tarfile
        from io import BytesIO

        # Create a temporary tar.xz file with a dummy file
        tar_content = BytesIO()
        with tarfile.open(fileobj=tar_content, mode="w:xz") as tar:
            # Add a dummy file to the archive
            info = tarfile.TarInfo("test.txt")
            data = b"test content"
            info.size = len(data)
            tar.addfile(info, BytesIO(data))

        # Get the tar.xz content
        tar_content.seek(0)
        content = tar_content.read()

        # Create a LibraryFileAlias
        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.tar.xz",
            db_only=True,  # We'll mock the content access
        )

        # Create a mock file-like object that returns our content
        mock_file = BytesIO(content)

        # Mock the open method of the LibraryFileAlias
        def mock_open():
            mock_file.seek(0)
            return mock_file

        self.patch(removeSecurityProxy(mock_lfa), "open", mock_open)

        # Add the file to the build
        removeSecurityProxy(self.build).addFile(mock_lfa)

        job = getUtility(ICraftPublishingJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No .crate file found in archive",
            job.error_message,
        )

    def test_run_failure_cargo_publish(self):
        """Test failure when cargo publish command fails."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with proper Cargo publishing info
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "CARGO_PUBLISH_URL": "https://example.com/cargo",
                    "CARGO_PUBLISH_AUTH": "user:pass",
                }
            ),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a tar.xz file with a dummy crate file
        import subprocess
        import tarfile
        from io import BytesIO
        from unittest.mock import Mock

        # Create a temporary tar.xz file with a crate file
        tar_content = BytesIO()
        with tarfile.open(fileobj=tar_content, mode="w:xz") as tar:
            # Add a dummy crate file
            info = tarfile.TarInfo("test-package.crate")
            data = b"dummy crate content"
            info.size = len(data)
            tar.addfile(info, BytesIO(data))

        # Get the tar.xz content
        tar_content.seek(0)
        content = tar_content.read()

        # Create a LibraryFileAlias
        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.tar.xz",
            db_only=True,  # We'll mock the content access
        )

        # Create a mock file-like object that returns our content
        mock_file = BytesIO(content)

        # Mock the open method of the LibraryFileAlias
        def mock_open():
            mock_file.seek(0)
            return mock_file

        self.patch(removeSecurityProxy(mock_lfa), "open", mock_open)

        # Add the file to the build
        removeSecurityProxy(self.build).addFile(mock_lfa)

        # Mock subprocess.run to simulate a cargo command failure
        mock_result = Mock()
        mock_result.returncode = 1
        mock_result.stderr = (
            "error: failed to publish to registry at "
            "https://example.com/cargo\n\nCaused by:\n  The package "
            "test-package cannot be found in the registry."
        )

        self.patch(subprocess, "run", lambda *args, **kwargs: mock_result)

        job = getUtility(ICraftPublishingJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "Failed to publish crate: error: failed to publish to registry at "
            "https://example.com/cargo\n\nCaused by:\n  The package "
            "test-package cannot be found in the registry.",
            job.error_message,
        )

    def test_run_success_cargo(self):
        """Test successful execution of the Rust crate upload job."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with proper Cargo publishing info
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "CARGO_PUBLISH_URL": "https://example.com/cargo",
                    "CARGO_PUBLISH_AUTH": "user:pass",
                }
            ),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )

        git_repository = self.factory.makeGitRepository(target=package)

        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a tar.xz file with a dummy crate file
        import subprocess
        import tarfile
        from io import BytesIO
        from unittest.mock import Mock

        # Create a temporary tar.xz file with a crate file
        tar_content = BytesIO()
        with tarfile.open(fileobj=tar_content, mode="w:xz") as tar:
            # Add a dummy crate file
            info = tarfile.TarInfo("test-package.crate")
            data = b"dummy crate content"
            info.size = len(data)
            tar.addfile(info, BytesIO(data))

        # Get the tar.xz content
        tar_content.seek(0)
        content = tar_content.read()

        # Create a LibraryFileAlias
        mock_lfa = self.factory.makeLibraryFileAlias(
            filename="test.tar.xz",
            db_only=True,  # We'll mock the content access
        )

        # Create a mock file-like object that returns our content
        mock_file = BytesIO(content)

        # Mock the open method of the LibraryFileAlias
        def mock_open():
            mock_file.seek(0)
            return mock_file

        self.patch(removeSecurityProxy(mock_lfa), "open", mock_open)

        # Add the file to the build
        removeSecurityProxy(self.build).addFile(mock_lfa)

        # Mock subprocess.run to simulate a successful cargo command
        mock_result = Mock()
        mock_result.returncode = 0

        self.patch(subprocess, "run", lambda *args, **kwargs: mock_result)

        job = getUtility(ICraftPublishingJobSource).create(self.build)

        JobRunner([job]).runAll()

        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.COMPLETED, job.job.status)
        self.assertIsNone(job.error_message)
