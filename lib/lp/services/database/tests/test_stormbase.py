# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""StormBase tests."""

import transaction
from storm.locals import Int
from zope.component import getUtility

from lp.services.database.interfaces import (
    DEFAULT_FLAVOR,
    MAIN_STORE,
    IStore,
    IStoreSelector,
)
from lp.services.database.stormbase import StormBase
from lp.testing import TestCase
from lp.testing.layers import ZopelessDatabaseLayer


class StormExample(StormBase):
    __storm_table__ = "StormExample"

    id = Int(primary=True)

    @classmethod
    def new(cls):
        example = cls()
        IStore(cls).add(example)
        return example


class TestStormBase(TestCase):
    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        self.store.execute("CREATE TABLE StormExample (id serial PRIMARY KEY)")

    def test_eq_ne(self):
        examples = [StormExample.new() for _ in range(3)]
        transaction.commit()
        for i in range(len(examples)):
            for j in range(len(examples)):
                if i == j:
                    self.assertEqual(examples[i], examples[j])
                else:
                    self.assertNotEqual(examples[i], examples[j])

    def test_ne_removed(self):
        # A removed object is not equal to a newly-created object, even
        # though we no longer know the removed object's primary key.
        example = StormExample.new()
        self.store.remove(example)
        self.store.flush()
        new_example = StormExample.new()
        self.assertNotEqual(example, new_example)
