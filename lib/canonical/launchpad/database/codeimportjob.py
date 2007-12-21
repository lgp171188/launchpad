# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Database classes for the CodeImportJob table."""

__metaclass__ = type
__all__ = [
    'CodeImportJob',
    'CodeImportJobSet',
    'CodeImportJobWorkflow',
    ]

from sqlobject import ForeignKey, IntCol, SQLObjectNotFound, StringCol

from zope.interface import implements
from zope.security.proxy import removeSecurityProxy

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad.database.codeimportresult import CodeImportResult
from canonical.launchpad.interfaces import (
    CodeImportJobState, CodeImportReviewStatus, ICodeImportJob,
    ICodeImportJobSet, ICodeImportJobWorkflow)


class CodeImportJob(SQLBase):
    """See `ICodeImportJob`."""

    implements(ICodeImportJob)

    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    code_import = ForeignKey(
        dbName='code_import', foreignKey='CodeImport', notNull=True)

    machine = ForeignKey(
        dbName='machine', foreignKey='CodeImportMachine',
        notNull=False, default=None)

    date_due = UtcDateTimeCol(notNull=True)

    state = EnumCol(
        enum=CodeImportJobState, notNull=True,
        default=CodeImportJobState.PENDING)

    requesting_user = ForeignKey(
        dbName='requesting_user', foreignKey='Person',
        notNull=False, default=None)

    ordering = IntCol(notNull=False, default=None)

    heartbeat = UtcDateTimeCol(notNull=False, default=None)

    logtail = StringCol(notNull=False, default=None)

    date_started = UtcDateTimeCol(notNull=False, default=None)

    def isOverdue(self):
        """See `ICodeImportJob`."""
        # SQLObject offers no easy way to compare a timestamp to UTC_NOW, so
        # we must use trickery here.

        # First we flush any pending update to self to ensure that the
        # following database query will give the correct result even if
        # date_due was modified in this transaction.
        self.syncUpdate()

        # Then, we try to find a CodeImportJob object with the id of self, and
        # a date_due of now or past. If we find one, this means self is
        # overdue.
        import_job = CodeImportJob.selectOne(
            "id = %s AND date_due <= %s" % sqlvalues(self.id, UTC_NOW))
        return import_job is not None


class CodeImportJobSet(object):
    """See `ICodeImportJobSet`."""

    implements(ICodeImportJobSet)

    # CodeImportJob database objects are created using
    # CodeImportJobWorkflow.newJob.

    def getById(self, id):
        """See `ICodeImportJobSet`."""
        try:
            return CodeImportJob.get(id)
        except SQLObjectNotFound:
            return None


class CodeImportJobWorkflow:
    """See `ICodeImportJobWorkflow`."""

    implements(ICodeImportJobWorkflow)

    def newJob(self, code_import):
        """See `ICodeImportJobWorkflow`."""
        assert code_import.review_status == CodeImportReviewStatus.REVIEWED, (
            "Review status of %s is not REVIEWED: %s" % (
            code_import.branch.unique_name, code_import.review_status.name))
        assert code_import.import_job is None, (
            "Already associated to a CodeImportJob: %s" % (
            code_import.branch.unique_name))

        job = CodeImportJob(code_import=code_import, date_due=UTC_NOW)

        # Find the most recent CodeImportResult for this CodeImport. We sort
        # by date_created because we do not have an index on date_job_started
        # in the database, and that should give the same sort order.
        most_recent_result_list = list(CodeImportResult.selectBy(
            code_import=code_import).orderBy(['-date_created']).limit(1))

        if len(most_recent_result_list) != 0:
            [most_recent_result] = most_recent_result_list
            interval = code_import.effective_update_interval
            date_due = most_recent_result.date_job_started + interval
            job.date_due = max(job.date_due, date_due)
            job.sync()

        return job

    def deletePendingJob(self, code_import):
        """See `ICodeImportJobWorkflow`."""
        assert code_import.review_status != CodeImportReviewStatus.REVIEWED, (
            "The review status of %s is %s." % (
            code_import.branch.unique_name, code_import.review_status.name))
        assert code_import.import_job is not None, (
            "Not associated to a CodeImportJob: %s" % (
            code_import.branch.unique_name,))
        assert code_import.import_job.state == CodeImportJobState.PENDING, (
            "The CodeImportJob associated to %s is %s." % (
            code_import.branch.unique_name,
            code_import.import_job.state.name))
        # CodeImportJobWorkflow is the only class that is allowed to delete
        # CodeImportJob rows, so destroySelf is not exposed in ICodeImportJob.
        removeSecurityProxy(code_import).import_job.destroySelf()
