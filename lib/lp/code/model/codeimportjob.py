# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes for the CodeImportJob table."""

__all__ = [
    "CodeImportJob",
    "CodeImportJobSet",
    "CodeImportJobWorkflow",
]

from datetime import timedelta, timezone

from storm.expr import Cast
from storm.locals import DateTime, Desc, Int, Reference, Store, Unicode
from zope.component import getUtility
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.code.enums import (
    CodeImportJobState,
    CodeImportMachineState,
    CodeImportResultStatus,
    CodeImportReviewStatus,
    GitRepositoryType,
    RevisionControlSystems,
)
from lp.code.interfaces.branch import IBranch, get_blacklisted_hostnames
from lp.code.interfaces.codehosting import branch_id_alias, compose_public_url
from lp.code.interfaces.codeimport import ICodeImportSet
from lp.code.interfaces.codeimportevent import ICodeImportEventSet
from lp.code.interfaces.codeimportjob import (
    ICodeImportJob,
    ICodeImportJobSet,
    ICodeImportJobSetPublic,
    ICodeImportJobWorkflow,
)
from lp.code.interfaces.codeimportmachine import ICodeImportMachineSet
from lp.code.interfaces.codeimportresult import ICodeImportResultSet
from lp.code.interfaces.gitrepository import IGitRepository
from lp.code.model.codeimportresult import CodeImportResult
from lp.registry.interfaces.person import validate_public_person
from lp.services.config import config
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.sqlbase import get_transaction_timestamp
from lp.services.database.stormbase import StormBase
from lp.services.macaroons.interfaces import (
    NO_USER,
    BadMacaroonContext,
    IMacaroonIssuer,
)
from lp.services.macaroons.model import MacaroonIssuerBase


@implementer(ICodeImportJob)
class CodeImportJob(StormBase):
    """See `ICodeImportJob`."""

    __storm_table__ = "CodeImportJob"

    id = Int(primary=True)

    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )

    code_import_id = Int(name="code_import", allow_none=False)
    code_import = Reference(code_import_id, "CodeImport.id")

    machine_id = Int(name="machine", allow_none=True, default=None)
    machine = Reference(machine_id, "CodeImportMachine.id")

    date_due = DateTime(tzinfo=timezone.utc, allow_none=False)

    state = DBEnum(
        enum=CodeImportJobState,
        allow_none=False,
        default=CodeImportJobState.PENDING,
    )

    requesting_user_id = Int(
        name="requesting_user",
        allow_none=True,
        validator=validate_public_person,
        default=None,
    )
    requesting_user = Reference(requesting_user_id, "Person.id")

    ordering = Int(allow_none=True, default=None)

    heartbeat = DateTime(tzinfo=timezone.utc, allow_none=True, default=None)

    logtail = Unicode(allow_none=True, default=None)

    date_started = DateTime(tzinfo=timezone.utc, allow_none=True, default=None)

    def __init__(self, code_import, date_due):
        super().__init__()
        self.code_import = code_import
        self.date_due = date_due

    def isOverdue(self):
        """See `ICodeImportJob`."""
        return self.date_due <= get_transaction_timestamp(Store.of(self))

    def makeWorkerArguments(self):
        """See `ICodeImportJob`."""
        # Keep this in sync with CodeImportSourceDetails.fromArguments.
        code_import = self.code_import
        target = code_import.target

        if IBranch.providedBy(target):
            target_id = target.id
        else:
            # We don't have a better way to identify the target repository
            # than the mutable unique name, but the macaroon constrains
            # pushes tightly enough that the worst case is an authentication
            # failure.
            target_id = target.unique_name

        if code_import.rcs_type == RevisionControlSystems.BZR_SVN:
            rcs_type = "bzr-svn"
            target_rcs_type = "bzr"
        elif code_import.rcs_type == RevisionControlSystems.CVS:
            rcs_type = "cvs"
            target_rcs_type = "bzr"
        elif code_import.rcs_type == RevisionControlSystems.GIT:
            rcs_type = "git"
            if IBranch.providedBy(target):
                target_rcs_type = "bzr"
            else:
                target_rcs_type = "git"
        elif code_import.rcs_type == RevisionControlSystems.BZR:
            rcs_type = "bzr"
            target_rcs_type = "bzr"
        else:
            raise AssertionError("Unknown rcs_type %r." % code_import.rcs_type)

        result = [str(target_id), rcs_type, target_rcs_type]
        if rcs_type in ("bzr-svn", "git", "bzr"):
            result.append(str(code_import.url))
            if (
                IBranch.providedBy(target)
                and target.stacked_on is not None
                and not target.stacked_on.private
            ):
                stacked_path = branch_id_alias(target.stacked_on)
                stacked_on_url = compose_public_url("http", stacked_path)
                result.extend(["--stacked-on", stacked_on_url])
        elif rcs_type == "cvs":
            result.append(str(code_import.cvs_root))
            result.extend(["--cvs-module", str(code_import.cvs_module)])
        else:
            raise AssertionError("Unknown rcs_type %r." % rcs_type)
        if target_rcs_type == "git":
            issuer = getUtility(IMacaroonIssuer, "code-import-job")
            macaroon = removeSecurityProxy(issuer).issueMacaroon(self)
            # XXX cjwatson 2016-10-12: Consider arranging for this to be
            # passed to worker processes in the environment instead.
            result.extend(["--macaroon", macaroon.serialize()])
        # Refuse pointless self-mirroring.
        if rcs_type == target_rcs_type:
            result.extend(["--exclude-host", config.vhost.mainsite.hostname])
        # Refuse to import from configured hostnames, typically localhost
        # and similar.
        for hostname in get_blacklisted_hostnames():
            result.extend(["--exclude-host", hostname])
        return result

    def destroySelf(self):
        Store.of(self).remove(self)


@implementer(ICodeImportJobSet, ICodeImportJobSetPublic)
class CodeImportJobSet:
    """See `ICodeImportJobSet`."""

    # CodeImportJob database objects are created using
    # CodeImportJobWorkflow.newJob.

    def getById(self, id):
        """See `ICodeImportJobSet`."""
        return IStore(CodeImportJob).get(CodeImportJob, id)

    def getJobForMachine(self, hostname, worker_limit):
        """See `ICodeImportJobSet`."""
        job_workflow = getUtility(ICodeImportJobWorkflow)
        for job in self.getReclaimableJobs():
            job_workflow.reclaimJob(job)
        machine = getUtility(ICodeImportMachineSet).getByHostname(hostname)
        if machine is None:
            machine = getUtility(ICodeImportMachineSet).new(
                hostname, CodeImportMachineState.ONLINE
            )
        elif not machine.shouldLookForJob(worker_limit):
            return None
        job = (
            IStore(CodeImportJob)
            .find(
                CodeImportJob,
                CodeImportJob.date_due <= UTC_NOW,
                CodeImportJob.state == CodeImportJobState.PENDING,
            )
            .order_by(
                CodeImportJob.requesting_user == None, CodeImportJob.date_due
            )
            .first()
        )
        if job is not None:
            job_workflow.startJob(job, machine)
            return job
        else:
            return None

    def getReclaimableJobs(self):
        """See `ICodeImportJobSet`."""
        interval = config.codeimportworker.maximum_heartbeat_interval
        return IStore(CodeImportJob).find(
            CodeImportJob,
            CodeImportJob.state == CodeImportJobState.RUNNING,
            CodeImportJob.heartbeat
            < (UTC_NOW - Cast(timedelta(seconds=interval), "interval")),
        )

    def getJobsInState(self, state):
        return IStore(CodeImportJob).find(
            CodeImportJob, CodeImportJob.state == state
        )


@implementer(ICodeImportJobWorkflow)
class CodeImportJobWorkflow:
    """See `ICodeImportJobWorkflow`."""

    def newJob(self, code_import, interval=None):
        """See `ICodeImportJobWorkflow`."""
        assert (
            code_import.review_status == CodeImportReviewStatus.REVIEWED
        ), "Review status of %s is not REVIEWED: %s" % (
            code_import.target.unique_name,
            code_import.review_status.name,
        )
        assert (
            code_import.import_job is None
        ), "Already associated to a CodeImportJob: %s" % (
            code_import.target.unique_name
        )

        if interval is None:
            interval = code_import.effective_update_interval

        job = CodeImportJob(code_import=code_import, date_due=UTC_NOW)
        IStore(CodeImportJob).add(job)

        # Find the most recent CodeImportResult for this CodeImport. We
        # sort by date_created because we do not have an index on
        # date_job_started in the database, and that should give the same
        # sort order.
        most_recent_result = (
            IStore(CodeImportResult)
            .find(
                CodeImportResult, CodeImportResult.code_import == code_import
            )
            .order_by(Desc(CodeImportResult.date_created))
            .first()
        )

        if most_recent_result is not None:
            date_due = most_recent_result.date_job_started + interval
            job.date_due = max(job.date_due, date_due)

        return job

    def deletePendingJob(self, code_import):
        """See `ICodeImportJobWorkflow`."""
        assert (
            code_import.review_status != CodeImportReviewStatus.REVIEWED
        ), "The review status of %s is %s." % (
            code_import.target.unique_name,
            code_import.review_status.name,
        )
        assert (
            code_import.import_job is not None
        ), "Not associated to a CodeImportJob: %s" % (
            code_import.target.unique_name,
        )
        assert (
            code_import.import_job.state == CodeImportJobState.PENDING
        ), "The CodeImportJob associated to %s is %s." % (
            code_import.target.unique_name,
            code_import.import_job.state.name,
        )
        # CodeImportJobWorkflow is the only class that is allowed to delete
        # CodeImportJob rows, so destroySelf is not exposed in ICodeImportJob.
        removeSecurityProxy(code_import).import_job.destroySelf()

    def requestJob(self, import_job, user):
        """See `ICodeImportJobWorkflow`."""
        assert (
            import_job.state == CodeImportJobState.PENDING
        ), "The CodeImportJob associated with %s is %s." % (
            import_job.code_import.target.unique_name,
            import_job.state.name,
        )
        assert import_job.requesting_user is None, (
            "The CodeImportJob associated with %s "
            "was already requested by %s."
            % (
                import_job.code_import.target.unique_name,
                import_job.requesting_user.name,
            )
        )
        # CodeImportJobWorkflow is the only class that is allowed to set the
        # date_due and requesting_user attributes of CodeImportJob, they are
        # not settable through ICodeImportJob. So we must use
        # removeSecurityProxy here.
        if not import_job.isOverdue():
            removeSecurityProxy(import_job).date_due = UTC_NOW
        removeSecurityProxy(import_job).requesting_user = user
        getUtility(ICodeImportEventSet).newRequest(
            import_job.code_import, user
        )

    def startJob(self, import_job, machine):
        """See `ICodeImportJobWorkflow`."""
        assert (
            import_job.state == CodeImportJobState.PENDING
        ), "The CodeImportJob associated with %s is %s." % (
            import_job.code_import.target.unique_name,
            import_job.state.name,
        )
        assert (
            machine.state == CodeImportMachineState.ONLINE
        ), "The machine %s is %s." % (machine.hostname, machine.state.name)
        # CodeImportJobWorkflow is the only class that is allowed to set the
        # date_created, heartbeat, logtail, machine and state attributes of
        # CodeImportJob, they are not settable through ICodeImportJob. So we
        # must use removeSecurityProxy here.
        naked_job = removeSecurityProxy(import_job)
        naked_job.date_started = UTC_NOW
        naked_job.heartbeat = UTC_NOW
        naked_job.logtail = ""
        naked_job.machine = machine
        naked_job.state = CodeImportJobState.RUNNING
        getUtility(ICodeImportEventSet).newStart(
            import_job.code_import, machine
        )

    def updateHeartbeat(self, import_job, logtail):
        """See `ICodeImportJobWorkflow`."""
        assert (
            import_job.state == CodeImportJobState.RUNNING
        ), "The CodeImportJob associated with %s is %s." % (
            import_job.code_import.target.unique_name,
            import_job.state.name,
        )
        # CodeImportJobWorkflow is the only class that is allowed to
        # set the heartbeat and logtail attributes of CodeImportJob,
        # they are not settable through ICodeImportJob. So we must use
        # removeSecurityProxy here.
        naked_job = removeSecurityProxy(import_job)
        naked_job.heartbeat = UTC_NOW
        naked_job.logtail = logtail

    def _makeResultAndDeleteJob(self, import_job, status, logfile_alias):
        """Create a result for and delete 'import_job'.

        This method does some of the housekeeping required when a job has
        ended, no matter if it has finished normally or been killed or
        reclaimed.

        :param import_job: The job that has ended.
        :param status: The member of CodeImportResultStatus to create the
            result with.
        :param logfile_alias: A reference to the log file of the job, can be
            None.
        """
        result = getUtility(ICodeImportResultSet).new(
            code_import=import_job.code_import,
            machine=import_job.machine,
            log_excerpt=import_job.logtail,
            requesting_user=import_job.requesting_user,
            log_file=logfile_alias,
            status=status,
            date_job_started=import_job.date_started,
        )
        # CodeImportJobWorkflow is the only class that is allowed to delete
        # CodeImportJob objects, there is no method in the ICodeImportJob
        # interface to do this. So we must use removeSecurityProxy here.
        naked_job = removeSecurityProxy(import_job)
        naked_job.destroySelf()
        return result

    def finishJob(self, import_job, status, logfile_alias):
        """See `ICodeImportJobWorkflow`."""
        assert (
            import_job.state == CodeImportJobState.RUNNING
        ), "The CodeImportJob associated with %s is %s." % (
            import_job.code_import.target.unique_name,
            import_job.state.name,
        )
        code_import = import_job.code_import
        machine = import_job.machine
        result = self._makeResultAndDeleteJob(
            import_job, status, logfile_alias
        )
        # If the import has failed too many times in a row, mark it as
        # FAILING.
        failure_limit = config.codeimport.consecutive_failure_limit
        failure_count = code_import.consecutive_failure_count
        if failure_count >= failure_limit:
            code_import.updateFromData(
                dict(review_status=CodeImportReviewStatus.FAILING), None
            )
        elif status == CodeImportResultStatus.SUCCESS_PARTIAL:
            interval = timedelta(0)
        elif failure_count > 0:
            interval = code_import.effective_update_interval * (
                2 ** (failure_count - 1)
            )
        else:
            interval = code_import.effective_update_interval
        # Only start a new one if the import is still in the REVIEWED state.
        if code_import.review_status == CodeImportReviewStatus.REVIEWED:
            self.newJob(code_import, interval=interval)
        # If the status was successful, update date_last_successful.
        if status in [
            CodeImportResultStatus.SUCCESS,
            CodeImportResultStatus.SUCCESS_NOCHANGE,
        ]:
            naked_import = removeSecurityProxy(code_import)
            naked_import.date_last_successful = result.date_created
        # If the status was successful and revisions were imported, arrange
        # for the branch to be mirrored.
        if (
            status == CodeImportResultStatus.SUCCESS
            and code_import.branch is not None
        ):
            code_import.branch.requestMirror()
        getUtility(ICodeImportEventSet).newFinish(code_import, machine)

    def reclaimJob(self, import_job):
        """See `ICodeImportJobWorkflow`."""
        assert (
            import_job.state == CodeImportJobState.RUNNING
        ), "The CodeImportJob associated with %s is %s." % (
            import_job.code_import.target.unique_name,
            import_job.state.name,
        )
        # Cribbing from codeimport-job.rst, this method does four things:
        # 1) deletes the passed in job,
        # 2) creates a CodeImportResult with a status of 'RECLAIMED',
        # 3) creates a new, already due, job for the code import, and
        # 4) logs a 'RECLAIM' CodeImportEvent.
        job_id = import_job.id
        code_import = import_job.code_import
        machine = import_job.machine
        # 1) and 2)
        self._makeResultAndDeleteJob(
            import_job, CodeImportResultStatus.RECLAIMED, None
        )
        # 3)
        if code_import.review_status == CodeImportReviewStatus.REVIEWED:
            self.newJob(code_import, timedelta(0))
        # 4)
        getUtility(ICodeImportEventSet).newReclaim(
            code_import, machine, job_id
        )


@implementer(IMacaroonIssuer)
class CodeImportJobMacaroonIssuer(MacaroonIssuerBase):
    identifier = "code-import-job"

    @property
    def _root_secret(self):
        secret = config.launchpad.internal_macaroon_secret_key
        if not secret:
            raise RuntimeError(
                "launchpad.internal_macaroon_secret_key not configured."
            )
        return secret

    def checkIssuingContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`."""
        if context.code_import.git_repository is None:
            raise BadMacaroonContext(
                context, "context.code_import.git_repository is None"
            )
        return context.id

    def checkVerificationContext(self, context, **kwargs):
        """See `MacaroonIssuerBase`.

        For verification, the context may be an `ICodeImportJob`, in which
        case we check that the context job is currently running; or it may
        be an `IGitRepository`, in which case we check that the repository
        is an imported repository with an associated code import, and then
        perform the previously-stated check on its code import job.
        """
        if IGitRepository.providedBy(context):
            if context.repository_type != GitRepositoryType.IMPORTED:
                raise BadMacaroonContext(
                    context, "%r is not an IMPORTED repository." % context
                )
            code_import = getUtility(ICodeImportSet).getByGitRepository(
                context
            )
            if code_import is None:
                raise BadMacaroonContext(
                    context, "%r does not have a code import." % context
                )
            context = code_import.import_job
        if not ICodeImportJob.providedBy(context):
            raise BadMacaroonContext(context)
        if context.state != CodeImportJobState.RUNNING:
            raise BadMacaroonContext(
                context, "%r is not in the RUNNING state." % context
            )
        return context

    def verifyPrimaryCaveat(
        self, verified, caveat_value, context, user=None, **kwargs
    ):
        """See `MacaroonIssuerBase`."""
        # Code import jobs only support free-floating macaroons for Git
        # authentication, not ones bound to a user.
        if user:
            return False
        verified.user = NO_USER
        if context is None:
            # We're only verifying that the macaroon could be valid for some
            # context.
            return True
        return caveat_value == str(context.id)
