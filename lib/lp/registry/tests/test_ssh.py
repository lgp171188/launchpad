# Copyright 2016-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for SSHKey."""

from testtools.matchers import StartsWith
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.registry.interfaces.ssh import (
    SSH_TEXT_TO_KEY_TYPE,
    ISSHKeySet,
    SSHKeyAdditionError,
)
from lp.services.webapp.interfaces import OAuthPermission
from lp.testing import (
    TestCaseWithFactory,
    admin_logged_in,
    api_url,
    person_logged_in,
)
from lp.testing.layers import DatabaseFunctionalLayer
from lp.testing.mail_helpers import pop_notifications
from lp.testing.pages import webservice_for_person


class TestSSHKey(TestCaseWithFactory):
    """Test `ISSHKey`."""

    layer = DatabaseFunctionalLayer

    def test_getFullKeyText_for_rsa_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ssh-rsa")
        expected = "ssh-rsa %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_dsa_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ssh-dss")
        expected = "ssh-dss %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_ecdsa_nistp256_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ecdsa-sha2-nistp256")
        expected = "ecdsa-sha2-nistp256 %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_ecdsa_nistp384_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ecdsa-sha2-nistp384")
        expected = "ecdsa-sha2-nistp384 %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_ecdsa_nistp521_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ecdsa-sha2-nistp521")
        expected = "ecdsa-sha2-nistp521 %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_ed25519_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ssh-ed25519")
        expected = "ssh-ed25519 %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_key_without_comment(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ssh-rsa", comment="")
        expected = "ssh-rsa %s" % (key.keytext)
        self.assertEqual(expected, key.getFullKeyText())

    def test_getFullKeyText_for_corrupt_key(self):
        # If the key text is corrupt, the type from the database is used
        # instead of the one decoded from the text.
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ssh-rsa")
            # The base64 has a valid netstring, but the contents are garbage so
            # can't be a valid key type.
            removeSecurityProxy(key).keytext = "AAAAB3NzaC1012EAAAA="
        expected = "ssh-rsa %s %s" % (key.keytext, key.comment)
        self.assertEqual(expected, key.getFullKeyText())

    def test_destroySelf_sends_notification_by_default(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, send_notification=False)
            key.destroySelf()
            [email] = pop_notifications()
            self.assertEqual(
                email["Subject"],
                "SSH key removed from your Launchpad account.",
            )
            self.assertThat(
                email.get_payload(),
                StartsWith(
                    "The SSH key %s was removed from your " % key.comment
                ),
            )

    def test_destroySelf_notification_empty_comment(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(
                person, send_notification=False, comment=""
            )
            key.destroySelf()
            [email] = pop_notifications()
            self.assertEqual(
                "SSH key removed from your Launchpad account.",
                email["Subject"],
            )
            self.assertThat(
                email.get_payload(),
                StartsWith(
                    "An SSH key of type '%s' was removed "
                    "from your account." % key.keytype.title
                ),
            )

    def test_destroySelf_notifications_can_be_suppressed(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, send_notification=False)
            key.destroySelf(False)
            self.assertEqual([], pop_notifications())


class TestSSHKeySet(TestCaseWithFactory):
    """Test `ISSHKeySet`."""

    layer = DatabaseFunctionalLayer

    def test_sends_notification_by_default(self):
        person = self.factory.makePerson()
        key_text = self.factory.makeSSHKeyText(comment="comment")
        with person_logged_in(person):
            keyset = getUtility(ISSHKeySet)
            keyset.new(person, key_text)
            [email] = pop_notifications()
        self.assertEqual(
            email["Subject"], "New SSH key added to your account."
        )
        self.assertThat(
            email.get_payload(),
            StartsWith(
                "The SSH key 'comment' has been added to your account."
            ),
        )

    def test_notification_add_ssh_key_comment_empty(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = getUtility(ISSHKeySet).new(
                person, self.factory.makeSSHKeyText(comment="")
            )
            [email] = pop_notifications()
        self.assertEqual(
            "New SSH key added to your account.", email["Subject"]
        )
        self.assertThat(
            email.get_payload(),
            StartsWith(
                "An SSH key of type '%s' has been added "
                "to your account." % key.keytype.title
            ),
        )

    def test_does_not_send_notifications(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            keyset = getUtility(ISSHKeySet)
            keyset.new(
                person, self.factory.makeSSHKeyText(), send_notification=False
            )
            self.assertEqual([], pop_notifications())

    def test_getByPersonAndKeyText_retrieves_target_key(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person)
            keytext = key.getFullKeyText()

            results = getUtility(ISSHKeySet).getByPersonAndKeyText(
                person, keytext
            )
            self.assertEqual([key], list(results))

    def test_getByPersonAndKeyText_raises_on_invalid_key_type(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            invalid_keytext = "foo bar baz"
            keyset = getUtility(ISSHKeySet)
            self.assertRaises(
                SSHKeyAdditionError,
                keyset.getByPersonAndKeyText,
                person,
                invalid_keytext,
            )

    def test_getByPersonAndKeyText_raises_on_invalid_key_data(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            invalid_keytext = "glorp!"
            keyset = getUtility(ISSHKeySet)
            self.assertRaises(
                SSHKeyAdditionError,
                keyset.getByPersonAndKeyText,
                person,
                invalid_keytext,
            )

    def test_can_retrieve_keys_by_id(self):
        keyset = getUtility(ISSHKeySet)
        person = self.factory.makePerson()
        with person_logged_in(person):
            new_key = self.factory.makeSSHKey(person)

        retrieved_new_key = keyset.getByID(new_key.id)

        self.assertEqual(retrieved_new_key, new_key)

    def test_can_add_new_key(self):
        keyset = getUtility(ISSHKeySet)
        person = self.factory.makePerson()
        full_key = self.factory.makeSSHKeyText()
        keytype, keytext, comment = full_key.split(" ", 2)
        with person_logged_in(person):
            key = keyset.new(person, full_key)
            self.assertEqual([key], list(person.sshkeys))
            self.assertEqual(SSH_TEXT_TO_KEY_TYPE[keytype], key.keytype)
            self.assertEqual(keytext, key.keytext)
            self.assertEqual(comment, key.comment)

    def test_new_raises_KeyAdditionError_on_bad_key_data(self):
        person = self.factory.makePerson()
        keyset = getUtility(ISSHKeySet)
        self.assertRaisesWithContent(
            SSHKeyAdditionError,
            "Invalid SSH key data: 'thiskeyhasnospaces'",
            keyset.new,
            person,
            "thiskeyhasnospaces",
        )
        self.assertRaisesWithContent(
            SSHKeyAdditionError,
            "Invalid SSH key type: 'bad_key_type'",
            keyset.new,
            person,
            "bad_key_type keytext comment",
        )
        self.assertRaisesWithContent(
            SSHKeyAdditionError,
            "Invalid SSH key data: 'ssh-rsa badkeytext comment' "
            "(Incorrect padding)",
            keyset.new,
            person,
            "ssh-rsa badkeytext comment",
        )
        self.assertRaisesWithContent(
            SSHKeyAdditionError,
            "Invalid SSH key data: 'ssh-rsa asdfasdf comment' "
            "(unknown blob type: b'\\xc7_')",
            keyset.new,
            person,
            "ssh-rsa asdfasdf comment",
        )
        self.assertRaisesWithContent(
            SSHKeyAdditionError,
            "Invalid SSH key data: key type 'ssh-rsa' does not match key "
            "data type 'ssh-dss'",
            keyset.new,
            person,
            "ssh-rsa " + self.factory.makeSSHKeyText(key_type="ssh-dss")[8:],
        )
        self.assertRaisesWithContent(
            SSHKeyAdditionError,
            "Invalid SSH key data: 'None'",
            keyset.new,
            person,
            None,
        )

    def test_can_retrieve_keys_for_multiple_people(self):
        with admin_logged_in():
            person1 = self.factory.makePerson()
            person1_key1 = self.factory.makeSSHKey(person1)
            person1_key2 = self.factory.makeSSHKey(person1)
            person2 = self.factory.makePerson()
            person2_key1 = self.factory.makeSSHKey(person2)

        keyset = getUtility(ISSHKeySet)
        keys = keyset.getByPeople([person1, person2])
        self.assertEqual(3, keys.count())
        self.assertContentEqual(
            [person1_key1, person1_key2, person2_key1], keys
        )


class TestSSHKeyWebservice(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def test_getFullKeyText(self):
        person = self.factory.makePerson()
        with person_logged_in(person):
            key = self.factory.makeSSHKey(person, "ssh-rsa")
            key_url = api_url(key)
        expected = "ssh-rsa %s %s" % (key.keytext, key.comment)
        webservice = webservice_for_person(
            person,
            permission=OAuthPermission.READ_PUBLIC,
            default_api_version="devel",
        )
        response = webservice.named_get(key_url, "getFullKeyText")
        self.assertEqual(200, response.status)
        self.assertEqual(expected, response.jsonBody())
