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
import six
from storm.databases.postgres import JSON
from storm.locals import (
    Int,
    Reference,
    )
import transaction
from zope.component import getUtility
from zope.interface import (
    implementer,
    provider,
    )

from lp.app.errors import NotFoundError
from lp.oci.interfaces.ocirecipebuildjob import (
    IOCIRecipeBuildJob,
    IOCIRegistryUploadJob,
    IOCIRegistryUploadJobSource,
    )
from lp.oci.interfaces.ociregistryclient import (
    IOCIRegistryClient,
    OCIRegistryError,
    )
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import (
    IMasterStore,
    IStore,
    )
from lp.services.database.stormbase import StormBase
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import (
    EnumeratedSubclass,
    Job,
    )
from lp.services.job.runner import BaseRunnableJob
from lp.services.propertycache import get_property_cache
from lp.services.webapp.snapshot import notify_modified


class OCIRecipeBuildJobType(DBEnumeratedType):
    """Values that `OCIBuildJobType.job_type` can take."""

    REGISTRY_UPLOAD = DBItem(0, """
        Registry upload

        This job uploads an OCI Image to the registry.
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
        return OCIRecipeBuildJobDerived.makeSubclass(self)


@delegate_to(IOCIRecipeBuildJob)
class OCIRecipeBuildJobDerived(
        six.with_metaclass(EnumeratedSubclass, BaseRunnableJob)):

    def __init__(self, oci_build_job):
        self.context = oci_build_job

    def __repr__(self):
        """An informative representation of the job."""
        build = self.build
        return "<%s for ~%s/%s/+oci/%s/+recipe/%s/+build/%d>" % (
            self.__class__.__name__, build.recipe.owner.name,
            build.recipe.oci_project.pillar.name,
            build.recipe.oci_project.name, build.recipe.name, build.id)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `OCIRecipeBuildJob` with the specified id, as the current
            `OCIRecipeBuildJobDerived` subclass.
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
            ('recipe_owner_id', self.context.build.recipe.owner.id),
            ('oci_project_name', self.context.build.recipe.oci_project.name)
            ])
        return oops_vars


@implementer(IOCIRegistryUploadJob)
@provider(IOCIRegistryUploadJobSource)
class OCIRegistryUploadJob(OCIRecipeBuildJobDerived):

    class_job_type = OCIRecipeBuildJobType.REGISTRY_UPLOAD

    @classmethod
    def create(cls, build):
        """See `IOCIRegistryUploadJobSource`"""
        edited_fields = set()
        with notify_modified(build, edited_fields) as before_modification:
            oci_build_job = OCIRecipeBuildJob(
                build, cls.class_job_type, {})
            job = cls(oci_build_job)
            job.celeryRunOnCommit()
            del get_property_cache(build).last_registry_upload_job
            upload_status = build.registry_upload_status
            if upload_status != before_modification.registry_upload_status:
                edited_fields.add("registry_upload_status")
        return job

    # Ideally we'd just override Job._set_status or similar, but
    # lazr.delegates makes that difficult, so we use this to override all
    # the individual Job lifecycle methods instead.
    def _do_lifecycle(self, method_name, manage_transaction=False,
                      *args, **kwargs):
        edited_fields = set()
        with notify_modified(self.build, edited_fields) as before_modification:
            getattr(super(OCIRegistryUploadJob, self), method_name)(
                *args, manage_transaction=manage_transaction, **kwargs)
            upload_status = self.build.registry_upload_status
            if upload_status != before_modification.registry_upload_status:
                edited_fields.add('registry_upload_status')
        if edited_fields and manage_transaction:
            transaction.commit()

    def start(self, *args, **kwargs):
        self._do_lifecycle("start", *args, **kwargs)

    def complete(self, *args, **kwargs):
        self._do_lifecycle("complete", *args, **kwargs)

    def fail(self, *args, **kwargs):
        self._do_lifecycle("fail", *args, **kwargs)

    def queue(self, *args, **kwargs):
        self._do_lifecycle("queue", *args, **kwargs)

    def suspend(self, *args, **kwargs):
        self._do_lifecycle("suspend", *args, **kwargs)

    def resume(self, *args, **kwargs):
        self._do_lifecycle("resume", *args, **kwargs)

    @property
    def error_summary(self):
        """See `IOCIRegistryUploadJob`."""
        return self.json_data.get("error_summary")

    @error_summary.setter
    def error_summary(self, summary):
        """See `IOCIRegistryUploadJob`."""
        self.json_data["error_summary"] = summary

    @property
    def errors(self):
        """See `IOCIRegistryUploadJob`."""
        return self.json_data.get("errors")

    @errors.setter
    def errors(self, errors):
        """See `IOCIRegistryUploadJob`."""
        self.json_data["errors"] = errors

    @property
    def is_multi_arch(self):
        return len(self.build.getAllowedArchitectures()) > 1

    def allBuildsUploaded(self, build_request):
        """Returns True if all other builds already finished uploading.
        False otherwise."""
        builds = list(build_request.builds)
        uploads_per_build = {i: list(i.registry_upload_jobs) for i in builds}
        upload_jobs = sum(uploads_per_build.values(), [])

        # Lock the Job rows, so no other job updates it's status until the
        # end of this transation. This is done to avoid race conditions,
        # where 2 upload jobs could be running simultaneously and none of them
        # realises that is the last upload.
        store = IMasterStore(builds[0])
        placeholders = ', '.join('?' for _ in upload_jobs)
        sql = (
            "SELECT id, status FROM job WHERE id IN (%s) FOR UPDATE"
            % placeholders)
        store.execute(sql, [i.job_id for i in upload_jobs])

        for build, upload_jobs in uploads_per_build.items():
            has_finished_upload = any(
                i.status == JobStatus.COMPLETED or i.job_id == self.job_id
                for i in upload_jobs)
            if not has_finished_upload:
                return False
        return True

    def run(self):
        """See `IRunnableJob`."""
        client = getUtility(IOCIRegistryClient)
        # XXX twom 2020-04-16 This is taken from SnapStoreUploadJob
        # it will need to gain retry support.
        try:
            try:
                client.upload(self.build)
                # The "allBuildsUploaded" call will lock, on the database,
                # all upload jobs for update until this transaction finishes.
                # So, make sure this is the last thing being done by this job.
                if self.allBuildsUploaded(self.build.build_request):
                    client.uploadManifestList(self.build.build_request)
            except OCIRegistryError as e:
                self.error_summary = str(e)
                self.errors = e.errors
                raise
            except Exception as e:
                self.error_summary = str(e)
                self.errors = None
                raise
        except Exception:
            transaction.commit()
            raise
