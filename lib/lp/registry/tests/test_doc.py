# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import logging
import os

from lp.services.testing import build_doctest_suite, build_test_suite
from lp.testing.layers import (
    DatabaseFunctionalLayer,
    DatabaseLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
)
from lp.testing.systemdocs import LayeredDocFileSuite, setUp, tearDown

here = os.path.dirname(os.path.realpath(__file__))


def peopleKarmaTearDown(test):
    """Restore the database after testing karma."""
    # We can't detect db changes made by the subprocess (yet).
    DatabaseLayer.force_dirty_database()
    tearDown(test)


special = {
    "distribution-mirror.rst": LayeredDocFileSuite(
        "../doc/distribution-mirror.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "person-karma.rst": LayeredDocFileSuite(
        "../doc/person-karma.rst",
        setUp=setUp,
        tearDown=peopleKarmaTearDown,
        layer=LaunchpadFunctionalLayer,
        stdout_logging_level=logging.WARNING,
    ),
    "product.rst": LayeredDocFileSuite(
        "../doc/product.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "private-team-roles.rst": LayeredDocFileSuite(
        "../doc/private-team-roles.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "productrelease.rst": LayeredDocFileSuite(
        "../doc/productrelease.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "productrelease-file-download.rst": LayeredDocFileSuite(
        "../doc/productrelease-file-download.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "standing.rst": LayeredDocFileSuite(
        "../doc/standing.rst",
        layer=LaunchpadZopelessLayer,
        setUp=setUp,
        tearDown=tearDown,
    ),
    "karmacache.rst": LayeredDocFileSuite(
        "../doc/karmacache.rst",
        layer=LaunchpadZopelessLayer,
        setUp=setUp,
        tearDown=tearDown,
    ),
    "sourcepackage.rst": LayeredDocFileSuite(
        "../doc/sourcepackage.rst",
        layer=LaunchpadFunctionalLayer,
        setUp=setUp,
        tearDown=tearDown,
    ),
    "distribution-sourcepackage.rst": LayeredDocFileSuite(
        "../doc/distribution-sourcepackage.rst",
        layer=LaunchpadZopelessLayer,
        setUp=setUp,
        tearDown=tearDown,
    ),
}


def test_suite():
    suite = build_test_suite(here, special, layer=DatabaseFunctionalLayer)
    launchpadlib_path = os.path.join(os.path.pardir, "doc", "launchpadlib")
    lplib_suite = build_doctest_suite(
        here, launchpadlib_path, layer=DatabaseFunctionalLayer
    )
    suite.addTest(lplib_suite)
    return suite
