# Copyright 2025 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test text searching functionality."""

from testtools.matchers import Equals, MatchesAny
from zope.component import getUtility

from lp.services.database.interfaces import (
    DEFAULT_FLAVOR,
    MAIN_STORE,
    IStoreSelector,
)
from lp.services.helpers import backslashreplace
from lp.testing import TestCaseWithFactory
from lp.testing.layers import DatabaseFunctionalLayer


def get_store():
    return getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)


def ftq(query):
    store = get_store()
    try:
        result = store.execute("SELECT _ftq(%s), ftq(%s)", (query, query))
        uncompiled, compiled = result.get_one()
    except Exception:
        store.rollback()
        raise
    if uncompiled is not None:
        uncompiled = backslashreplace(uncompiled)
        uncompiled = uncompiled.replace(" ", "")
    if compiled is not None:
        compiled = backslashreplace(compiled)
    result = "%s <=> %s" % (uncompiled, compiled)
    return result


def search(text_to_search, search_phrase):
    store = get_store()
    result = store.execute("SELECT to_tsvector(%s)", (text_to_search,))
    ts_vector = result.get_all()[0][0]
    result = store.execute("SELECT ftq(%s)", (search_phrase,))
    ts_query = result.get_all()[0][0]
    result = store.execute(
        "SELECT to_tsvector(%s) @@ ftq(%s)",
        (text_to_search, search_phrase),
    )
    match = result.get_all()[0][0]
    return "FTI data: %s query: %s match: %s" % (
        ts_vector,
        ts_query,
        str(match),
    )


def search_same(text):
    return search(text, text)


class TestTextSearchingFTI(TestCaseWithFactory):
    layer = DatabaseFunctionalLayer

    def assert_result_matches(self, result, expected, placeholders_list):
        matchers = [
            Equals(expected.format(*placeholders))
            for placeholders in placeholders_list
        ]
        self.assertThat(
            result,
            MatchesAny(
                *matchers,
            ),
        )

    def test_hyphens_surrounded_by_two_words_retained(self):
        # Hyphens surrounded by two words are retained. This reflects the way
        # how to_tsquery() and to_tsvector() handle such strings.
        result = search_same("foo-bar")
        expected = (
            "FTI data: 'bar':3 'foo':2 'foo-bar':1 query: "
            "'foo-bar' {} 'foo' {} 'bar' match: True"
        )
        self.assert_result_matches(result, expected, (["&"] * 3, ["<->"] * 3))

    def test_hyphen_surrounded_by_numbers_sign_of_right_number(self):
        # A '-' surrounded by numbers is treated as the sign of the
        # right-hand number.
        result = search_same("123-456")
        expected = (
            "FTI data: '-456':2 '123':1 query: '123' {} '-456' match: True"
        )
        self.assert_result_matches(result, expected, (["&"], ["<->"]))

    def test_consistent_handling_of_punctuation(self):
        # Punctuation is handled consistently. If a string containing
        # punctuation appears in an FTI, it can also be passed to ftq(),
        # and a search for this string finds the indexed text.
        result = search_same("foo'bar")
        expected = (
            "FTI data: 'bar':2 'foo':1 query: 'foo' {} 'bar' match: True"
        )
        placeholders = (["&"], ["<->"])
        punctuations = "'\"#$%*+,:;<=>?@[\\]^`{}`"
        for symbol in punctuations:
            result = search_same(f"foo{symbol}bar")
            self.assert_result_matches(
                result,
                expected,
                placeholders,
            )
        result = search_same("foo.bar")
        expected = "FTI data: 'foo.bar':1 query: 'foo.bar' match: True"
        self.assert_result_matches(
            result,
            expected,
            ([], []),
        )

    def test_unicode_characters_in_the_wrong_place(self):
        # Bug #44913 - Unicode characters in the wrong place.
        result = search_same("abc-a\N{LATIN SMALL LETTER C WITH CEDILLA}")
        expected = (
            "FTI data: 'abc':2 'abc-aç':1 'aç':3 query: 'abc-aç' {} 'abc' "
            "{} 'aç' match: True"
        )
        self.assert_result_matches(
            result,
            expected,
            (["&"] * 2, ["<->"] * 2),
        )

    def test_cut_and_past_of_smart_quotes(self):
        # Cut & Paste of 'Smart' quotes. Note that the quotation mark is
        # retained in the FTI.
        result = search_same("a-a\N{RIGHT DOUBLE QUOTATION MARK}")
        expected = (
            "FTI data: 'a-a”':1 'a”':3 query: 'a-a”' {} 'a”' match: True"
        )
        self.assert_result_matches(
            result,
            expected,
            (["&"], ["<2>"]),
        )
        result = search_same(
            "\N{LEFT SINGLE QUOTATION MARK}a.a"
            "\N{RIGHT SINGLE QUOTATION MARK}"
        )
        expected = "FTI data: 'a’':2 '‘a':1 query: '‘a' {} 'a’' match: True"
        self.assert_result_matches(result, expected, (["&"], ["<->"]))

    def test_bug_160236_ftq(self):
        # filing a bug with summary "a&& a-a" oopses with sql syntax error
        result = ftq("foo AND AND bar-baz")
        expected = "foo&bar-baz <=> 'foo' {} 'bar-baz' {} 'bar' {} 'baz'"
        self.assert_result_matches(
            result, expected, (["&"] * 3, ["&", "<->", "<->"])
        )
