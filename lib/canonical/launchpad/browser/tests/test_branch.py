# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Unit tests for BranchView."""

__metaclass__ = type
__all__ = ['TestBranchView', 'test_suite']

from datetime import datetime
import unittest

import pytz

from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from canonical.launchpad.browser.branch import BranchAddView, BranchView
from canonical.launchpad.ftests.harness import login, logout, ANONYMOUS
from canonical.launchpad.helpers import truncate_text
from canonical.launchpad.interfaces import (
    BranchLifecycleStatus, IBranchSet, IPersonSet, IProductSet)
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.testing import LaunchpadFunctionalLayer


class TestBranchView(unittest.TestCase):

    layer = LaunchpadFunctionalLayer

    def setUp(self):
        login(ANONYMOUS)
        self.request = LaunchpadTestRequest()

    def tearDown(self):
        logout()

    def testMirrorStatusMessageIsTruncated(self):
        """mirror_status_message is truncated if the text is overly long."""
        branch = getUtility(IBranchSet).get(28)
        branch_view = BranchView(branch, self.request)
        self.assertEqual(
            truncate_text(branch.mirror_status_message,
                          branch_view.MAXIMUM_STATUS_MESSAGE_LENGTH) + ' ...',
            branch_view.mirror_status_message())

    def testMirrorStatusMessage(self):
        """mirror_status_message on the view is the same as on the branch."""
        branch = getUtility(IBranchSet).get(5)
        branch_view = BranchView(branch, self.request)
        self.assertEqual(
            branch.mirror_status_message, branch_view.mirror_status_message())

    def testBranchAddRequestsMirror(self):
        """Registering a mirrored branch requests a mirror."""
        arbitrary_person = getUtility(IPersonSet).get(1)
        arbitrary_product = getUtility(IProductSet).get(1)
        login(arbitrary_person.preferredemail.email)
        try:
            add_view = BranchAddView(arbitrary_person, self.request)
            add_view.initialize()
            data = {
                'name': 'some-branch',
                'url': 'http://example.com',
                'title': 'Branch Title',
                'summary': '',
                'lifecycle_status': BranchLifecycleStatus.NEW,
                'home_page': 'http://example.com',
                'whiteboard': '',
                'author': arbitrary_person,
                'product': arbitrary_product
                }
            add_view.add_action.success(data)
            # Make sure that mirror_request_time is a datetime, not an
            # sqlbuilder expression.
            removeSecurityProxy(add_view.branch).sync()
            now = datetime.now(pytz.timezone('UTC'))
            self.assertNotEqual(None, add_view.branch.mirror_request_time)
            self.assertTrue(
                add_view.branch.mirror_request_time < now,
                "mirror_request_time not set to UTC_NOW: %s < %s"
                % (add_view.branch.mirror_request_time, now))
        finally:
            logout()


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
