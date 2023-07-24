# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe jobs."""

__all__ = [
    "CharmRecipeJob",
    "CharmRecipeJobType",
    "CharmRecipeRequestBuildsJob",
]

import transaction
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.databases.postgres import JSON
from storm.locals import Desc, Int, Reference
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer, provider

from lp.app.errors import NotFoundError
from lp.charms.interfaces.charmrecipe import (
    CannotFetchCharmcraftYaml,
    CannotParseCharmcraftYaml,
    MissingCharmcraftYaml,
)
from lp.charms.interfaces.charmrecipejob import (
    ICharmRecipeJob,
    ICharmRecipeRequestBuildsJob,
    ICharmRecipeRequestBuildsJobSource,
)
from lp.charms.model.charmrecipebuild import CharmRecipeBuild
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


class CharmRecipeJobType(DBEnumeratedType):
    """Values that `ICharmRecipeJob.job_type` can take."""

    REQUEST_BUILDS = DBItem(
        0,
        """
        Request builds

        This job requests builds of a charm recipe.
        """,
    )


@implementer(ICharmRecipeJob)
class CharmRecipeJob(StormBase):
    """See `ICharmRecipeJob`."""

    __storm_table__ = "CharmRecipeJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "CharmRecipe.id")

    job_type = DBEnum(
        name="job_type", enum=CharmRecipeJobType, allow_none=False
    )

    metadata = JSON("json_data", allow_none=False)

    def __init__(self, recipe, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param recipe: The `ICharmRecipe` this job relates to.
        :param job_type: The `CharmRecipeJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super().__init__()
        self.job = Job(**job_args)
        self.recipe = recipe
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return CharmRecipeJobDerived.makeSubclass(self)


@delegate_to(ICharmRecipeJob)
class CharmRecipeJobDerived(BaseRunnableJob, metaclass=EnumeratedSubclass):
    def __init__(self, recipe_job):
        self.context = recipe_job

    def __repr__(self):
        """An informative representation of the job."""
        return "<%s for ~%s/%s/+charm/%s>" % (
            self.__class__.__name__,
            self.recipe.owner.name,
            self.recipe.project.name,
            self.recipe.name,
        )

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `CharmRecipeJob` with the specified id, as the current
            `CharmRecipeJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        recipe_job = IStore(CharmRecipeJob).get(CharmRecipeJob, job_id)
        if recipe_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s"
                % (job_id, cls.class_job_type.title)
            )
        return cls(recipe_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IPrimaryStore(CharmRecipeJob).find(
            CharmRecipeJob,
            CharmRecipeJob.job_type == cls.class_job_type,
            CharmRecipeJob.job == Job.id,
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


@implementer(ICharmRecipeRequestBuildsJob)
@provider(ICharmRecipeRequestBuildsJobSource)
class CharmRecipeRequestBuildsJob(CharmRecipeJobDerived):
    """A Job that processes a request for builds of a charm recipe."""

    class_job_type = CharmRecipeJobType.REQUEST_BUILDS

    user_error_types = (
        CannotParseCharmcraftYaml,
        MissingCharmcraftYaml,
    )
    retry_error_types = (CannotFetchCharmcraftYaml,)

    max_retries = 5

    config = config.ICharmRecipeRequestBuildsJobSource

    @classmethod
    def create(cls, recipe, requester, channels=None, architectures=None):
        """See `ICharmRecipeRequestBuildsJobSource`."""
        metadata = {
            "requester": requester.id,
            "channels": channels,
            # Really a set or None, but sets aren't directly
            # JSON-serialisable.
            "architectures": (
                list(architectures) if architectures is not None else None
            ),
        }
        recipe_job = CharmRecipeJob(recipe, cls.class_job_type, metadata)
        job = cls(recipe_job)
        job.celeryRunOnCommit()
        IStore(CharmRecipeJob).flush()
        return job

    @classmethod
    def findByRecipe(cls, recipe, statuses=None, job_ids=None):
        """See `ICharmRecipeRequestBuildsJobSource`."""
        clauses = [
            CharmRecipeJob.recipe == recipe,
            CharmRecipeJob.job_type == cls.class_job_type,
        ]
        if statuses is not None:
            clauses.extend(
                [
                    CharmRecipeJob.job == Job.id,
                    Job._status.is_in(statuses),
                ]
            )
        if job_ids is not None:
            clauses.append(CharmRecipeJob.job_id.is_in(job_ids))
        recipe_jobs = (
            IStore(CharmRecipeJob)
            .find(CharmRecipeJob, *clauses)
            .order_by(Desc(CharmRecipeJob.job_id))
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
        """See `ICharmRecipeRequestBuildsJobSource`."""
        recipe_job = (
            IStore(CharmRecipeJob)
            .find(
                CharmRecipeJob,
                CharmRecipeJob.job_id == job_id,
                CharmRecipeJob.recipe == recipe,
                CharmRecipeJob.job_type == cls.class_job_type,
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
        """See `ICharmRecipeRequestBuildsJob`."""
        requester_id = self.metadata["requester"]
        return getUtility(IPersonSet).get(requester_id)

    @property
    def channels(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        return self.metadata["channels"]

    @property
    def architectures(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        architectures = self.metadata["architectures"]
        return set(architectures) if architectures is not None else None

    @property
    def date_created(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        return self.context.job.date_created

    @property
    def date_finished(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        return self.context.job.date_finished

    @property
    def error_message(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `ICharmRecipeRequestBuildsJob`."""
        self.metadata["error_message"] = message

    @property
    def build_request(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        return self.recipe.getBuildRequest(self.job.id)

    @property
    def builds(self):
        """See `ICharmRecipeRequestBuildsJob`."""
        build_ids = self.metadata.get("builds")
        if build_ids:
            return IStore(CharmRecipeBuild).find(
                CharmRecipeBuild, CharmRecipeBuild.id.is_in(build_ids)
            )
        else:
            return EmptyResultSet()

    @builds.setter
    def builds(self, builds):
        """See `ICharmRecipeRequestBuildsJob`."""
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
