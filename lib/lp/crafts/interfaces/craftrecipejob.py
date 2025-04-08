# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Craft recipe job interfaces."""

__all__ = [
    "ICraftRecipeJob",
    "ICraftRecipeRequestBuildsJob",
    "ICraftRecipeRequestBuildsJobSource",
    "IRustCrateUploadJob",
    "IRustCrateUploadJobSource",
    "IMavenArtifactUploadJob",
    "IMavenArtifactUploadJobSource",
]

from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import Datetime, Dict, List, Set, TextLine

from lp import _
from lp.crafts.interfaces.craftrecipe import (
    ICraftRecipe,
    ICraftRecipeBuildRequest,
)
from lp.crafts.interfaces.craftrecipebuild import ICraftRecipeBuild
from lp.registry.interfaces.person import IPerson
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob


class ICraftRecipeJob(Interface):
    """A job related to a craft recipe."""

    job = Reference(
        title=_("The common Job attributes."),
        schema=IJob,
        required=True,
        readonly=True,
    )

    recipe = Reference(
        title=_("The craft recipe to use for this job."),
        schema=ICraftRecipe,
        required=True,
        readonly=True,
    )

    metadata = Attribute(_("A dict of data about the job."))


class ICraftRecipeRequestBuildsJob(IRunnableJob):
    """A Job that processes a request for builds of a craft recipe."""

    requester = Reference(
        title=_("The person requesting the builds."),
        schema=IPerson,
        required=True,
        readonly=True,
    )

    channels = Dict(
        title=_("Source snap channels to use for these builds."),
        description=_(
            "A dictionary mapping snap names to channels to use for these "
            "builds.  Currently only 'core', 'core18', 'core20', and "
            "'sourcecraft' keys are supported."
        ),
        key_type=TextLine(),
        required=False,
        readonly=True,
    )

    architectures = Set(
        title=_("If set, limit builds to these architecture tags."),
        value_type=TextLine(),
        required=False,
        readonly=True,
    )

    date_created = Datetime(
        title=_("Time when this job was created."),
        required=True,
        readonly=True,
    )

    date_finished = Datetime(
        title=_("Time when this job finished."), required=True, readonly=True
    )

    error_message = TextLine(
        title=_("Error message resulting from running this job."),
        required=False,
        readonly=True,
    )

    build_request = Reference(
        title=_("The build request corresponding to this job."),
        schema=ICraftRecipeBuildRequest,
        required=True,
        readonly=True,
    )

    builds = List(
        title=_("The builds created by this request."),
        value_type=Reference(schema=ICraftRecipeBuild),
        required=True,
        readonly=True,
    )


class ICraftRecipeRequestBuildsJobSource(IJobSource):

    def create(recipe, requester, channels=None, architectures=None):
        """Request builds of a craft recipe.

        :param recipe: The craft recipe to build.
        :param requester: The person requesting the builds.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        """

    def findByRecipe(recipe, statuses=None, job_ids=None):
        """Find jobs for a craft recipe.

        :param recipe: A craft recipe to search for.
        :param statuses: An optional iterable of `JobStatus`es to search for.
        :param job_ids: An optional iterable of job IDs to search for.
        :return: A sequence of `CraftRecipeRequestBuildsJob`s with the
            specified recipe.
        """

    def getByRecipeAndID(recipe, job_id):
        """Get a job by craft recipe and job ID.

        :return: The `CraftRecipeRequestBuildsJob` with the specified recipe
            and ID.
        :raises: `NotFoundError` if there is no job with the specified
            recipe and ID, or its `job_type` is not
            `CraftRecipeJobType.REQUEST_BUILDS`.
        """


class IRustCrateUploadJob(IRunnableJob):
    """A job that uploads a Rust crate to a registry."""

    build_id = Attribute("The ID of the build to upload.")
    build = Attribute("The build to upload.")
    error_message = Attribute("The error message if the upload failed.")

    def create(build):
        """Create a new RustCrateUploadJob."""


class IRustCrateUploadJobSource(IJobSource):
    """A source for creating and finding RustCrateUploadJobs."""

    def create(build):
        """Upload a Rust crate build to a registry.

        :param build: The build to upload.
        """


class IMavenArtifactUploadJob(IRunnableJob):
    """A job that uploads a Maven artifact to a repository."""

    build_id = Attribute("The ID of the build to upload.")
    build = Attribute("The build to upload.")
    error_message = Attribute("The error message if the upload failed.")

    def create(build):
        """Create a new MavenArtifactUploadJob."""


class IMavenArtifactUploadJobSource(IJobSource):
    """A source for creating and finding MavenArtifactUploadJobs."""

    def create(build):
        """Upload a Maven artifact build to a repository.

        :param build: The build to upload.
        """
