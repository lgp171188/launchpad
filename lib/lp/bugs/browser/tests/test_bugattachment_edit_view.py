# Copyright 2010-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

import transaction
from zope.security.interfaces import Unauthorized

from lp.testing import (
    login_person,
    person_logged_in,
    TestCaseWithFactory,
    )
from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.views import create_initialized_view


class TestBugAttachmentEditView(TestCaseWithFactory):
    """Tests of traversal to and access of files of bug attachments."""

    layer = LaunchpadFunctionalLayer

    CHANGE_FORM_DATA = {
        'field.title': 'new description',
        'field.patch': 'on',
        'field.contenttype': 'application/whatever',
        'field.actions.change': 'Change',
        }

    def setUp(self):
        super(TestBugAttachmentEditView, self).setUp()
        self.bug_owner = self.factory.makePerson()
        login_person(self.bug_owner)
        self.bug = self.factory.makeBug(owner=self.bug_owner)
        self.bugattachment = self.factory.makeBugAttachment(
            bug=self.bug, filename='foo.diff', data=b'file content',
            description='attachment description', content_type='text/plain',
            is_patch=False)
        # The Librarian server should know about the new file before
        # we start the tests.
        transaction.commit()

    def test_change_action_public_bug(self):
        # Properties of attachments for public bugs can be
        # changed by every user.
        user = self.factory.makePerson()
        login_person(user)
        create_initialized_view(
            self.bugattachment, name='+edit', form=self.CHANGE_FORM_DATA)
        self.assertEqual('new description', self.bugattachment.title)
        self.assertTrue(self.bugattachment.is_patch)
        self.assertEqual(
            'application/whatever', self.bugattachment.libraryfile.mimetype)

    def test_change_action_private_bug(self):
        # Subscribers of a private bug can edit attachments.
        user = self.factory.makePerson()
        self.bug.setPrivate(True, self.bug_owner)
        with person_logged_in(self.bug_owner):
            self.bug.subscribe(user, self.bug_owner)
        transaction.commit()
        login_person(user)
        create_initialized_view(
            self.bugattachment, name='+edit', form=self.CHANGE_FORM_DATA)
        self.assertEqual('new description', self.bugattachment.title)
        self.assertTrue(self.bugattachment.is_patch)
        self.assertEqual(
            'application/whatever', self.bugattachment.libraryfile.mimetype)

    def test_change_action_private_bug_unauthorized(self):
        # Other users cannot edit attachments of private bugs.
        user = self.factory.makePerson()
        self.bug.setPrivate(True, self.bug_owner)
        transaction.commit()
        login_person(user)
        self.assertRaises(
            Unauthorized, create_initialized_view, self.bugattachment,
            name='+edit', form=self.CHANGE_FORM_DATA)

    DELETE_FORM_DATA = {
        'field.actions.delete': 'Delete Attachment',
        }

    def test_delete_cannot_be_performed_by_other_users(self):
        user = self.factory.makePerson()
        login_person(user)
        create_initialized_view(
            self.bugattachment, name='+edit', form=self.DELETE_FORM_DATA)
        self.assertEqual(1, self.bug.attachments.count())

    def test_admin_can_delete_any_attachment(self):
        admin = self.factory.makeAdministrator()
        login_person(admin)
        create_initialized_view(
            self.bugattachment, name='+edit', form=self.DELETE_FORM_DATA)
        self.assertEqual(0, self.bug.attachments.count())

    def test_attachment_owner_can_delete_his_own_attachment(self):
        bug = self.factory.makeBug(owner=self.bug_owner)
        another_user = self.factory.makePerson()
        attachment = self.factory.makeBugAttachment(
            bug=bug, owner=another_user, filename='foo.diff',
            data=b'the file content', description='some file',
            content_type='text/plain', is_patch=False)

        login_person(another_user)
        create_initialized_view(
            attachment, name='+edit', form=self.DELETE_FORM_DATA)
        self.assertEqual(0, bug.attachments.count())

    def test_bug_owner_can_delete_any_attachment(self):
        bug = self.factory.makeBug(owner=self.bug_owner)
        # Attachment from bug owner.
        attachment1 = self.factory.makeBugAttachment(
            bug=bug, owner=self.bug_owner, filename='foo.diff',
            data=b'the file content', description='some file',
            content_type='text/plain', is_patch=False)

        # Attachment from another user.
        another_user = self.factory.makePerson()
        attachment2 = self.factory.makeBugAttachment(
            bug=bug, owner=another_user, filename='foo.diff',
            data=b'the file content', description='some file',
            content_type='text/plain', is_patch=False)

        login_person(self.bug_owner)
        # Bug owner can remove his own attachment.
        create_initialized_view(
            attachment1, name='+edit', form=self.DELETE_FORM_DATA)
        self.assertEqual(1, bug.attachments.count())

        # Bug owner can remove someone else's attachment.
        create_initialized_view(
            attachment2, name='+edit', form=self.DELETE_FORM_DATA)
        self.assertEqual(0, bug.attachments.count())
