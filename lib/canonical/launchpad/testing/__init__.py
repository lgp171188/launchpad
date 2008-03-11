# Copyright 2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=W0401,C0301

from unittest import TestCase

from canonical.database.sqlbase import cursor
from canonical.testing import LaunchpadZopelessLayer

from canonical.launchpad.ftests import login
from canonical.launchpad.testing.factory import *

class TestCaseWithFactory(TestCase):

    layer = LaunchpadZopelessLayer

    def setUp(self):
        login('test@canonical.com')
        self.factory = LaunchpadObjectFactory()

    def assertIsDBNow(self, value):
        cur = cursor()
        cur.execute("SELECT CURRENT_TIMESTAMP AT TIME ZONE 'UTC';")
        [database_now] = cur.fetchone()
        self.assertEqual(
            database_now.utctimetuple(), value.utctimetuple())

