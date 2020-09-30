# Copyright 2011-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import os

from zope.testing.cleanup import cleanUp

from lp.services.testing import build_test_suite
from lp.testing import browser
from lp.testing.layers import (
    AppServerLayer,
    LaunchpadFunctionalLayer,
    )
from lp.testing.pages import setUpGlobs
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    )


here = os.path.dirname(os.path.realpath(__file__))


def layerlessTearDown(test):
    """Clean up any Zope registrations."""
    cleanUp()


special = {
    'webservice-configuration.txt': LayeredDocFileSuite(
        '../doc/webservice-configuration.txt',
        setUp=lambda test: setGlobs(test, future=True),
        tearDown=layerlessTearDown,
        layer=None),
    # This test is actually run twice to prove that the AppServerLayer
    # properly isolates the database between tests.
    'launchpadlib.txt': LayeredDocFileSuite(
        '../doc/launchpadlib.txt',
        layer=AppServerLayer, setUp=browser.setUp),
    'launchpadlib.txt-2': LayeredDocFileSuite(
        '../doc/launchpadlib.txt',
        id_extensions=['launchpadlib.txt-2'],
        layer=AppServerLayer, setUp=browser.setUp),
    }


def test_suite():
    return build_test_suite(
        here, special, setUp=lambda test: setUp(test, future=True),
        pageTestsSetUp=lambda test: setUpGlobs(test, future=True),
        layer=LaunchpadFunctionalLayer)
