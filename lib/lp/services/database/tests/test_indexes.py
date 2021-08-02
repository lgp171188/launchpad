# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test database index correctness."""

__metaclass__ = type

from testscenarios import (
    load_tests_apply_scenarios,
    WithScenarios,
    )

from lp.services.database.postgresql import (
    listIndexes,
    listReferences,
    )
from lp.services.database.sqlbase import cursor
from lp.testing import TestCase
from lp.testing.layers import ZopelessDatabaseLayer


class TestIndexedReferences(WithScenarios, TestCase):
    """Test that all references to certain tables are indexed.

    Without this, we may run into problems deleting rows from those tables.
    """

    layer = ZopelessDatabaseLayer

    scenarios = [
        ("Archive", {"table": "archive", "column": "id"}),
        ("Job", {"table": "job", "column": "id"}),
        ]

    def test_references_are_indexed(self):
        cur = cursor()
        self.addCleanup(cur.close)
        references = list(
            listReferences(cur, self.table, self.column, indirect=False))
        missing = []
        for src_tab, src_col, _, _, _, _ in references:
            for index in listIndexes(cur, src_tab, src_col):
                if index[0] == src_col:
                    break
            else:
                missing.append((src_tab, src_col))
        self.assertEqual([], missing)


load_tests = load_tests_apply_scenarios
