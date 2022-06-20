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
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    )


here = os.path.dirname(os.path.realpath(__file__))


def layerlessTearDown(test):
    """Clean up any Zope registrations."""
    cleanUp()


special = {
    'webservice-configuration.rst': LayeredDocFileSuite(
        '../doc/webservice-configuration.rst',
        setUp=setGlobs, tearDown=layerlessTearDown,
        layer=None),
    # This test is actually run twice to prove that the AppServerLayer
    # properly isolates the database between tests.
    'launchpadlib.rst': LayeredDocFileSuite(
        '../doc/launchpadlib.rst',
        layer=AppServerLayer, setUp=browser.setUp),
    'launchpadlib.rst-2': LayeredDocFileSuite(
        '../doc/launchpadlib.rst',
        id_extensions=['launchpadlib.rst-2'],
        layer=AppServerLayer, setUp=browser.setUp),
    }


def test_suite():
    return build_test_suite(here, special, layer=LaunchpadFunctionalLayer)
