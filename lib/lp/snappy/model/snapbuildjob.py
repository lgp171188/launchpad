# Copyright 2016-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Snap build jobs."""

__all__ = [
    "SnapBuildJob",
    "SnapBuildJobType",
    "SnapBuildStoreUploadStatusChangedEvent",
    "SnapStoreUploadJob",
]

from datetime import timedelta

import transaction
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.locals import JSON, Int, Reference
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer, provider
from zope.interface.interfaces import ObjectEvent

from lp.app.errors import NotFoundError
from lp.services.config import config
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import EnumeratedSubclass, Job
from lp.services.job.runner import BaseRunnableJob
from lp.services.propertycache import get_property_cache
from lp.services.scripts import log
from lp.snappy.interfaces.snapbuildjob import (
    ISnapBuildJob,
    ISnapBuildStoreUploadStatusChangedEvent,
    ISnapStoreUploadJob,
    ISnapStoreUploadJobSource,
)
from lp.snappy.interfaces.snapstoreclient import (
    BadRefreshResponse,
    BadScanStatusResponse,
    ISnapStoreClient,
    ScanFailedResponse,
    SnapStoreError,
    UnauthorizedUploadResponse,
    UploadFailedResponse,
    UploadNotScannedYetResponse,
)
from lp.snappy.mail.snapbuild import SnapBuildMailer


class SnapBuildJobType(DBEnumeratedType):
    """Values that `ISnapBuildJob.job_type` can take."""

    STORE_UPLOAD = DBItem(
        0,
        """
        Store upload

        This job uploads a snap build to the store.
        """,
    )


@implementer(ISnapBuildJob)
class SnapBuildJob(StormBase):
    """See `ISnapBuildJob`."""

    __storm_table__ = "SnapBuildJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    snapbuild_id = Int(name="snapbuild", allow_none=False)
    snapbuild = Reference(snapbuild_id, "SnapBuild.id")

    job_type = DBEnum(enum=SnapBuildJobType, allow_none=False)

    metadata = JSON("json_data", allow_none=False)

    def __init__(self, snapbuild, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param snapbuild: The `ISnapBuild` this job relates to.
        :param job_type: The `SnapBuildJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super().__init__()
        self.job = Job(**job_args)
        self.snapbuild = snapbuild
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return SnapBuildJobDerived.makeSubclass(self)


@delegate_to(ISnapBuildJob)
class SnapBuildJobDerived(BaseRunnableJob, metaclass=EnumeratedSubclass):
    def __init__(self, snap_build_job):
        self.context = snap_build_job

    def __repr__(self):
        """An informative representation of the job."""
        snap = self.snapbuild.snap
        return "<%s for ~%s/+snap/%s/+build/%d>" % (
            self.__class__.__name__,
            snap.owner.name,
            snap.name,
            self.snapbuild.id,
        )

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `SnapBuildJob` with the specified id, as the current
            `SnapBuildJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        snap_build_job = IStore(SnapBuildJob).get(SnapBuildJob, job_id)
        if snap_build_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s"
                % (job_id, cls.class_job_type.title)
            )
        return cls(snap_build_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IPrimaryStore(SnapBuildJob).find(
            SnapBuildJob,
            SnapBuildJob.job_type == cls.class_job_type,
            SnapBuildJob.job == Job.id,
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
                ("snapbuild_id", self.context.snapbuild.id),
                ("snap_owner_name", self.context.snapbuild.snap.owner.name),
                ("snap_name", self.context.snapbuild.snap.name),
            ]
        )
        return oops_vars


class RetryableSnapStoreError(SnapStoreError):
    pass


@implementer(ISnapBuildStoreUploadStatusChangedEvent)
class SnapBuildStoreUploadStatusChangedEvent(ObjectEvent):
    """See `ISnapBuildStoreUploadStatusChangedEvent`."""


@implementer(ISnapStoreUploadJob)
@provider(ISnapStoreUploadJobSource)
class SnapStoreUploadJob(SnapBuildJobDerived):
    """A Job that uploads a snap build to the store."""

    class_job_type = SnapBuildJobType.STORE_UPLOAD

    user_error_types = (
        UnauthorizedUploadResponse,
        ScanFailedResponse,
    )

    retry_error_types = (UploadNotScannedYetResponse, RetryableSnapStoreError)
    max_retries = 30

    config = config.ISnapStoreUploadJobSource

    @classmethod
    def create(cls, snapbuild):
        """See `ISnapStoreUploadJobSource`."""
        snap_build_job = SnapBuildJob(snapbuild, cls.class_job_type, {})
        job = cls(snap_build_job)
        job.celeryRunOnCommit()
        IStore(SnapBuildJob).flush()
        del get_property_cache(snapbuild).last_store_upload_job
        notify(SnapBuildStoreUploadStatusChangedEvent(snapbuild))
        return job

    @property
    def store_metadata(self):
        """See `ISnapStoreUploadJob`."""
        intermediate = {}
        intermediate.update(self.metadata)
        intermediate.update(self.snapbuild.store_upload_metadata or {})
        return intermediate

    @property
    def error_message(self):
        """See `ISnapStoreUploadJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `ISnapStoreUploadJob`."""
        self.metadata["error_message"] = message

    @property
    def error_detail(self):
        """See `ISnapStoreUploadJob`."""
        return self.metadata.get("error_detail")

    @error_detail.setter
    def error_detail(self, detail):
        """See `ISnapStoreUploadJob`."""
        self.metadata["error_detail"] = detail

    @property
    def error_messages(self):
        """See `ISnapStoreUploadJob`."""
        return self.metadata.get("error_messages")

    @error_messages.setter
    def error_messages(self, messages):
        """See `ISnapStoreUploadJob`."""
        self.metadata["error_messages"] = messages

    @property
    def upload_id(self):
        """See `ISnapStoreUploadJob`."""
        return self.store_metadata.get("upload_id")

    @upload_id.setter
    def upload_id(self, upload_id):
        """See `ISnapStoreUploadJob`."""
        if self.snapbuild.store_upload_metadata is None:
            self.snapbuild.store_upload_metadata = {}
        self.snapbuild.store_upload_metadata["upload_id"] = upload_id

    @property
    def components_ids(self):
        """See `ISnapStoreUploadJob`."""
        return self.store_metadata.get("components_ids")

    @components_ids.setter
    def components_ids(self, components_ids):
        """See `ISnapStoreUploadJob`."""
        if self.snapbuild.store_upload_metadata is None:
            self.snapbuild.store_upload_metadata = {}
        self.snapbuild.store_upload_metadata["components_ids"] = components_ids

    @property
    def status_url(self):
        """See `ISnapStoreUploadJob`."""
        return self.store_metadata.get("status_url")

    @status_url.setter
    def status_url(self, url):
        if self.snapbuild.store_upload_metadata is None:
            self.snapbuild.store_upload_metadata = {}
        self.snapbuild.store_upload_metadata["status_url"] = url

    @property
    def store_url(self):
        """See `ISnapStoreUploadJob`."""
        return self.store_metadata.get("store_url")

    @store_url.setter
    def store_url(self, url):
        """See `ISnapStoreUploadJob`."""
        if self.snapbuild.store_upload_metadata is None:
            self.snapbuild.store_upload_metadata = {}
        self.snapbuild.store_upload_metadata["store_url"] = url

    @property
    def store_revision(self):
        """See `ISnapStoreUploadJob`."""
        return self.store_metadata.get("store_revision")

    @store_revision.setter
    def store_revision(self, revision):
        """See `ISnapStoreUploadJob`."""
        if self.snapbuild.store_upload_metadata is None:
            self.snapbuild.store_upload_metadata = {}
        self.snapbuild.store_upload_metadata["store_revision"] = revision
        self.snapbuild.store_upload_revision = revision

    # Ideally we'd just override Job._set_status or similar, but
    # lazr.delegates makes that difficult, so we use this to override all
    # the individual Job lifecycle methods instead.
    def _do_lifecycle(
        self, method_name, manage_transaction=False, *args, **kwargs
    ):
        old_store_upload_status = self.snapbuild.store_upload_status
        getattr(super(), method_name)(
            *args, manage_transaction=manage_transaction, **kwargs
        )
        if self.snapbuild.store_upload_status != old_store_upload_status:
            notify(SnapBuildStoreUploadStatusChangedEvent(self.snapbuild))
            if manage_transaction:
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

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super().getOopsVars()
        oops_vars.append(("error_detail", self.error_detail))
        return oops_vars

    @property
    def retry_delay(self):
        """See `BaseRunnableJob`."""
        if "status_url" in self.store_metadata and self.store_url is None:
            # At the moment we have to poll the status endpoint to find out
            # if the store has finished scanning.  Try to deal with easy
            # cases quickly without hammering our job runners or the store
            # too badly.
            delays = (15, 15, 30, 30)
            try:
                return timedelta(seconds=delays[self.attempt_count - 1])
            except IndexError:
                pass
        return timedelta(minutes=1)

    @staticmethod
    def _extract_component_name(filename):
        """Extract component name from built component filename

        The built filename has the following pattern:
        <snap_name>+<component_name>_<component_revision>.comp.
        <snap_name> and <component_name> cannot contain `+` nor `_`
        by desing.
        """
        start = filename.find("+")
        end = filename.find("_")
        if start == -1 or end == -1:
            return filename
        else:
            return filename[start + 1 : end]

    def run(self):
        """See `IRunnableJob`."""
        client = getUtility(ISnapStoreClient)
        try:
            try:
                snap_lfa = next(
                    (
                        lfa
                        for _, lfa, _ in self.snapbuild.getFiles()
                        if lfa.filename.endswith(".snap")
                    ),
                    None,
                )
                if snap_lfa is None:
                    # Nothing to do.
                    self.error_message = None
                    return

                # Get components if any
                components = []
                components_ids = {}
                for _, lfa, _ in self.snapbuild.getFiles():
                    if lfa.filename.endswith(".comp"):
                        comp_name = self._extract_component_name(lfa.filename)
                        components_ids[comp_name] = None
                        components.append(lfa)

                if "components_ids" not in self.store_metadata:
                    self.components_ids = components_ids
                if "upload_id" not in self.store_metadata:
                    self.upload_id = client.uploadFile(snap_lfa)
                    # We made progress, so reset attempt_count.
                    self.attempt_count = 1

                # Process components
                for component in components:
                    # if the id is None, we need to upload the component
                    # because it means that that component was never uploaded.
                    # Note that the id is returned directly from SnapStore API.
                    comp_name = self._extract_component_name(
                        component.filename
                    )
                    if self.components_ids.get(comp_name) is None:
                        self.components_ids[comp_name] = client.uploadFile(
                            component
                        )
                        self.attempt_count = 1
                if "status_url" not in self.store_metadata:
                    log.info(
                        "[SnapStoreUploadJob] Pushing build %s with id %s.",
                        self.snapbuild.snap.name,
                        self.snapbuild.id,
                    )
                    log.info(
                        "[SnapStoreUploadJob] Components: %s",
                        self.components_ids,
                    )
                    self.status_url = client.push(
                        self.snapbuild, self.upload_id, self.components_ids
                    )
                    # We made progress, so reset attempt_count.
                    self.attempt_count = 1

                if self.store_url is None:
                    # This is no longer strictly necessary as the store is
                    # handling releases via the release intent, but we
                    # export various fields via the API, so once this is
                    # called, we're done with this task.
                    self.store_url, self.store_revision = client.checkStatus(
                        self.status_url
                    )
                self.error_message = None
            except self.retry_error_types:
                raise
            except Exception as e:
                if (
                    isinstance(e, SnapStoreError)
                    and e.can_retry
                    and self.attempt_count <= self.max_retries
                ):
                    raise RetryableSnapStoreError(e.args[0], detail=e.detail)
                self.error_message = str(e)
                self.error_messages = getattr(e, "messages", None)
                self.error_detail = getattr(e, "detail", None)
                mailer_factory = None
                if isinstance(e, UnauthorizedUploadResponse):
                    mailer_factory = SnapBuildMailer.forUnauthorizedUpload
                elif isinstance(e, BadRefreshResponse):
                    mailer_factory = SnapBuildMailer.forRefreshFailure
                elif isinstance(e, UploadFailedResponse):
                    mailer_factory = SnapBuildMailer.forUploadFailure
                elif isinstance(
                    e, (BadScanStatusResponse, ScanFailedResponse)
                ):
                    mailer_factory = SnapBuildMailer.forUploadScanFailure
                if mailer_factory is not None:
                    mailer_factory(self.snapbuild).sendAll()
                raise
        except Exception:
            # The normal job infrastructure will abort the transaction, but
            # we want to commit instead: the only database changes we make
            # are to this job's metadata and should be preserved.
            transaction.commit()
            raise
