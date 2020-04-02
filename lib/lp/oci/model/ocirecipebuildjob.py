# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe build jobs."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type
__all__ = [
    'OCIRecipeBuildJob',
    'OCIRecipeBuildJobType',
    ]

from lazr.delegates import delegate_to
from lazr.enum import (
    DBEnumeratedType,
    DBItem,
    )
from storm.locals import (
    Int,
    JSON,
    Reference,
    )
from zope.interface import implementer

from lp.app.errors import NotFoundError
from lp.oci.interfaces.ocirecipebuildjob import IOCIRecipeBuildJob
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import (
    EnumeratedSubclass,
    Job,
    )
from lp.services.job.runner import BaseRunnableJob


class OCIRecipeBuildJobType(DBEnumeratedType):
    """Values that `OCIBuildJobType.job_type` can take."""

    REGISTRY_UPLOAD = DBItem(0, """
        Registry upload

        This job uploads an OCI Image to registry.
        """)


@implementer(IOCIRecipeBuildJob)
class OCIRecipeBuildJob(StormBase):
    """See `IOCIRecipeBuildJob`."""

    __storm_table__ = 'OCIRecipeBuildJob'

    job_id = Int(name='job', primary=True, allow_none=False)
    job = Reference(job_id, 'Job.id')

    build_id = Int(name='build', allow_none=False)
    build = Reference(build_id, 'OCIRecipeBuild.id')

    job_type = DBEnum(enum=OCIRecipeBuildJobType, allow_none=True)

    json_data = JSON('json_data', allow_none=False)

    def __init__(self, build, job_type, json_data, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param build: The `IOCIRecipeBuild` this job relates to.
        :param job_type: The `OCIRecipeBuildJobType` of this job.
        :param json_data: The type-specific variables, as a JSON-compatible
            dict.
        """
        super(OCIRecipeBuildJob, self).__init__()
        self.job = Job(**job_args)
        self.build = build
        self.job_type = job_type
        self.json_data = json_data

    def makeDerived(self):
        return OCIRecipeBuildJob.makeSubclass(self)


@delegate_to(IOCIRecipeBuildJob)
class OCIRecipeBuildJobDerived(BaseRunnableJob):

    __metaclass__ = EnumeratedSubclass

    def __init__(self, oci_build_job):
        self.context = oci_build_job

    def __repr__(self):
        """An informative representation of the job."""
        return "<%s for %s>" % (
            self.__class__.__name__, self.build.id)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `OCIBuildJob` with the specified id, as the current
            `OCIBuildJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        oci_build_job = IStore(OCIRecipeBuildJob).get(
            OCIRecipeBuildJob, job_id)
        if oci_build_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s" %
                (job_id, cls.class_job_type.title))
        return cls(oci_build_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IStore(OCIRecipeBuildJob).find(
            OCIRecipeBuildJob,
            OCIRecipeBuildJob.job_type == cls.class_job_type,
            OCIRecipeBuildJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs))
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super(OCIRecipeBuildJobDerived, self).getOopsVars()
        oops_vars.extend([
            ('job_type', self.context.job_type.title),
            ('build_id', self.context.build.id),
            ('owner_id', self.context.build.recipe.owner.id),
            ('project_name', self.context.build.recipe.oci_project.name)
            ])
        return oops_vars
