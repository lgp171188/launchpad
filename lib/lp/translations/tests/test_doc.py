# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import logging
import os
import unittest

from lp.testing.layers import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.pages import PageTestSuite
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    tearDown,
)

here = os.path.dirname(os.path.realpath(__file__))


special = {
    "poexport-queue.rst": LayeredDocFileSuite(
        "../doc/poexport-queue.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "rosetta-karma.rst": LayeredDocFileSuite(
        "../doc/rosetta-karma.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "sourcepackagerelease-translations.rst": LayeredDocFileSuite(
        "../doc/sourcepackagerelease-translations.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "translationimportqueue.rst": LayeredDocFileSuite(
        "../doc/translationimportqueue.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "translationmessage-destroy.rst": LayeredDocFileSuite(
        "../doc/translationmessage-destroy.rst",
        setUp=setGlobs,
        layer=LaunchpadZopelessLayer,
    ),
    "translations-export-to-branch.rst": LayeredDocFileSuite(
        "../doc/translations-export-to-branch.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "translationsoverview.rst": LayeredDocFileSuite(
        "../doc/translationsoverview.rst",
        setUp=setGlobs,
        layer=LaunchpadZopelessLayer,
    ),
}


def test_suite():
    suite = unittest.TestSuite()

    stories_dir = os.path.join(os.path.pardir, "stories")
    suite.addTest(PageTestSuite(stories_dir))
    stories_path = os.path.join(here, stories_dir)
    for story_entry in os.scandir(stories_path):
        if not story_entry.is_dir():
            continue
        story_path = os.path.join(stories_dir, story_entry.name)
        suite.addTest(PageTestSuite(story_path))

    testsdir = os.path.abspath(
        os.path.normpath(os.path.join(here, os.path.pardir, "doc"))
    )

    # Add special needs tests
    for key in sorted(special):
        special_suite = special[key]
        suite.addTest(special_suite)

    # Add tests using default setup/teardown
    filenames = [
        filename
        for filename in os.listdir(testsdir)
        if filename.endswith(".rst") and filename not in special
    ]
    # Sort the list to give a predictable order.
    filenames.sort()
    for filename in filenames:
        path = os.path.join("../doc/", filename)
        one_test = LayeredDocFileSuite(
            path,
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
            stdout_logging_level=logging.WARNING,
        )
        suite.addTest(one_test)

    return suite
