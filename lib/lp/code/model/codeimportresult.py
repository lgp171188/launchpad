# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes for the CodeImportResult table."""

__all__ = ["CodeImportResult", "CodeImportResultSet"]

from datetime import timezone

from storm.locals import DateTime, Int, Reference, Unicode
from zope.interface import implementer

from lp.code.enums import CodeImportResultStatus
from lp.code.interfaces.codeimportresult import (
    ICodeImportResult,
    ICodeImportResultSet,
)
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(ICodeImportResult)
class CodeImportResult(StormBase):
    """See `ICodeImportResult`."""

    __storm_table__ = "CodeImportResult"

    id = Int(primary=True)

    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=UTC_NOW
    )

    code_import_id = Int(name="code_import", allow_none=False)
    code_import = Reference(code_import_id, "CodeImport.id")

    machine_id = Int(name="machine", allow_none=False)
    machine = Reference(machine_id, "CodeImportMachine.id")

    requesting_user_id = Int(
        name="requesting_user",
        allow_none=True,
        validator=validate_public_person,
        default=None,
    )
    requesting_user = Reference(requesting_user_id, "Person.id")

    log_excerpt = Unicode(allow_none=True, default=None)

    log_file_id = Int(name="log_file", allow_none=True, default=None)
    log_file = Reference(log_file_id, "LibraryFileAlias.id")

    status = DBEnum(enum=CodeImportResultStatus, allow_none=False)

    date_job_started = DateTime(tzinfo=timezone.utc, allow_none=False)

    def __init__(
        self,
        code_import,
        machine,
        status,
        date_job_started,
        requesting_user=None,
        log_excerpt=None,
        log_file=None,
        date_created=UTC_NOW,
    ):
        super().__init__()
        self.code_import = code_import
        self.machine = machine
        self.status = status
        self.date_job_started = date_job_started
        self.requesting_user = requesting_user
        self.log_excerpt = log_excerpt
        self.log_file = log_file
        self.date_created = date_created

    @property
    def date_job_finished(self):
        """See `ICodeImportResult`."""
        return self.date_created

    @property
    def job_duration(self):
        return self.date_job_finished - self.date_job_started


@implementer(ICodeImportResultSet)
class CodeImportResultSet:
    """See `ICodeImportResultSet`."""

    def new(
        self,
        code_import,
        machine,
        requesting_user,
        log_excerpt,
        log_file,
        status,
        date_job_started,
        date_job_finished=None,
    ):
        """See `ICodeImportResultSet`."""
        if date_job_finished is None:
            date_job_finished = UTC_NOW
        result = CodeImportResult(
            code_import=code_import,
            machine=machine,
            requesting_user=requesting_user,
            log_excerpt=log_excerpt,
            log_file=log_file,
            status=status,
            date_job_started=date_job_started,
            date_created=date_job_finished,
        )
        IStore(CodeImportResult).add(result)
        return result
