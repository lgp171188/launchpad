# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Confirm nobody has broken sampledata.

By editing the sampledata manually, it is possible to corrupt the data
silently switching off some of our constraints. We can detect this by
doing a dump and restore - this will fail if the data is corrupt.
"""

import subprocess
from typing import List

from lp.testing import TestCase
from lp.testing.layers import DatabaseLayer
from lp.testing.pgsql import PgTestSetup

__all__: List[str] = []


class SampleDataTestCase(TestCase):
    layer = DatabaseLayer

    def setUp(self):
        super().setUp()
        self.pg_fixture = PgTestSetup(template="template1")
        self.pg_fixture.setUp()

    def tearDown(self):
        self.pg_fixture.tearDown()
        super().tearDown()

    def test_testSampledata(self):
        """Test the sample data used by the test suite."""
        self.dump_and_restore("launchpad_ftest_template")

    # XXX bug 365385
    def disabled_test_devSampledata(self):
        """Test the sample data used by developers for manual testing."""
        self.dump_and_restore("launchpad_dev_template")

    def dump_and_restore(self, source_dbname):
        cmd = (
            "pg_dump --format=c --compress=0 --no-privileges --no-owner"
            " %s | pg_restore "
            " --exit-on-error --dbname=%s"
            % (source_dbname, self.pg_fixture.dbname)
        )
        proc = subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            stdin=subprocess.PIPE,
        )
        (stdout, stderr) = proc.communicate()
        rv = proc.wait()
        self.assertEqual(rv, 0, "Dump/Restore failed: %s" % stdout)
