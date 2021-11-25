# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""MemcacheFixture tests."""

from pymemcache.exceptions import MemcacheIllegalInputError

from lp.services.memcache.testing import MemcacheFixture
from lp.testing import TestCase
from lp.testing.layers import BaseLayer


class TestMemcacheFixture(TestCase):
    layer = BaseLayer

    def setUp(self):
        super().setUp()
        self.client = self.useFixture(MemcacheFixture())

    def test_set_expire_requires_integer(self):
        self.assertRaises(
            MemcacheIllegalInputError,
            self.client.set, "key", "value", expire=0.5)
