# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for productreleasefinder.log."""

__author__ = "Scott James Remnant <scott@canonical.com>"

import logging
import unittest

from lp.registry.scripts.productreleasefinder.log import get_logger


class GetLogger(unittest.TestCase):
    def testLogger(self):
        """get_logger returns a Logger instance."""
        self.assertTrue(isinstance(get_logger("test"), logging.Logger))

    def testNoParent(self):
        """get_logger works if no parent is given."""
        self.assertEqual(get_logger("test").name, "test")

    def testRootParent(self):
        """get_logger works if root logger is given."""
        self.assertEqual(get_logger("test", logging.root).name, "test")

    def testNormalParent(self):
        """get_logger works if non-root logger is given."""
        parent = logging.getLogger("foo")
        self.assertEqual(get_logger("test", parent).name, "foo.test")

    def testDeepParent(self):
        """get_logger works if deep-level logger is given."""
        logging.getLogger("foo")
        parent2 = logging.getLogger("foo.bar")
        self.assertEqual(get_logger("test", parent2).name, "foo.bar.test")
