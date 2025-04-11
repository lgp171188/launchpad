# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe jobs."""

__all__ = [
    "CraftRecipeJob",
    "CraftRecipeJobType",
    "CraftRecipeRequestBuildsJob",
    "CraftPublishingJob",
]

import json
import lzma
import os
import subprocess
import tarfile
import tempfile
from configparser import NoSectionError
from pathlib import Path

import transaction
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.databases.postgres import JSON
from storm.locals import Desc, Int, Reference
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer, provider

from lp.app.errors import NotFoundError
from lp.crafts.interfaces.craftrecipe import (
    CannotFetchSourcecraftYaml,
    CannotParseSourcecraftYaml,
    MissingSourcecraftYaml,
)
from lp.crafts.interfaces.craftrecipejob import (
    ICraftPublishingJob,
    ICraftPublishingJobSource,
    ICraftRecipeJob,
    ICraftRecipeRequestBuildsJob,
    ICraftRecipeRequestBuildsJobSource,
)
from lp.crafts.model.craftrecipebuild import CraftRecipeBuild
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.registry.interfaces.person import IPersonSet
from lp.services.config import config
from lp.services.database.bulk import load_related
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import EnumeratedSubclass, Job
from lp.services.job.runner import BaseRunnableJob
from lp.services.mail.sendmail import format_address_for_person
from lp.services.propertycache import cachedproperty
from lp.services.scripts import log


class CraftRecipeJobType(DBEnumeratedType):
    """Values that `ICraftRecipeJob.job_type` can take."""

    REQUEST_BUILDS = DBItem(
        0,
        """
        Request builds

        This job requests builds of a craft recipe.
        """,
    )

    PUBLISH_ARTIFACTS = DBItem(
        1,
        """
        Publish artifacts

        This job publishes craft recipe build artifacts to external
        repositories.
        """,
    )


@implementer(ICraftRecipeJob)
class CraftRecipeJob(StormBase):
    """See `ICraftRecipeJob`."""

    __storm_table__ = "CraftRecipeJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "CraftRecipe.id")

    job_type = DBEnum(
        name="job_type", enum=CraftRecipeJobType, allow_none=False
    )

    metadata = JSON("json_data", allow_none=False)

    def __init__(self, recipe, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param recipe: The `ICraftRecipe` this job relates to.
        :param job_type: The `CraftRecipeJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super().__init__()
        self.job = Job(**job_args)
        self.recipe = recipe
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return CraftRecipeJobDerived.makeSubclass(self)


@delegate_to(ICraftRecipeJob)
class CraftRecipeJobDerived(BaseRunnableJob, metaclass=EnumeratedSubclass):

    def __init__(self, recipe_job):
        self.context = recipe_job

    def __repr__(self):
        """An informative representation of the job."""
        return "<%s for ~%s/%s/+craft/%s>" % (
            self.__class__.__name__,
            self.recipe.owner.name,
            self.recipe.project.name,
            self.recipe.name,
        )

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `CraftRecipeJob` with the specified id, as the current
            `CraftRecipeJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        recipe_job = IStore(CraftRecipeJob).get(CraftRecipeJob, job_id)
        if recipe_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s"
                % (job_id, cls.class_job_type.title)
            )
        return cls(recipe_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IPrimaryStore(CraftRecipeJob).find(
            CraftRecipeJob,
            CraftRecipeJob.job_type == cls.class_job_type,
            CraftRecipeJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs),
        )
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super().getOopsVars()
        oops_vars.extend(
            [
                ("job_id", self.context.job.id),
                ("job_type", self.context.job_type.title),
                ("recipe_owner_name", self.context.recipe.owner.name),
                ("recipe_project_name", self.context.recipe.project.name),
                ("recipe_name", self.context.recipe.name),
            ]
        )
        return oops_vars


@implementer(ICraftRecipeRequestBuildsJob)
@provider(ICraftRecipeRequestBuildsJobSource)
class CraftRecipeRequestBuildsJob(CraftRecipeJobDerived):
    """A Job that processes a request for builds of a craft recipe."""

    class_job_type = CraftRecipeJobType.REQUEST_BUILDS

    user_error_types = (
        CannotParseSourcecraftYaml,
        MissingSourcecraftYaml,
    )
    retry_error_types = (CannotFetchSourcecraftYaml,)

    max_retries = 5

    config = config.ICraftRecipeRequestBuildsJobSource

    @classmethod
    def create(cls, recipe, requester, channels=None, architectures=None):
        """See `ICraftRecipeRequestBuildsJobSource`."""
        # architectures can be a iterable of strings or Processors
        # in the latter case, we need to convert them to strings
        if architectures and all(
            not isinstance(arch, str) for arch in architectures
        ):
            architectures = [
                architecture.name for architecture in architectures
            ]
        metadata = {
            "requester": requester.id,
            "channels": channels,
            # Really a set or None, but sets aren't directly
            # JSON-serialisable.
            "architectures": (
                list(architectures) if architectures is not None else None
            ),
        }
        recipe_job = CraftRecipeJob(recipe, cls.class_job_type, metadata)
        job = cls(recipe_job)
        job.celeryRunOnCommit()
        IStore(CraftRecipeJob).flush()
        return job

    @classmethod
    def findByRecipe(cls, recipe, statuses=None, job_ids=None):
        """See `ICraftRecipeRequestBuildsJobSource`."""
        clauses = [
            CraftRecipeJob.recipe == recipe,
            CraftRecipeJob.job_type == cls.class_job_type,
        ]
        if statuses is not None:
            clauses.extend(
                [
                    CraftRecipeJob.job == Job.id,
                    Job._status.is_in(statuses),
                ]
            )
        if job_ids is not None:
            clauses.append(CraftRecipeJob.job_id.is_in(job_ids))
        recipe_jobs = (
            IStore(CraftRecipeJob)
            .find(CraftRecipeJob, *clauses)
            .order_by(Desc(CraftRecipeJob.job_id))
        )

        def preload_jobs(rows):
            load_related(Job, rows, ["job_id"])

        return DecoratedResultSet(
            recipe_jobs,
            lambda recipe_job: cls(recipe_job),
            pre_iter_hook=preload_jobs,
        )

    @classmethod
    def getByRecipeAndID(cls, recipe, job_id):
        """See `ICraftRecipeRequestBuildsJobSource`."""
        recipe_job = (
            IStore(CraftRecipeJob)
            .find(
                CraftRecipeJob,
                CraftRecipeJob.job_id == job_id,
                CraftRecipeJob.recipe == recipe,
                CraftRecipeJob.job_type == cls.class_job_type,
            )
            .one()
        )
        if recipe_job is None:
            raise NotFoundError(
                "No REQUEST_BUILDS job with ID %d found for %r"
                % (job_id, recipe)
            )
        return cls(recipe_job)

    def getOperationDescription(self):
        return "requesting builds of %s" % self.recipe.name

    def getErrorRecipients(self):
        if self.requester is None or self.requester.preferredemail is None:
            return []
        return [format_address_for_person(self.requester)]

    @cachedproperty
    def requester(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        requester_id = self.metadata["requester"]
        return getUtility(IPersonSet).get(requester_id)

    @property
    def channels(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        return self.metadata["channels"]

    @property
    def architectures(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        architectures = self.metadata["architectures"]
        return set(architectures) if architectures is not None else None

    @property
    def date_created(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        return self.context.job.date_created

    @property
    def date_finished(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        return self.context.job.date_finished

    @property
    def error_message(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `ICraftRecipeRequestBuildsJob`."""
        self.metadata["error_message"] = message

    @property
    def build_request(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        return self.recipe.getBuildRequest(self.job.id)

    @property
    def builds(self):
        """See `ICraftRecipeRequestBuildsJob`."""
        build_ids = self.metadata.get("builds")
        if build_ids:
            return IStore(CraftRecipeBuild).find(
                CraftRecipeBuild, CraftRecipeBuild.id.is_in(build_ids)
            )
        else:
            return EmptyResultSet()

    @builds.setter
    def builds(self, builds):
        """See `ICraftRecipeRequestBuildsJob`."""
        self.metadata["builds"] = [build.id for build in builds]

    def run(self):
        """See `IRunnableJob`."""
        requester = self.requester
        if requester is None:
            log.info(
                "Skipping %r because the requester has been deleted." % self
            )
            return
        try:
            self.builds = self.recipe.requestBuildsFromJob(
                self.build_request,
                channels=self.channels,
                architectures=self.architectures,
                logger=log,
            )
            self.error_message = None
        except Exception as e:
            self.error_message = str(e)
            # The normal job infrastructure will abort the transaction, but
            # we want to commit instead: the only database changes we make
            # are to this job's metadata and should be preserved.
            transaction.commit()
            raise


@implementer(ICraftPublishingJob)
@provider(ICraftPublishingJobSource)
class CraftPublishingJob(CraftRecipeJobDerived):
    """
    A Job that publishes craft recipe build artifacts to external
    repositories.
    """

    class_job_type = CraftRecipeJobType.PUBLISH_ARTIFACTS

    user_error_types = ()
    retry_error_types = ()
    max_retries = 5

    config = config.ICraftPublishingJobSource

    @classmethod
    def create(cls, build):
        """See `ICraftPublishingJobSource`."""
        cls.metadata = {
            "build_id": build.id,
        }
        recipe_job = CraftRecipeJob(
            build.recipe, cls.class_job_type, cls.metadata
        )
        job = cls(recipe_job)
        job.celeryRunOnCommit()
        IStore(CraftRecipeJob).flush()
        return job

    @property
    def build_id(self):
        """See `ICraftPublishingJob`."""
        return self.metadata["build_id"]

    @cachedproperty
    def build(self):
        """See `ICraftPublishingJob`."""
        return IStore(CraftRecipeBuild).get(CraftRecipeBuild, self.build_id)

    @property
    def error_message(self):
        """See `ICraftPublishingJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `ICraftPublishingJob`."""
        self.metadata["error_message"] = message

    def getPublishingType(self, archive_path):
        """Determine the type of artifacts to publish.

        :param archive_path: Optional path to an already downloaded archive
        file
        :return: "cargo", "maven", or None if no publishable artifacts found
        """
        try:
            has_crate = False
            has_jar = False
            has_pom = False

            with lzma.open(archive_path) as xz:
                with tarfile.open(fileobj=xz) as tar:
                    for member in tar.getmembers():
                        if member.name.endswith(".crate"):
                            has_crate = True
                        elif member.name.endswith(".jar"):
                            has_jar = True
                        elif member.name == "pom.xml":
                            has_pom = True

                        if has_crate:
                            return "cargo"
                        if has_jar and has_pom:
                            return "maven"
        except Exception:
            pass

        return None

    def run(self):
        """See `IRunnableJob`."""
        try:
            # Get the distribution name to access the correct configuration
            distribution_name = None
            git_repo = self.build.recipe.git_repository
            if git_repo is not None:
                if IDistributionSourcePackage.providedBy(git_repo.target):
                    distribution_name = git_repo.target.distribution.name

            if not distribution_name:
                self.error_message = (
                    "Could not determine distribution for build"
                )
                raise Exception(self.error_message)

            # Get environment variables from configuration
            try:
                env_vars_json = config["craftbuild." + distribution_name][
                    "environment_variables"
                ]
                if env_vars_json and env_vars_json.lower() != "none":
                    env_vars = json.loads(env_vars_json)
                    # Replace auth placeholders
                    for key, value in env_vars.items():
                        if (
                            isinstance(value, str)
                            and "%(write_auth)s" in value
                        ):
                            env_vars[key] = value.replace(
                                "%(write_auth)s",
                                config.artifactory.write_credentials,
                            )
                else:
                    env_vars = {}
            except (NoSectionError, KeyError):
                self.error_message = (
                    f"No configuration found for {distribution_name}"
                )
                raise Exception(self.error_message)

            # Find the archive file in the build
            archive_file = None
            for _, lfa, _ in self.build.getFiles():
                if lfa.filename.endswith(".tar.xz"):
                    archive_file = lfa
                    break

            if archive_file is None:
                raise Exception("No archive file found in build")

            # Process the archive file
            with tempfile.TemporaryDirectory() as tmpdir:
                # Download the archive file to a temporary location
                archive_path = os.path.join(tmpdir, "archive.tar.xz")

                # Use the correct pattern for LibraryFileAlias
                archive_file.open()  # This sets _datafile but returns None
                try:
                    with open(archive_path, "wb") as f:
                        f.write(archive_file.read())
                finally:
                    archive_file.close()

                # Determine what to publish using the getPublishingType method
                publishing_type = self.getPublishingType(archive_path)

                if publishing_type is None:
                    raise Exception(
                        "No publishable artifacts found in archive"
                    )

                # Extract the archive
                extract_dir = os.path.join(tmpdir, "extract")
                os.makedirs(extract_dir, exist_ok=True)

                try:
                    with lzma.open(archive_path) as xz:
                        with tarfile.open(fileobj=xz, mode="r") as tar:
                            tar.extractall(path=extract_dir)
                except Exception as e:
                    raise Exception(f"Failed to extract archive: {str(e)}")

                # Publish artifacts based on type
                if publishing_type == "cargo":
                    self._publish_rust_crate(extract_dir, env_vars)
                elif publishing_type == "maven":
                    self._publish_maven_artifact(extract_dir, env_vars)

        except Exception as e:
            self.error_message = str(e)
            # The normal job infrastructure will abort the transaction, but
            # we want to commit instead: the only database changes we make
            # are to this job's metadata and should be preserved.
            transaction.commit()
            raise

    def _publish_rust_crate(self, extract_dir, env_vars):
        """Publish Rust crates found in the extracted archive.

        :param extract_dir: Path to the extracted archive
        :param env_vars: Environment variables from configuration
        :raises: Exception if publishing fails
        """
        # Look for specific Cargo publishing repository configuration
        cargo_publish_url = env_vars.get("CARGO_PUBLISH_URL")
        cargo_publish_auth = env_vars.get("CARGO_PUBLISH_AUTH")

        if not cargo_publish_url or not cargo_publish_auth:
            raise Exception(
                "Missing Cargo publishing repository configuration"
            )

        # Look for .crate files
        crate_files = list(Path(extract_dir).rglob("*.crate"))
        crate_file = crate_files[0]

        # Set up cargo config
        cargo_dir = os.path.join(extract_dir, ".cargo")
        os.makedirs(cargo_dir, exist_ok=True)

        # Create config.toml
        with open(os.path.join(cargo_dir, "config.toml"), "w") as f:
            f.write(
                """
[registry]
global-credential-providers = ["cargo:token"]

[registries.launchpad]
index = "{}"
""".format(
                    cargo_publish_url
                )
            )

        # Create credentials.toml
        with open(os.path.join(cargo_dir, "credentials.toml"), "w") as f:
            f.write(
                """
[registries.launchpad]
token = "Bearer {}"
""".format(
                    cargo_publish_auth
                )
            )

        # Run cargo publish
        result = subprocess.run(
            [
                "cargo",
                "publish",
                "--no-verify",
                "--allow-dirty",
                "--registry",
                "launchpad",
            ],
            cwd=os.path.dirname(str(crate_file)),
            env={"CARGO_HOME": cargo_dir},
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise Exception(f"Failed to publish crate: {result.stderr}")

    def _publish_maven_artifact(self, extract_dir, env_vars):
        """Publish Maven artifacts found in the extracted archive.

        :param extract_dir: Path to the extracted archive
        :param env_vars: Environment variables from configuration
        :raises: Exception if publishing fails
        """
        # Look for specific Maven publishing repository configuration
        maven_publish_url = env_vars.get("MAVEN_PUBLISH_URL")
        maven_publish_auth = env_vars.get("MAVEN_PUBLISH_AUTH")

        if not maven_publish_url or not maven_publish_auth:
            raise Exception(
                "Missing Maven publishing repository configuration"
            )

        # Find the JAR file and pom.xml in the extracted archive
        jar_file = None
        pom_file = None

        for root, _, files in os.walk(extract_dir):
            for filename in files:
                if filename.endswith(".jar"):
                    jar_file = os.path.join(root, filename)
                elif filename == "pom.xml":
                    pom_file = os.path.join(root, filename)

        if jar_file is None:
            raise Exception("No .jar file found in archive")

        if pom_file is None:
            raise Exception("No pom.xml file found in archive")

        # Set up Maven settings
        maven_dir = os.path.join(extract_dir, ".m2")
        os.makedirs(maven_dir, exist_ok=True)

        # Extract username and password from auth string
        if ":" in maven_publish_auth:
            username, password = maven_publish_auth.split(":", 1)
        else:
            username = "token"
            password = maven_publish_auth

        # Create settings.xml with server configuration for the
        # publishing repository
        settings_xml = f"""<settings>
<servers>
    <server>
        <id>launchpad-publish</id>
        <username>{username}</username>
        <password>{password}</password>
    </server>
</servers>
</settings>"""

        with open(os.path.join(maven_dir, "settings.xml"), "w") as f:
            f.write(settings_xml)

        # Run mvn deploy using the pom file
        result = subprocess.run(
            [
                "mvn",
                "deploy:deploy-file",
                f"-DpomFile={pom_file}",
                f"-Dfile={jar_file}",
                "-DrepositoryId=launchpad-publish",
                f"-Durl={maven_publish_url}",
                "--settings={}".format(
                    os.path.join(maven_dir, "settings.xml")
                ),
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise Exception(
                f"Failed to publish Maven artifact: {result.stderr}"
            )
