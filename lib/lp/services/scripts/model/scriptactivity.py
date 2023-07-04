# Copyright 2009-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "ScriptActivity",
    "ScriptActivitySet",
]

import socket
from datetime import timezone

import six
from storm.locals import DateTime, Int, Unicode
from zope.interface import implementer

from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.scripts.interfaces.scriptactivity import (
    IScriptActivity,
    IScriptActivitySet,
)
from lp.services.scripts.metrics import emit_script_activity_metric


@implementer(IScriptActivity)
class ScriptActivity(StormBase):
    __storm_table__ = "ScriptActivity"

    id = Int(primary=True)
    name = Unicode(allow_none=False)
    hostname = Unicode(allow_none=False)
    date_started = DateTime(tzinfo=timezone.utc, allow_none=False)
    date_completed = DateTime(tzinfo=timezone.utc, allow_none=False)

    def __init__(self, name, hostname, date_started, date_completed):
        super().__init__()
        self.name = name
        self.hostname = hostname
        self.date_started = date_started
        self.date_completed = date_completed


@implementer(IScriptActivitySet)
class ScriptActivitySet:
    def recordSuccess(self, name, date_started, date_completed, hostname=None):
        """See IScriptActivitySet"""
        if hostname is None:
            hostname = socket.gethostname()
        activity = ScriptActivity(
            name=six.ensure_text(name),
            hostname=six.ensure_text(hostname),
            date_started=date_started,
            date_completed=date_completed,
        )
        IStore(ScriptActivity).add(activity)
        # Pass equivalent information through to statsd as well.
        emit_script_activity_metric(name, date_completed - date_started)
        return activity

    def getLastActivity(self, name):
        """See IScriptActivitySet"""
        rows = IStore(ScriptActivity).find(
            ScriptActivity, name=six.ensure_text(name)
        )
        return rows.order_by(ScriptActivity.date_started).last()
