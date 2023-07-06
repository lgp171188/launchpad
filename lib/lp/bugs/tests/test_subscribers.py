# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the BugActivity code."""

from lazr.lifecycle.event import ObjectCreatedEvent, ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from testtools.matchers import Equals, MatchesDict, MatchesStructure
from zope.event import notify

from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.bugs.subscribers.bugactivity import what_changed
from lp.services.webapp.publisher import canonical_url
from lp.services.webapp.snapshot import notify_modified
from lp.testing import TestCaseWithFactory, person_logged_in
from lp.testing.layers import DatabaseFunctionalLayer


class TestWhatChanged(TestCaseWithFactory):
    """Tests for the what_changed function."""

    layer = DatabaseFunctionalLayer

    def test_what_changed_works_with_fieldnames(self):
        # When what_changed is passed an ObjectModifiedEvent with a list
        # of fieldnames in its edited_fields property, it will deal with
        # those fields appropriately.
        bug = self.factory.makeBug()
        bug_before_modification = Snapshot(bug, providing=IBug)
        with person_logged_in(bug.owner):
            bug.setPrivate(True, bug.owner)
        event = ObjectModifiedEvent(bug, bug_before_modification, ["private"])
        expected_changes = {"private": ["False", "True"]}
        changes = what_changed(event)
        self.assertEqual(expected_changes, changes)

    def test_what_changed_works_with_field_instances(self):
        # Sometimes something will pass what_changed an
        # ObjectModifiedEvent where the edited_fields list contains
        # field instances. what_changed handles that correctly, too.
        bug = self.factory.makeBug()
        bug_before_modification = Snapshot(bug, providing=IBug)
        with person_logged_in(bug.owner):
            bug.setPrivate(True, bug.owner)
        event = ObjectModifiedEvent(
            bug, bug_before_modification, [IBug["private"]]
        )
        expected_changes = {"private": ["False", "True"]}
        changes = what_changed(event)
        self.assertEqual(expected_changes, changes)


class TestBugWebhooksTriggered(TestCaseWithFactory):
    """Tests that bug and bug comment webhooks get triggered"""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.target = self.factory.makeProduct()
        self.owner = self.target.owner
        self.bugtask = self.factory.makeBugTask(target=self.target)
        self.hook = self.factory.makeWebhook(
            target=self.target, event_types=["bug:comment:0.1", "bug:0.1"]
        )

    def _assert_last_webhook_delivery(self, hook, event, payload):
        with person_logged_in(self.owner):
            delivery = hook.deliveries.last()
            expected_structure = MatchesStructure(
                event_type=Equals(event),
                payload=MatchesDict(payload),
            )
            self.assertThat(delivery, expected_structure)

    def _build_comment_expected_payload(self, comment, content):
        return {
            "action": Equals("created"),
            "bug_comment": Equals(
                canonical_url(comment, force_local_path=True)
            ),
            "bug": Equals(
                canonical_url(self.bugtask.bug, force_local_path=True)
            ),
            "target": Equals(
                canonical_url(self.target, force_local_path=True)
            ),
            "new": MatchesDict(
                {
                    "content": Equals(content),
                    "commenter": Equals("/~" + comment.owner.name),
                }
            ),
        }

    def _build_bugtask_expected_payload(
        self, bugtask, action, changed_fields=None
    ):
        assignee = "/~" + bugtask.assignee.name if bugtask.assignee else None

        bug_task_attributes = {
            "title": Equals(bugtask.bug.title),
            "description": Equals(bugtask.bug.description),
            "reporter": Equals(
                canonical_url(bugtask.bug.owner, force_local_path=True)
            ),
            "status": Equals(bugtask.status.title),
            "importance": Equals(bugtask.importance.title),
            "assignee": Equals(assignee),
            "date_created": Equals(bugtask.datecreated.isoformat()),
        }

        expected_payload = {
            "action": Equals(action),
            "bug": Equals(canonical_url(bugtask.bug, force_local_path=True)),
            "target": Equals(
                canonical_url(self.target, force_local_path=True)
            ),
            "new": MatchesDict(bug_task_attributes),
        }

        if changed_fields:
            old_bug_attributes = bug_task_attributes.copy()
            for k, v in changed_fields.items():
                old_bug_attributes[k] = Equals(v)
            expected_payload["old"] = MatchesDict(old_bug_attributes)

        return expected_payload

    def test_new_bug_comment_triggers_webhook(self):
        """Adding a comment to a bug with a webhook, triggers webhook"""
        comment = self.factory.makeBugComment(
            bug=self.bugtask.bug, body="test comment"
        )
        expected_payload = self._build_comment_expected_payload(
            comment, content="test comment"
        )
        self._assert_last_webhook_delivery(
            self.hook, "bug:comment:0.1", expected_payload
        )

    def test_new_bug_triggers_webhook(self):
        """Adding a bug to a target with a webhook, triggers webhook"""
        bug = self.factory.makeBug(target=self.target)
        expected_payload = self._build_bugtask_expected_payload(
            bug.bugtasks[0], "created"
        )
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload
        )

    def test_new_bugtask_triggers_webhook(self):
        """Adding a new task targeted at our webhook target, will invoke the
        bug 'created' event"""
        bug = self.factory.makeBug()
        with person_logged_in(self.owner):
            new_task = bug.addTask(owner=self.owner, target=self.target)
            # The ObjectCreatedEvent would be triggered in BugAlsoAffectsView
            notify(ObjectCreatedEvent(new_task))

        expected_payload = self._build_bugtask_expected_payload(
            new_task, "created"
        )
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload
        )

    def test_bug_modified_triggers_webhook(self):
        """Modifying the bug fields, will trigger webhook"""
        bug = self.bugtask.bug
        original_title = bug.title
        with person_logged_in(self.owner), notify_modified(
            bug, ["title"], user=self.owner
        ):
            bug.title = "new title"
        expected_payload = self._build_bugtask_expected_payload(
            self.bugtask, "title-changed", {"title": original_title}
        )
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload
        )

    def test_bugtask_modified_triggers_webhook(self):
        """Modifying the bug task fields, will trigger webhook"""
        original_status = self.bugtask.status.title
        with person_logged_in(self.owner):
            self.bugtask.bug.setStatus(
                self.target, BugTaskStatus.FIXRELEASED, self.owner
            )
        expected_payload = self._build_bugtask_expected_payload(
            self.bugtask, "status-changed", {"status": original_status}
        )
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload
        )

    def test_webhook_subscription(self):
        """Check that a webhook only subscribed to the 'bug:0.1' event, does
        not get a 'bug:comment:0.1' event, and vice-versa"""
        bug_hook = self.factory.makeWebhook(
            target=self.target, event_types=["bug:0.1"]
        )
        comment_hook = self.factory.makeWebhook(
            target=self.target, event_types=["bug:comment:0.1"]
        )

        bug = self.factory.makeBug(target=self.target)
        comment = self.factory.makeBugComment(
            bug=self.bugtask.bug, body="test comment"
        )

        b_exptd_payload = self._build_bugtask_expected_payload(
            bug.bugtasks[0], "created"
        )
        c_exptd_payload = self._build_comment_expected_payload(
            comment,
            content="test comment",
        )

        self._assert_last_webhook_delivery(
            bug_hook, "bug:0.1", b_exptd_payload
        )

        self._assert_last_webhook_delivery(
            comment_hook, "bug:comment:0.1", c_exptd_payload
        )
