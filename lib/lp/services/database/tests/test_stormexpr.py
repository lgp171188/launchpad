# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test custom Storm expressions."""

from types import MappingProxyType, SimpleNamespace

from storm.exceptions import NoneError
from storm.expr import Column, Select
from storm.info import get_obj_info
from zope.component import getUtility

from lp.services.database.interfaces import (
    MAIN_STORE,
    PRIMARY_FLAVOR,
    IStoreSelector,
)
from lp.services.database.sqlbase import convert_storm_clause_to_string
from lp.services.database.stormexpr import (
    ImmutablePgJSON,
    ImmutablePgJSONVariable,
    WithMaterialized,
)
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


class TestImmutablePgJSON(TestCase):
    layer = BaseLayer

    def setUpProperty(self, *args, **kwargs):
        class Class:
            __storm_table__ = "mytable"
            prop1 = ImmutablePgJSON("column1", *args, primary=True, **kwargs)

        class Subclass(Class):
            pass

        self.Class = Class
        self.Subclass = Subclass
        self.obj = Subclass()
        self.obj_info = get_obj_info(self.obj)
        self.column1 = self.Subclass.prop1
        self.variable1 = self.obj_info.variables[self.column1]

    def test_basic(self):
        self.setUpProperty(default_factory=dict, allow_none=False)
        self.assertIsInstance(self.column1, Column)
        self.assertEqual("column1", self.column1.name)
        self.assertEqual(self.Subclass, self.column1.table)
        self.assertIsInstance(self.variable1, ImmutablePgJSONVariable)

    def test_immutable_default(self):
        self.setUpProperty(default_factory=dict, allow_none=False)
        self.assertIsInstance(self.obj.prop1, MappingProxyType)
        self.assertEqual({}, self.obj.prop1)
        self.assertEqual("{}", self.variable1.get(to_db=True))
        self.assertRaises(NoneError, setattr, self.obj, "prop1", None)
        self.assertRaises(
            AttributeError, getattr, self.obj.prop1, "__setitem__"
        )

    def test_immutable_dict(self):
        self.setUpProperty()
        self.variable1.set({"a": {"b": []}}, from_db=True)
        self.assertIsInstance(self.obj.prop1, MappingProxyType)
        self.assertIsInstance(self.obj.prop1["a"], MappingProxyType)
        self.assertIsInstance(self.obj.prop1["a"]["b"], tuple)
        self.assertEqual({"a": {"b": ()}}, self.obj.prop1)
        self.assertEqual('{"a": {"b": []}}', self.variable1.get(to_db=True))
        self.assertRaises(
            AttributeError, getattr, self.obj.prop1, "__setitem__"
        )
        self.obj.prop1 = {"a": 1}
        self.assertIsInstance(self.obj.prop1, MappingProxyType)
        self.assertEqual({"a": 1}, self.obj.prop1)
        self.assertEqual('{"a": 1}', self.variable1.get(to_db=True))

    def test_immutable_list(self):
        self.setUpProperty()
        self.variable1.set([], from_db=True)
        self.assertIsInstance(self.obj.prop1, tuple)
        self.assertEqual((), self.obj.prop1)
        self.assertEqual("[]", self.variable1.get(to_db=True))
        self.obj.prop1 = ["a"]
        self.assertIsInstance(self.obj.prop1, tuple)
        self.assertEqual(("a",), self.obj.prop1)
        self.assertEqual('["a"]', self.variable1.get(to_db=True))
