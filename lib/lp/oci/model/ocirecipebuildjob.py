# Copyright 2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""OCIRecipe build jobs."""

__all__ = [
    "OCIRecipeBuildJob",
    "OCIRecipeBuildJobType",
]

import random
from datetime import timedelta

import transaction
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.databases.postgres import JSON
from storm.locals import Int, Reference, Store
from zope.component import getUtility
from zope.interface import implementer, provider

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
from lp.services.config import config
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.locking import (
    AdvisoryLockHeld,
    LockType,
    try_advisory_lock,
)
from lp.services.database.stormbase import StormBase
from lp.services.job.interfaces.job import JobStatus
from lp.services.job.model.job import EnumeratedSubclass, Job
from lp.services.job.runner import BaseRunnableJob
from lp.services.propertycache import get_property_cache
from lp.services.webapp.snapshot import notify_modified


class OCIRecipeBuildJobType(DBEnumeratedType):
    """Values that `OCIBuildJobType.job_type` can take."""

    REGISTRY_UPLOAD = DBItem(
        0,
        """
        Registry upload

        This job uploads an OCI Image to the registry.
        """,
    )


@implementer(IOCIRecipeBuildJob)
class OCIRecipeBuildJob(StormBase):
    """See `IOCIRecipeBuildJob`."""

    __storm_table__ = "OCIRecipeBuildJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    build_id = Int(name="build", allow_none=False)
    build = Reference(build_id, "OCIRecipeBuild.id")

    job_type = DBEnum(enum=OCIRecipeBuildJobType, allow_none=True)

    json_data = JSON("json_data", allow_none=False)

    def __init__(self, build, job_type, json_data, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param build: The `IOCIRecipeBuild` this job relates to.
        :param job_type: The `OCIRecipeBuildJobType` of this job.
        :param json_data: The type-specific variables, as a JSON-compatible
            dict.
        """
        super().__init__()
        self.job = Job(**job_args)
        self.build = build
        self.job_type = job_type
        self.json_data = json_data

    def makeDerived(self):
        return OCIRecipeBuildJobDerived.makeSubclass(self)


@delegate_to(IOCIRecipeBuildJob)
class OCIRecipeBuildJobDerived(BaseRunnableJob, metaclass=EnumeratedSubclass):
    def __init__(self, oci_build_job):
        self.context = oci_build_job

    def __repr__(self):
        """An informative representation of the job."""
        try:
            build = self.build
            return "<%s for ~%s/%s/+oci/%s/+recipe/%s/+build/%d>" % (
                self.__class__.__name__,
                build.recipe.owner.name,
                build.recipe.oci_project.pillar.name,
                build.recipe.oci_project.name,
                build.recipe.name,
                build.id,
            )
        except Exception:
            # There might be errors while trying to do the full
            # representation of this object (database transaction errors,
            # for example). There has been some issues in the past trying to
            # log this object, so let's not crash everything in case we
            # cannot provide a full description of self.
            return "<%s ID#%s>" % (self.__class__.__name__, self.job_id)

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `OCIRecipeBuildJob` with the specified id, as the current
            `OCIRecipeBuildJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        oci_build_job = IStore(OCIRecipeBuildJob).get(
            OCIRecipeBuildJob, job_id
        )
        if oci_build_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s"
                % (job_id, cls.class_job_type.title)
            )
        return cls(oci_build_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IStore(OCIRecipeBuildJob).find(
            OCIRecipeBuildJob,
            OCIRecipeBuildJob.job_type == cls.class_job_type,
            OCIRecipeBuildJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs),
        )
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super().getOopsVars()
        oops_vars.extend(
            [
                ("job_type", self.context.job_type.title),
                ("build_id", self.context.build.id),
                ("recipe_owner_id", self.context.build.recipe.owner.id),
                (
                    "oci_project_name",
                    self.context.build.recipe.oci_project.name,
                ),
            ]
        )
        return oops_vars


@implementer(IOCIRegistryUploadJob)
@provider(IOCIRegistryUploadJobSource)
class OCIRegistryUploadJob(OCIRecipeBuildJobDerived):
    """Manages the OCI image upload to registries.

    This job coordinates with other OCIRegistryUploadJob in a way that the
    last job uploading its layers and manifest will also upload the
    manifest list with all the previously built OCI images uploaded from
    other architectures in the same build request. To avoid race conditions,
    we synchronize that using a SELECT ... FOR UPDATE at database level to
    make sure that the status is consistent across all the upload jobs.
    """

    class_job_type = OCIRecipeBuildJobType.REGISTRY_UPLOAD

    # This is a known slow task that will exceed the timeouts for
    # the normal job queue, so put it on a queue with longer timeouts
    task_queue = "launchpad_job_slow"

    soft_time_limit = timedelta(minutes=60)
    lease_duration = timedelta(minutes=60)

    class ManifestListUploadError(Exception):
        pass

    retry_error_types = (
        ManifestListUploadError,
        AdvisoryLockHeld,
    )
    max_retries = 5

    config = config.IOCIRegistryUploadJobSource

    @classmethod
    def create(cls, build):
        """See `IOCIRegistryUploadJobSource`"""
        edited_fields = set()
        with notify_modified(build, edited_fields) as before_modification:
            json_data = {
                "build_uploaded": False,
            }
            oci_build_job = OCIRecipeBuildJob(
                build, cls.class_job_type, json_data
            )
            job = cls(oci_build_job)
            job.celeryRunOnCommit()
            IStore(OCIRecipeBuildJob).flush()
            del get_property_cache(build).last_registry_upload_job
            upload_status = build.registry_upload_status
            if upload_status != before_modification.registry_upload_status:
                edited_fields.add("registry_upload_status")
        return job

    @property
    def retry_delay(self):
        dithering_secs = int(random.random() * 60)
        delays = (10, 15, 20, 30)
        try:
            return timedelta(
                minutes=delays[self.attempt_count - 1], seconds=dithering_secs
            )
        except IndexError:
            return timedelta(minutes=10, seconds=dithering_secs)

    # Ideally we'd just override Job._set_status or similar, but
    # lazr.delegates makes that difficult, so we use this to override all
    # the individual Job lifecycle methods instead.
    def _do_lifecycle(
        self, method_name, manage_transaction=False, *args, **kwargs
    ):
        edited_fields = set()
        with notify_modified(self.build, edited_fields) as before_modification:
            getattr(super(), method_name)(
                *args, manage_transaction=manage_transaction, **kwargs
            )
            upload_status = self.build.registry_upload_status
            if upload_status != before_modification.registry_upload_status:
                edited_fields.add("registry_upload_status")
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
    def build_uploaded(self):
        return self.json_data.get("build_uploaded", False)

    @build_uploaded.setter
    def build_uploaded(self, value):
        self.json_data["build_uploaded"] = bool(value)

    def getUploadedBuilds(self, build_request):
        """Returns the list of builds in the given build_request that
        already finished uploading.

        Note that this method locks all upload jobs at database level,
        preventing them from updating their status until the end of the
        current transaction. Use it with caution. Note also that self.build is
        always included in the resulting list, as this method should only be
        called *after* the untagged manifest is uploaded.
        """
        builds = list(build_request.builds)
        uploads_per_build = {i: list(i.registry_upload_jobs) for i in builds}

        builds = set()
        for build, upload_jobs in uploads_per_build.items():
            has_finished_upload = any(
                i.status == JobStatus.COMPLETED or i.job_id == self.job_id
                for i in upload_jobs
            )
            if has_finished_upload:
                builds.add(build)
        return builds

    def uploadManifestList(self, client):
        """Uploads the aggregated manifest list for all uploaded builds in the
        current build request.
        """
        build_request = self.build.build_request
        if not build_request:
            return
        try:
            uploaded_builds = self.getUploadedBuilds(build_request)
            if uploaded_builds:
                client.uploadManifestList(build_request, uploaded_builds)
        except OCIRegistryError:
            # Do not retry automatically on known OCI registry errors.
            raise
        except Exception as e:
            raise self.ManifestListUploadError(str(e))

    def run(self):
        """See `IRunnableJob`."""
        client = getUtility(IOCIRegistryClient)
        try:
            with try_advisory_lock(
                LockType.REGISTRY_UPLOAD,
                self.build.recipe.id,
                Store.of(self.build.recipe),
            ):
                try:
                    if not self.build_uploaded:
                        client.upload(self.build)
                        self.build_uploaded = True

                    self.uploadManifestList(client)

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
