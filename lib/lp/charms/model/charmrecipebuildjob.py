# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Charm recipe build jobs."""

__all__ = [
    "CharmhubUploadJob",
    "CharmRecipeBuildJob",
    "CharmRecipeBuildJobType",
]

from datetime import timedelta

import transaction
from lazr.delegates import delegate_to
from lazr.enum import DBEnumeratedType, DBItem
from storm.databases.postgres import JSON
from storm.locals import Int, Reference
from zope.component import getUtility
from zope.interface import implementer, provider

from lp.app.errors import NotFoundError
from lp.charms.interfaces.charmhubclient import (
    BadReviewStatusResponse,
    CharmhubError,
    ICharmhubClient,
    ReleaseFailedResponse,
    ReviewFailedResponse,
    UnauthorizedUploadResponse,
    UploadFailedResponse,
    UploadNotReviewedYetResponse,
)
from lp.charms.interfaces.charmrecipebuildjob import (
    ICharmhubUploadJob,
    ICharmhubUploadJobSource,
    ICharmRecipeBuildJob,
)
from lp.charms.mail.charmrecipebuild import CharmRecipeBuildMailer
from lp.services.config import config
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IPrimaryStore, IStore
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import EnumeratedSubclass, Job
from lp.services.job.runner import BaseRunnableJob
from lp.services.propertycache import get_property_cache
from lp.services.webapp.snapshot import notify_modified


class CharmRecipeBuildJobType(DBEnumeratedType):
    """Values that `ICharmRecipeBuildJob.job_type` can take."""

    CHARMHUB_UPLOAD = DBItem(
        0,
        """
        Charmhub upload

        This job uploads a charm recipe build to Charmhub.
        """,
    )


@implementer(ICharmRecipeBuildJob)
class CharmRecipeBuildJob(StormBase):
    """See `ICharmRecipeBuildJob`."""

    __storm_table__ = "CharmRecipeBuildJob"

    job_id = Int(name="job", primary=True, allow_none=False)
    job = Reference(job_id, "Job.id")

    build_id = Int(name="build", allow_none=False)
    build = Reference(build_id, "CharmRecipeBuild.id")

    job_type = DBEnum(enum=CharmRecipeBuildJobType, allow_none=False)

    metadata = JSON("json_data", allow_none=False)

    def __init__(self, build, job_type, metadata, **job_args):
        """Constructor.

        Extra keyword arguments are used to construct the underlying Job
        object.

        :param build: The `ICharmRecipeBuild` this job relates to.
        :param job_type: The `CharmRecipeBuildJobType` of this job.
        :param metadata: The type-specific variables, as a JSON-compatible
            dict.
        """
        super().__init__()
        self.job = Job(**job_args)
        self.build = build
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return CharmRecipeBuildJobDerived.makeSubclass(self)


@delegate_to(ICharmRecipeBuildJob)
class CharmRecipeBuildJobDerived(
    BaseRunnableJob, metaclass=EnumeratedSubclass
):
    def __init__(self, charm_recipe_build_job):
        self.context = charm_recipe_build_job

    def __repr__(self):
        """An informative representation of the job."""
        recipe = self.build.recipe
        return "<%s for ~%s/%s/+charm/%s/+build/%d>" % (
            self.__class__.__name__,
            recipe.owner.name,
            recipe.project.name,
            recipe.name,
            self.build.id,
        )

    @classmethod
    def get(cls, job_id):
        """Get a job by id.

        :return: The `CharmRecipeBuildJob` with the specified id, as the
            current `CharmRecipeBuildJobDerived` subclass.
        :raises: `NotFoundError` if there is no job with the specified id,
            or its `job_type` does not match the desired subclass.
        """
        charm_recipe_build_job = IStore(CharmRecipeBuildJob).get(
            CharmRecipeBuildJob, job_id
        )
        if charm_recipe_build_job.job_type != cls.class_job_type:
            raise NotFoundError(
                "No object found with id %d and type %s"
                % (job_id, cls.class_job_type.title)
            )
        return cls(charm_recipe_build_job)

    @classmethod
    def iterReady(cls):
        """See `IJobSource`."""
        jobs = IPrimaryStore(CharmRecipeBuildJob).find(
            CharmRecipeBuildJob,
            CharmRecipeBuildJob.job_type == cls.class_job_type,
            CharmRecipeBuildJob.job == Job.id,
            Job.id.is_in(Job.ready_jobs),
        )
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super().getOopsVars()
        recipe = self.context.build.recipe
        oops_vars.extend(
            [
                ("job_id", self.context.job.id),
                ("job_type", self.context.job_type.title),
                ("build_id", self.context.build.id),
                ("recipe_owner_name", recipe.owner.name),
                ("recipe_project_name", recipe.project.name),
                ("recipe_name", recipe.name),
            ]
        )
        return oops_vars


class RetryableCharmhubError(CharmhubError):
    pass


@implementer(ICharmhubUploadJob)
@provider(ICharmhubUploadJobSource)
class CharmhubUploadJob(CharmRecipeBuildJobDerived):
    """A Job that uploads a charm recipe build to Charmhub."""

    class_job_type = CharmRecipeBuildJobType.CHARMHUB_UPLOAD

    user_error_types = (
        UnauthorizedUploadResponse,
        ReviewFailedResponse,
        ReleaseFailedResponse,
    )

    retry_error_types = (UploadNotReviewedYetResponse, RetryableCharmhubError)
    max_retries = 30

    config = config.ICharmhubUploadJobSource

    @classmethod
    def create(cls, build):
        """See `ICharmhubUploadJobSource`."""
        edited_fields = set()
        with notify_modified(build, edited_fields) as before_modification:
            charm_recipe_build_job = CharmRecipeBuildJob(
                build, cls.class_job_type, {}
            )
            job = cls(charm_recipe_build_job)
            job.celeryRunOnCommit()
            IStore(CharmRecipeBuildJob).flush()
            del get_property_cache(build).last_store_upload_job
            upload_status = build.store_upload_status
            if upload_status != before_modification.store_upload_status:
                edited_fields.add("store_upload_status")
        return job

    @property
    def store_metadata(self):
        """See `ICharmhubUploadJob`."""
        intermediate = {}
        intermediate.update(self.metadata)
        intermediate.update(self.build.store_upload_metadata or {})
        return intermediate

    @property
    def error_message(self):
        """See `ICharmhubUploadJob`."""
        return self.metadata.get("error_message")

    @error_message.setter
    def error_message(self, message):
        """See `ICharmhubUploadJob`."""
        self.metadata["error_message"] = message

    @property
    def error_detail(self):
        """See `ICharmhubUploadJob`."""
        return self.metadata.get("error_detail")

    @error_detail.setter
    def error_detail(self, detail):
        """See `ICharmhubUploadJob`."""
        self.metadata["error_detail"] = detail

    @property
    def upload_id(self):
        """See `ICharmhubUploadJob`."""
        return self.store_metadata.get("upload_id")

    @upload_id.setter
    def upload_id(self, upload_id):
        """See `ICharmhubUploadJob`."""
        if self.build.store_upload_metadata is None:
            self.build.store_upload_metadata = {}
        self.build.store_upload_metadata["upload_id"] = upload_id

    @property
    def status_url(self):
        """See `ICharmhubUploadJob`."""
        return self.store_metadata.get("status_url")

    @status_url.setter
    def status_url(self, url):
        if self.build.store_upload_metadata is None:
            self.build.store_upload_metadata = {}
        self.build.store_upload_metadata["status_url"] = url

    @property
    def store_revision(self):
        """See `ICharmhubUploadJob`."""
        return self.store_metadata.get("store_revision")

    @store_revision.setter
    def store_revision(self, revision):
        """See `ICharmhubUploadJob`."""
        if self.build.store_upload_metadata is None:
            self.build.store_upload_metadata = {}
        self.build.store_upload_metadata["store_revision"] = revision

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
            upload_status = self.build.store_upload_status
            if upload_status != before_modification.store_upload_status:
                edited_fields.add("store_upload_status")
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

    def getOopsVars(self):
        """See `IRunnableJob`."""
        oops_vars = super().getOopsVars()
        oops_vars.append(("error_detail", self.error_detail))
        return oops_vars

    @property
    def retry_delay(self):
        """See `BaseRunnableJob`."""
        if "status_url" in self.store_metadata and self.store_revision is None:
            # At the moment we have to poll the status endpoint to find out
            # if Charmhub has finished scanning.  Try to deal with easy
            # cases quickly without hammering our job runners or Charmhub
            # too badly.
            delays = (15, 15, 30, 30)
            try:
                return timedelta(seconds=delays[self.attempt_count - 1])
            except IndexError:
                pass
        return timedelta(minutes=1)

    def run(self):
        """See `IRunnableJob`."""
        client = getUtility(ICharmhubClient)
        try:
            try:
                charm_lfa = next(
                    (
                        lfa
                        for _, lfa, _ in self.build.getFiles()
                        if lfa.filename.endswith(".charm")
                    ),
                    None,
                )
                if charm_lfa is None:
                    # Nothing to do.
                    self.error_message = None
                    return
                if "upload_id" not in self.store_metadata:
                    self.upload_id = client.uploadFile(charm_lfa)
                    # We made progress, so reset attempt_count.
                    self.attempt_count = 1
                if "status_url" not in self.store_metadata:
                    self.status_url = client.push(self.build, self.upload_id)
                    # We made progress, so reset attempt_count.
                    self.attempt_count = 1
                if self.store_revision is None:
                    self.store_revision = client.checkStatus(
                        self.build, self.status_url
                    )
                    if self.store_revision is None:
                        raise AssertionError(
                            "checkStatus returned successfully but with no "
                            "revision"
                        )
                    # We made progress, so reset attempt_count.
                    self.attempt_count = 1
                if self.build.recipe.store_channels:
                    client.release(self.build, self.store_revision)
                self.error_message = None
            except self.retry_error_types:
                raise
            except Exception as e:
                if (
                    isinstance(e, CharmhubError)
                    and e.can_retry
                    and self.attempt_count <= self.max_retries
                ):
                    raise RetryableCharmhubError(e.args[0], detail=e.detail)
                self.error_message = str(e)
                self.error_detail = getattr(e, "detail", None)
                mailer_factory = None
                if isinstance(e, UnauthorizedUploadResponse):
                    mailer_factory = (
                        CharmRecipeBuildMailer.forUnauthorizedUpload
                    )
                elif isinstance(e, UploadFailedResponse):
                    mailer_factory = CharmRecipeBuildMailer.forUploadFailure
                elif isinstance(
                    e, (BadReviewStatusResponse, ReviewFailedResponse)
                ):
                    mailer_factory = (
                        CharmRecipeBuildMailer.forUploadReviewFailure
                    )
                elif isinstance(e, ReleaseFailedResponse):
                    mailer_factory = CharmRecipeBuildMailer.forReleaseFailure
                if mailer_factory is not None:
                    mailer_factory(self.build).sendAll()
                raise
        except Exception:
            # The normal job infrastructure will abort the transaction, but
            # we want to commit instead: the only database changes we make
            # are to this job's metadata and should be preserved.
            transaction.commit()
            raise
