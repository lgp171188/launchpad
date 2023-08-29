# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import logging
import os
import unittest

import transaction

from lp.services.config import config
from lp.services.database.interfaces import IStore
from lp.services.identity.interfaces.emailaddress import EmailAddressStatus
from lp.services.identity.model.emailaddress import EmailAddress
from lp.testing import logout
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import LaunchpadFunctionalLayer, LaunchpadZopelessLayer
from lp.testing.pages import PageTestSuite
from lp.testing.systemdocs import LayeredDocFileSuite, setUp, tearDown

here = os.path.dirname(os.path.realpath(__file__))


def lobotomize_stevea():
    """Set SteveA's email address' status to NEW.

    Call this method first in a test's setUp where needed. Tests
    using this function should be refactored to use the unaltered
    sample data and this function eventually removed.

    In the past, SteveA's account erroneously appeared in the old
    ValidPersonOrTeamCache materialized view. This materialized view
    has since been replaced and now SteveA is correctly listed as
    invalid in the sampledata. This fix broke some tests testing
    code that did not use the ValidPersonOrTeamCache to determine
    validity.
    """
    stevea_emailaddress = (
        IStore(EmailAddress)
        .find(EmailAddress, email="steve.alexander@ubuntulinux.com")
        .one()
    )
    stevea_emailaddress.status = EmailAddressStatus.NEW
    transaction.commit()


def uploaderSetUp(test):
    """setup the package uploader script tests."""
    setUp(test)
    switch_dbuser("uploader")


def statisticianSetUp(test):
    test_dbuser = config.statistician.dbuser
    test.globs["test_dbuser"] = test_dbuser
    switch_dbuser(test_dbuser)
    setUp(test)


def statisticianTearDown(test):
    tearDown(test)


def uploadQueueSetUp(test):
    lobotomize_stevea()
    test_dbuser = config.uploadqueue.dbuser
    switch_dbuser(test_dbuser)
    setUp(test)
    test.globs["test_dbuser"] = test_dbuser


def uploaderBugsSetUp(test):
    """Set up a test suite using the 'uploader' db user.

    Some aspects of the bug tracker are being used by the Soyuz uploader.
    In order to test that these functions work as expected from the uploader,
    we run them using the same db user used by the uploader.
    """
    lobotomize_stevea()
    test_dbuser = config.uploader.dbuser
    switch_dbuser(test_dbuser)
    setUp(test)
    test.globs["test_dbuser"] = test_dbuser


def uploaderBugsTearDown(test):
    logout()


def uploadQueueTearDown(test):
    logout()


special = {
    "package-cache.rst": LayeredDocFileSuite(
        "../doc/package-cache.rst",
        setUp=statisticianSetUp,
        tearDown=statisticianTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "distroarchseriesbinarypackage.rst": LayeredDocFileSuite(
        "../doc/distroarchseriesbinarypackage.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "closing-bugs-from-changelogs.rst": LayeredDocFileSuite(
        "../doc/closing-bugs-from-changelogs.rst",
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "closing-bugs-from-changelogs.rst-uploader": LayeredDocFileSuite(
        "../doc/closing-bugs-from-changelogs.rst",
        id_extensions=["closing-bugs-from-changelogs.rst-uploader"],
        setUp=uploaderBugsSetUp,
        tearDown=uploaderBugsTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "soyuz-set-of-uploads.rst": LayeredDocFileSuite(
        "../doc/soyuz-set-of-uploads.rst",
        setUp=setUp,
        layer=LaunchpadZopelessLayer,
    ),
    "package-relationship.rst": LayeredDocFileSuite(
        "../doc/package-relationship.rst", stdout_logging=False, layer=None
    ),
    "publishing.rst": LayeredDocFileSuite(
        "../doc/publishing.rst",
        setUp=setUp,
        layer=LaunchpadZopelessLayer,
    ),
    "build-failedtoupload-workflow.rst": LayeredDocFileSuite(
        "../doc/build-failedtoupload-workflow.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "distroseriesqueue.rst": LayeredDocFileSuite(
        "../doc/distroseriesqueue.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "distroseriesqueue-notify.rst": LayeredDocFileSuite(
        "../doc/distroseriesqueue-notify.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "distroseriesqueue-translations.rst": LayeredDocFileSuite(
        "../doc/distroseriesqueue-translations.rst",
        setUp=setUp,
        tearDown=tearDown,
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

    # Add special needs tests
    for key in sorted(special):
        special_suite = special[key]
        suite.addTest(special_suite)

    testsdir = os.path.abspath(
        os.path.normpath(os.path.join(here, os.path.pardir, "doc"))
    )

    # Add tests using default setup/teardown
    filenames = [
        filename
        for filename in os.listdir(testsdir)
        if filename.endswith(".rst") and filename not in special
    ]

    # Sort the list to give a predictable order.
    filenames.sort()
    for filename in filenames:
        path = os.path.join("../doc", filename)
        one_test = LayeredDocFileSuite(
            path,
            setUp=setUp,
            tearDown=tearDown,
            layer=LaunchpadFunctionalLayer,
            stdout_logging_level=logging.WARNING,
        )
        suite.addTest(one_test)

    return suite
