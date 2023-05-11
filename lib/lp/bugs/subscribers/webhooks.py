# Copyright 2023 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Webhook subscribers for bugs and bugtasks."""

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
def _trigger_bugtask_webhook(bugtask: IBugTask, action: str):
    """ "Builds payload and triggers event for a specific BugTask"""
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
def _trigger_bug_comment_webhook(bug_comment: IBugMessage, action: str):
    """Builds payload and triggers "bug:comment" events for a bug comment"""
    if not getFeatureFlag(BUG_WEBHOOKS_FEATURE_FLAG):
        return

    bugtasks = bug_comment.bug.bugtasks

    # We trigger one webhook for each coment's bugtask that has webhooks set up
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


def bugtask_created(bugtask: IBugTask, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a BugTask is created for an existing bug

    #NOTE Ideally, when we create a new bug, we would also trigger this since
    we are creating a bug task with it. That is not the case, so we separate it
    into 'bugtask_created' and 'bug_created' to get all bugtask creation cases
    """
    _trigger_bugtask_webhook(bugtask, "created")


def bug_created(bug: IBug, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new Bug is created"""
    for bugtask in bug.bugtasks:
        _trigger_bugtask_webhook(bugtask, "created")


def bugtask_modified(bugtask: IBugTask, event: IObjectModifiedEvent):
    """Trigger a 'modified' event when a BugTask is modified"""
    _trigger_bugtask_webhook(bugtask, "modified")


def bug_comment_added(comment, event: IObjectCreatedEvent):
    """Trigger a 'created' event when a new comment is added to a Bug"""
    _trigger_bug_comment_webhook(comment, "created")
