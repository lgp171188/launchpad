# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe build jobs."""

__all__ = [
    "CraftPublishingJob",
    "CraftRecipeBuildJob",
    "CraftRecipeBuildJobType",
]

import glob
import json
import os
import subprocess
import tempfile
from configparser import NoSectionError
from urllib.parse import urlparse

import transaction
import yaml
from artifactory import ArtifactoryPath
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.databases.postgres import JSON
from storm.locals import Int, Reference
from zope.interface import implementer, provider

from lp.app.errors import NotFoundError
from lp.crafts.interfaces.craftrecipebuildjob import (
    ICraftPublishingJob,
    ICraftPublishingJobSource,
    ICraftRecipeBuildJob,
)
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
)
from lp.services.config import config
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import EnumeratedSubclass, Job
from lp.services.job.runner import BaseRunnableJob
from lp.services.scripts import log

# Timeout in seconds for HTTP requests made through Cargo.
# Prevents builds from hanging if network connectivity issues occur.
CARGO_HTTP_TIMEOUT = 60


class CraftRecipeBuildJobType(DBEnumeratedType):
    """Values that `ICraftRecipeBuildJob.job_type` can take."""

    PUBLISH_ARTIFACTS = DBItem(
        0,
        "Publish artifacts to external repositories",
    )


@implementer(ICraftRecipeBuildJob)
class CraftRecipeBuildJob(StormBase):
    """See `ICraftRecipeBuildJob`."""

    __storm_table__ = "CraftRecipeBuildJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    build_id = Int(name="build", allow_none=False)
    build = Reference(build_id, "CraftRecipeBuild.id")

    job_type = DBEnum(enum=CraftRecipeBuildJobType, allow_none=False)

    metadata = JSON("json_data", allow_none=False)

    def __init__(self, build, job_type, metadata, **job_args):
        super().__init__()
        self.job = Job(**job_args)
        self.build = build
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return CraftRecipeBuildJobDerived.makeSubclass(self)


@delegate_to(ICraftRecipeBuildJob)
class CraftRecipeBuildJobDerived(
    BaseRunnableJob, metaclass=EnumeratedSubclass
):
    """See `ICraftRecipeBuildJob`."""

    def __init__(self, craft_recipe_build_job):
        self.context = craft_recipe_build_job

    def __repr__(self):
        """An informative representation of the job."""
        recipe = self.build.recipe
        return (
            f"<{self.__class__.__name__} for "
            f"~{recipe.owner.name}/{recipe.project.name}/+craft/{recipe.name}/"
            f"+build/{self.build.id}>"
        )

    @classmethod
    def get(cls, job_id):
        craft_recipe_build_job = IStore(CraftRecipeBuildJob).get(
            CraftRecipeBuildJob, job_id
        )
        if craft_recipe_build_job.job_type != cls.class_job_type:
            raise NotFoundError(
                f"No object found with id {job_id} "
                f"and type {cls.class_job_type.title}"
            )
        return cls(craft_recipe_build_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IPrimaryStore(CraftRecipeBuildJob).find(
            CraftRecipeBuildJob,
            CraftRecipeBuildJob.job_type == cls.class_job_type,
            CraftRecipeBuildJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs),
        )
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super().getOopsVars()
        recipe = self.context.build.recipe
        oops_vars.extend(
            [
                ("job_id", self.context.job.id),
                ("job_type", self.context.job_type.title),
                ("build_id", self.context.build.id),
                ("recipe_owner_name", recipe.owner.name),
                ("recipe_project_name", recipe.project.name),
                ("recipe_name", recipe.name),
            ]
        )
        return oops_vars


@implementer(ICraftPublishingJob)
@provider(ICraftPublishingJobSource)
class CraftPublishingJob(CraftRecipeBuildJobDerived):
    """
    A Job that publishes craft recipe build artifacts to external
    repositories.
    """

    class_job_type = CraftRecipeBuildJobType.PUBLISH_ARTIFACTS

    user_error_types = ()
    retry_error_types = ()
    max_retries = 5

    task_queue = "native_publisher_job"
    config = config.ICraftPublishingJobSource

    @classmethod
    def create(cls, build):
        """See `ICraftPublishingJobSource`."""
        metadata = {
            "build_id": build.id,
        }
        recipe_job = CraftRecipeBuildJob(build, cls.class_job_type, metadata)
        job = cls(recipe_job)
        job.celeryRunOnCommit()
        IStore(CraftRecipeBuildJob).flush()
        return job

    @property
    def error_message(self):
        """See `ICraftPublishingJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `ICraftPublishingJob`."""
        self.metadata["error_message"] = message

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

            # Check if HTTP proxy is configured - log a warning but continue
            if not config.launchpad.http_proxy:
                log.warning(
                    "No HTTP proxy configured for artifact publishing. "
                    "This may cause connectivity issues with external "
                    "repositories."
                )

            # Check if we have a .crate file or .jar file
            crate_file = None
            jar_file = None
            pom_file = None

            for _, lfa, _ in self.build.getFiles():
                if lfa.filename.endswith(".crate"):
                    crate_file = lfa
                elif lfa.filename.endswith(".jar"):
                    jar_file = lfa
                elif lfa.filename == "pom.xml":
                    pom_file = lfa

            # Process the crate file
            with tempfile.TemporaryDirectory() as tmpdir:
                if crate_file is not None:
                    # Download the crate file
                    crate_path = os.path.join(tmpdir, crate_file.filename)
                    crate_file.open()
                    try:
                        with open(crate_path, "wb") as f:
                            f.write(crate_file.read())
                    finally:
                        crate_file.close()

                    # Create a directory to extract the crate
                    crate_extract_dir = os.path.join(tmpdir, "crate_contents")
                    os.makedirs(crate_extract_dir, exist_ok=True)

                    # Extract the .crate file using system tar command
                    result = subprocess.run(
                        ["tar", "-xf", crate_path, "-C", crate_extract_dir],
                        capture_output=True,
                        text=True,
                    )

                    if result.returncode != 0:
                        raise Exception(
                            f"Failed to extract crate: {result.stderr}"
                        )

                    # Find the extracted directory(should be the only one)
                    extracted_dirs = [
                        d
                        for d in os.listdir(crate_extract_dir)
                        if os.path.isdir(os.path.join(crate_extract_dir, d))
                    ]

                    if not extracted_dirs:
                        raise Exception(
                            "No directory found in extracted crate"
                        )

                    # Use the first directory as the crate directory
                    crate_dir = os.path.join(
                        crate_extract_dir, extracted_dirs[0]
                    )

                    # Publish the Rust crate
                    self._publish_rust_crate(
                        crate_dir, env_vars, crate_file.filename
                    )
                elif jar_file is not None and pom_file is not None:
                    # Download the jar file
                    jar_path = os.path.join(tmpdir, jar_file.filename)
                    jar_file.open()
                    try:
                        with open(jar_path, "wb") as f:
                            f.write(jar_file.read())
                    finally:
                        jar_file.close()

                    # Download the pom file
                    pom_path = os.path.join(tmpdir, "pom.xml")
                    pom_file.open()
                    try:
                        with open(pom_path, "wb") as f:
                            f.write(pom_file.read())
                    finally:
                        pom_file.close()

                    # Publish the Maven artifact
                    self._publish_maven_artifact(
                        tmpdir,
                        env_vars,
                        jar_file.filename,
                        jar_path,
                        pom_path,
                    )

                else:
                    raise Exception("No publishable artifacts found in build")

        except Exception as e:
            self.error_message = str(e)
            # The normal job infrastructure will abort the transaction, but
            # we want to commit instead: the only database changes we make
            # are to this job's metadata and should be preserved.
            transaction.commit()
            raise

    def _publish_rust_crate(self, extract_dir, env_vars, artifact_name):
        """Publish Rust crates from the extracted crate directory.

        :param extract_dir: Path to the extracted crate directory
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

        # Extract token from auth string (discard username if present)
        if ":" in cargo_publish_auth:
            _, token = cargo_publish_auth.split(":", 1)
            token = token.strip('"')
        else:
            token = cargo_publish_auth

        # Set up cargo config
        cargo_dir = os.path.join(extract_dir, ".cargo")
        os.makedirs(cargo_dir, exist_ok=True)

        # Create config.toml
        with open(os.path.join(cargo_dir, "config.toml"), "w") as f:
            config_content = (
                "\n"
                "[registry]\n"
                'global-credential-providers = ["cargo:token"]\n'
                "\n"
                "[registries.launchpad]\n"
                f'index = "{cargo_publish_url}"\n'
            )

            # Only add the HTTP proxy configuration if it's set
            if config.launchpad.http_proxy:
                config_content += (
                    "\n"
                    "[http]\n"
                    f"proxy = '{config.launchpad.http_proxy}'\n"
                    f"timeout = {CARGO_HTTP_TIMEOUT}\n"
                    "multiplexing = false\n"
                )

            f.write(config_content)

        # Replace any Cargo.toml files with their .orig versions if they exist,
        # as the .orig files contain the original content before build
        # modifications
        orig_files = glob.glob(
            f"{extract_dir}/**/Cargo.toml.orig", recursive=True
        )
        for orig_file in orig_files:
            cargo_toml = orig_file.replace(".orig", "")
            if os.path.exists(cargo_toml):
                os.replace(orig_file, cargo_toml)

        # Run cargo publish from the extracted directory
        result = subprocess.run(
            [
                "cargo",
                "publish",
                "--no-verify",
                "--allow-dirty",
                "--registry",
                "launchpad",
            ],
            capture_output=True,
            cwd=extract_dir,
            env={"CARGO_HOME": cargo_dir},
        )

        if result.returncode != 0:
            raise Exception(f"Failed to publish crate: {result.stderr}")

        # XXX ruinedyourlife 2025-06-06:
        # The publish_properties method is not working as expected.
        # Artifactory is giving us a 403.
        # We should fix it, but for now we'll skip it.
        # self._publish_properties(cargo_publish_url, artifact_name)

    def _publish_maven_artifact(
        self, work_dir, env_vars, artifact_name, jar_path=None, pom_path=None
    ):
        """Publish Maven artifacts.

        :param work_dir: Working directory
        :param env_vars: Environment variables from configuration
        :param jar_path: Path to the JAR file
        :param pom_path: Path to the pom.xml file
        :raises: Exception if publishing fails
        """
        # Look for specific Maven publishing repository configuration
        maven_publish_url = env_vars.get("MAVEN_PUBLISH_URL")
        maven_publish_auth = env_vars.get("MAVEN_PUBLISH_AUTH")

        if not maven_publish_url or not maven_publish_auth:
            raise Exception(
                "Missing Maven publishing repository configuration"
            )

        if jar_path is None or pom_path is None:
            raise Exception("Missing JAR or POM file for Maven publishing")

        # Set up Maven settings
        maven_dir = os.path.join(work_dir, ".m2")
        os.makedirs(maven_dir, exist_ok=True)

        # Extract username and password from auth string
        if ":" in maven_publish_auth:
            username, password = maven_publish_auth.split(":", 1)
        else:
            username = "launchpad"
            password = maven_publish_auth

        # Generate settings.xml content
        settings_xml = self._get_maven_settings_xml(username, password)

        with open(os.path.join(maven_dir, "settings.xml"), "w") as f:
            f.write(settings_xml)

        # Run mvn deploy using the pom file
        result = subprocess.run(
            [
                "mvn",
                "deploy:deploy-file",
                f"-DpomFile={pom_path}",
                f"-Dfile={jar_path}",
                "-DrepositoryId=central",
                f"-Durl={maven_publish_url}",
                "--settings={}".format(
                    os.path.join(maven_dir, "settings.xml")
                ),
            ],
            capture_output=True,
            cwd=work_dir,
        )

        if result.returncode != 0:
            raise Exception(
                f"Failed to publish Maven artifact: {result.stderr}"
            )

        # XXX ruinedyourlife 2025-06-06:
        # The publish_properties method is not working as expected.
        # Artifactory is giving us a 403.
        # We should fix it, but for now we'll skip it.
        # self._publish_properties(maven_publish_url, artifact_name)

    def _get_maven_settings_xml(self, username, password):
        """Generate Maven settings.xml content.

        :param username: Maven repository username
        :param password: Maven repository password
        :return: XML content as string
        """
        # Get proxy settings from config
        proxy_url = config.launchpad.http_proxy
        proxy_host = None
        proxy_port = None

        if proxy_url:
            # Parse the proxy URL using urllib.parse
            parsed_url = urlparse(proxy_url)

            # Extract host and port from the parsed URL
            proxy_host = parsed_url.hostname
            proxy_port = parsed_url.port

            # Log warning if proxy URL doesn't contain both host and port
            if not proxy_host or not proxy_port:
                log.warning(
                    f"Invalid proxy URL format: {proxy_url}. "
                    "Expected format: http://hostname:port. "
                    "Maven proxy configuration will be skipped."
                )
                proxy_host = None
                proxy_port = None

        # Break it into smaller parts to avoid long lines
        header = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<settings xmlns="http://maven.apache.org/SETTINGS/1.0.0"\n'
            '        xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance"\n'
        )

        schema = (
            '        xsi:schemaLocation="'
            "http://maven.apache.org/SETTINGS/1.0.0 "
            'http://maven.apache.org/xsd/settings-1.0.0.xsd">\n'
        )

        servers = (
            "    <servers>\n"
            "        <server>\n"
            "            <id>central</id>\n"
            f"            <username>{username}</username>\n"
            f"            <password>{password}</password>\n"
            "        </server>\n"
            "    </servers>\n"
        )

        # Add proxy configuration if proxy is configured
        proxies = ""
        if proxy_host and proxy_port:
            proxies = (
                "    <proxies>\n"
                "        <proxy>\n"
                "            <id>launchpad-proxy</id>\n"
                "            <active>true</active>\n"
                "            <protocol>http</protocol>\n"
                f"            <host>{proxy_host}</host>\n"
                f"            <port>{proxy_port}</port>\n"
                "        </proxy>\n"
                "    </proxies>\n"
            )

        profiles = (
            "    <profiles>\n"
            "        <profile>\n"
            "            <id>system</id>\n"
            "            <pluginRepositories>\n"
            "                <pluginRepository>\n"
            "                    <id>central</id>\n"
            "                    <url>file:///usr/share/maven-repo</url>\n"
            "                </pluginRepository>\n"
            "            </pluginRepositories>\n"
            "        </profile>\n"
            "    </profiles>\n"
        )

        active_profiles = (
            "    <activeProfiles>\n"
            "        <activeProfile>system</activeProfile>\n"
            "    </activeProfiles>\n"
            "</settings>"
        )

        # Combine all parts
        return header + schema + servers + proxies + profiles + active_profiles

    def _publish_properties(
        self, publish_url: str, artifact_name: str
    ) -> None:
        """Publish properties to the artifact in Artifactory."""

        new_properties = {}

        new_properties["soss.commit_id"] = (
            [self.build.revision_id] if self.build.revision_id else ["unknown"]
        )
        new_properties["soss.source_url"] = [self._recipe_git_url()]
        new_properties["soss.type"] = ["source"]
        new_properties["soss.license"] = [self._get_license_metadata()]

        # Repo name is derived from the URL
        # We assume the URL ends with the repository name
        repo_name = publish_url.rstrip("/").split("/")[-1]

        root_path_str = self._extract_root_path(publish_url)
        if not root_path_str:
            raise NotFoundError(
                f"Could not extract root path from URL: {publish_url}"
            )

        # Search for the artifact in Artifactory using AQL
        root_path = ArtifactoryPath(root_path_str)
        artifacts = root_path.aql(
            "items.find",
            {
                "repo": repo_name,
                "name": artifact_name,
            },
            ".include",
            ["repo", "path", "name"],
            ".limit(1)",
        )

        if not artifacts:
            raise NotFoundError(
                f"Artifact '{artifact_name}' not found in repository \
                '{repo_name}'"
            )

        if len(artifacts) > 1:
            log.info(
                f"Multiple artifacts found for '{artifact_name}'"
                + f"in repository '{repo_name}'. Using the first one."
            )

        # Get the first artifact that matches the name
        artifact = artifacts[0]

        artifact_path = ArtifactoryPath(
            root_path, artifact["repo"], artifact["path"], artifact["name"]
        )
        artifact_path.set_properties(new_properties)

    def _extract_root_path(self, publish_url: str) -> str:
        """
        Extracts everything from the first occurrence of 'https' up to and
        including 'artifactory'."""
        start_index = publish_url.find("https")
        if start_index == -1:
            return ""

        end_index = publish_url.find("artifactory", start_index)
        if end_index == -1:
            return ""

        return publish_url[start_index : end_index + len("artifactory")]

    def _recipe_git_url(self):
        """Get the recipe git URL."""

        craft_recipe = self.build.recipe
        if craft_recipe.git_repository is not None:
            return craft_recipe.git_repository.git_https_url
        elif craft_recipe.git_repository_url is not None:
            return craft_recipe.git_repository_url
        else:
            log.info(
                f"Recipe {craft_recipe.id} has no git repository URL defined."
            )
            return "unknown"

    def _get_license_metadata(self) -> str:
        """Get the license metadata from the build files."""
        for _, lfa, _ in self.build.getFiles():
            if lfa.filename == "metadata.yaml":
                lfa.open()
                try:
                    content = lfa.read().decode("utf-8")
                    metadata = yaml.safe_load(content)

                    if "license" not in metadata:
                        log.info(
                            "No license found in metadata.yaml, returning \
                            'unknown'."
                        )
                        return "unknown"

                    return metadata.get("license")

                except yaml.YAMLError as e:
                    self.error_message = f"Failed to parse metadata.yaml: {e}"

                    log.info(self.error_message)
                    return "unknown"
                finally:
                    lfa.close()

        log.info("No metadata.yaml file found in the build files.")
        return "unknown"
