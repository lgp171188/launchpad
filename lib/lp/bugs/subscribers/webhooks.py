# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webhook subscribers for bugs and bugtasks."""

from typing import AnyStr, Union

from lazr.lifecycle.interfaces import IObjectCreatedEvent, IObjectModifiedEvent
from zope.component import getUtility

from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.bugs.interfaces.bugtarget import BUG_WEBHOOKS_FEATURE_FLAG
from lp.bugs.interfaces.bugtask import IBugTask
from lp.services.database.sqlbase import block_implicit_flushes
from lp.services.features import getFeatureFlag
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet, IWebhookTarget


@block_implicit_flushes
def _trigger_bugtask_webhook(bugtask: IBugTask, action: AnyStr):
    """ "Builds payload and triggers event for a specific BugTask.

    TODO: Define a payload for this event (use compose_webhook_payload())
    """
    if not getFeatureFlag(BUG_WEBHOOKS_FEATURE_FLAG):
        return

    target = bugtask.target
    if IWebhookTarget.providedBy(target):
        payload = {
            "target": canonical_url(target, force_local_path=True),
            "action": action,
            "bug": canonical_url(bugtask.bug),
        }
        getUtility(IWebhookSet).trigger(target, "bug:0.1", payload)


@block_implicit_flushes
def _trigger_bug_comment_webhook(bug_comment: IBugMessage, action: AnyStr):
    """Builds payload and triggers "bug:comment" events for a bug comment.

    One event is triggered for each BugTask target that has webhooks setup.

    TODO: Define a payload for this event (use compose_webhook_payload())
    """
    if not getFeatureFlag(BUG_WEBHOOKS_FEATURE_FLAG):
        return

    bugtasks = bug_comment.bug.bugtasks
    for bugtask in bugtasks:
        target = bugtask.target
        if IWebhookTarget.providedBy(target):
            payload = {
                "target": canonical_url(target, force_local_path=True),
                "action": action,
                "bug": canonical_url(bug_comment.bug),
                "bug_comment": canonical_url(bug_comment),
            }
            getUtility(IWebhookSet).trigger(target, "bug:comment:0.1", payload)


def bug_created(
    event_target: Union[IBug, IBugTask],
    event: IObjectCreatedEvent,
):
    """Trigger a 'created' event for a Bug or BugTask.

    Triggering the event for Bug AND BugTask creation ensures that the event is
    triggered both when a user reports a new bug and when an existing bug is
    referenced to another target (BugTask creation).
    """
    if IBug.providedBy(event_target):
        bugtasks = event_target.bugtasks
    else:
        bugtasks = [event_target]

    for bugtask in bugtasks:
        _trigger_bugtask_webhook(bugtask, "created")


def bug_task_modified(bugtask: IBugTask, event: IObjectModifiedEvent):
    """Trigger a 'modified' event when a BugTask is modified"""
    _trigger_bugtask_webhook(bugtask, "modified")


def bug_comment_added(comment, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new comment is added to a Bug"""
    _trigger_bug_comment_webhook(comment, "created")
