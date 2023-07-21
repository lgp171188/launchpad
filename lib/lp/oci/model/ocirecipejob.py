# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A build job for OCI Recipe."""

__all__ = [
    "OCIRecipeJob",
]

import transaction
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.databases.postgres import JSON
from storm.expr import Desc
from storm.properties import Int
from storm.references import Reference
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer, provider
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.buildmaster.model.processor import Processor
from lp.oci.interfaces.ocirecipe import IOCIRecipeSet
from lp.oci.interfaces.ocirecipebuild import (
    OCIRecipeBuildRegistryUploadStatus,
    OCIRecipeBuildSetRegistryUploadStatus,
)
from lp.oci.interfaces.ocirecipejob import (
    IOCIRecipeJob,
    IOCIRecipeRequestBuildsJob,
    IOCIRecipeRequestBuildsJobSource,
)
from lp.oci.model.ocirecipebuild import OCIRecipeBuild
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
from lp.soyuz.interfaces.binarypackagebuild import BuildSetStatus


class OCIRecipeJobType(DBEnumeratedType):
    """Values that `IOCIRecipeJob.job_type` can take."""

    REQUEST_BUILDS = DBItem(
        0,
        """
        Request builds

        This job requests builds of an OCI recipe.
        """,
    )


@implementer(IOCIRecipeJob)
class OCIRecipeJob(StormBase):
    """See `IOCIRecipeJob`."""

    __storm_table__ = "OCIRecipeJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    recipe_id = Int(name="recipe", allow_none=False)
    recipe = Reference(recipe_id, "OCIRecipe.id")

    job_type = DBEnum(enum=OCIRecipeJobType, allow_none=False)

    metadata = JSON("json_data", allow_none=False)

    def __init__(self, recipe, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param recipe: The `IOCIRecipe` this job relates to.
        :param job_type: The `OCIRecipeJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super().__init__()
        self.job = Job(**job_args)
        self.recipe = recipe
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return OCIRecipeJobDerived.makeSubclass(self)


@delegate_to(IOCIRecipeJob)
class OCIRecipeJobDerived(BaseRunnableJob, metaclass=EnumeratedSubclass):
    def __init__(self, recipe_job):
        self.context = recipe_job

    def __repr__(self):
        """An informative representation of the job."""
        return "<%s for %s>" % (self.__class__.__name__, self.recipe)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `IOCIRecipeJob` with the specified id, as the current
            `IOCIRecipeJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        recipe_job = IStore(IOCIRecipeJob).get(IOCIRecipeJob, job_id)
        if recipe_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s"
                % (job_id, cls.class_job_type.title)
            )
        return cls(recipe_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IPrimaryStore(OCIRecipeJob).find(
            OCIRecipeJob,
            OCIRecipeJob.job_type == cls.class_job_type,
            OCIRecipeJob.job == Job.id,
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
                ("oci_project_name", self.context.recipe.oci_project.name),
                ("recipe_owner_name", self.context.recipe.owner.name),
                ("recipe_name", self.context.recipe.name),
            ]
        )
        return oops_vars


@implementer(IOCIRecipeRequestBuildsJob)
@provider(IOCIRecipeRequestBuildsJobSource)
class OCIRecipeRequestBuildsJob(OCIRecipeJobDerived):
    """A Job that processes a request for builds of an OCI Recipe."""

    class_job_type = OCIRecipeJobType.REQUEST_BUILDS

    max_retries = 5

    config = config.IOCIRecipeRequestBuildsJobSource

    @classmethod
    def create(cls, recipe, requester, architectures=None):
        """See `OCIRecipeRequestBuildsJob`."""
        metadata = {
            "requester": requester.id,
            "architectures": (
                list(architectures) if architectures is not None else None
            ),
            # A dict of build_id: manifest location
            "uploaded_manifests": {},
        }
        recipe_job = OCIRecipeJob(recipe, cls.class_job_type, metadata)
        job = cls(recipe_job)
        job.celeryRunOnCommit()
        IStore(OCIRecipeJob).flush()
        return job

    @classmethod
    def getByOCIRecipeAndID(cls, recipe, job_id):
        job = (
            IStore(OCIRecipeJob)
            .find(
                OCIRecipeJob,
                OCIRecipeJob.recipe == recipe,
                OCIRecipeJob.job_id == job_id,
            )
            .one()
        )
        if job is None:
            raise NotFoundError("Could not find job ID %s" % job_id)
        return cls(job)

    @classmethod
    def findByOCIRecipe(cls, recipe, statuses=None, job_ids=None):
        conditions = [
            OCIRecipeJob.recipe == recipe,
            OCIRecipeJob.job_type == cls.class_job_type,
        ]
        if statuses is not None:
            conditions.append(Job._status.is_in(statuses))
        if job_ids is not None:
            conditions.append(OCIRecipeJob.job_id.is_in(job_ids))
        oci_jobs = (
            IStore(OCIRecipeJob)
            .find(OCIRecipeJob, OCIRecipeJob.job_id == Job.id, *conditions)
            .order_by(Desc(OCIRecipeJob.job_id))
        )

        def preload_jobs(rows):
            load_related(Job, rows, ["job_id"])

        return DecoratedResultSet(
            oci_jobs, lambda oci_job: cls(oci_job), pre_iter_hook=preload_jobs
        )

    def getOperationDescription(self):
        return "requesting builds of %s" % self.recipe

    def getErrorRecipients(self):
        if self.requester is None or self.requester.preferredemail is None:
            return []
        return [format_address_for_person(self.requester)]

    @cachedproperty
    def requester(self):
        """See `OCIRecipeRequestBuildsJob`."""
        requester_id = self.metadata["requester"]
        return getUtility(IPersonSet).get(requester_id)

    @property
    def date_created(self):
        """See `OCIRecipeRequestBuildsJob`."""
        return self.context.job.date_created

    @property
    def date_finished(self):
        """See `OCIRecipeRequestBuildsJob`."""
        return self.context.job.date_finished

    @property
    def error_message(self):
        """See `OCIRecipeRequestBuildsJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `OCIRecipeRequestBuildsJob`."""
        self.metadata["error_message"] = message

    @property
    def build_request(self):
        """See `OCIRecipeRequestBuildsJob`."""
        return self.recipe.getBuildRequest(self.job.id)

    @property
    def builds(self):
        """See `OCIRecipeRequestBuildsJob`."""
        build_ids = self.metadata.get("builds")
        # Sort this by architecture/processor name, so it's consistent
        # when displayed
        if build_ids:
            return (
                IStore(OCIRecipeBuild)
                .find(
                    OCIRecipeBuild,
                    OCIRecipeBuild.id.is_in(build_ids),
                    OCIRecipeBuild.processor_id == Processor.id,
                )
                .order_by(Desc(Processor.name))
            )
        else:
            return EmptyResultSet()

    @builds.setter
    def builds(self, builds):
        """See `OCIRecipeRequestBuildsJob`."""
        self.metadata["builds"] = [build.id for build in builds]

    @property
    def architectures(self):
        architectures = self.metadata["architectures"]
        return set(architectures) if architectures is not None else None

    @property
    def uploaded_manifests(self):
        return {
            # Converts keys to integer since saving json to database
            # converts them to strings.
            int(k): v
            for k, v in self.metadata["uploaded_manifests"].items()
        }

    def addUploadedManifest(self, build_id, manifest_info):
        self.metadata["uploaded_manifests"][int(build_id)] = manifest_info

    @property
    def build_status(self):
        builds = self.builds
        # This just returns a dict, but Zope is really helpful here
        status = removeSecurityProxy(
            getUtility(IOCIRecipeSet).getStatusSummaryForBuilds(list(builds))
        )

        # This has a really long name!
        singleStatus = OCIRecipeBuildRegistryUploadStatus
        setStatus = OCIRecipeBuildSetRegistryUploadStatus

        # Set the pending upload status if either we're not done uploading,
        # or there was no upload requested in the first place (no push rules)
        if status["status"] == BuildSetStatus.FULLYBUILT:
            upload_status = [
                (
                    x.registry_upload_status == singleStatus.UPLOADED
                    or x.registry_upload_status == singleStatus.UNSCHEDULED
                )
                for x in status["builds"]
            ]
            if not all(upload_status):
                status["status"] = BuildSetStatus.FULLYBUILT_PENDING

        # Are we expecting an upload to be or to have been attempted?
        # This is slightly complicated as the upload depends on the push
        # rules at the time of build completion
        upload_requested = False
        # If there's an upload job for any of the builds, we have
        # requested an upload
        if any(x.last_registry_upload_job for x in builds):
            upload_requested = True
        # If all of the builds haven't finished, but the recipe currently
        # has push rules specified, then we will attempt an upload
        # in the future
        if any(
            not x.date_finished and x.recipe.can_upload_to_registry
            for x in builds
        ):
            upload_requested = True
        status["upload_requested"] = upload_requested

        # Convert the set of registry statuses into a single line
        # for display
        upload_status = [x.registry_upload_status for x in builds]
        # Any of the builds failed
        if any(x == singleStatus.FAILEDTOUPLOAD for x in upload_status):
            status["upload"] = setStatus.FAILEDTOUPLOAD
        # All of the builds uploaded
        elif all(x == singleStatus.UPLOADED for x in upload_status):
            status["upload"] = setStatus.UPLOADED
        # All of the builds are yet to attempt an upload
        elif all(x == singleStatus.UNSCHEDULED for x in upload_status):
            status["upload"] = setStatus.UNSCHEDULED
        # Any of the builds have uploaded. Set after 'all of the builds'
        # have uploaded.
        elif any(x == singleStatus.UPLOADED for x in upload_status):
            status["upload"] = setStatus.PARTIAL
        # And if it's none of the above, we're waiting
        else:
            status["upload"] = setStatus.PENDING

        # Get the longest date and whether any of them are estimated
        # for the summary of the builds
        dates = [x.date for x in self.builds if x.date]
        status["date"] = max(dates) if dates else None
        status["date_estimated"] = any(x.estimate for x in self.builds)

        return status

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
                requester,
                build_request=self.build_request,
                architectures=self.architectures,
            )
            self.error_message = None
        except self.retry_error_types:
            raise
        except Exception as e:
            self.error_message = str(e)
            # The normal job infrastructure will abort the transaction, but
            # we want to commit instead: the only database changes we make
            # are to this job's metadata and should be preserved.
            transaction.commit()
            raise
