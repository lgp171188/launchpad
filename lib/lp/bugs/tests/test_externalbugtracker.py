# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test related to ExternalBugtracker test infrastructure."""

import unittest
from typing import List

from lp.testing.layers import LaunchpadFunctionalLayer
from lp.testing.systemdocs import LayeredDocFileSuite, setUp, tearDown

__all__: List[str] = []


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(
        LayeredDocFileSuite(
            "bugzilla-xmlrpc-transport.rst",
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
        )
    )
    suite.addTest(
        LayeredDocFileSuite(
            "bugzilla-api-xmlrpc-transport.rst",
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
        )
    )
    suite.addTest(
        LayeredDocFileSuite(
            "trac-xmlrpc-transport.rst",
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
        )
    )
    suite.addTest(
        LayeredDocFileSuite(
            "externalbugtracker-xmlrpc-transport.rst",
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
        )
    )

    return suite
