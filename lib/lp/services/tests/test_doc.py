# Copyright 2010-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import os

from lp.services.testing import build_test_suite
from lp.testing.layers import BaseLayer
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    )


here = os.path.dirname(os.path.realpath(__file__))


special = {
    'limitedlist.txt': LayeredDocFileSuite(
        '../doc/limitedlist.txt',
        setUp=lambda test: setGlobs(test, future=True),
        layer=BaseLayer),
    'propertycache.txt': LayeredDocFileSuite(
        '../doc/propertycache.txt',
        setUp=lambda test: setGlobs(test, future=True),
        layer=BaseLayer),
    }


def test_suite():
    return build_test_suite(
        here, special, setUp=lambda test: setUp(test, future=True))
