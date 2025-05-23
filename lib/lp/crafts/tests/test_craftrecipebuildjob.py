# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import io
import json
import tarfile

from fixtures import FakeLogger
from testtools.matchers import Equals, Is, MatchesStructure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.crafts.interfaces.craftrecipe import CRAFT_RECIPE_ALLOW_CREATE
from lp.crafts.interfaces.craftrecipebuildjob import (
    ICraftPublishingJob,
    ICraftPublishingJobSource,
    ICraftRecipeBuildJob,
)
from lp.crafts.model.craftrecipebuildjob import (
    CraftPublishingJob,
    CraftRecipeBuildJob,
    CraftRecipeBuildJobType,
)
from lp.services.features.testing import FeatureFixture
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.runner import JobRunner
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.testing import TestCaseWithFactory
from lp.testing.layers import CeleryJobLayer, ZopelessDatabaseLayer


class TestCraftRecipeBuildJob(TestCaseWithFactory):

    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))

    def test_provides_interface(self):
        # CraftRecipeBuildJob provides ICraftRecipeBuildJob.
        build = self.factory.makeCraftRecipeBuild()
        self.assertProvides(
            CraftRecipeBuildJob(
                build,
                CraftRecipeBuildJobType.PUBLISH_ARTIFACTS,
                {},
            ),
            ICraftRecipeBuildJob,
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
                class_job_type=Equals(
                    CraftRecipeBuildJobType.PUBLISH_ARTIFACTS
                ),
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
                    "CARGO_PUBLISH_AUTH": "lp:token123",
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
                    "CARGO_PUBLISH_AUTH": "lp:token123",
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

    def test_run_cargo_publish_success(self):
        """Test success when a crate is found and Cargo config is present."""
        distribution = self.factory.makeDistribution(name="soss")
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "CARGO_PUBLISH_URL": "https://example.com/registry",
                    "CARGO_PUBLISH_AUTH": "lp:token123",
                }
            ),
        )
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
            crate_dir_info.mode = 0o755  # rwxr-xr-x
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

        # Create a mock return value for subprocess.run
        mock_completed_process = type(
            "MockCompletedProcess",
            (),
            {"returncode": 0, "stdout": "", "stderr": ""},
        )()

        from lp.crafts.model.craftrecipebuildjob import (
            subprocess as crbj_subprocess,
        )

        # Mock subprocess.run to only mock cargo calls
        subprocess_calls = []
        original_run = crbj_subprocess.run

        def mock_run(*args, **kwargs):
            if args and len(args[0]) > 0 and "cargo" in args[0][0]:
                subprocess_calls.append((args, kwargs))
                return mock_completed_process
            return original_run(*args, **kwargs)

        self.patch(crbj_subprocess, "run", mock_run)

        # Create and run the job
        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()

        # Verify job succeeded
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.COMPLETED, job.job.status)

        # Find the call for cargo publish (should be the second call)
        cargo_call = None
        for call in subprocess_calls:
            args = call[0][0]
            if "cargo" in args[0] and "publish" in args:
                cargo_call = call
                break

        self.assertIsNotNone(cargo_call, "No cargo publish command was called")

        # Extract the command arguments and verify them
        args = cargo_call[0][0]
        self.assertEqual("cargo", args[0])
        self.assertEqual("publish", args[1])
        self.assertIn("--no-verify", args)
        self.assertIn("--allow-dirty", args)
        self.assertIn("--registry", args)

        # Check registry argument
        registry_index = args.index("--registry") + 1
        self.assertEqual("launchpad", args[registry_index])

        # Verify that the correct working directory was used
        kwargs = cargo_call[1]
        self.assertIn("cwd", kwargs)
        cwd = kwargs["cwd"]
        self.assertTrue(
            cwd.endswith("test-0.1.0"),
            f"Expected working directory to end with 'test-0.1.0', got {cwd}",
        )

        # Verify CARGO_HOME was set in the environment
        self.assertIn("env", kwargs)
        env = kwargs["env"]
        self.assertIn("CARGO_HOME", env)

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

    def test_run_maven_deploy_success(self):
        """Test successful Maven artifact publishing."""
        distribution = self.factory.makeDistribution(name="soss")

        # Set up config with Maven publishing environment variables
        self.pushConfig(
            "craftbuild.soss",
            environment_variables=json.dumps(
                {
                    "MAVEN_PUBLISH_URL": "https://example.com/maven",
                    "MAVEN_PUBLISH_AUTH": "maven_user:maven_password",
                }
            ),
        )

        package = self.factory.makeDistributionSourcePackage(
            distribution=distribution
        )
        git_repository = self.factory.makeGitRepository(target=package)
        removeSecurityProxy(self.recipe).git_repository = git_repository

        # Create a dummy jar file
        dummy_jar_content = b"dummy jar content"
        librarian = getUtility(ILibraryFileAliasSet)
        jar_lfa = librarian.create(
            "test-artifact-0.1.0.jar",
            len(dummy_jar_content),
            io.BytesIO(dummy_jar_content),
            "application/java-archive",
        )

        # Create a dummy pom file
        pom_content = """
    <project>
        <modelVersion>4.0.0</modelVersion>
        <groupId>com.example</groupId>
        <artifactId>test-artifact</artifactId>
        <version>0.1.0</version>
    </project>
    """
        pom_bytes = pom_content.encode("utf-8")
        pom_lfa = librarian.create(
            "pom.xml",
            len(pom_bytes),
            io.BytesIO(pom_bytes),
            "application/xml",
        )

        # Add the files to the build
        removeSecurityProxy(self.build).addFile(jar_lfa)
        removeSecurityProxy(self.build).addFile(pom_lfa)

        # Create a mock return value for subprocess.run
        mock_completed_process = type(
            "MockCompletedProcess",
            (),
            {"returncode": 0, "stdout": "", "stderr": ""},
        )()

        from lp.crafts.model.craftrecipebuildjob import (
            subprocess as crbj_subprocess,
        )

        # Mock subprocess.run to only mock mvn calls
        subprocess_calls = []
        original_run = crbj_subprocess.run

        def mock_run(*args, **kwargs):
            if args and len(args[0]) > 0 and "mvn" in args[0][0]:
                subprocess_calls.append((args, kwargs))
                return mock_completed_process
            return original_run(*args, **kwargs)

        self.patch(crbj_subprocess, "run", mock_run)

        # Create and run the job
        job = getUtility(ICraftPublishingJobSource).create(self.build)
        JobRunner([job]).runAll()

        # Verify job succeeded
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.COMPLETED, job.job.status)

        # Find the call for mvn deploy
        mvn_call = None
        for call in subprocess_calls:
            args = call[0][0]
            if "mvn" in args[0] and "deploy:deploy-file" in args:
                mvn_call = call
                break

        self.assertIsNotNone(mvn_call, "No mvn deploy command was called")

        # Extract the command arguments and verify them
        args = mvn_call[0][0]
        self.assertEqual("mvn", args[0])
        self.assertEqual("deploy:deploy-file", args[1])

        # Convert args to a string to make it easier to check for parameters
        args_str = " ".join(args)

        # Check for required Maven arguments
        self.assertIn("-DrepositoryId=central", args_str)
        self.assertIn("-Durl=https://example.com/maven", args_str)

        # Verify that the POM and JAR files are correctly referenced
        pom_found = False
        jar_found = False
        for arg in args:
            if arg.startswith("-DpomFile=") and "pom.xml" in arg:
                pom_found = True
            if arg.startswith("-Dfile=") and ".jar" in arg:
                jar_found = True

        self.assertTrue(
            pom_found, "POM file parameter not found in Maven command"
        )
        self.assertTrue(
            jar_found, "JAR file parameter not found in Maven command"
        )

        # Verify settings file path is included
        settings_found = False
        for arg in args:
            if arg.startswith("--settings=") and ".m2/settings.xml" in arg:
                settings_found = True

        self.assertTrue(
            settings_found, "Maven settings file path not found in command"
        )

        # Verify working directory was set correctly
        kwargs = mvn_call[1]
        self.assertIn("cwd", kwargs)
