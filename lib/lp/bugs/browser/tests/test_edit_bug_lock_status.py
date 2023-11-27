# Copyright 2011-2022 Canonical Ltd. This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests related to the view for editing the bug lock status."""

from soupmatchers import HTMLContains, Tag
from testtools.matchers import MatchesStructure, Not
from zope.security.interfaces import Unauthorized

from lp.bugs.enums import BugLockStatus
from lp.services.webapp import canonical_url
from lp.services.webapp.servers import LaunchpadTestRequest
from lp.testing import (
    BrowserTestCase,
    TestCaseWithFactory,
    anonymous_logged_in,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.views import create_initialized_view


class TestBugLockStatusEditView(TestCaseWithFactory):
    """
    Tests for the view to edit the bug lock status.
    """

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        self.target = self.factory.makeProduct()

    def test_form_submission_missing_required_fields(self):
        bug = self.factory.makeBug(target=self.target)
        form = {
            "a": 1,
            "b": 2,
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.UNLOCKED, bug.lock_status)
        self.assertIsNone(bug.lock_reason)

    def test_users_without_moderate_permission_cannot_edit_lock_status(self):
        bug = self.factory.makeBug(target=self.target)
        with person_logged_in(self.target.owner):
            bug.lock(who=self.target.owner, status=BugLockStatus.COMMENT_ONLY)

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Unlocked",
            "field.lock_reason": "",
            "field.lock_status-empty-marker": "1",
        }

        with anonymous_logged_in():
            self.assertRaises(
                Unauthorized,
                create_initialized_view,
                bug.default_bugtask,
                name="+lock-status",
                form=form,
            )

        with person_logged_in(self.person):
            self.assertRaises(
                Unauthorized,
                create_initialized_view,
                bug.default_bugtask,
                name="+lock-status",
                form=form,
            )

    def test_locking_a_locked_bug(self):
        bug = self.factory.makeBug(target=self.target)
        with person_logged_in(self.target.owner):
            bug.lock(who=self.target.owner, status=BugLockStatus.COMMENT_ONLY)

        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertIsNone(bug.lock_reason)

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Comment-only",
            "field.lock_reason": "",
            "field.lock_status-empty-marker": "1",
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertIsNone(bug.lock_reason)

    def test_unlocking_an_unlocked_bug(self):
        bug = self.factory.makeBug(target=self.target)

        self.assertEqual(BugLockStatus.UNLOCKED, bug.lock_status)
        self.assertIsNone(bug.lock_reason)

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Unlocked",
            "field.lock_reason": "too hot",
            "field.lock_status-empty-marker": "1",
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.UNLOCKED, bug.lock_status)
        self.assertIsNone(bug.lock_reason)

    def test_unlocking_a_bug_locked_with_reason_clears_the_reason(self):
        bug = self.factory.makeBug(target=self.target)

        with person_logged_in(self.target.owner):
            bug.lock(
                who=self.target.owner,
                status=BugLockStatus.COMMENT_ONLY,
                reason="too hot",
            )
        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertEqual("too hot", bug.lock_reason)

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Unlocked",
            "field.lock_reason": "too hot!",
            "field.lock_status-empty-marker": "1",
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.UNLOCKED, bug.lock_status)
        self.assertIsNone(bug.lock_reason)

    def test_locking_an_unlocked_bug(self):
        bug = self.factory.makeBug(target=self.target)

        self.assertEqual(BugLockStatus.UNLOCKED, bug.lock_status)
        self.assertIsNone(bug.lock_reason)
        self.assertEqual(1, bug.activity.count())

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Comment-only",
            "field.lock_reason": "too hot",
            "field.lock_status-empty-marker": "1",
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertEqual("too hot", bug.lock_reason)
        self.assertEqual(2, bug.activity.count())
        self.assertThat(
            bug.activity[1],
            MatchesStructure.byEquality(
                person=self.target.owner,
                whatchanged="lock status",
                oldvalue=str(BugLockStatus.UNLOCKED),
                newvalue=str(BugLockStatus.COMMENT_ONLY),
            ),
        )

    def test_unlocking_a_locked_bug(self):
        bug = self.factory.makeBug(target=self.target)
        self.assertEqual(1, bug.activity.count())

        with person_logged_in(self.target.owner):
            bug.lock(
                who=self.target.owner,
                status=BugLockStatus.COMMENT_ONLY,
                reason="too hot",
            )
        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertEqual("too hot", bug.lock_reason)
        self.assertEqual(2, bug.activity.count())

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Unlocked",
            "field.lock_reason": "too hot!!",
            "field.lock_status-empty-marker": "1",
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.UNLOCKED, bug.lock_status)
        self.assertIsNone(bug.lock_reason)
        self.assertEqual(3, bug.activity.count())
        self.assertThat(
            bug.activity[2],
            MatchesStructure.byEquality(
                person=self.target.owner,
                whatchanged="lock status",
                oldvalue=str(BugLockStatus.COMMENT_ONLY),
                newvalue=str(BugLockStatus.UNLOCKED),
            ),
        )

    def test_changing_lock_reason_of_a_locked_bug(self):
        bug = self.factory.makeBug(target=self.target)
        self.assertEqual(1, bug.activity.count())

        with person_logged_in(self.target.owner):
            bug.lock(
                who=self.target.owner,
                status=BugLockStatus.COMMENT_ONLY,
                reason="too hot",
            )
        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertEqual("too hot", bug.lock_reason)
        self.assertEqual(2, bug.activity.count())

        form = {
            "field.actions.change": "Change",
            "field.lock_status": "Comment-only",
            "field.lock_reason": "too hot!",
            "field.lock_status-empty-marker": "1",
        }
        with person_logged_in(self.target.owner):
            request = LaunchpadTestRequest(
                method="POST",
                form=form,
            )
            view = create_initialized_view(
                bug.default_bugtask, name="+lock-status", request=request
            )
            self.assertEqual([], view.errors)

        self.assertEqual(BugLockStatus.COMMENT_ONLY, bug.lock_status)
        self.assertEqual("too hot!", bug.lock_reason)
        self.assertEqual(3, bug.activity.count())
        self.assertThat(
            bug.activity[2],
            MatchesStructure.byEquality(
                person=self.target.owner,
                whatchanged="lock reason",
                oldvalue="too hot",
                newvalue="too hot!",
            ),
        )


class TestBugLockFeatures(BrowserTestCase):
    """Test for the features related to the locking, unlocking a bug."""

    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        self.person = self.factory.makePerson()
        self.target = self.factory.makeProduct()

    def test_bug_lock_status_page_not_linked_for_non_moderators(self):
        bug = self.factory.makeBug(target=self.target)
        bugtask_url = canonical_url(bug.default_bugtask)
        browser = self.getUserBrowser(
            bugtask_url,
            user=self.person,
        )
        self.assertThat(
            browser.contents,
            Not(
                HTMLContains(
                    Tag(
                        "change lock status link tag",
                        "a",
                        text="Change lock status",
                        attrs={
                            "class": "edit",
                            "href": f"{bugtask_url}/+lock-status",
                        },
                    )
                )
            ),
        )

    def test_bug_lock_status_page_linked_for_moderators(self):
        bug = self.factory.makeBug(target=self.target)
        bugtask_url = canonical_url(bug.default_bugtask)

        browser = self.getUserBrowser(
            bugtask_url,
            user=self.target.owner,
        )
        self.assertThat(
            browser.contents,
            HTMLContains(
                Tag(
                    "change lock status link tag",
                    "a",
                    text="Change lock status",
                    attrs={
                        "class": "edit",
                        "href": f"{bugtask_url}/+lock-status",
                    },
                )
            ),
        )

    def test_bug_readonly_icon_displayed_when_bug_is_locked(self):
        bug = self.factory.makeBug(target=self.target)
        with person_logged_in(self.target.owner):
            bug.lock(
                who=self.target.owner,
                status=BugLockStatus.COMMENT_ONLY,
                reason="too hot",
            )

        bugtask_url = canonical_url(bug.default_bugtask)

        browser = self.getUserBrowser(
            bugtask_url,
            user=self.target.owner,
        )
        self.assertThat(
            browser.contents,
            HTMLContains(
                Tag(
                    "read-only icon tag",
                    "span",
                    attrs={"class": "read-only", "title": "Locked"},
                )
            ),
        )

    def test_bug_readonly_icon_not_displayed_when_bug_is_unlocked(self):
        bug = self.factory.makeBug(target=self.target)

        bugtask_url = canonical_url(bug.default_bugtask)

        browser = self.getUserBrowser(
            bugtask_url,
            user=self.target.owner,
        )
        self.assertThat(
            browser.contents,
            Not(
                HTMLContains(
                    Tag(
                        "read-only icon tag",
                        "span",
                        attrs={"class": "read-only", "title": "Locked"},
                    )
                )
            ),
        )
