# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe job interfaces."""

__all__ = [
    "ICharmRecipeJob",
    "ICharmRecipeRequestBuildsJob",
    "ICharmRecipeRequestBuildsJobSource",
]

from lazr.restful.fields import Reference
from zope.interface import Attribute, Interface
from zope.schema import Datetime, List, Set, TextLine

from lp import _
from lp.charms.interfaces.charmrecipe import (
    ICharmRecipe,
    ICharmRecipeBuildRequest,
)
from lp.charms.interfaces.charmrecipebuild import ICharmRecipeBuild
from lp.registry.interfaces.person import IPerson
from lp.services.fields import SnapBuildChannelsField
from lp.services.job.interfaces.job import IJob, IJobSource, IRunnableJob


class ICharmRecipeJob(Interface):
    """A job related to a charm recipe."""

    job = Reference(
        title=_("The common Job attributes."),
        schema=IJob,
        required=True,
        readonly=True,
    )

    recipe = Reference(
        title=_("The charm recipe to use for this job."),
        schema=ICharmRecipe,
        required=True,
        readonly=True,
    )

    metadata = Attribute(_("A dict of data about the job."))


class ICharmRecipeRequestBuildsJob(IRunnableJob):
    """A Job that processes a request for builds of a charm recipe."""

    requester = Reference(
        title=_("The person requesting the builds."),
        schema=IPerson,
        required=True,
        readonly=True,
    )

    channels = SnapBuildChannelsField(
        title=_("Source snap channels to use for these builds."),
        description_prefix=_(
            "A dictionary mapping snap names to channels to use for these "
            "builds."
        ),
        required=False,
        readonly=True,
        extra_snap_names=["charmcraft"],
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
        schema=ICharmRecipeBuildRequest,
        required=True,
        readonly=True,
    )

    builds = List(
        title=_("The builds created by this request."),
        value_type=Reference(schema=ICharmRecipeBuild),
        required=True,
        readonly=True,
    )


class ICharmRecipeRequestBuildsJobSource(IJobSource):
    def create(recipe, requester, channels=None, architectures=None):
        """Request builds of a charm recipe.

        :param recipe: The charm recipe to build.
        :param requester: The person requesting the builds.
        :param channels: A dictionary mapping snap names to channels to use
            for these builds.
        :param architectures: If not None, limit builds to architectures
            with these architecture tags (in addition to any other
            applicable constraints).
        """

    def findByRecipe(recipe, statuses=None, job_ids=None):
        """Find jobs for a charm recipe.

        :param recipe: A charm recipe to search for.
        :param statuses: An optional iterable of `JobStatus`es to search for.
        :param job_ids: An optional iterable of job IDs to search for.
        :return: A sequence of `CharmRecipeRequestBuildsJob`s with the
            specified recipe.
        """

    def getByRecipeAndID(recipe, job_id):
        """Get a job by charm recipe and job ID.

        :return: The `CharmRecipeRequestBuildsJob` with the specified recipe
            and ID.
        :raises: `NotFoundError` if there is no job with the specified
            recipe and ID, or its `job_type` is not
            `CharmRecipeJobType.REQUEST_BUILDS`.
        """
