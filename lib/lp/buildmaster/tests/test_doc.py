# Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run doctests and pagetests."""

import os

from lp.services.testing import build_test_suite
from lp.testing.layers import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.systemdocs import LayeredDocFileSuite, setUp, tearDown

here = os.path.dirname(os.path.realpath(__file__))


special = {
    "builder.rst": LayeredDocFileSuite(
        "../doc/builder.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "buildqueue.rst": LayeredDocFileSuite(
        "../doc/buildqueue.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
}


def test_suite():
    return build_test_suite(here, special, layer=LaunchpadZopelessLayer)
