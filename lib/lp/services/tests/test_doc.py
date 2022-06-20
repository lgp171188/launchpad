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
    )


here = os.path.dirname(os.path.realpath(__file__))


special = {
    'limitedlist.rst': LayeredDocFileSuite(
        '../doc/limitedlist.rst',
        setUp=setGlobs,
        layer=BaseLayer),
    'propertycache.rst': LayeredDocFileSuite(
        '../doc/propertycache.rst',
        setUp=setGlobs,
        layer=BaseLayer),
    }


def test_suite():
    return build_test_suite(here, special)
