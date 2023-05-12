# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webhook subscribers for bugs and bugtasks."""

from lazr.lifecycle.interfaces import IObjectCreatedEvent, IObjectModifiedEvent
from zope.component import getUtility

from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.bugs.interfaces.bugtarget import BUG_WEBHOOKS_FEATURE_FLAG
from lp.bugs.interfaces.bugtask import IBugTask
from lp.bugs.subscribers.bugactivity import what_changed
from lp.services.database.sqlbase import block_implicit_flushes
from lp.services.features import getFeatureFlag
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet, IWebhookTarget
from lp.services.webhooks.payload import compose_webhook_payload


@block_implicit_flushes
def _trigger_bugtask_webhook(bugtask: IBugTask, action: str):
    """Triggers 'bug' event for a specific bugtask"""
    if not getFeatureFlag(BUG_WEBHOOKS_FEATURE_FLAG):
        return

    if IWebhookTarget.providedBy(bugtask.target):
        payload = create_bugtask_payload(bugtask, action)
        getUtility(IWebhookSet).trigger(bugtask.target, "bug:0.1", payload)


@block_implicit_flushes
def _trigger_bug_comment_webhook(bug_comment: IBugMessage, action: str):
    """Triggers 'bug:comment' events for each bug target for that comment"""
    if not getFeatureFlag(BUG_WEBHOOKS_FEATURE_FLAG):
        return

    bugtasks = bug_comment.bug.bugtasks

    # We trigger one webhook for each coment's bugtask that has webhooks set up
    for bugtask in bugtasks:
        target = bugtask.target
        if IWebhookTarget.providedBy(target):
            payload = create_bug_comment_payload(bugtask, bug_comment, action)
            getUtility(IWebhookSet).trigger(target, "bug:comment:0.1", payload)


def create_bugtask_payload(bugtask, action):
    payload = {
        "target": canonical_url(bugtask.target, force_local_path=True),
        "action": action,
        "bug": canonical_url(bugtask.bug, force_local_path=True),
    }
    payload.update(
        compose_webhook_payload(
            IBug,
            bugtask.bug,
            ["title", "description", "owner"],
        )
    )
    payload.update(
        compose_webhook_payload(
            IBugTask,
            bugtask,
            ["status", "importance", "assignee", "datecreated"],
        )
    )
    return payload


def create_bug_comment_payload(bugtask, bug_comment, action):
    payload = {
        "target": canonical_url(bugtask.target, force_local_path=True),
        "action": action,
        "bug": canonical_url(bug_comment.bug, force_local_path=True),
        "bug_comment": canonical_url(bug_comment, force_local_path=True),
        "content": bug_comment.text_contents,
    }
    payload.update(
        compose_webhook_payload(IBugMessage, bug_comment, ["owner"])
    )
    return payload


def bug_created(bug: IBug, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new Bug is created

    #NOTE When a user creates a new Bug, only the 'bug_created' is called
    (not 'bugtask_created'). On the other hand, when a new project is added to
    a bug as being affected by it, then only 'bugtask_created' is called.
    """
    for bugtask in bug.bugtasks:
        _trigger_bugtask_webhook(bugtask, "created")


def bug_modified(bug: IBug, event: IObjectCreatedEvent):
    """Trigger a '<field>-updated' event when a bug is modified"""
    changed_fields = what_changed(event)

    for field in changed_fields:
        action = "{}-updated".format(field)
        for bugtask in bug.bugtasks:
            _trigger_bugtask_webhook(bugtask, action)


def bugtask_created(bugtask: IBugTask, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a BugTask is created in existing bug"""
    _trigger_bugtask_webhook(bugtask, "created")


def bugtask_modified(bugtask: IBugTask, event: IObjectModifiedEvent):
    """Trigger a '<field>-updated' event when a BugTask is modified"""
    changed_fields = what_changed(event)

    for field in changed_fields:
        action = "{}-updated".format(field)
        _trigger_bugtask_webhook(bugtask, action)


def bug_comment_added(comment, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new comment is added to a Bug"""
    _trigger_bug_comment_webhook(comment, "created")
