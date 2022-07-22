# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import unittest
from doctest import ELLIPSIS, DocTestSuite

import lp.services.encoding
from lp.services.encoding import wsgi_native_string
from lp.testing import TestCase


class TestWSGINativeString(TestCase):
    def test_not_bytes_or_unicode(self):
        self.assertRaises(TypeError, wsgi_native_string, object())

    def test_bytes_iso_8859_1(self):
        self.assertEqual("foo\xfe", wsgi_native_string(b"foo\xfe"))

    def test_unicode_iso_8859_1(self):
        self.assertEqual("foo\xfe", wsgi_native_string("foo\xfe"))

    def test_unicode_not_iso_8859_1(self):
        self.assertRaises(UnicodeEncodeError, wsgi_native_string, "foo\u2014")


def test_suite():
    return unittest.TestSuite(
        (
            unittest.TestLoader().loadTestsFromName(__name__),
            DocTestSuite(lp.services.encoding, optionflags=ELLIPSIS),
        )
    )
