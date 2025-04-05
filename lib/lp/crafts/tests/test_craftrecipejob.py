# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for craft recipe jobs."""

import json
from textwrap import dedent
from unittest.mock import patch

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
    IMavenArtifactUploadJobSource,
    IRustCrateUploadJobSource,
)
from lp.crafts.model.craftrecipejob import (
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
        job = getUtility(IRustCrateUploadJobSource).create(
            self.build, self.build.requester
        )
        self.assertProvides(job, IRustCrateUploadJobSource)

    def test_create(self):
        # RustCrateUploadJob.create creates a RustCrateUploadJob with the
        # correct attributes.
        job = getUtility(IRustCrateUploadJobSource).create(
            self.build, self.build.requester
        )
        self.assertThat(
            job,
            MatchesStructure(
                job_type=Equals(CraftRecipeJobType.RUST_CRATE_UPLOAD),
                recipe=Equals(self.recipe),
                requester=Equals(self.build.requester),
                build=Equals(self.build),
                error_message=Is(None),
            ),
        )

    @patch("subprocess.run")
    @patch("os.path.exists")
    def test_run_success(self, mock_exists, mock_run):
        # Test successful execution of the job
        mock_exists.return_value = True
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Published crate successfully"

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {"CARGO_REGISTRY_TOKEN": "test-token"}
                )
            }
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IRustCrateUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job completed successfully
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.COMPLETED, job.job.status)
            self.assertIsNone(job.error_message)

            # Verify cargo command was called correctly
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual(["cargo", "publish"], args[0][:2])
            self.assertTrue("capture_output" in kwargs)
            self.assertTrue("text" in kwargs)
            self.assertTrue("env" in kwargs)
            self.assertEqual(
                "test-token", kwargs["env"]["CARGO_REGISTRY_TOKEN"]
            )

    @patch("subprocess.run")
    @patch("os.path.exists")
    def test_run_failure_cargo_command(self, mock_exists, mock_run):
        # Test failure when cargo command fails
        mock_exists.return_value = True
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = (
            "Failed to publish crate: permission denied"
        )

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {"CARGO_REGISTRY_TOKEN": "test-token"}
                )
            }
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IRustCrateUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job failed with error message
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.FAILED, job.job.status)
            self.assertEqual(
                "Failed to publish crate: permission denied",
                job.error_message,
            )

    @patch("os.path.exists")
    def test_run_failure_no_cargo_toml(self, mock_exists):
        # Test failure when Cargo.toml doesn't exist
        mock_exists.return_value = False

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {"CARGO_REGISTRY_TOKEN": "test-token"}
                )
            }
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IRustCrateUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job failed with error message
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.FAILED, job.job.status)
            self.assertEqual(
                "Cargo.toml not found in build artifacts", job.error_message
            )

    def test_run_failure_missing_config(self):
        # Test failure when configuration is missing
        job = getUtility(IRustCrateUploadJobSource).create(
            self.build, self.build.requester
        )
        JobRunner([job]).runAll()

        # Verify job failed with error message
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No configuration found for ubuntu", job.error_message
        )


class TestMavenArtifactUploadJob(TestCaseWithFactory):
    """Test the MavenArtifactUploadJob."""

    layer = CeleryJobLayer

    def setUp(self):
        super().setUp()
        self.useFixture(FakeLogger())
        self.useFixture(FeatureFixture({CRAFT_RECIPE_ALLOW_CREATE: "on"}))
        self.recipe = self.factory.makeCraftRecipe()
        self.build = self.factory.makeCraftRecipeBuild(recipe=self.recipe)

    def test_provides_interface(self):
        # MavenArtifactUploadJob provides IMavenArtifactUploadJob.
        job = getUtility(IMavenArtifactUploadJobSource).create(
            self.build, self.build.requester
        )
        self.assertProvides(job, IMavenArtifactUploadJobSource)

    def test_create(self):
        # MavenArtifactUploadJob.create creates a MavenArtifactUploadJob
        # with the correct attributes.
        job = getUtility(IMavenArtifactUploadJobSource).create(
            self.build, self.build.requester
        )
        self.assertThat(
            job,
            MatchesStructure(
                job_type=Equals(CraftRecipeJobType.MAVEN_ARTIFACT_UPLOAD),
                recipe=Equals(self.recipe),
                requester=Equals(self.build.requester),
                build=Equals(self.build),
                error_message=Is(None),
            ),
        )

    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("builtins.open")
    def test_run_success(self, mock_open, mock_exists, mock_run):
        # Test successful execution of the job
        mock_exists.return_value = True
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Published Maven artifact successfully"

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {
                        "MAVEN_PUBLISH_URL": "https://repo.example.com/maven",
                        "MAVEN_PUBLISH_AUTH": "username:password",
                    }
                )
            },
            "artifactory": {"write_credentials": "test-write-auth"},
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IMavenArtifactUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job completed successfully
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.COMPLETED, job.job.status)
            self.assertIsNone(job.error_message)

            # Verify maven command was called correctly
            mock_run.assert_called_once()
            args, kwargs = mock_run.call_args
            self.assertEqual("mvn", args[0][0])
            self.assertEqual("deploy:deploy-file", args[0][1])
            self.assertTrue("capture_output" in kwargs)
            self.assertTrue("text" in kwargs)

    @patch("subprocess.run")
    @patch("os.path.exists")
    @patch("builtins.open")
    def test_run_failure_maven_command(self, mock_open, mock_exists, mock_run):
        # Test failure when maven command fails
        mock_exists.return_value = True
        mock_run.return_value.returncode = 1
        mock_run.return_value.stderr = (
            "Failed to deploy artifact: permission denied"
        )

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {
                        "MAVEN_PUBLISH_URL": "https://repo.example.com/maven",
                        "MAVEN_PUBLISH_AUTH": "username:password",
                    }
                )
            },
            "artifactory": {"write_credentials": "test-write-auth"},
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IMavenArtifactUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job failed with error message
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.FAILED, job.job.status)
            self.assertEqual(
                "Failed to publish Maven artifact: permission denied",
                job.error_message,
            )

    @patch("os.path.exists")
    def test_run_failure_no_pom_file(self, mock_exists):
        # Test failure when pom.xml doesn't exist
        mock_exists.side_effect = lambda path: (
            False if path.endswith(".pom") else True
        )

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {
                        "MAVEN_PUBLISH_URL": "https://repo.example.com/maven",
                        "MAVEN_PUBLISH_AUTH": "username:password",
                    }
                )
            },
            "artifactory": {"write_credentials": "test-write-auth"},
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IMavenArtifactUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job failed with error message
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.FAILED, job.job.status)
            self.assertEqual(
                "No POM file found in build artifacts", job.error_message
            )

    @patch("os.path.exists")
    def test_run_failure_no_jar_file(self, mock_exists):
        # Test failure when JAR file doesn't exist
        mock_exists.side_effect = lambda path: (
            False if path.endswith(".jar") else True
        )

        # Create a test config section
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps(
                    {
                        "MAVEN_PUBLISH_URL": "https://repo.example.com/maven",
                        "MAVEN_PUBLISH_AUTH": "username:password",
                    }
                )
            },
            "artifactory": {"write_credentials": "test-write-auth"},
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IMavenArtifactUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job failed with error message
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.FAILED, job.job.status)
            self.assertEqual(
                "No JAR file found in build artifacts", job.error_message
            )

    def test_run_failure_missing_config(self):
        # Test failure when configuration is missing
        job = getUtility(IMavenArtifactUploadJobSource).create(
            self.build, self.build.requester
        )
        JobRunner([job]).runAll()

        # Verify job failed with error message
        job = removeSecurityProxy(job)
        self.assertEqual(JobStatus.FAILED, job.job.status)
        self.assertEqual(
            "No configuration found for ubuntu", job.error_message
        )

    def test_run_failure_missing_maven_config(self):
        # Test failure when Maven-specific configuration is missing
        test_config = {
            "craftbuild.ubuntu": {
                "environment_variables": json.dumps({"OTHER_VAR": "value"})
            }
        }

        with patch.dict(config._sections, test_config):
            job = getUtility(IMavenArtifactUploadJobSource).create(
                self.build, self.build.requester
            )
            JobRunner([job]).runAll()

            # Verify job failed with error message
            job = removeSecurityProxy(job)
            self.assertEqual(JobStatus.FAILED, job.job.status)
            self.assertEqual(
                "Missing Maven publishing repository configuration",
                job.error_message,
            )
