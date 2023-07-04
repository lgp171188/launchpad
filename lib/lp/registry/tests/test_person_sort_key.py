# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the person_sort_key stored procedure and its in-app twin."""

from lp.registry.model.person import person_sort_key
from lp.testing import TestCase
from lp.testing.layers import DatabaseLayer


class TestPersonSortKeyBase:
    def test_composition(self):
        # person_sort_key returns the concatenation of the display name and
        # the name for use in sorting.
        self.assertSortKeysEqual(
            "Stuart Bishop", "stub", "stuart bishop, stub"
        )

    def test_whitespace(self):
        # Leading and trailing whitespace is removed.
        self.assertSortKeysEqual(
            " Stuart Bishop\t", "stub", "stuart bishop, stub"
        )

    def test_valid_name_is_assumed(self):
        # 'name' is assumed to be lowercase and not containing anything we
        # don't want. This should never happen as the valid_name database
        # constraint should prevent it.
        self.assertSortKeysEqual(
            "Stuart Bishop", " stub42!!!", "stuart bishop,  stub42!!!"
        )

    def test_strip_all_but_letters_and_whitespace(self):
        # Everything except for letters and whitespace is stripped.
        self.assertSortKeysEqual(
            "-= Mass1v3 T0SSA =-", "tossa", "massv tssa, tossa"
        )

    def test_non_ascii_allowed(self):
        # Non ASCII letters are currently allowed. Eventually they should
        # become transliterated to ASCII but we don't do this yet.
        self.assertSortKeysEqual(
            "Bj\N{LATIN SMALL LETTER O WITH DIAERESIS}rn",
            "bjorn",
            "bj\xf6rn, bjorn",
        )

    def test_unicode_case_conversion(self):
        # Case conversion is handled correctly using Unicode.
        self.assertSortKeysEqual(
            "Bj\N{LATIN CAPITAL LETTER O WITH DIAERESIS}rn",
            "bjorn",
            "bj\xf6rn, bjorn",
        )  # Lower case o with diaeresis


class TestPersonSortKeyInDatabase(TestPersonSortKeyBase, TestCase):
    layer = DatabaseLayer

    def setUp(self):
        super().setUp()
        self.con = self.layer.connect()
        self.cur = self.con.cursor()

    def tearDown(self):
        super().tearDown()
        self.con.close()

    def get_person_sort_key(self, display_name, name):
        """Calls the `person_sort_key` stored procedure.

        Note that although the stored procedure returns a UTF-8 encoded
        string, our database driver converts that to Unicode for us.
        """
        self.cur.execute(
            "SELECT person_sort_key(%s, %s)", (display_name, name)
        )
        return self.cur.fetchone()[0]

    def assertSortKeysEqual(self, display_name, name, expected):
        # The sort key from the database matches the expected sort key.
        self.assertEqual(
            expected, self.get_person_sort_key(display_name, name)
        )


class PersonNames:
    """A fake with enough information for `person_sort_key`."""

    def __init__(self, display_name, name):
        self.display_name = display_name
        self.name = name


class TestPersonSortKeyInProcess(TestPersonSortKeyBase, TestCase):
    def assertSortKeysEqual(self, display_name, name, expected):
        # The sort key calculated in-process matches the expected sort key.
        self.assertEqual(
            expected, person_sort_key(PersonNames(display_name, name))
        )
