# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webhook subscribers for bugs and bugtasks."""

from typing import Union

from lazr.lifecycle.interfaces import IObjectCreatedEvent, IObjectModifiedEvent
from zope.component import getUtility

from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugmessage import IBugMessage
from lp.bugs.interfaces.bugtarget import DISABLE_BUG_WEBHOOKS_FEATURE_FLAG
from lp.bugs.interfaces.bugtask import IBugTask
from lp.bugs.subscribers.bugactivity import what_changed
from lp.services.database.sqlbase import block_implicit_flushes
from lp.services.features import getFeatureFlag
from lp.services.webapp.publisher import canonical_url
from lp.services.webhooks.interfaces import IWebhookSet, IWebhookTarget
from lp.services.webhooks.payload import compose_webhook_payload


@block_implicit_flushes
def _trigger_bugtask_webhook(
    action: str,
    bugtask: IBugTask,
    previous_state: Union[IBug, IBugTask] = None,
):
    """Triggers 'bug' event for a specific bugtask"""
    if getFeatureFlag(DISABLE_BUG_WEBHOOKS_FEATURE_FLAG):
        return

    if IWebhookTarget.providedBy(bugtask.target):
        payload = create_bugtask_payload(action, bugtask, previous_state)
        getUtility(IWebhookSet).trigger(bugtask.target, "bug:0.1", payload)


@block_implicit_flushes
def _trigger_bug_comment_webhook(action: str, bug_comment: IBugMessage):
    """Triggers 'bug:comment' events for each bug target for that comment"""
    if getFeatureFlag(DISABLE_BUG_WEBHOOKS_FEATURE_FLAG):
        return

    bugtasks = bug_comment.bug.bugtasks

    # We trigger one webhook per comment's bugtask that has webhooks set up
    for bugtask in bugtasks:
        target = bugtask.target
        if IWebhookTarget.providedBy(target):
            payload = create_bug_comment_payload(action, bugtask, bug_comment)
            getUtility(IWebhookSet).trigger(target, "bug:comment:0.1", payload)


def create_bugtask_payload(
    action: str,
    bugtask: IBugTask,
    previous_state: Union[IBugTask, IBug] = None,
):
    payload = {
        "action": action,
        "target": canonical_url(bugtask.target, force_local_path=True),
        "bug": canonical_url(bugtask.bug, force_local_path=True),
    }
    payload["new"] = get_bugtask_attributes(bugtask, bugtask.bug)

    # A previous state exists when a bug or bugtask are modified
    # We get the old state depending on whether the bug or bugtask were changed
    if previous_state:
        if IBugTask.providedBy(previous_state):
            old_bugtask = previous_state
            old_bug = bugtask.bug
        else:
            old_bugtask = bugtask
            old_bug = previous_state

        payload["old"] = get_bugtask_attributes(old_bugtask, old_bug)
    return payload


def get_bugtask_attributes(bugtask: IBugTask, bug: IBug):
    data = compose_webhook_payload(
        IBug,
        bug,
        ["title", "description", "owner", "tags"],
        preferred_names={"owner": "reporter"},
    )
    data.update(
        compose_webhook_payload(
            IBugTask,
            bugtask,
            ["status", "importance", "assignee", "datecreated"],
            preferred_names={"datecreated": "date_created"},
        )
    )
    return data


def create_bug_comment_payload(
    action: str, bugtask: IBugTask, bug_comment: IBugMessage
):
    payload = {
        "action": action,
        "target": canonical_url(bugtask.target, force_local_path=True),
        "bug": canonical_url(bug_comment.bug, force_local_path=True),
        "bug_comment": canonical_url(bug_comment, force_local_path=True),
    }

    # NOTE We might want to add a comment 'modified' event in the future, and
    # an 'old' field as well. Having the 'new' field here now, makes it
    # coherent with the bug events and allows for that addition to be seamless
    payload["new"] = {
        "commenter": canonical_url(bug_comment.owner, force_local_path=True),
        "content": bug_comment.text_contents,
    }

    return payload


def bug_created(bug: IBug, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new Bug is created

    #NOTE When a user creates a new Bug, only the 'bug_created' is called
    (not 'bugtask_created'). On the other hand, when a new project is added to
    a bug as being affected by it, then only 'bugtask_created' is called.
    """
    for bugtask in bug.bugtasks:
        _trigger_bugtask_webhook("created", bugtask)


def bug_modified(bug: IBug, event: IObjectCreatedEvent):
    """Trigger a '<field>-updated' event when a bug is modified"""
    changed_fields = what_changed(event)
    previous_state = event.object_before_modification

    for field in changed_fields:
        action = "{}-changed".format(field)
        for bugtask in bug.bugtasks:
            _trigger_bugtask_webhook(action, bugtask, previous_state)


def bugtask_created(bugtask: IBugTask, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a BugTask is created in existing bug"""
    _trigger_bugtask_webhook("created", bugtask)


def bugtask_modified(bugtask: IBugTask, event: IObjectModifiedEvent):
    """Trigger a '<field>-updated' event when a BugTask is modified"""
    changed_fields = what_changed(event)
    previous_state = event.object_before_modification

    for field in changed_fields:
        action = "{}-changed".format(field)
        _trigger_bugtask_webhook(action, bugtask, previous_state)


def bug_comment_added(comment, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new comment is added to a Bug"""
    _trigger_bug_comment_webhook("created", comment)
