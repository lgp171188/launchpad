# Copyright 2015-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run doctests and pagetests."""

import os

from lp.services.testing import build_test_suite
from lp.testing.layers import (
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
    )
from lp.testing.pages import setUpGlobs
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setUp,
    tearDown,
    )


here = os.path.dirname(os.path.realpath(__file__))


special = {
    'builder.txt': LayeredDocFileSuite(
        '../doc/builder.txt',
        setUp=lambda test: setUp(test, future=True), tearDown=tearDown,
        layer=LaunchpadFunctionalLayer),
    'buildqueue.txt': LayeredDocFileSuite(
        '../doc/buildqueue.txt',
        setUp=lambda test: setUp(test, future=True), tearDown=tearDown,
        layer=LaunchpadFunctionalLayer),
    }


def test_suite():
    return build_test_suite(
        here, special, layer=LaunchpadZopelessLayer,
        setUp=lambda test: setUp(test, future=True),
        pageTestsSetUp=lambda test: setUpGlobs(test, future=True))
