# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import logging
import os
import unittest

from lp.code.tests.test_doc import branchscannerSetUp
from lp.services.config import config
from lp.services.features.testing import FeatureFixture
from lp.services.mail.tests.test_doc import ProcessMailLayer
from lp.soyuz.tests.test_doc import (
    lobotomize_stevea,
    uploaderSetUp,
    uploadQueueSetUp,
)
from lp.testing import login, logout
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import (
    DatabaseLayer,
    LaunchpadFunctionalLayer,
    LaunchpadZopelessLayer,
)
from lp.testing.pages import PageTestSuite
from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setGlobs,
    setUp,
    tearDown,
)

here = os.path.dirname(os.path.realpath(__file__))


def lobotomizeSteveASetUp(test):
    """Call lobotomize_stevea() and standard setUp"""
    lobotomize_stevea()
    setUp(test)


def checkwatchesSetUp(test):
    """Setup the check watches script tests."""
    setUp(test)
    switch_dbuser(config.checkwatches.dbuser)


def branchscannerBugsSetUp(test):
    """Setup the user for the branch scanner tests."""
    lobotomize_stevea()
    branchscannerSetUp(test)


def bugNotificationSendingSetUp(test):
    lobotomize_stevea()
    switch_dbuser(config.malone.bugnotification_dbuser)
    setUp(test)


def bugNotificationSendingTearDown(test):
    tearDown(test)


def cveSetUp(test):
    lobotomize_stevea()
    switch_dbuser(config.cveupdater.dbuser)
    setUp(test)


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


def noPrivSetUp(test):
    """Set up a test logged in as no-priv."""
    setUp(test)
    login("no-priv@canonical.com")


def bugtaskExpirationSetUp(test):
    """Setup globs for bug expiration."""
    setUp(test)
    login("test@canonical.com")


def updateRemoteProductSetup(test):
    """Setup to use the 'updateremoteproduct' db user."""
    setUp(test)
    switch_dbuser(config.updateremoteproduct.dbuser)


def updateRemoteProductTeardown(test):
    # Mark the DB as dirty, since we run a script in a sub process.
    DatabaseLayer.force_dirty_database()
    tearDown(test)


def bugSetStatusSetUp(test):
    setUp(test)
    test.globs["test_dbuser"] = config.processmail.dbuser


def bugmessageSetUp(test):
    setUp(test)
    login("no-priv@canonical.com")


def enableDSPPickerSetUp(test):
    setUp(test)
    ff = FeatureFixture({"disclosure.dsp_picker.enabled": "on"})
    ff.setUp()
    test.globs["dsp_picker_feature_fixture"] = ff


def enableDSPPickerTearDown(test):
    test.globs["dsp_picker_feature_fixture"].cleanUp()
    tearDown(test)


special = {
    "cve-update.rst": LayeredDocFileSuite(
        "../doc/cve-update.rst",
        setUp=cveSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bug-heat.rst": LayeredDocFileSuite(
        "../doc/bug-heat.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugnotificationrecipients.rst-uploader": LayeredDocFileSuite(
        "../doc/bugnotificationrecipients.rst",
        id_extensions=["bugnotificationrecipients.rst-uploader"],
        setUp=uploaderBugsSetUp,
        tearDown=uploaderBugsTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugnotificationrecipients.rst-queued": LayeredDocFileSuite(
        "../doc/bugnotificationrecipients.rst",
        id_extensions=["bugnotificationrecipients.rst-queued"],
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugnotificationrecipients.rst-branchscanner": LayeredDocFileSuite(
        "../doc/bugnotificationrecipients.rst",
        id_extensions=["bugnotificationrecipients.rst-branchscanner"],
        setUp=branchscannerBugsSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugnotificationrecipients.rst": LayeredDocFileSuite(
        "../doc/bugnotificationrecipients.rst",
        id_extensions=["bugnotificationrecipients.rst"],
        setUp=lobotomizeSteveASetUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "bugnotification-threading.rst": LayeredDocFileSuite(
        "../doc/bugnotification-threading.rst",
        setUp=lobotomizeSteveASetUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "bugnotification-sending.rst": LayeredDocFileSuite(
        "../doc/bugnotification-sending.rst",
        layer=LaunchpadZopelessLayer,
        setUp=bugNotificationSendingSetUp,
        tearDown=bugNotificationSendingTearDown,
    ),
    "bugmail-headers.rst": LayeredDocFileSuite(
        "../doc/bugmail-headers.rst",
        layer=LaunchpadZopelessLayer,
        setUp=bugNotificationSendingSetUp,
        tearDown=bugNotificationSendingTearDown,
    ),
    "bug-export.rst": LayeredDocFileSuite(
        "../doc/bug-export.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bug-set-status.rst": LayeredDocFileSuite(
        "../doc/bug-set-status.rst",
        id_extensions=["bug-set-status.rst"],
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bug-set-status.rst-uploader": LayeredDocFileSuite(
        "../doc/bug-set-status.rst",
        id_extensions=["bug-set-status.rst-uploader"],
        setUp=uploaderBugsSetUp,
        tearDown=uploaderBugsTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugtask-expiration.rst": LayeredDocFileSuite(
        "../doc/bugtask-expiration.rst",
        setUp=bugtaskExpirationSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugtask-package-widget.rst": LayeredDocFileSuite(
        "../doc/bugtask-package-widget.rst",
        id_extensions=["bugtask-package-widget.rst"],
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "bugtask-package-widget.rst-dsp-picker": LayeredDocFileSuite(
        "../doc/bugtask-package-widget.rst",
        id_extensions=["bugtask-package-widget.rst-dsp-picker"],
        setUp=enableDSPPickerSetUp,
        tearDown=enableDSPPickerTearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "bugmessage.rst": LayeredDocFileSuite(
        "../doc/bugmessage.rst",
        id_extensions=["bugmessage.rst"],
        setUp=noPrivSetUp,
        tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
    ),
    "bugmessage.rst-queued": LayeredDocFileSuite(
        "../doc/bugmessage.rst",
        id_extensions=["bugmessage.rst-queued"],
        setUp=uploadQueueSetUp,
        tearDown=uploadQueueTearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugmessage.rst-uploader": LayeredDocFileSuite(
        "../doc/bugmessage.rst",
        id_extensions=["bugmessage.rst-uploader"],
        setUp=uploaderSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugmessage.rst-checkwatches": LayeredDocFileSuite(
        "../doc/bugmessage.rst",
        id_extensions=["bugmessage.rst-checkwatches"],
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugtracker-person.rst": LayeredDocFileSuite(
        "../doc/bugtracker-person.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugwatch.rst": LayeredDocFileSuite(
        "../doc/bugwatch.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bug-watch-activity.rst": LayeredDocFileSuite(
        "../doc/bug-watch-activity.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "bugtracker.rst": LayeredDocFileSuite(
        "../doc/bugtracker.rst",
        setUp=setUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "checkwatches.rst": LayeredDocFileSuite(
        "../doc/checkwatches.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        stdout_logging_level=logging.WARNING,
        layer=LaunchpadZopelessLayer,
    ),
    "checkwatches-cli-switches.rst": LayeredDocFileSuite(
        "../doc/checkwatches-cli-switches.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker.rst",
        setUp=setUp,
        tearDown=tearDown,
        stdout_logging_level=logging.WARNING,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-bug-imports.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-bug-imports.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-bugzilla.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-bugzilla.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-bugzilla-api.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-bugzilla-api.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-bugzilla-lp-plugin.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-bugzilla-lp-plugin.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-bugzilla-oddities.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-bugzilla-oddities.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-checkwatches.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-checkwatches.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-comment-imports.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-comment-imports.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-comment-pushing.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-comment-pushing.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-debbugs.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-debbugs.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-emailaddress.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-emailaddress.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-linking-back.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-linking-back.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        stdout_logging_level=logging.ERROR,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-mantis-csv.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-mantis-csv.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-mantis.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-mantis.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-roundup-python-bugs.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-roundup-python-bugs.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-roundup.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-roundup.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-rt.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-rt.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-sourceforge.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-sourceforge.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-trac.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-trac.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "externalbugtracker-trac-lp-plugin.rst": LayeredDocFileSuite(
        "../doc/externalbugtracker-trac-lp-plugin.rst",
        setUp=checkwatchesSetUp,
        tearDown=tearDown,
        layer=LaunchpadZopelessLayer,
    ),
    "product-update-remote-product.rst": LayeredDocFileSuite(
        "../doc/product-update-remote-product.rst",
        setUp=updateRemoteProductSetup,
        tearDown=updateRemoteProductTeardown,
        layer=LaunchpadZopelessLayer,
    ),
    "product-update-remote-product-script.rst": LayeredDocFileSuite(
        "../doc/product-update-remote-product-script.rst",
        setUp=updateRemoteProductSetup,
        tearDown=updateRemoteProductTeardown,
        layer=LaunchpadZopelessLayer,
    ),
    "sourceforge-remote-products.rst": LayeredDocFileSuite(
        "../doc/sourceforge-remote-products.rst",
        setUp=setGlobs,
        layer=LaunchpadZopelessLayer,
    ),
    "bug-set-status.rst-processmail": LayeredDocFileSuite(
        "../doc/bug-set-status.rst",
        id_extensions=["bug-set-status.rst-processmail"],
        setUp=bugSetStatusSetUp,
        tearDown=tearDown,
        layer=ProcessMailLayer,
        stdout_logging=False,
    ),
    "bugmessage.rst-processmail": LayeredDocFileSuite(
        "../doc/bugmessage.rst",
        id_extensions=["bugmessage.rst-processmail"],
        setUp=bugmessageSetUp,
        tearDown=tearDown,
        layer=ProcessMailLayer,
        stdout_logging=False,
    ),
    "bugs-emailinterface.rst-processmail": LayeredDocFileSuite(
        "../tests/bugs-emailinterface.rst",
        id_extensions=["bugs-emailinterface.rst-processmail"],
        setUp=setUp,
        tearDown=tearDown,
        layer=ProcessMailLayer,
        stdout_logging=False,
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
    for _, special_suite in sorted(special.items()):
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
