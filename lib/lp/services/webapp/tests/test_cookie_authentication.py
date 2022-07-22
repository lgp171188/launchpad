# Copyright 2010-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test harness for running the cookie-authentication.rst tests."""

__all__ = []

import unittest

from lp.testing.browser import setUp
from lp.testing.layers import AppServerLayer
from lp.testing.systemdocs import LayeredDocFileSuite


def test_suite():
    suite = unittest.TestSuite()
    # We run this test on the AppServerLayer because it needs the cookie login
    # page (+login), which cannot be used through the normal testbrowser that
    # goes straight to zope's publication instead of making HTTP requests.
    suite.addTest(
        LayeredDocFileSuite(
            "cookie-authentication.rst", setUp=setUp, layer=AppServerLayer
        )
    )
    return suite
