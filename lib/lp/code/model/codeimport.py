# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes including and related to CodeImport."""

__all__ = [
    "CodeImport",
    "CodeImportSet",
]

from datetime import timedelta, timezone

from lazr.lifecycle.event import ObjectCreatedEvent
from storm.expr import And, Desc, Func, Select
from storm.locals import (
    DateTime,
    Int,
    Reference,
    ReferenceSet,
    Store,
    TimeDelta,
    Unicode,
)
from zope.component import getUtility
from zope.event import notify
from zope.interface import implementer
from zope.security.proxy import removeSecurityProxy

from lp.app.errors import NotFoundError
from lp.code.enums import (
    NON_CVS_RCS_TYPES,
    BranchType,
    CodeImportJobState,
    CodeImportResultStatus,
    CodeImportReviewStatus,
    GitRepositoryType,
    RevisionControlSystems,
    TargetRevisionControlSystems,
)
from lp.code.errors import (
    CodeImportAlreadyRequested,
    CodeImportAlreadyRunning,
    CodeImportInvalidTargetType,
    CodeImportNotInReviewedState,
)
from lp.code.interfaces.branch import IBranch
from lp.code.interfaces.branchtarget import IBranchTarget
from lp.code.interfaces.codeimport import ICodeImport, ICodeImportSet
from lp.code.interfaces.codeimportevent import ICodeImportEventSet
from lp.code.interfaces.codeimportjob import ICodeImportJobWorkflow
from lp.code.interfaces.githosting import IGitHostingClient
from lp.code.interfaces.gitnamespace import get_git_namespace
from lp.code.interfaces.gitrepository import IGitRepository
from lp.code.interfaces.hasgitrepositories import IHasGitRepositories
from lp.code.mail.codeimport import code_import_updated
from lp.code.model.codeimportjob import CodeImportJobWorkflow
from lp.code.model.codeimportresult import CodeImportResult
from lp.registry.interfaces.person import validate_public_person
from lp.services.config import config
from lp.services.database.constants import DEFAULT
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(ICodeImport)
class CodeImport(StormBase):
    """See `ICodeImport`."""

    __storm_table__ = "CodeImport"
    __storm_order__ = "id"

    id = Int(primary=True)

    def __init__(
        self,
        registrant,
        owner,
        target,
        review_status,
        rcs_type=None,
        url=None,
        cvs_root=None,
        cvs_module=None,
    ):
        super().__init__()
        self.registrant = registrant
        self.owner = owner
        if IBranch.providedBy(target):
            self.branch = target
            self.git_repository = None
        elif IGitRepository.providedBy(target):
            self.branch = None
            self.git_repository = target
        else:
            raise AssertionError("Unknown code import target %s" % target)
        self.review_status = review_status
        self.rcs_type = rcs_type
        self.url = url
        self.cvs_root = cvs_root
        self.cvs_module = cvs_module

    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=DEFAULT
    )
    branch_id = Int(name="branch", allow_none=True)
    branch = Reference(branch_id, "Branch.id")
    git_repository_id = Int(name="git_repository", allow_none=True)
    git_repository = Reference(git_repository_id, "GitRepository.id")

    @property
    def target(self):
        if self.branch is not None:
            return self.branch
        else:
            assert self.git_repository is not None
            return self.git_repository

    registrant_id = Int(
        name="registrant", allow_none=False, validator=validate_public_person
    )
    registrant = Reference(registrant_id, "Person.id")
    owner_id = Int(
        name="owner", allow_none=False, validator=validate_public_person
    )
    owner = Reference(owner_id, "Person.id")
    assignee_id = Int(
        name="assignee",
        allow_none=True,
        validator=validate_public_person,
        default=None,
    )
    assignee = Reference(assignee_id, "Person.id")

    review_status = DBEnum(
        enum=CodeImportReviewStatus,
        allow_none=False,
        default=CodeImportReviewStatus.REVIEWED,
    )

    rcs_type = DBEnum(
        enum=RevisionControlSystems, allow_none=True, default=None
    )

    @property
    def target_rcs_type(self):
        if self.branch is not None:
            return TargetRevisionControlSystems.BZR
        else:
            return TargetRevisionControlSystems.GIT

    cvs_root = Unicode(default=None)

    cvs_module = Unicode(default=None)

    url = Unicode(default=None)

    date_last_successful = DateTime(tzinfo=timezone.utc, default=None)
    update_interval = TimeDelta(default=None)

    @property
    def effective_update_interval(self):
        """See `ICodeImport`."""
        if self.update_interval is not None:
            return self.update_interval
        default_interval_dict = {
            RevisionControlSystems.CVS: config.codeimport.default_interval_cvs,
            RevisionControlSystems.BZR_SVN: (
                config.codeimport.default_interval_subversion
            ),
            RevisionControlSystems.GIT: config.codeimport.default_interval_git,
            RevisionControlSystems.BZR: config.codeimport.default_interval_bzr,
        }
        # The default can be removed when HG is fully purged.
        seconds = default_interval_dict.get(self.rcs_type, 21600)
        return timedelta(seconds=seconds)

    import_job = Reference(id, "CodeImportJob.code_import_id", on_remote=True)

    def getImportDetailsForDisplay(self):
        """See `ICodeImport`."""
        assert (
            self.rcs_type is not None
        ), "Only makes sense for series with import details set."
        if self.rcs_type == RevisionControlSystems.CVS:
            return "%s %s" % (self.cvs_root, self.cvs_module)
        elif self.rcs_type in (
            RevisionControlSystems.SVN,
            RevisionControlSystems.GIT,
            RevisionControlSystems.BZR_SVN,
            RevisionControlSystems.HG,
            RevisionControlSystems.BZR,
        ):
            return self.url
        else:
            raise AssertionError("Unknown rcs type: %s" % self.rcs_type.title)

    def _removeJob(self):
        """If there is a pending job, remove it."""
        job = self.import_job
        if job is not None:
            if job.state == CodeImportJobState.PENDING:
                CodeImportJobWorkflow().deletePendingJob(self)

    results = ReferenceSet(
        id,
        "CodeImportResult.code_import_id",
        order_by=Desc("CodeImportResult.date_job_started"),
    )

    @property
    def consecutive_failure_count(self):
        """See `ICodeImport`."""
        # This SQL translates as "how many code import results have there been
        # for this code import since the last successful one".
        # This is not very efficient for long lists of code imports.
        last_success = Func(
            "coalesce",
            Select(
                CodeImportResult.id,
                And(
                    CodeImportResult.status.is_in(
                        CodeImportResultStatus.successes
                    ),
                    CodeImportResult.code_import == self,
                ),
                order_by=Desc(CodeImportResult.id),
                limit=1,
            ),
            0,
        )
        return (
            Store.of(self)
            .find(
                CodeImportResult,
                CodeImportResult.code_import == self,
                CodeImportResult.id > last_success,
            )
            .count()
        )

    def updateFromData(self, data, user):
        """See `ICodeImport`."""
        event_set = getUtility(ICodeImportEventSet)
        new_whiteboard = None
        if "whiteboard" in data:
            whiteboard = data.pop("whiteboard")
            # XXX cjwatson 2016-10-03: Do we need something similar for Git?
            if self.branch is not None:
                if whiteboard != self.branch.whiteboard:
                    if whiteboard is None:
                        new_whiteboard = ""
                    else:
                        new_whiteboard = whiteboard
                    self.branch.whiteboard = whiteboard
        token = event_set.beginModify(self)
        for name, value in data.items():
            setattr(self, name, value)
        if "review_status" in data:
            if data["review_status"] == CodeImportReviewStatus.REVIEWED:
                if self.import_job is None:
                    CodeImportJobWorkflow().newJob(self)
            else:
                self._removeJob()
        event = event_set.newModify(self, user, token)
        if event is not None or new_whiteboard is not None:
            code_import_updated(self, event, new_whiteboard, user)
        return event

    def setURL(self, url, user):
        self.updateURL(url, user)

    def updateURL(self, new_url, user):
        if self.url != new_url:
            data = {"url": new_url}
            event = self.updateFromData(data, user)
            return event

    def __repr__(self):
        return "<CodeImport for %s>" % self.target.unique_name

    def tryFailingImportAgain(self, user):
        """See `ICodeImport`."""
        if self.review_status != CodeImportReviewStatus.FAILING:
            raise AssertionError(
                "review_status is %s not FAILING" % self.review_status.name
            )
        self.updateFromData(
            {"review_status": CodeImportReviewStatus.REVIEWED}, user
        )
        getUtility(ICodeImportJobWorkflow).requestJob(self.import_job, user)

    def requestImport(self, requester, error_if_already_requested=False):
        """See `ICodeImport`."""
        if self.import_job is None:
            # Not in automatic mode.
            raise CodeImportNotInReviewedState(
                "This code import is %s, and must be Reviewed for you to "
                "call requestImport." % self.review_status.name
            )
        if self.import_job.state != CodeImportJobState.PENDING:
            assert self.import_job.state == CodeImportJobState.RUNNING
            raise CodeImportAlreadyRunning(
                "This code import is already running."
            )
        elif self.import_job.requesting_user is not None:
            if error_if_already_requested:
                raise CodeImportAlreadyRequested(
                    "This code import has " "already been requested to run.",
                    self.import_job.requesting_user,
                )
        else:
            getUtility(ICodeImportJobWorkflow).requestJob(
                self.import_job, requester
            )

    def destroySelf(self):
        if self.import_job is not None:
            self.import_job.destroySelf()
        Store.of(self).remove(self)


@implementer(ICodeImportSet)
class CodeImportSet:
    """See `ICodeImportSet`."""

    def new(
        self,
        registrant,
        context,
        branch_name,
        rcs_type,
        target_rcs_type,
        url=None,
        cvs_root=None,
        cvs_module=None,
        review_status=None,
        owner=None,
    ):
        """See `ICodeImportSet`."""
        if rcs_type == RevisionControlSystems.CVS:
            assert cvs_root is not None and cvs_module is not None
            assert url is None
        elif rcs_type in NON_CVS_RCS_TYPES:
            assert cvs_root is None and cvs_module is None
            assert url is not None
        else:
            raise AssertionError(
                "Don't know how to sanity check source details for unknown "
                "rcs_type %s" % rcs_type
            )
        if owner is None:
            owner = registrant
        if target_rcs_type == TargetRevisionControlSystems.BZR:
            # XXX cjwatson 2016-10-15: Testing
            # IHasBranches.providedBy(context) would seem more in line with
            # the Git case, but for some reason ProductSeries doesn't
            # provide that.  We should sync this up somehow.
            try:
                target = IBranchTarget(context)
            except TypeError:
                raise CodeImportInvalidTargetType(context, target_rcs_type)
            namespace = target.getNamespace(owner)
        elif target_rcs_type == TargetRevisionControlSystems.GIT:
            if not IHasGitRepositories.providedBy(context):
                raise CodeImportInvalidTargetType(context, target_rcs_type)
            if rcs_type != RevisionControlSystems.GIT:
                raise AssertionError(
                    "Can't import rcs_type %s into a Git repository" % rcs_type
                )
            target = namespace = get_git_namespace(context, owner)
        else:
            raise AssertionError(
                "Can't import to target_rcs_type %s" % target_rcs_type
            )
        if review_status is None:
            # Auto approve imports.
            review_status = CodeImportReviewStatus.REVIEWED
        if not target.supports_code_imports:
            raise AssertionError("%r doesn't support code imports" % target)
        # Create the branch for the CodeImport.
        if target_rcs_type == TargetRevisionControlSystems.BZR:
            import_target = namespace.createBranch(
                branch_type=BranchType.IMPORTED,
                name=branch_name,
                registrant=registrant,
            )
        else:
            import_target = namespace.createRepository(
                repository_type=GitRepositoryType.IMPORTED,
                name=branch_name,
                registrant=registrant,
            )
            hosting_path = import_target.getInternalPath()
            getUtility(IGitHostingClient).create(hosting_path)

        code_import = CodeImport(
            registrant=registrant,
            owner=owner,
            target=import_target,
            rcs_type=rcs_type,
            url=url,
            cvs_root=cvs_root,
            cvs_module=cvs_module,
            review_status=review_status,
        )
        IStore(CodeImport).add(code_import)

        getUtility(ICodeImportEventSet).newCreate(code_import, registrant)
        notify(ObjectCreatedEvent(code_import))

        # If created in the reviewed state, create a job.
        if review_status == CodeImportReviewStatus.REVIEWED:
            CodeImportJobWorkflow().newJob(code_import)

        return code_import

    def delete(self, code_import):
        """See `ICodeImportSet`."""
        # XXX cjwatson 2020-03-13: This means that in terms of Zope
        # permissions anyone can delete a code import, which seems
        # unfortunate, although it appears to have been this way even before
        # converting CodeImport to Storm.
        removeSecurityProxy(code_import).destroySelf()

    def get(self, id):
        """See `ICodeImportSet`."""
        code_import = IStore(CodeImport).get(CodeImport, id)
        if code_import is None:
            raise NotFoundError(id)
        return code_import

    def getByCVSDetails(self, cvs_root, cvs_module):
        """See `ICodeImportSet`."""
        return (
            IStore(CodeImport)
            .find(
                CodeImport,
                CodeImport.cvs_root == cvs_root,
                CodeImport.cvs_module == cvs_module,
            )
            .one()
        )

    def getByURL(self, url, target_rcs_type):
        """See `ICodeImportSet`."""
        clauses = [CodeImport.url == url]
        if target_rcs_type == TargetRevisionControlSystems.BZR:
            clauses.append(CodeImport.branch != None)
        elif target_rcs_type == TargetRevisionControlSystems.GIT:
            clauses.append(CodeImport.git_repository != None)
        else:
            raise AssertionError(
                "Unknown target_rcs_type %s" % target_rcs_type
            )
        return IStore(CodeImport).find(CodeImport, *clauses).one()

    def getByBranch(self, branch):
        """See `ICodeImportSet`."""
        return (
            IStore(CodeImport)
            .find(CodeImport, CodeImport.branch == branch)
            .one()
        )

    def getByGitRepository(self, repository):
        return (
            IStore(CodeImport)
            .find(CodeImport, CodeImport.git_repository == repository)
            .one()
        )

    def search(self, review_status=None, rcs_type=None, target_rcs_type=None):
        """See `ICodeImportSet`."""
        clauses = []
        if review_status is not None:
            clauses.append(CodeImport.review_status == review_status)
        if rcs_type is not None:
            clauses.append(CodeImport.rcs_type == rcs_type)
        if target_rcs_type == TargetRevisionControlSystems.BZR:
            clauses.append(CodeImport.branch != None)
        elif target_rcs_type == TargetRevisionControlSystems.GIT:
            clauses.append(CodeImport.git_repository != None)
        return IStore(CodeImport).find(CodeImport, *clauses)
