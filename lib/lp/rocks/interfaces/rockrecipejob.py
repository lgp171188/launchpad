# Copyright 2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Rock recipe job interfaces."""

__all__ = [
    "IRockRecipeJob",
    "IRockRecipeRequestBuildsJob",
    "IRockRecipeRequestBuildsJobSource",
]

from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import Datetime, Dict, List, Set, TextLine

from lp import _
from lp.registry.interfaces.person import IPerson
from lp.rocks.interfaces.rockrecipe import IRockRecipe, IRockRecipeBuildRequest
from lp.rocks.interfaces.rockrecipebuild import IRockRecipeBuild
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob


class IRockRecipeJob(Interface):
    """A job related to a rock recipe."""

    job = Reference(
        title=_("The common Job attributes."),
        schema=IJob,
        required=True,
        readonly=True,
    )

    recipe = Reference(
        title=_("The rock recipe to use for this job."),
        schema=IRockRecipe,
        required=True,
        readonly=True,
    )

    metadata = Attribute(_("A dict of data about the job."))


class IRockRecipeRequestBuildsJob(IRunnableJob):
    """A Job that processes a request for builds of a rock recipe."""

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
            "'rockcraft' keys are supported."
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
        schema=IRockRecipeBuildRequest,
        required=True,
        readonly=True,
    )

    builds = List(
        title=_("The builds created by this request."),
        value_type=Reference(schema=IRockRecipeBuild),
        required=True,
        readonly=True,
    )


class IRockRecipeRequestBuildsJobSource(IJobSource):

    def create(recipe, requester, channels=None, architectures=None):
        """Request builds of a rock recipe.

        :param recipe: The rock recipe to build.
        :param requester: The person requesting the builds.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        """

    def findByRecipe(recipe, statuses=None, job_ids=None):
        """Find jobs for a rock recipe.

        :param recipe: A rock recipe to search for.
        :param statuses: An optional iterable of `JobStatus`es to search for.
        :param job_ids: An optional iterable of job IDs to search for.
        :return: A sequence of `RockRecipeRequestBuildsJob`s with the
            specified recipe.
        """

    def getByRecipeAndID(recipe, job_id):
        """Get a job by rock recipe and job ID.

        :return: The `RockRecipeRequestBuildsJob` with the specified recipe
            and ID.
        :raises: `NotFoundError` if there is no job with the specified
            recipe and ID, or its `job_type` is not
            `RockRecipeJobType.REQUEST_BUILDS`.
        """
