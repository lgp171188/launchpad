# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = ["BugActivity", "BugActivitySet"]

import re
from datetime import timezone

from storm.locals import DateTime, Int, Reference, Unicode
from storm.store import Store
from zope.interface import implementer

from lp.bugs.adapters.bugchange import (
    ATTACHMENT_ADDED,
    ATTACHMENT_REMOVED,
    BRANCH_LINKED,
    BRANCH_UNLINKED,
    BUG_WATCH_ADDED,
    BUG_WATCH_REMOVED,
    CHANGED_DUPLICATE_MARKER,
    CVE_LINKED,
    CVE_UNLINKED,
    MARKED_AS_DUPLICATE,
    MERGE_PROPOSAL_LINKED,
    MERGE_PROPOSAL_UNLINKED,
    REMOVED_DUPLICATE_MARKER,
    REMOVED_SUBSCRIBER,
)
from lp.bugs.interfaces.bugactivity import IBugActivity, IBugActivitySet
from lp.registry.interfaces.person import validate_person
from lp.services.database.stormbase import StormBase


@implementer(IBugActivity)
class BugActivity(StormBase):
    """Bug activity log entry."""

    __storm_table__ = "BugActivity"

    id = Int(primary=True)

    bug_id = Int(name="bug", allow_none=False)
    bug = Reference(bug_id, "Bug.id")

    datechanged = DateTime(tzinfo=timezone.utc, allow_none=False)

    person_id = Int(name="person", allow_none=False, validator=validate_person)
    person = Reference(person_id, "Person.id")

    whatchanged = Unicode(allow_none=False)
    oldvalue = Unicode(allow_none=True, default=None)
    newvalue = Unicode(allow_none=True, default=None)
    message = Unicode(allow_none=True, default=None)

    # The regular expression we use for matching bug task changes.
    bugtask_change_re = re.compile(
        r"(?P<target>[a-z0-9][a-z0-9\+\.\-]+( \([A-Za-z0-9\s]+\))?): "
        r"(?P<attribute>assignee|importance explanation|importance|"
        r"milestone|status explanation|status)"
    )

    def __init__(
        self,
        bug,
        datechanged,
        person,
        whatchanged,
        oldvalue=None,
        newvalue=None,
        message=None,
    ):
        self.bug = bug
        self.datechanged = datechanged
        self.person = person
        self.whatchanged = whatchanged
        self.oldvalue = oldvalue
        self.newvalue = newvalue
        self.message = message

    @property
    def target(self):
        """Return the target of this BugActivityItem.

        `target` is determined based on the `whatchanged` string.

        :return: The target name of the item if `whatchanged` is of the
        form <target_name>: <attribute>. Otherwise, return None.
        """
        match = self.bugtask_change_re.match(self.whatchanged)
        if match is None:
            return None
        else:
            return match.groupdict()["target"]

    @property
    def attribute(self):
        """Return the attribute changed in this BugActivityItem.

        `attribute` is determined based on the `whatchanged` string.

        :return: The attribute name of the item if `whatchanged` is of
            the form <target_name>: <attribute>. If we know how to determine
            the attribute by normalizing whatchanged, we return that.
            Otherwise, return the original `whatchanged` string.
        """
        match = self.bugtask_change_re.match(self.whatchanged)
        if match is None:
            result = self.whatchanged
            # Now we normalize names, as necessary.  This is fragile, but
            # a reasonable incremental step.  These are consumed in
            # lp.bugs.scripts.bugnotification.get_activity_key.
            if result in (
                CHANGED_DUPLICATE_MARKER,
                MARKED_AS_DUPLICATE,
                REMOVED_DUPLICATE_MARKER,
            ):
                result = "duplicateof"
            elif result in (ATTACHMENT_ADDED, ATTACHMENT_REMOVED):
                result = "attachments"
            elif result in (BRANCH_LINKED, BRANCH_UNLINKED):
                result = "linked_branches"
            elif result in (BUG_WATCH_ADDED, BUG_WATCH_REMOVED):
                result = "watches"
            elif result in (CVE_LINKED, CVE_UNLINKED):
                result = "cves"
            elif result in (MERGE_PROPOSAL_LINKED, MERGE_PROPOSAL_UNLINKED):
                result = "linked_merge_proposals"
            elif str(result).startswith(REMOVED_SUBSCRIBER):
                result = "removed_subscriber"
            elif result == "summary":
                result = "title"
            return result
        else:
            return match.groupdict()["attribute"]


@implementer(IBugActivitySet)
class BugActivitySet:
    """See IBugActivitySet."""

    def new(
        self,
        bug,
        datechanged,
        person,
        whatchanged,
        oldvalue=None,
        newvalue=None,
        message=None,
    ):
        """See IBugActivitySet."""
        activity = BugActivity(
            bug=bug,
            datechanged=datechanged,
            person=person,
            whatchanged=whatchanged,
            oldvalue=oldvalue,
            newvalue=newvalue,
            message=message,
        )
        Store.of(activity).flush()
        return activity
