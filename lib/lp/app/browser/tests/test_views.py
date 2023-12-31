# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Run the view tests."""

import logging
import os

from lp.services.features.testing import FeatureFixture
from lp.services.testing import build_test_suite
from lp.testing.layers import BingLaunchpadFunctionalLayer, PageTestLayer
from lp.testing.systemdocs import LayeredDocFileSuite, setUp, tearDown

here = os.path.dirname(os.path.realpath(__file__))
bing_flag = FeatureFixture({"sitesearch.engine.name": "bing"})


def setUp_bing(test):
    setUp(test)
    bing_flag.setUp()


def tearDown_bing(test):
    bing_flag.cleanUp()
    tearDown(test)


# The default layer of view tests is the DatabaseFunctionalLayer. Tests
# that require something special like the librarian must run on a layer
# that sets those services up.
special = {
    "launchpad-search-pages.rst(Bing)": LayeredDocFileSuite(
        "../doc/launchpad-search-pages.rst",
        id_extensions=["launchpad-search-pages.rst(Bing)"],
        setUp=setUp_bing,
        tearDown=tearDown_bing,
        layer=BingLaunchpadFunctionalLayer,
        stdout_logging_level=logging.WARNING,
    ),
    # Run these doctests again with the default search engine.
    "launchpad-search-pages.rst": LayeredDocFileSuite(
        "../doc/launchpad-search-pages.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=PageTestLayer,
        stdout_logging_level=logging.WARNING,
    ),
}


def test_suite():
    return build_test_suite(here, special)
