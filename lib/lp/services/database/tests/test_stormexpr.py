# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test custom Storm expressions."""

from types import SimpleNamespace

from storm.expr import Select
from zope.component import getUtility

from lp.services.database.interfaces import (
    MAIN_STORE,
    PRIMARY_FLAVOR,
    IStoreSelector,
)
from lp.services.database.sqlbase import convert_storm_clause_to_string
from lp.services.database.stormexpr import WithMaterialized
from lp.testing import TestCase
from lp.testing.layers import BaseLayer, ZopelessDatabaseLayer


class TestWithMaterialized(TestCase):
    """Test how `WithMaterialized` works with different PostgreSQL versions.

    We use a fake store for these tests so that we can control exactly what
    PostgreSQL version the query compiler sees.
    """

    layer = BaseLayer

    def makeFakeStore(self, version):
        # Return a fake `storm.store.Store` that's just enough to satisfy
        # the Storm query compiler for `WithMaterialized`.
        return SimpleNamespace(_database=SimpleNamespace(_version=version))

    def test_postgresql_10(self):
        query = WithMaterialized("test", self.makeFakeStore(100019), Select(1))
        self.assertEqual(
            "test AS (SELECT 1)", convert_storm_clause_to_string(query)
        )

    def test_postgresql_12(self):
        query = WithMaterialized("test", self.makeFakeStore(120011), Select(1))
        self.assertEqual(
            "test AS MATERIALIZED (SELECT 1)",
            convert_storm_clause_to_string(query),
        )


class TestWithMaterializedRealDatabase(TestCase):
    """Test how `WithMaterialized` works with a real database."""

    layer = ZopelessDatabaseLayer

    def test_current_store(self):
        store = getUtility(IStoreSelector).get(MAIN_STORE, PRIMARY_FLAVOR)
        query = WithMaterialized("test", store, Select(1))
        self.assertIn(
            convert_storm_clause_to_string(query),
            [
                # PostgreSQL < 12
                "test AS (SELECT 1)",
                # PostgreSQL >= 12
                "test AS MATERIALIZED (SELECT 1)",
            ],
        )
