# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the script that does a smoke-test of the librarian."""

from functools import partial
import io

from fixtures import MockPatch
import six

from lp.services.librarian.smoketest import (
    do_smoketest,
    FILE_DATA,
    store_file,
    )
from lp.services.librarianserver.testing.fake import FakeLibrarian
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer


def good_urlopen(url):
    """A urllib replacement for testing that returns good results."""
    return io.BytesIO(FILE_DATA)


def bad_urlopen(url):
    """A urllib replacement for testing that returns bad results."""
    return io.BytesIO(b'bad data')


def error_urlopen(url):
    """A urllib replacement for testing that raises an exception."""
    raise OSError('network error')


def explosive_urlopen(exception, url):
    """A urllib replacement that raises an "explosive" exception."""
    raise exception


class SmokeTestTestCase(TestCaseWithFactory):
    """Class test for translation importer creation."""
    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        self.fake_librarian = self.useFixture(FakeLibrarian())

    def test_store_file(self):
        # Make sure that the function meant to store a file in the librarian
        # and return the file's HTTP URL works.
        aid, url = store_file(self.fake_librarian)
        self.assertEqual(
            '%s%d/smoke-test-file' % (self.fake_librarian.download_url, aid),
            url)

    def test_good_data(self):
        # If storing and retrieving both the public and private files work,
        # the main function will return 0 (which will be used as the processes
        # exit code to signal success).
        with MockPatch(
                "lp.services.librarian.smoketest.urlopen", good_urlopen):
            self.assertEqual(
                do_smoketest(self.fake_librarian, self.fake_librarian,
                             output=six.StringIO()),
                0)

    def test_bad_data(self):
        # If incorrect data is retrieved, the main function will return 1
        # (which will be used as the processes exit code to signal an error).
        with MockPatch("lp.services.librarian.smoketest.urlopen", bad_urlopen):
            self.assertEqual(
                do_smoketest(self.fake_librarian, self.fake_librarian,
                             output=six.StringIO()),
                1)

    def test_exception(self):
        # If an exception is raised when retrieving the data, the main
        # function will return 1 (which will be used as the processes exit
        # code to signal an error).
        with MockPatch(
                "lp.services.librarian.smoketest.urlopen", error_urlopen):
            self.assertEqual(
                do_smoketest(self.fake_librarian, self.fake_librarian,
                             output=six.StringIO()),
                1)

    def test_explosive_errors(self):
        # If an "explosive" exception (an exception that should not be caught)
        # is raised when retrieving the data it is re-raised.
        for exception in MemoryError, SystemExit, KeyboardInterrupt:
            with MockPatch(
                    "lp.services.librarian.smoketest.urlopen",
                    partial(explosive_urlopen, exception)):
                self.assertRaises(
                    exception,
                    do_smoketest, self.fake_librarian, self.fake_librarian,
                    output=six.StringIO())
