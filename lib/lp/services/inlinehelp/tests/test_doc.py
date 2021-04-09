# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests.
"""

from __future__ import absolute_import, print_function, unicode_literals

from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    )


def test_suite():
    return LayeredDocFileSuite(
        '../README.txt', setUp=lambda test: setGlobs(test, future=True))
