# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for the BugActivity code."""

from lazr.lifecycle.event import ObjectCreatedEvent, ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from testtools.matchers import Equals, MatchesDict, MatchesStructure
from zope.event import notify

from lp.bugs.interfaces.bug import IBug
from lp.bugs.interfaces.bugtarget import BUG_WEBHOOKS_FEATURE_FLAG
from lp.bugs.interfaces.bugtask import BugTaskStatus
from lp.bugs.subscribers.bugactivity import what_changed
from lp.services.features.testing import FeatureFixture
from lp.services.webapp.publisher import canonical_url
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
        self.useFixture(
            FeatureFixture(
                {
                    BUG_WEBHOOKS_FEATURE_FLAG: "on",
                }
            )
        )
        self.target = self.factory.makeProduct()
        self.owner = self.target.owner
        self.bugtask = self.factory.makeBugTask(target=self.target)
        self.hook = self.factory.makeWebhook(
            target=self.target, event_types=["bug:comment:0.1", "bug:0.1"]
        )

    def _assert_last_webhook_delivery(self, hook, event, payload, total_count):
        with person_logged_in(self.owner):
            self.assertEqual(total_count, hook.deliveries.count())
            delivery = hook.deliveries.last()
            expected_structure = MatchesStructure(
                event_type=Equals(event),
                payload=MatchesDict(payload),
            )
            self.assertThat(delivery, expected_structure)

    def _build_comment_expected_payload(self, comment):
        return {
            "action": Equals("created"),
            "url": Equals(canonical_url(comment)),
            "target": Equals(
                canonical_url(self.target, force_local_path=True)
            ),
        }

    def _build_bug_expected_payload(self, bug, action):
        return {
            "action": Equals(action),
            "url": Equals(canonical_url(bug)),
            "target": Equals(
                canonical_url(self.target, force_local_path=True)
            ),
        }

    def test_new_bug_comment_triggers_webhook(self):
        comment = self.factory.makeBugComment(bug=self.bugtask.bug)
        expected_payload = self._build_comment_expected_payload(comment)
        self._assert_last_webhook_delivery(
            self.hook, "bug:comment:0.1", expected_payload, total_count=1
        )

    def test_new_bug_triggers_webhook(self):
        bug = self.factory.makeBug(target=self.target)
        expected_payload = self._build_bug_expected_payload(bug, "created")
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload, total_count=1
        )

    def test_new_bugtask_triggers_webhook(self):
        """Check that adding a new task targeted at our webhook target, will
        invoke the bug 'created' event"""
        bug = self.factory.makeBug()
        with person_logged_in(self.owner):
            new_task = bug.addTask(owner=self.owner, target=self.target)
            # The ObjectCreatedEvent would be triggered in BugAlsoAffectsView
            notify(ObjectCreatedEvent(new_task))

        expected_payload = self._build_bug_expected_payload(bug, "created")
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload, total_count=1
        )

    def test_bugtask_modified_triggers_webhook(self):
        with person_logged_in(self.owner):
            self.bugtask.bug.setStatus(
                self.target, BugTaskStatus.FIXRELEASED, self.owner
            )
        expected_payload = self._build_bug_expected_payload(
            self.bugtask.bug, "modified"
        )
        self._assert_last_webhook_delivery(
            self.hook, "bug:0.1", expected_payload, total_count=1
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
        comment = self.factory.makeBugComment(bug=self.bugtask.bug)

        b_expected_payload = self._build_bug_expected_payload(bug, "created")
        c_expected_payload = self._build_comment_expected_payload(comment)

        self._assert_last_webhook_delivery(
            bug_hook, "bug:0.1", b_expected_payload, total_count=1
        )

        self._assert_last_webhook_delivery(
            comment_hook, "bug:comment:0.1", c_expected_payload, total_count=1
        )
