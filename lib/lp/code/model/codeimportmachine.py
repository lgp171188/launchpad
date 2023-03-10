# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes including and related to CodeImportMachine."""

__all__ = [
    "CodeImportMachine",
    "CodeImportMachineSet",
]

from datetime import timezone

from storm.locals import DateTime, Desc, Int, ReferenceSet, Unicode
from zope.component import getUtility
from zope.interface import implementer

from lp.code.enums import (
    CodeImportMachineOfflineReason,
    CodeImportMachineState,
)
from lp.code.interfaces.codeimportevent import ICodeImportEventSet
from lp.code.interfaces.codeimportmachine import (
    ICodeImportMachine,
    ICodeImportMachineSet,
)
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(ICodeImportMachine)
class CodeImportMachine(StormBase):
    """See `ICodeImportMachine`."""

    __storm_table__ = "CodeImportMachine"
    __storm_order__ = "hostname"

    id = Int(primary=True)

    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=DEFAULT
    )

    hostname = Unicode(allow_none=False)
    state = DBEnum(
        enum=CodeImportMachineState,
        allow_none=False,
        default=CodeImportMachineState.OFFLINE,
    )
    heartbeat = DateTime(tzinfo=timezone.utc, allow_none=True)

    current_jobs = ReferenceSet(
        id,
        "CodeImportJob.machine_id",
        order_by=("CodeImportJob.date_started", "CodeImportJob.id"),
    )

    events = ReferenceSet(
        id,
        "CodeImportEvent.machine_id",
        order_by=(
            Desc("CodeImportEvent.date_created"),
            Desc("CodeImportEvent.id"),
        ),
    )

    def __init__(self, hostname, heartbeat=None):
        super().__init__()
        self.hostname = hostname
        self.heartbeat = heartbeat
        self.state = CodeImportMachineState.OFFLINE

    def shouldLookForJob(self, worker_limit):
        """See `ICodeImportMachine`."""
        job_count = self.current_jobs.count()

        if self.state == CodeImportMachineState.OFFLINE:
            return False
        self.heartbeat = UTC_NOW
        if self.state == CodeImportMachineState.QUIESCING:
            if job_count == 0:
                self.setOffline(CodeImportMachineOfflineReason.QUIESCED)
            return False
        elif self.state == CodeImportMachineState.ONLINE:
            return job_count < worker_limit
        else:
            raise AssertionError("Unknown machine state %r??" % self.state)

    def setOnline(self, user=None, message=None):
        """See `ICodeImportMachine`."""
        if self.state not in (
            CodeImportMachineState.OFFLINE,
            CodeImportMachineState.QUIESCING,
        ):
            raise AssertionError(
                "State of machine %s was %s."
                % (self.hostname, self.state.name)
            )
        self.state = CodeImportMachineState.ONLINE
        getUtility(ICodeImportEventSet).newOnline(self, user, message)

    def setOffline(self, reason, user=None, message=None):
        """See `ICodeImportMachine`."""
        if self.state not in (
            CodeImportMachineState.ONLINE,
            CodeImportMachineState.QUIESCING,
        ):
            raise AssertionError(
                "State of machine %s was %s."
                % (self.hostname, self.state.name)
            )
        self.state = CodeImportMachineState.OFFLINE
        getUtility(ICodeImportEventSet).newOffline(self, reason, user, message)

    def setQuiescing(self, user, message=None):
        """See `ICodeImportMachine`."""
        if self.state != CodeImportMachineState.ONLINE:
            raise AssertionError(
                "State of machine %s was %s."
                % (self.hostname, self.state.name)
            )
        self.state = CodeImportMachineState.QUIESCING
        getUtility(ICodeImportEventSet).newQuiesce(self, user, message)


@implementer(ICodeImportMachineSet)
class CodeImportMachineSet:
    """See `ICodeImportMachineSet`."""

    def getAll(self):
        """See `ICodeImportMachineSet`."""
        return IStore(CodeImportMachine).find(CodeImportMachine)

    def getByHostname(self, hostname):
        """See `ICodeImportMachineSet`."""
        return (
            IStore(CodeImportMachine)
            .find(CodeImportMachine, CodeImportMachine.hostname == hostname)
            .one()
        )

    def new(self, hostname, state=CodeImportMachineState.OFFLINE):
        """See `ICodeImportMachineSet`."""
        machine = CodeImportMachine(hostname=hostname, heartbeat=None)
        if state == CodeImportMachineState.ONLINE:
            machine.setOnline()
        elif state != CodeImportMachineState.OFFLINE:
            raise AssertionError("Invalid machine creation state: %r." % state)
        IStore(CodeImportMachine).add(machine)
        return machine
