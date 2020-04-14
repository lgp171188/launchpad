# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""A build job for OCI Recipe."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    ]

from lazr.delegates import delegate_to
from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    )
from storm.properties import (
    Int,
    JSON,
    )
from storm.references import Reference
from storm.store import EmptyResultSet
import transaction
from zope.component import getUtility
from zope.interface import (
    implementer,
    provider,
    )

from lp.app.errors import NotFoundError
from lp.oci.interfaces.ocirecipejob import (
    IOCIRecipeJob,
    IOCIRecipeRequestBuildsJob,
    IOCIRecipeRequestBuildsJobSource,
    )
from lp.oci.model.ocirecipebuild import OCIRecipeBuild
from lp.registry.interfaces.person import IPersonSet
from lp.services.config import config
from lp.services.database.enumcol import EnumCol
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import (
    EnumeratedSubclass,
    Job,
    )
from lp.services.job.runner import BaseRunnableJob
from lp.services.mail.sendmail import format_address_for_person
from lp.services.propertycache import cachedproperty
from lp.services.scripts import log


class OCIRecipeJobType(DBEnumeratedType):
    """Values that `IOCIRecipeJob.job_type` can take."""

    REQUEST_BUILDS = DBItem(0, """
        Request builds

        This job requests builds of an OCI recipe.
        """)


@implementer(IOCIRecipeJob)
class OCIRecipeJob(StormBase):
    """See `IOCIRecipeJob`."""

    __storm_table__ = 'OCIRecipeJob'

    job_id = Int(name='job', primary=True, allow_none=False)
    job = Reference(job_id, 'Job.id')

    oci_recipe_id = Int(name='oci_recipe', allow_none=False)
    oci_recipe = Reference(oci_recipe_id, 'OCIRecipe.id')

    job_type = EnumCol(enum=OCIRecipeJobType, notNull=True)

    metadata = JSON('json_data', allow_none=False)

    def __init__(self, oci_recipe, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param oci_recipe: The `IOCIRecipe` this job relates to.
        :param job_type: The `OCIRecipeJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super(OCIRecipeJob, self).__init__()
        self.job = Job(**job_args)
        self.oci_recipe = oci_recipe
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return OCIRecipeJobDerived.makeSubclass(self)


@delegate_to(IOCIRecipeJob)
class OCIRecipeJobDerived(BaseRunnableJob):

    __metaclass__ = EnumeratedSubclass

    def __init__(self, oci_recipe_job):
        self.context = oci_recipe_job

    def __repr__(self):
        """An informative representation of the job."""
        return "<%s for %s>" % (
            self.__class__.__name__, self.oci_recipe)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `IOCIRecipeJob` with the specified id, as the current
            `IOCIRecipeJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        oci_recipe_job = IStore(IOCIRecipeJob).get(IOCIRecipeJob, job_id)
        if oci_recipe_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s" %
                (job_id, cls.class_job_type.title))
        return cls(oci_recipe_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IMasterStore(OCIRecipeJob).find(
            OCIRecipeJob,
            OCIRecipeJob.job_type == cls.class_job_type,
            OCIRecipeJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs))
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super(OCIRecipeJobDerived, self).getOopsVars()
        oops_vars.extend([
            ("job_id", self.context.job.id),
            ("job_type", self.context.job_type.title),
            ("oci_recipe_owner_name", self.context.oci_recipe.owner.name),
            ("oci_recipe_name", self.context.oci_recipe.name),
            ])
        return oops_vars


@implementer(IOCIRecipeRequestBuildsJob)
@provider(IOCIRecipeRequestBuildsJobSource)
class OCIRecipeRequestBuildsJob(OCIRecipeJobDerived):
    """A Job that processes a request for builds of an OCI Recipe package."""

    class_job_type = OCIRecipeJobType.REQUEST_BUILDS

    user_error_types = tuple()
    retry_error_types = tuple()

    max_retries = 5

    # XXX: pappacena 2020-04-14: Add specific configuration for OCI jobs
    # here, once other MP is landed with "oci-build-job" database user.
    # See shcema-lazr.conf notes too.
    # config = config.IOCIRecipeRequestBuildsJobSource

    @classmethod
    def create(cls, oci_recipe, requester):
        """See `OCIRecipeRequestBuildsJob`."""
        metadata = {"requester": requester.id}
        oci_recipe_job = OCIRecipeJob(oci_recipe, cls.class_job_type, metadata)
        job = cls(oci_recipe_job)
        job.celeryRunOnCommit()
        return job

    @classmethod
    def findByOCIRecipeAndID(cls, oci_recipe, job_id):
        job = IStore(OCIRecipeJob).find(
            OCIRecipeJob,
            OCIRecipeJob.oci_recipe == oci_recipe,
            OCIRecipeJob.job_id == job_id).one()
        if job is None:
            raise NotFoundError("Could not find job ID %s" % job_id)
        return cls(job)

    def getOperationDescription(self):
        return "requesting builds of %s" % self.oci_recipe

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
        return self.oci_recipe.getBuildRequest(self.job.id)

    @property
    def builds(self):
        """See `OCIRecipeRequestBuildsJob`."""
        build_ids = self.metadata.get("builds")
        if build_ids:
            return IStore(OCIRecipeBuild).find(
                OCIRecipeBuild, OCIRecipeBuild.id.is_in(build_ids))
        else:
            return EmptyResultSet()

    @builds.setter
    def builds(self, builds):
        """See `OCIRecipeRequestBuildsJob`."""
        self.metadata["builds"] = [build.id for build in builds]

    def run(self):
        """See `IRunnableJob`."""
        requester = self.requester
        if requester is None:
            log.info(
                "Skipping %r because the requester has been deleted." % self)
            return
        try:
            self.builds = self.oci_recipe.requestBuildsFromJob(requester)
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
