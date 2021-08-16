# Copyright 2019-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests memoizer decorators"""

from unittest import mock

from lp.services.memoizer import memoize
from lp.testing import TestCase


class TestMemoizeDecorator(TestCase):
    def test_vary_on_args(self):
        @memoize
        def do_expensive_thing(obj):
            return obj.some_method()

        heavy_obj = mock.Mock()

        do_expensive_thing(heavy_obj)
        self.assertEqual(1, heavy_obj.some_method.call_count)
        self.assertEqual(do_expensive_thing.memo, {
            (heavy_obj, ): heavy_obj.some_method.return_value})

        do_expensive_thing(heavy_obj)
        self.assertEqual(1, heavy_obj.some_method.call_count)
        self.assertEqual(do_expensive_thing.memo, {
            (heavy_obj, ): heavy_obj.some_method.return_value})

        another_heavy = mock.Mock()
        do_expensive_thing(another_heavy)
        self.assertEqual(1, heavy_obj.some_method.call_count)
        self.assertEqual(1, another_heavy.some_method.call_count)
        self.assertEqual(do_expensive_thing.memo, {
            (heavy_obj, ): heavy_obj.some_method.return_value,
            (another_heavy, ): another_heavy.some_method.return_value})

    def test_clean_memo(self):
        @memoize
        def do_expensive_thing(obj):
            return obj.some_method()

        heavy_obj = mock.Mock()
        do_expensive_thing(heavy_obj)
        self.assertEqual(1, heavy_obj.some_method.call_count)

        do_expensive_thing.clean_memo()
        self.assertEqual(do_expensive_thing.memo, {})
        do_expensive_thing(heavy_obj)
        self.assertEqual(2, heavy_obj.some_method.call_count)
