# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Implementations for bug changes."""

__all__ = [
    "ATTACHMENT_ADDED",
    "ATTACHMENT_REMOVED",
    "BRANCH_LINKED",
    "BRANCH_UNLINKED",
    "BranchLinkedToBug",
    "BranchUnlinkedFromBug",
    "BUG_WATCH_ADDED",
    "BUG_WATCH_REMOVED",
    "BugAttachmentChange",
    "BugConvertedToQuestion",
    "BugDescriptionChange",
    "BugDuplicateChange",
    "BugInformationTypeChange",
    "BugLocked",
    "BugLockReasonSet",
    "BugPresenceAdded",
    "BugPresenceRemoved",
    "BugTagsChange",
    "BugTaskAdded",
    "BugTaskAssigneeChange",
    "BugTaskBugWatchChange",
    "BugTaskDeleted",
    "BugTaskImportanceChange",
    "BugTaskMilestoneChange",
    "BugTaskStatusChange",
    "BugTaskTargetChange",
    "BugTitleChange",
    "BugUnlocked",
    "BugWatchAdded",
    "BugWatchRemoved",
    "CHANGED_DUPLICATE_MARKER",
    "CVE_LINKED",
    "CVE_UNLINKED",
    "CveLinkedToBug",
    "CveUnlinkedFromBug",
    "get_bug_change_class",
    "get_bug_changes",
    "MARKED_AS_DUPLICATE",
    "MERGE_PROPOSAL_LINKED",
    "MERGE_PROPOSAL_UNLINKED",
    "MergeProposalLinkedToBug",
    "MergeProposalUnlinkedFromBug",
    "REMOVED_DUPLICATE_MARKER",
    "REMOVED_SUBSCRIBER",
    "SeriesNominated",
    "UnsubscribedFromBug",
]

from textwrap import dedent

from zope.interface import implementer
from zope.security.proxy import isinstance as zope_isinstance

from lp.bugs.enums import BugLockStatus, BugNotificationLevel
from lp.bugs.interfaces.bugchange import IBugChange
from lp.bugs.interfaces.bugtask import (
    RESOLVED_BUGTASK_STATUSES,
    UNRESOLVED_BUGTASK_STATUSES,
    IBugTask,
)
from lp.registry.interfaces.product import IProduct
from lp.services.webapp.publisher import canonical_url

# These are used lp.bugs.model.bugactivity.BugActivity.attribute to normalize
# the output from these change objects into the attribute that actually
# changed.  It is fragile, but a reasonable incremental step.
ATTACHMENT_ADDED = "attachment added"
ATTACHMENT_REMOVED = "attachment removed"
BRANCH_LINKED = "branch linked"
BRANCH_UNLINKED = "branch unlinked"
BUG_PRESENCE_ADDED = "bug presence added"
BUG_PRESENCE_REMOVED = "bug presence removed"
BUG_WATCH_ADDED = "bug watch added"
BUG_WATCH_REMOVED = "bug watch removed"
CHANGED_DUPLICATE_MARKER = "changed duplicate marker"
CVE_LINKED = "cve linked"
CVE_UNLINKED = "cve unlinked"
MARKED_AS_DUPLICATE = "marked as duplicate"
MERGE_PROPOSAL_LINKED = "merge proposal linked"
MERGE_PROPOSAL_UNLINKED = "merge proposal unlinked"
REMOVED_DUPLICATE_MARKER = "removed duplicate marker"
REMOVED_SUBSCRIBER = "removed subscriber"


class NoBugChangeFoundError(Exception):
    """Raised when a BugChange class can't be found for an object."""


def get_bug_change_class(obj, field_name):
    """Return a suitable IBugChange to describe obj and field_name."""

    if IBugTask.providedBy(obj):
        lookup = BUGTASK_CHANGE_LOOKUP
    else:
        lookup = BUG_CHANGE_LOOKUP

    try:
        return lookup[field_name]
    except KeyError:
        raise NoBugChangeFoundError(
            "Unable to find a suitable BugChange for field '%s' on object "
            "%s" % (field_name, obj)
        )


def get_bug_changes(bug_delta):
    """Generate `IBugChange` objects describing an `IBugDelta`."""
    # The order of the field names in this list is important; this is
    # the order in which changes will appear both in the bug activity
    # log and in notification emails.
    bug_change_field_names = [
        "duplicateof",
        "title",
        "description",
        "information_type",
        "tags",
        "attachment",
    ]
    for field_name in bug_change_field_names:
        field_delta = getattr(bug_delta, field_name)
        if field_delta is not None:
            bug_change_class = get_bug_change_class(bug_delta.bug, field_name)
            yield bug_change_class(
                when=None,
                person=bug_delta.user,
                what_changed=field_name,
                old_value=field_delta["old"],
                new_value=field_delta["new"],
            )

    if bug_delta.bugtask_deltas is not None:
        bugtask_deltas = bug_delta.bugtask_deltas
        # Use zope_isinstance, to ensure that this Just Works with
        # security-proxied objects.
        if not zope_isinstance(bugtask_deltas, (list, tuple)):
            bugtask_deltas = [bugtask_deltas]

        # The order here is important; see bug_change_field_names.
        bugtask_change_field_names = [
            "target",
            "importance",
            "status",
            "milestone",
            "bugwatch",
            "assignee",
            "importance_explanation",
            "status_explanation",
        ]
        for bugtask_delta in bugtask_deltas:
            for field_name in bugtask_change_field_names:
                field_delta = getattr(bugtask_delta, field_name)
                if field_delta is not None:
                    bug_change_class = get_bug_change_class(
                        bugtask_delta.bugtask, field_name
                    )
                    yield bug_change_class(
                        bug_task=bugtask_delta.bugtask,
                        when=None,
                        person=bug_delta.user,
                        what_changed=field_name,
                        old_value=field_delta["old"],
                        new_value=field_delta["new"],
                    )


@implementer(IBugChange)
class BugChangeBase:
    """An abstract base class for Bug[Task]Changes."""

    # Most changes will be at METADATA level.
    change_level = BugNotificationLevel.METADATA

    def __init__(self, when, person):
        self.person = person
        self.when = when

    def getBugActivity(self):
        """Return the `BugActivity` entry for this change."""
        raise NotImplementedError(self.getBugActivity)

    def getBugNotification(self):
        """Return the `BugNotification` for this event."""
        raise NotImplementedError(self.getBugNotification)


class AttributeChange(BugChangeBase):
    """A mixin class that provides basic functionality for `IBugChange`s."""

    def __init__(self, when, person, what_changed, old_value, new_value):
        super().__init__(when, person)
        self.new_value = new_value
        self.old_value = old_value
        self.what_changed = what_changed

    def getBugActivity(self):
        """Return the BugActivity data for the textual change."""
        return {
            "newvalue": self.new_value,
            "oldvalue": self.old_value,
            "whatchanged": self.what_changed,
        }


class UnsubscribedFromBug(BugChangeBase):
    """A user got unsubscribed from a bug."""

    def __init__(self, when, person, unsubscribed_user, **kwargs):
        super().__init__(when, person)
        self.unsubscribed_user = unsubscribed_user
        self.send_notification = kwargs.get("send_notification", False)
        self.notification_text = kwargs.get("notification_text")

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged="%s %s"
            % (REMOVED_SUBSCRIBER, self.unsubscribed_user.displayname)
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        if self.send_notification and self.notification_text:
            return {"text": "** %s" % self.notification_text}
        else:
            return None


class BugConvertedToQuestion(BugChangeBase):
    """A bug got converted into a question."""

    def __init__(self, when, person, question):
        super().__init__(when, person)
        self.question = question

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged="converted to question", newvalue=str(self.question.id)
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": (
                "** Converted to question:\n"
                "   %s" % canonical_url(self.question)
            ),
        }


class BugTaskAdded(BugChangeBase):
    """A bug task got added to the bug."""

    change_level = BugNotificationLevel.LIFECYCLE

    def __init__(self, when, person, bug_task):
        super().__init__(when, person)
        self.bug_task = bug_task

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged="bug task added", newvalue=self.bug_task.bugtargetname
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        lines = []
        if self.bug_task.bugwatch:
            lines.append(
                "** Also affects: %s via" % (self.bug_task.bugtargetname)
            )
            lines.append("   %s" % self.bug_task.bugwatch.url)
        else:
            lines.append("** Also affects: %s" % (self.bug_task.bugtargetname))
        lines.append(
            "%13s: %s" % ("Importance", self.bug_task.importance.title)
        )
        if self.bug_task.assignee:
            assignee = self.bug_task.assignee
            lines.append(
                "%13s: %s" % ("Assignee", assignee.unique_displayname)
            )
        lines.append("%13s: %s" % ("Status", self.bug_task.status.title))
        return {
            "text": "\n".join(lines),
        }


class BugTaskDeleted(BugChangeBase):
    """A bugtask was removed from the bug."""

    change_level = BugNotificationLevel.LIFECYCLE

    def __init__(self, when, person, bugtask):
        super().__init__(when, person)
        self.targetname = bugtask.bugtargetname

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(whatchanged="bug task deleted", oldvalue=self.targetname)

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": ("** No longer affects: %s" % self.targetname),
        }


class SeriesNominated(BugChangeBase):
    """A user nominated the bug to be fixed in a series."""

    def __init__(self, when, person, series):
        super().__init__(when, person)
        self.series = series

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged="nominated for series",
            newvalue=self.series.bugtargetname,
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        return None


class BugPresenceAdded(BugChangeBase):
    """A bug presence was added to the bug."""

    def __init__(self, when, person, bug_presence):
        super().__init__(when, person)
        self.bug_presence = bug_presence

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged=BUG_PRESENCE_ADDED,
            newvalue=str(self.bug_presence.break_fix_data),
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": "** Bug presence added: \n"
            f"   product: {self.bug_presence.product}\n"
            f"   distribution: {self.bug_presence.distribution}\n"
            "   source_package_name: "
            f"{self.bug_presence.source_package_name}\n"
            f"   gitrepository: {self.bug_presence.git_repository}\n"
            f"   break_fix_data: {self.bug_presence.break_fix_data}"
        }


class BugPresenceRemoved(BugChangeBase):
    """A bug presence was removed from the bug."""

    def __init__(self, when, person, bug_presence):
        super().__init__(when, person)
        self.bug_presence = bug_presence

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged=BUG_PRESENCE_REMOVED,
            newvalue=str(self.bug_presence.break_fix_data),
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": "** Bug presence removed: \n"
            f"   product: {self.bug_presence.product}\n"
            f"   distribution: {self.bug_presence.distribution}\n"
            "   source_package_name: "
            f"{self.bug_presence.source_package_name}\n"
            f"   gitrepository: {self.bug_presence.git_repository}\n"
            f"   break_fix_data: {self.bug_presence.break_fix_data}"
        }


class BugWatchAdded(BugChangeBase):
    """A bug watch was added to the bug."""

    def __init__(self, when, person, bug_watch):
        super().__init__(when, person)
        self.bug_watch = bug_watch

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(whatchanged=BUG_WATCH_ADDED, newvalue=self.bug_watch.url)

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": (
                "** Bug watch added: %s #%s\n"
                "   %s"
                % (
                    self.bug_watch.bugtracker.title,
                    self.bug_watch.remotebug,
                    self.bug_watch.url,
                )
            ),
        }


class BugWatchRemoved(BugChangeBase):
    """A bug watch was removed from the bug."""

    def __init__(self, when, person, bug_watch):
        super().__init__(when, person)
        self.bug_watch = bug_watch

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(whatchanged=BUG_WATCH_REMOVED, oldvalue=self.bug_watch.url)

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": (
                "** Bug watch removed: %s #%s\n"
                "   %s"
                % (
                    self.bug_watch.bugtracker.title,
                    self.bug_watch.remotebug,
                    self.bug_watch.url,
                )
            ),
        }


class BranchLinkedToBug(BugChangeBase):
    """A branch got linked to the bug."""

    def __init__(self, when, person, branch, bug):
        super().__init__(when, person)
        self.branch = branch
        self.bug = bug

    def getBugActivity(self):
        """See `IBugChange`."""
        if self.branch.private:
            return None
        return dict(
            whatchanged=BRANCH_LINKED, newvalue=self.branch.bzr_identity
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        if self.branch.private or self.bug.is_complete:
            return None
        return {"text": "** Branch linked: %s" % self.branch.bzr_identity}


class BranchUnlinkedFromBug(BugChangeBase):
    """A branch got unlinked from the bug."""

    def __init__(self, when, person, branch, bug):
        super().__init__(when, person)
        self.branch = branch
        self.bug = bug

    def getBugActivity(self):
        """See `IBugChange`."""
        if self.branch.private:
            return None
        return dict(
            whatchanged=BRANCH_UNLINKED, oldvalue=self.branch.bzr_identity
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        if self.branch.private or self.bug.is_complete:
            return None
        return {"text": "** Branch unlinked: %s" % self.branch.bzr_identity}


class MergeProposalLinkedToBug(BugChangeBase):
    """A merge proposal got linked to the bug."""

    def __init__(self, when, person, merge_proposal, bug):
        super().__init__(when, person)
        self.merge_proposal = merge_proposal
        self.bug = bug

    def getBugActivity(self):
        """See `IBugChange`."""
        if self.merge_proposal.private:
            return None
        return dict(
            whatchanged=MERGE_PROPOSAL_LINKED,
            newvalue=canonical_url(self.merge_proposal),
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        if self.merge_proposal.private or self.bug.is_complete:
            return None
        return {
            "text": (
                "** Merge proposal linked:\n"
                "   %s" % canonical_url(self.merge_proposal)
            ),
        }


class MergeProposalUnlinkedFromBug(BugChangeBase):
    """A merge proposal got unlinked from the bug."""

    def __init__(self, when, person, merge_proposal, bug):
        super().__init__(when, person)
        self.merge_proposal = merge_proposal
        self.bug = bug

    def getBugActivity(self):
        """See `IBugChange`."""
        if self.merge_proposal.private:
            return None
        return dict(
            whatchanged=MERGE_PROPOSAL_UNLINKED,
            oldvalue=canonical_url(self.merge_proposal),
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        if self.merge_proposal.private or self.bug.is_complete:
            return None
        return {
            "text": (
                "** Merge proposal unlinked:\n"
                "   %s" % canonical_url(self.merge_proposal)
            ),
        }


class BugDescriptionChange(AttributeChange):
    """Describes a change to a bug's description."""

    def getBugNotification(self):
        from lp.services.mail.notification import get_unified_diff

        description_diff = get_unified_diff(self.old_value, self.new_value, 72)
        notification_text = "** Description changed:\n\n%s" % description_diff
        return {"text": notification_text}


def _is_status_change_lifecycle_change(old_status, new_status):
    """Is a status change a lifecycle change?"""
    # Bug is moving from one of unresolved bug statuses (like
    # 'in progress') to one of resolved ('fix released').
    bug_is_closed = (
        old_status in UNRESOLVED_BUGTASK_STATUSES
        and new_status in RESOLVED_BUGTASK_STATUSES
    )

    # Bug is moving back from one of resolved bug statuses (reopening).
    bug_is_reopened = (
        old_status in RESOLVED_BUGTASK_STATUSES
        and new_status in UNRESOLVED_BUGTASK_STATUSES
    )
    return bug_is_closed or bug_is_reopened


class BugDuplicateChange(AttributeChange):
    """Describes a change to a bug's duplicate marker."""

    @property
    def change_level(self):
        lifecycle = False
        old_bug = self.old_value
        new_bug = self.new_value
        if old_bug is not None and new_bug is not None:
            # Bug was already a duplicate of one bug,
            # and we are changing it to be a duplicate of another bug.
            lifecycle = _is_status_change_lifecycle_change(
                old_bug.default_bugtask.status, new_bug.default_bugtask.status
            )
        elif new_bug is not None:
            # old_bug is None here, so we are just adding a duplicate marker.
            lifecycle = (
                new_bug.default_bugtask.status in RESOLVED_BUGTASK_STATUSES
            )
        elif old_bug is not None:
            # Unmarking a bug as duplicate.  This is lifecycle change
            # only if bug has been reopened as a result.
            lifecycle = (
                old_bug.default_bugtask.status in RESOLVED_BUGTASK_STATUSES
            )
        else:
            pass

        if lifecycle:
            return BugNotificationLevel.LIFECYCLE
        else:
            return BugNotificationLevel.METADATA

    def getBugActivity(self):
        if self.old_value is not None and self.new_value is not None:
            return {
                "whatchanged": CHANGED_DUPLICATE_MARKER,
                "oldvalue": str(self.old_value.id),
                "newvalue": str(self.new_value.id),
            }
        elif self.old_value is None:
            return {
                "whatchanged": MARKED_AS_DUPLICATE,
                "newvalue": str(self.new_value.id),
            }
        elif self.new_value is None:
            return {
                "whatchanged": REMOVED_DUPLICATE_MARKER,
                "oldvalue": str(self.old_value.id),
            }
        else:
            raise AssertionError(
                "There is no change: both the old bug and new bug are None."
            )

    def getBugNotification(self):
        if self.old_value is not None and self.new_value is not None:
            if self.old_value.private:
                old_value_text = (
                    "** This bug is no longer a duplicate of private bug "
                    "%d" % self.old_value.id
                )
            else:
                old_value_text = (
                    "** This bug is no longer a duplicate of bug %d\n"
                    "   %s" % (self.old_value.id, self.old_value.title)
                )
            if self.new_value.private:
                new_value_text = (
                    "** This bug has been marked a duplicate of private bug "
                    "%d" % self.new_value.id
                )
            else:
                new_value_text = (
                    "** This bug has been marked a duplicate of bug %d\n"
                    "   %s" % (self.new_value.id, self.new_value.title)
                )

            text = "\n".join((old_value_text, new_value_text))

        elif self.old_value is None:
            if self.new_value.private:
                text = (
                    "** This bug has been marked a duplicate of private bug "
                    "%d" % self.new_value.id
                )
            else:
                text = (
                    "** This bug has been marked a duplicate of bug %d\n"
                    "   %s" % (self.new_value.id, self.new_value.title)
                )

        elif self.new_value is None:
            if self.old_value.private:
                text = (
                    "** This bug is no longer a duplicate of private bug "
                    "%d" % self.old_value.id
                )
            else:
                text = (
                    "** This bug is no longer a duplicate of bug %d\n"
                    "   %s" % (self.old_value.id, self.old_value.title)
                )

        else:
            raise AssertionError(
                "There is no change: both the old bug and new bug are None."
            )

        return {"text": text}


class BugTitleChange(AttributeChange):
    """Describes a change to a bug's title, aka summary."""

    def getBugActivity(self):
        activity = super().getBugActivity()

        # We return 'summary' instead of 'title' for title changes
        # because the bug's title is referred to as its summary in the
        # UI.
        activity["whatchanged"] = "summary"
        return activity

    def getBugNotification(self):
        notification_text = dedent(
            """\
            ** Summary changed:

            - %s
            + %s"""
            % (self.old_value, self.new_value)
        )
        return {"text": notification_text}


class BugInformationTypeChange(AttributeChange):
    """Used to represent a change to the information_type of an `IBug`."""

    def getBugActivity(self):
        return {
            "newvalue": self.new_value.title,
            "oldvalue": self.old_value.title,
            "whatchanged": "information type",
        }

    def getBugNotification(self):
        return {
            "text": "** Information type changed from %s to %s"
            % (self.old_value.title, self.new_value.title)
        }


class BugTagsChange(AttributeChange):
    """Used to represent a change to an `IBug`s tags."""

    def getBugActivity(self):
        # Convert the new and old values into space-separated strings of
        # tags.
        new_value = " ".join(sorted(set(self.new_value)))
        old_value = " ".join(sorted(set(self.old_value)))

        return {
            "newvalue": new_value,
            "oldvalue": old_value,
            "whatchanged": self.what_changed,
        }

    def getBugNotification(self):
        new_tags = set(self.new_value)
        old_tags = set(self.old_value)
        added_tags = new_tags.difference(old_tags)
        removed_tags = old_tags.difference(new_tags)

        messages = []
        if len(removed_tags) > 0:
            messages.append(
                "** Tags removed: %s" % " ".join(sorted(removed_tags))
            )
        if len(added_tags) > 0:
            messages.append("** Tags added: %s" % " ".join(sorted(added_tags)))

        return {"text": "\n".join(messages)}


class BugAttachmentChange(AttributeChange):
    """Used to represent a change to an `IBug`'s attachments."""

    def getBugActivity(self):
        if self.old_value is None:
            what_changed = ATTACHMENT_ADDED
            old_value = None
            new_value = "%s %s" % (
                self.new_value.title,
                self.new_value.displayed_url,
            )
        else:
            what_changed = ATTACHMENT_REMOVED
            old_value = "%s %s" % (
                self.old_value.title,
                self.old_value.displayed_url,
            )
            new_value = None

        return {
            "newvalue": new_value,
            "oldvalue": old_value,
            "whatchanged": what_changed,
        }

    def getBugNotification(self):
        if self.old_value is None:
            if self.new_value.is_patch:
                attachment_str = "Patch"
            else:
                attachment_str = "Attachment"
            message = '** %s added: "%s"\n   %s' % (
                attachment_str,
                self.new_value.title,
                self.new_value.displayed_url,
            )
        else:
            if self.old_value.is_patch:
                attachment_str = "Patch"
            else:
                attachment_str = "Attachment"
            message = '** %s removed: "%s"\n   %s' % (
                attachment_str,
                self.old_value.title,
                self.old_value.displayed_url,
            )

        return {"text": message}


class CveLinkedToBug(BugChangeBase):
    """Used to represent the linking of a CVE to a bug."""

    def __init__(self, when, person, cve):
        super().__init__(when, person)
        self.cve = cve

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(newvalue=self.cve.sequence, whatchanged=CVE_LINKED)

    def getBugNotification(self):
        """See `IBugChange`."""
        return {"text": "** CVE added: %s" % self.cve.url}


class CveUnlinkedFromBug(BugChangeBase):
    """Used to represent the unlinking of a CVE from a bug."""

    def __init__(self, when, person, cve):
        super().__init__(when, person)
        self.cve = cve

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(oldvalue=self.cve.sequence, whatchanged=CVE_UNLINKED)

    def getBugNotification(self):
        """See `IBugChange`."""
        return {"text": "** CVE removed: %s" % self.cve.url}


class BugLocked(BugChangeBase):
    """Used to represent the locking of a bug."""

    def __init__(self, when, person, old_status, new_status, reason, **kwargs):
        super().__init__(when, person)
        self.old_status = old_status
        self.new_status = new_status
        self.reason = reason

    def getBugActivity(self):
        """See `IBugChange'."""
        activity = dict(
            whatchanged="lock status",
            oldvalue=str(self.old_status),
            newvalue=str(self.new_status),
        )
        if self.reason:
            activity["message"] = self.reason

        return activity

    def getBugNotification(self):
        """See `IBugChange`."""
        text = "** Bug metadata locked and limited to project staff"
        if self.reason:
            text = f"{text}: {self.reason}"

        return {"text": text}


class BugUnlocked(BugChangeBase):
    """Used to represent the unlocking of a bug."""

    def __init__(self, when, person, old_status, **kwargs):
        super().__init__(when, person)
        self.old_status = old_status

    def getBugActivity(self):
        """See `IBugChange'."""
        return dict(
            whatchanged="lock status",
            newvalue=str(BugLockStatus.UNLOCKED),
            oldvalue=str(self.old_status),
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        return {"text": "** Bug unlocked"}


class BugLockReasonSet(BugChangeBase):
    """Used to represent setting of the Bug.lock_reason field."""

    def __init__(self, when, person, old_reason, new_reason, **kwargs):
        super().__init__(when, person)
        self.old_reason = old_reason
        self.new_reason = new_reason

    def getBugActivity(self):
        """See `IBugChange`."""
        return dict(
            whatchanged="lock reason",
            oldvalue=self.old_reason if self.old_reason else "unset",
            newvalue=self.new_reason if self.new_reason else "unset",
        )

    def getBugNotification(self):
        """See `IBugChange`."""
        if self.new_reason is None:
            text = "Bug lock reason unset"
        else:
            text = f"** Bug lock reason changed: {self.new_reason}"

        return {"text": text}


class BugTaskAttributeChange(AttributeChange):
    """Used to represent a change in a BugTask's attributes.

    This is a base class. Implementations should define
    `display_attribute` and optionally override
    `display_activity_label` and/or `display_notification_label`.

    `display_attribute` is the name of an attribute on the value
    objects that, when fetched, is usable when recording activity and
    sending notifications.
    """

    def __init__(
        self, bug_task, when, person, what_changed, old_value, new_value
    ):
        super().__init__(when, person, what_changed, old_value, new_value)
        self.bug_task = bug_task

        if self.old_value is None:
            self.display_old_value = None
        else:
            self.display_old_value = getattr(
                self.old_value, self.display_attribute
            )

        if self.new_value is None:
            self.display_new_value = None
        else:
            self.display_new_value = getattr(
                self.new_value, self.display_attribute
            )

    @property
    def display_activity_label(self):
        """The label to use when recording activity.

        By default, it is the same as attribute that changed.
        """
        return self.what_changed

    @property
    def display_notification_label(self):
        """The label to use for notifications.

        By default, it is the same as the attribute that changed,
        capitalized.
        """
        return self.what_changed.capitalize()

    def getBugActivity(self):
        """Return the bug activity data for this change as a dict.

        The `whatchanged` value of the dict refers to the `BugTask`'s
        target so as to make it clear in which task the change was made.
        """
        return {
            "whatchanged": "%s: %s"
            % (self.bug_task.bugtargetname, self.display_activity_label),
            "oldvalue": self.display_old_value,
            "newvalue": self.display_new_value,
        }

    def getBugNotification(self):
        """Return the bug notification text for this change.

        The notification will refer to the `BugTask`'s target so as to
        make it clear in which task the change was made.
        """
        text = (
            "** Changed in: %(bug_target_name)s\n"
            "%(label)13s: %(oldval)s => %(newval)s\n"
            % {
                "bug_target_name": self.bug_task.bugtargetname,
                "label": self.display_notification_label,
                "oldval": self.display_old_value,
                "newval": self.display_new_value,
            }
        )

        return {"text": text.rstrip()}


class BugTaskImportanceChange(BugTaskAttributeChange):
    """Represents a change in BugTask.importance."""

    # Use `importance.title` in activity records and notifications.
    display_attribute = "title"


class BugTaskStatusChange(BugTaskAttributeChange):
    """Represents a change in BugTask.status."""

    # Use `status.title` in activity records and notifications.
    display_attribute = "title"

    @property
    def change_level(self):
        """See `IBugChange`."""
        # Is bug being closed or reopened?
        lifecycle_change = _is_status_change_lifecycle_change(
            self.old_value, self.new_value
        )

        if lifecycle_change:
            return BugNotificationLevel.LIFECYCLE
        else:
            return BugNotificationLevel.METADATA


class BugTaskMilestoneChange(BugTaskAttributeChange):
    """Represents a change in BugTask.milestone."""

    # Use `milestone.name` in activity records and notifications.
    display_attribute = "name"


class BugTaskBugWatchChange(BugTaskAttributeChange):
    """Represents a change in BugTask.bugwatch."""

    # Use the term "remote watch" as this is used in the UI.
    display_activity_label = "remote watch"
    display_notification_label = "Remote watch"

    # Use `bugwatch.title` in activity records and notifications.
    display_attribute = "title"


class BugTaskAssigneeChange(AttributeChange):
    """Represents a change in BugTask.assignee."""

    def __init__(
        self, bug_task, when, person, what_changed, old_value, new_value
    ):
        super().__init__(when, person, what_changed, old_value, new_value)
        self.bug_task = bug_task

    def getBugActivity(self):
        """See `IBugChange`."""

        def assignee_for_display(assignee):
            if assignee is None:
                return None
            else:
                return assignee.unique_displayname

        return {
            "whatchanged": "%s: assignee" % self.bug_task.bugtargetname,
            "oldvalue": assignee_for_display(self.old_value),
            "newvalue": assignee_for_display(self.new_value),
        }

    def getBugNotification(self):
        """See `IBugChange`."""

        def assignee_for_display(assignee):
            if assignee is None:
                return "(unassigned)"
            else:
                return assignee.unique_displayname

        return {
            "text": (
                "** Changed in: %s\n"
                "     Assignee: %s => %s"
                % (
                    self.bug_task.bugtargetname,
                    assignee_for_display(self.old_value),
                    assignee_for_display(self.new_value),
                )
            ),
        }


class BugTaskTargetChange(AttributeChange):
    """Used to represent a change in a BugTask's target."""

    change_level = BugNotificationLevel.LIFECYCLE

    def __init__(
        self, bug_task, when, person, what_changed, old_value, new_value
    ):
        super().__init__(when, person, what_changed, old_value, new_value)
        self.bug_task = bug_task

    def getBugActivity(self):
        """See `IBugChange`."""
        return {
            "whatchanged": "affects",
            "oldvalue": self.old_value.bugtargetname,
            "newvalue": self.new_value.bugtargetname,
        }

    def getBugNotification(self):
        """See `IBugChange`."""
        if IProduct.providedBy(self.old_value):
            template = "** Project changed: %s => %s"
        else:
            template = "** Package changed: %s => %s"
        text = template % (
            self.old_value.bugtargetname,
            self.new_value.bugtargetname,
        )
        return {"text": text}


class BugTaskImportanceExplanationChange(AttributeChange):
    """Represents a change in BugTask.importance_explanation."""

    def __init__(
        self, bug_task, when, person, what_changed, old_value, new_value
    ):
        # XXX: lgp171188 2022-04-12: This is a sub-class of
        # the `AttributeChange` class instead of
        # the `BugTaskAttributeChange` class because the latter
        # requires the `display_attribute` property to be set and
        # does a getattr(<old/new value>, self.display_attribute).
        # This works when an attribute of the field has to be used
        # like `milestone.name`, `importance.title` etc. But this
        # will not work since the `importance_explanation` value
        # is a string that must be used directly.
        #
        # This could be fixed by refactoring the logic in
        # the `BugTaskAttributeChange` constructor to allow values to be used
        # directly.
        super().__init__(when, person, what_changed, old_value, new_value)
        self.bug_task = bug_task

    def getBugActivity(self):
        """See `IBugChange`."""
        return {
            "whatchanged": "%s: importance explanation"
            % (self.bug_task.bugtargetname,),
            "oldvalue": self.old_value or "unset",
            "newvalue": self.new_value or "unset",
        }

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": (
                "** Changed in %s\n"
                "     Importance explanation: %s => %s"
                % (
                    self.bug_task.bugtargetname,
                    self.old_value or "unset",
                    self.new_value or "unset",
                )
            )
        }


class BugTaskStatusExplanationChange(AttributeChange):
    """Represents a change in BugTask.status_explanation."""

    def __init__(
        self, bug_task, when, person, what_changed, old_value, new_value
    ):
        # XXX: lgp171188 2022-04-12: This is a sub-class of
        # the `AttributeChange` class instead of
        # the `BugTaskAttributeChange` class because the latter
        # requires the `display_attribute` property to be set and
        # does a getattr(<old/new value>, self.display_attribute).
        # This works when an attribute of the field has to be used
        # like `milestone.name`, `importance.title` etc. But this
        # will not work since the `status_explanation` value
        # is a string that must be used directly.
        #
        # This could be fixed by refactoring the logic in
        # the `BugTaskAttributeChange` constructor to allow values to be used
        # directly.
        super().__init__(when, person, what_changed, old_value, new_value)
        self.bug_task = bug_task

    def getBugActivity(self):
        """See `IBugChange`."""
        return {
            "whatchanged": "%s: status explanation"
            % (self.bug_task.bugtargetname,),
            "oldvalue": self.old_value or "unset",
            "newvalue": self.new_value or "unset",
        }

    def getBugNotification(self):
        """See `IBugChange`."""
        return {
            "text": (
                "** Changed in %s\n"
                "     Status explanation: %s => %s"
                % (
                    self.bug_task.bugtargetname,
                    self.old_value or "unset",
                    self.new_value or "unset",
                )
            )
        }


BUG_CHANGE_LOOKUP = {
    "description": BugDescriptionChange,
    "information_type": BugInformationTypeChange,
    "tags": BugTagsChange,
    "title": BugTitleChange,
    "attachment": BugAttachmentChange,
    "duplicateof": BugDuplicateChange,
}


BUGTASK_CHANGE_LOOKUP = {
    "importance": BugTaskImportanceChange,
    "status": BugTaskStatusChange,
    "target": BugTaskTargetChange,
    "milestone": BugTaskMilestoneChange,
    "bugwatch": BugTaskBugWatchChange,
    "assignee": BugTaskAssigneeChange,
    "importance_explanation": BugTaskImportanceExplanationChange,
    "status_explanation": BugTaskStatusExplanationChange,
}
