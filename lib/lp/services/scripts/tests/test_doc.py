# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import os

from lp.services.testing import build_test_suite
from lp.testing.layers import DatabaseLayer, LaunchpadZopelessLayer
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    tearDown,
)

here = os.path.dirname(os.path.realpath(__file__))

special = {
    "script-monitoring.rst": LayeredDocFileSuite(
        "../doc/script-monitoring.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "launchpad-scripts.rst": LayeredDocFileSuite(
        "../doc/launchpad-scripts.rst",
        setUp=setGlobs,
        layer=DatabaseLayer,
    ),
}


def test_suite():
    return build_test_suite(here, special)
