# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the person_sort_key stored procedure."""

from zope.component import getUtility
from zope.interface.verify import verifyObject

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.registry.interfaces.nameblocklist import (
    INameBlocklist,
    INameBlocklistSet,
)
from lp.services.database.interfaces import IStore
from lp.services.webapp.authorization import check_permission
from lp.testing import ANONYMOUS, TestCaseWithFactory, login, login_celebrity
from lp.testing.layers import DatabaseFunctionalLayer, ZopelessDatabaseLayer


class TestNameBlocklist(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.name_blocklist_set = getUtility(INameBlocklistSet)
        self.caret_foo_exp = self.name_blocklist_set.create("^foo")
        self.foo_exp = self.name_blocklist_set.create("foo")
        self.verbose_exp = self.name_blocklist_set.create("v e r b o s e")
        team = self.factory.makeTeam()
        self.admin_exp = self.name_blocklist_set.create("fnord", admin=team)
        self.store = IStore(self.foo_exp)
        self.store.flush()

    def name_blocklist_match(self, name, user_id=None):
        """Return the result of the name_blocklist_match stored procedure."""
        user_id = user_id or 0
        result = self.store.execute(
            "SELECT name_blocklist_match(%s, %s)", (name, user_id)
        )
        return result.get_one()[0]

    def is_blocklisted_name(self, name, user_id=None):
        """Return the result of the is_blocklisted_name stored procedure."""
        user_id = user_id or 0
        result = self.store.execute(
            "SELECT is_blocklisted_name(%s, %s)", (name, user_id)
        )
        blocklisted = result.get_one()[0]
        self.assertIsNotNone(blocklisted, "is_blocklisted_name returned NULL")
        return bool(blocklisted)

    def test_name_blocklist_match(self):
        # A name that is not blocklisted returns NULL/None
        self.assertIsNone(self.name_blocklist_match("bar"))

        # A name that is blocklisted returns the id of the row in the
        # NameBlocklist table that matched. Rows are tried in order, and the
        # first match is returned.
        self.assertEqual(
            self.name_blocklist_match("foobar"), self.caret_foo_exp.id
        )
        self.assertEqual(self.name_blocklist_match("barfoo"), self.foo_exp.id)

    def test_name_blocklist_match_admin_does_not_match(self):
        # A user in the expresssion's admin team is exempt from the
        # blocklisted name restriction.
        user = self.admin_exp.admin.teamowner
        self.assertEqual(None, self.name_blocklist_match("fnord", user.id))

    def test_name_blocklist_match_launchpad_admin_can_change(self):
        # A Launchpad admin is exempt from any blocklisted name restriction
        # that has an admin.
        user = self.factory.makePerson()
        admins = getUtility(ILaunchpadCelebrities).admin
        admins.addMember(user, user)
        self.assertEqual(None, self.name_blocklist_match("fnord", user.id))

    def test_name_blocklist_match_launchpad_admin_cannot_change(self):
        # A Launchpad admin cannot override blocklisted names without admins.
        user = self.factory.makePerson()
        admins = getUtility(ILaunchpadCelebrities).admin
        admins.addMember(user, user)
        self.assertEqual(
            self.foo_exp.id, self.name_blocklist_match("barfoo", user.id)
        )

    def test_name_blocklist_match_cache(self):
        # If the blocklist is changed in the DB, these changes are noticed.
        # This test is needed because the stored procedure keeps a cache
        # of the compiled regular expressions.
        self.assertEqual(
            self.name_blocklist_match("foobar"), self.caret_foo_exp.id
        )
        self.caret_foo_exp.regexp = "nomatch"
        self.assertEqual(self.name_blocklist_match("foobar"), self.foo_exp.id)
        self.foo_exp.regexp = "nomatch2"
        self.assertIsNone(self.name_blocklist_match("foobar"))

    def test_is_blocklisted_name(self):
        # is_blocklisted_name() is just a wrapper around name_blocklist_match
        # that is friendlier to use in a boolean context.
        self.assertFalse(self.is_blocklisted_name("bar"))
        self.assertTrue(self.is_blocklisted_name("foo"))
        self.caret_foo_exp.regexp = "bar"
        self.foo_exp.regexp = "bar2"
        self.assertFalse(self.is_blocklisted_name("foo"))

    def test_is_blocklisted_name_admin_false(self):
        # Users in the expression's admin team are will return False.
        user = self.admin_exp.admin.teamowner
        self.assertFalse(self.is_blocklisted_name("fnord", user.id))

    def test_case_insensitive(self):
        self.assertTrue(self.is_blocklisted_name("Foo"))

    def test_verbose(self):
        # Testing the VERBOSE flag is used when compiling the regexp
        self.assertTrue(self.is_blocklisted_name("verbose"))


class TestNameBlocklistSet(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def setUp(self):
        super().setUp()
        login_celebrity("registry_experts")
        self.name_blocklist_set = getUtility(INameBlocklistSet)

    def test_create_with_one_arg(self):
        # Test NameBlocklistSet.create(regexp).
        name_blocklist = self.name_blocklist_set.create("foo")
        self.assertTrue(verifyObject(INameBlocklist, name_blocklist))
        self.assertEqual("foo", name_blocklist.regexp)
        self.assertIs(None, name_blocklist.comment)

    def test_create_with_two_args(self):
        # Test NameBlocklistSet.create(regexp, comment).
        name_blocklist = self.name_blocklist_set.create("foo", "bar")
        self.assertTrue(verifyObject(INameBlocklist, name_blocklist))
        self.assertEqual("foo", name_blocklist.regexp)
        self.assertEqual("bar", name_blocklist.comment)

    def test_create_with_three_args(self):
        # Test NameBlocklistSet.create(regexp, comment, admin).
        team = self.factory.makeTeam()
        name_blocklist = self.name_blocklist_set.create("foo", "bar", team)
        self.assertTrue(verifyObject(INameBlocklist, name_blocklist))
        self.assertEqual("foo", name_blocklist.regexp)
        self.assertEqual("bar", name_blocklist.comment)
        self.assertEqual(team, name_blocklist.admin)

    def test_get_int(self):
        # Test NameBlocklistSet.get() with int id.
        name_blocklist = self.name_blocklist_set.create("foo", "bar")
        store = IStore(name_blocklist)
        store.flush()
        retrieved = self.name_blocklist_set.get(name_blocklist.id)
        self.assertEqual(name_blocklist, retrieved)

    def test_get_string(self):
        # Test NameBlocklistSet.get() with string id.
        name_blocklist = self.name_blocklist_set.create("foo", "bar")
        store = IStore(name_blocklist)
        store.flush()
        retrieved = self.name_blocklist_set.get(str(name_blocklist.id))
        self.assertEqual(name_blocklist, retrieved)

    def test_get_returns_None_instead_of_ValueError(self):
        # Test that NameBlocklistSet.get() will return None instead of
        # raising a ValueError when it tries to cast the id to an int,
        # so that traversing an invalid url causes a Not Found error
        # instead of an error that is recorded as an oops.
        self.assertIs(None, self.name_blocklist_set.get("asdf"))

    def test_getAll(self):
        # Test NameBlocklistSet.getAll().
        result = [
            (item.regexp, item.comment)
            for item in self.name_blocklist_set.getAll()
        ]
        expected = [
            ("^admin", None),
            ("blocklist", "For testing purposes"),
        ]
        self.assertEqual(expected, result)

    def test_NameBlocklistSet_permissions(self):
        # Verify that non-registry-experts do not have permission to
        # access the NameBlocklistSet.
        self.assertTrue(
            check_permission("launchpad.View", self.name_blocklist_set)
        )
        self.assertTrue(
            check_permission("launchpad.Edit", self.name_blocklist_set)
        )
        login(ANONYMOUS)
        self.assertFalse(
            check_permission("launchpad.View", self.name_blocklist_set)
        )
        self.assertFalse(
            check_permission("launchpad.Edit", self.name_blocklist_set)
        )

    def test_NameBlocklist_permissions(self):
        # Verify that non-registry-experts do not have permission to
        # access the NameBlocklist.
        name_blocklist = self.name_blocklist_set.create("foo")
        self.assertTrue(check_permission("launchpad.View", name_blocklist))
        self.assertTrue(check_permission("launchpad.Edit", name_blocklist))
        login(ANONYMOUS)
        self.assertFalse(check_permission("launchpad.View", name_blocklist))
        self.assertFalse(check_permission("launchpad.Edit", name_blocklist))
