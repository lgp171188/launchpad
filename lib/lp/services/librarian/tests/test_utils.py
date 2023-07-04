# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import transaction

from lp.services.librarian.utils import (
    EncodableLibraryFileAlias,
    guess_librarian_encoding,
)
from lp.testing import TestCase, TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


class LibrarianUtils(TestCase):
    """Librarian utilities functions."""

    def test_guess_librarian_encoding(self):
        """Diffs and buillogs are served differently from the other files.

        Package Diffs ('.diff.gz') and buildlogs ('.txt.gz') should be
        served using mimetype 'text/plain' and encoding 'gzip'.
        """
        encoding, mimetype = guess_librarian_encoding("foo.html", "text/html")
        self.assertEqual(encoding, None)
        self.assertEqual(mimetype, "text/html")

        encoding, mimetype = guess_librarian_encoding(
            "foo.dsc", "application/debian-control"
        )
        self.assertEqual(encoding, None)
        self.assertEqual(mimetype, "application/debian-control")

        encoding, mimetype = guess_librarian_encoding(
            "foo.tar.gz", "application/octet-stream"
        )
        self.assertEqual(encoding, None)
        self.assertEqual(mimetype, "application/octet-stream")

        encoding, mimetype = guess_librarian_encoding(
            "foo.txt.gz", "will_be_overridden"
        )
        self.assertEqual(encoding, "gzip")
        self.assertEqual(mimetype, "text/plain; charset=utf-8")

        encoding, mimetype = guess_librarian_encoding(
            "foo.diff.gz", "will_be_overridden"
        )
        self.assertEqual(encoding, "gzip")
        self.assertEqual(mimetype, "text/plain")


class TestEncodableLibraryFileAlias(TestCaseWithFactory):
    layer = LaunchpadZopelessLayer

    def test_read_all(self):
        lfa = self.factory.makeLibraryFileAlias(content=b"abcdefgh")
        transaction.commit()
        lfa.open()
        try:
            encodable_lfa = EncodableLibraryFileAlias(lfa)
            self.assertEqual(8, len(encodable_lfa))
            self.assertEqual(b"abcdefgh", encodable_lfa.read())
            self.assertEqual(0, len(encodable_lfa))
        finally:
            lfa.close()

    def test_read_some(self):
        lfa = self.factory.makeLibraryFileAlias(content=b"abcdefgh")
        transaction.commit()
        lfa.open()
        try:
            encodable_lfa = EncodableLibraryFileAlias(lfa)
            self.assertEqual(8, len(encodable_lfa))
            self.assertEqual(b"a", encodable_lfa.read(1))
            self.assertEqual(7, len(encodable_lfa))
            self.assertEqual(b"bc", encodable_lfa.read(2))
            self.assertEqual(5, len(encodable_lfa))
            self.assertEqual(b"defgh", encodable_lfa.read())
            self.assertEqual(0, len(encodable_lfa))
        finally:
            lfa.close()

    def test_read_past_end(self):
        lfa = self.factory.makeLibraryFileAlias(content=b"abcdefgh")
        transaction.commit()
        lfa.open()
        try:
            encodable_lfa = EncodableLibraryFileAlias(lfa)
            self.assertEqual(8, len(encodable_lfa))
            self.assertEqual(b"a", encodable_lfa.read(1))
            self.assertEqual(7, len(encodable_lfa))
            self.assertEqual(b"bcdefgh", encodable_lfa.read(8))
            self.assertEqual(0, len(encodable_lfa))
            self.assertEqual(b"", encodable_lfa.read(8))
            self.assertEqual(0, len(encodable_lfa))
        finally:
            lfa.close()
