# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Database classes related to and including CodeImportEvent."""

__all__ = [
    "CodeImportEvent",
    "CodeImportEventSet",
    "CodeImportEventToken",
]

from datetime import timezone

from lazr.enum import DBItem
from storm.locals import DateTime, Int, Reference, Unicode
from zope.interface import implementer

from lp.code.enums import (
    CodeImportEventDataType,
    CodeImportEventType,
    CodeImportMachineOfflineReason,
    RevisionControlSystems,
)
from lp.code.interfaces.codeimportevent import (
    ICodeImportEvent,
    ICodeImportEventSet,
    ICodeImportEventToken,
)
from lp.registry.interfaces.person import validate_public_person
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase


@implementer(ICodeImportEvent)
class CodeImportEvent(StormBase):
    """See `ICodeImportEvent`."""

    __storm_table__ = "CodeImportEvent"

    id = Int(primary=True)

    date_created = DateTime(
        tzinfo=timezone.utc, allow_none=False, default=DEFAULT
    )

    event_type = DBEnum(
        name="entry_type", enum=CodeImportEventType, allow_none=False
    )
    code_import_id = Int(name="code_import", allow_none=True, default=None)
    code_import = Reference(code_import_id, "CodeImport.id")
    person_id = Int(
        name="person",
        allow_none=True,
        validator=validate_public_person,
        default=None,
    )
    person = Reference(person_id, "Person.id")
    machine_id = Int(name="machine", allow_none=True, default=None)
    machine = Reference(machine_id, "CodeImportMachine.id")

    def __init__(
        self,
        event_type,
        code_import=None,
        person=None,
        machine=None,
        date_created=DEFAULT,
    ):
        super().__init__()
        self.event_type = event_type
        self.code_import = code_import
        self.person = person
        self.machine = machine
        self.date_created = date_created

    def items(self):
        """See `ICodeImportEvent`."""
        return [
            (data.data_type, data.data_value)
            for data in IStore(_CodeImportEventData).find(
                _CodeImportEventData, _CodeImportEventData.event == self
            )
        ]


class _CodeImportEventData(StormBase):
    """Additional data associated to a CodeImportEvent.

    This class is for internal use only. This data should be created by
    CodeImportEventSet event creation methods, and should be accessed by
    CodeImport methods.
    """

    __storm_table__ = "CodeImportEventData"

    id = Int(primary=True)

    event_id = Int(name="event", allow_none=True)
    event = Reference(event_id, "CodeImportEvent.id")
    data_type = DBEnum(enum=CodeImportEventDataType, allow_none=False)
    data_value = Unicode(allow_none=True)

    def __init__(self, event, data_type, data_value):
        super().__init__()
        self.event = event
        self.data_type = data_type
        self.data_value = data_value


@implementer(ICodeImportEventSet)
class CodeImportEventSet:
    """See `ICodeImportEventSet`."""

    def getAll(self):
        """See `ICodeImportEventSet`."""
        return (
            IStore(CodeImportEvent)
            .find(CodeImportEvent)
            .order_by(CodeImportEvent.date_created, CodeImportEvent.id)
        )

    def getEventsForCodeImport(self, code_import):
        """See `ICodeImportEventSet`."""
        return (
            IStore(CodeImportEvent)
            .find(CodeImportEvent, CodeImportEvent.code_import == code_import)
            .order_by(CodeImportEvent.date_created, CodeImportEvent.id)
        )

    # All CodeImportEvent creation methods should assert arguments against
    # None. The database schema and the interface allow all foreign keys to be
    # NULL, but specific event types should be created with specific non-NULL
    # values. We want to fail when the client code is buggy and passes None
    # where a real object is expected.

    def newCreate(self, code_import, person):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert person is not None, "person must not be None"
        event = CodeImportEvent(
            event_type=CodeImportEventType.CREATE,
            code_import=code_import,
            person=person,
        )
        IStore(CodeImportEvent).add(event)
        self._recordSnapshot(event, code_import)
        return event

    def beginModify(self, code_import):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        items = list(self._iterItemsForSnapshot(code_import))
        return CodeImportEventToken(items)

    def newModify(self, code_import, person, token):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert token is not None, "token must not be None"
        items = self._findModifications(code_import, token)
        if items is None:
            return None
        event = CodeImportEvent(
            event_type=CodeImportEventType.MODIFY,
            code_import=code_import,
            person=person,
        )
        IStore(CodeImportEvent).add(event)
        self._recordItems(event, items)
        return event

    def newRequest(self, code_import, person):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert person is not None, "person must not be None"
        event = CodeImportEvent(
            event_type=CodeImportEventType.REQUEST,
            code_import=code_import,
            person=person,
        )
        IStore(CodeImportEvent).add(event)
        self._recordCodeImport(event, code_import)
        return event

    def _recordMessage(self, event, message):
        """Record a message if there is a message set."""
        if message:
            IStore(_CodeImportEventData).add(
                _CodeImportEventData(
                    event=event,
                    data_type=CodeImportEventDataType.MESSAGE,
                    data_value=message,
                )
            )

    def newOnline(self, machine, user=None, message=None, _date_created=None):
        """See `ICodeImportEventSet`."""
        assert machine is not None, "machine must not be None"
        if _date_created is None:
            _date_created = UTC_NOW
        event = CodeImportEvent(
            event_type=CodeImportEventType.ONLINE,
            machine=machine,
            person=user,
            date_created=_date_created,
        )
        IStore(CodeImportEvent).add(event)
        self._recordMessage(event, message)
        return event

    def newOffline(self, machine, reason, user=None, message=None):
        """See `ICodeImportEventSet`."""
        assert machine is not None, "machine must not be None"
        assert (
            type(reason) == DBItem
            and reason.enum == CodeImportMachineOfflineReason
        ), (
            "reason must be a CodeImportMachineOfflineReason value, "
            "but was: %r" % (reason,)
        )
        event = CodeImportEvent(
            event_type=CodeImportEventType.OFFLINE,
            machine=machine,
            person=user,
        )
        IStore(CodeImportEvent).add(event)
        IStore(_CodeImportEventData).add(
            _CodeImportEventData(
                event=event,
                data_type=CodeImportEventDataType.OFFLINE_REASON,
                data_value=str(reason.name),
            )
        )
        self._recordMessage(event, message)
        return event

    def newQuiesce(self, machine, user, message=None):
        """See `ICodeImportEventSet`."""
        assert machine is not None, "machine must not be None"
        assert user is not None, "user must not be None"
        event = CodeImportEvent(
            event_type=CodeImportEventType.QUIESCE,
            machine=machine,
            person=user,
        )
        IStore(CodeImportEvent).add(event)
        self._recordMessage(event, message)
        return event

    def newStart(self, code_import, machine):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert machine is not None, "machine must not be None"
        event = CodeImportEvent(
            event_type=CodeImportEventType.START,
            code_import=code_import,
            machine=machine,
        )
        IStore(CodeImportEvent).add(event)
        return event

    def newFinish(self, code_import, machine):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert machine is not None, "machine must not be None"
        event = CodeImportEvent(
            event_type=CodeImportEventType.FINISH,
            code_import=code_import,
            machine=machine,
        )
        IStore(CodeImportEvent).add(event)
        return event

    def newKill(self, code_import, machine):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert machine is not None, "machine must not be None"
        event = CodeImportEvent(
            event_type=CodeImportEventType.KILL,
            code_import=code_import,
            machine=machine,
        )
        IStore(CodeImportEvent).add(event)
        return event

    def newReclaim(self, code_import, machine, job_id):
        """See `ICodeImportEventSet`."""
        assert code_import is not None, "code_import must not be None"
        assert machine is not None, "machine must not be None"
        assert isinstance(job_id, int), (
            "job_id must be an int, was: %r" % job_id
        )
        event = CodeImportEvent(
            event_type=CodeImportEventType.RECLAIM,
            code_import=code_import,
            machine=machine,
        )
        IStore(CodeImportEvent).add(event)
        IStore(_CodeImportEventData).add(
            _CodeImportEventData(
                event=event,
                data_type=CodeImportEventDataType.RECLAIMED_JOB_ID,
                data_value=str(job_id),
            )
        )
        return event

    def _recordSnapshot(self, event, code_import):
        """Record a snapshot of the code import in the event data."""
        self._recordItems(event, self._iterItemsForSnapshot(code_import))

    def _recordCodeImport(self, event, code_import):
        """Record the code import id in the event data."""
        self._recordItems(event, [self._getCodeImportItem(code_import)])

    def _recordItems(self, event, items):
        """Record the specified event data into the database."""
        for key, value in items:
            data_type = getattr(CodeImportEventDataType, key)
            IStore(_CodeImportEventData).add(
                _CodeImportEventData(
                    event=event, data_type=data_type, data_value=value
                )
            )

    def _iterItemsForSnapshot(self, code_import):
        """Yield key-value tuples to save a snapshot of the code import."""
        yield self._getCodeImportItem(code_import)
        yield "REVIEW_STATUS", str(code_import.review_status.name)
        yield "OWNER", str(code_import.owner.id)
        yield "UPDATE_INTERVAL", self._getNullableValue(
            code_import.update_interval
        )
        yield "ASSIGNEE", self._getNullableValue(
            code_import.assignee, use_id=True
        )
        yield from self._iterSourceDetails(code_import)

    def _getCodeImportItem(self, code_import):
        """Return the key-value tuple for the code import id."""
        return "CODE_IMPORT", str(code_import.id)

    def _getNullableValue(self, value, use_id=False):
        """Return the string value for a nullable value.

        :param value: The value to represent as a string.
        :param use_id: Return the id of the object instead of the object, such
            as for a foreign key.
        """
        if value is None:
            return None
        elif use_id:
            return str(value.id)
        else:
            return str(value)

    def _iterSourceDetails(self, code_import):
        """Yield key-value tuples describing the source of the import."""
        if code_import.rcs_type in (
            RevisionControlSystems.BZR_SVN,
            RevisionControlSystems.GIT,
            RevisionControlSystems.BZR,
        ):
            yield "URL", code_import.url
        elif code_import.rcs_type == RevisionControlSystems.CVS:
            yield "CVS_ROOT", code_import.cvs_root
            yield "CVS_MODULE", code_import.cvs_module
        else:
            raise AssertionError(
                "Unknown RCS type: %s" % (code_import.rcs_type,)
            )

    def _findModifications(self, code_import, token):
        """Find modifications made to the code import.

        If no change was found, return None. Otherwise return a list of items
        that describe the old and new state of the modified code import.

        :param code_import: CodeImport object that was presumably modified.

        :param token: Token returned by a call to _makeModificationToken
            before the code import was modified.
        :return: Set of items that can be passed to _recordItems, or None.
        """
        old_dict = dict(token.items)
        new_dict = dict(self._iterItemsForSnapshot(code_import))

        assert old_dict["CODE_IMPORT"] == new_dict["CODE_IMPORT"], (
            "Token was produced from a different CodeImport object: "
            "id in token = %s, id of code_import = %s"
            % (old_dict["CODE_IMPORT"], new_dict["CODE_IMPORT"])
        )

        # The set of keys are not identical if the rcstype changed.
        all_keys = set(old_dict.keys()).union(set(new_dict.keys()))

        items = set()
        has_changes = False
        for key in all_keys:
            old_value = old_dict.get(key)
            new_value = new_dict.get(key)

            # Record current value for this key.
            items.add((key, new_value))

            if old_value != new_value:
                # Value has changed. Record previous value as well as current.
                has_changes = True
                items.add(("OLD_" + key, old_value))

        if has_changes:
            return items
        else:
            return None


@implementer(ICodeImportEventToken)
class CodeImportEventToken:
    """See `ICodeImportEventToken`."""

    def __init__(self, items):
        self.items = items
