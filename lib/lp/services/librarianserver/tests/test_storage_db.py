# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import hashlib
import os.path
import time

from fixtures import TempDir
from testtools.testcase import ExpectedException
from testtools.twistedsupport import AsynchronousDeferredRunTest
import transaction
from twisted.internet import defer

from lp.services.database.sqlbase import flush_database_updates
from lp.services.features.testing import FeatureFixture
from lp.services.librarian.model import LibraryFileContent
from lp.services.librarianserver import (
    db,
    swift,
    )
from lp.services.librarianserver.storage import (
    DigestMismatchError,
    DuplicateFileIDError,
    LibrarianStorage,
    LibraryFileUpload,
    )
from lp.services.log.logger import DevNullLogger
from lp.testing import TestCase
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.swift.fixture import SwiftFixture


class LibrarianStorageDBTests(TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super(LibrarianStorageDBTests, self).setUp()
        switch_dbuser('librarian')
        self.directory = self.useFixture(TempDir()).path
        self.storage = LibrarianStorage(self.directory, db.Library())

    def test_addFile(self):
        data = 'data ' * 50
        digest = hashlib.sha1(data).hexdigest()
        newfile = self.storage.startAddFile('file1', len(data))
        newfile.srcDigest = digest
        newfile.append(data)
        fileid, aliasid = newfile.store()
        self.assertTrue(self.storage.hasFile(fileid))

    def test_addFiles_identical(self):
        # Start adding two files with identical data
        data = 'data ' * 5000
        newfile1 = self.storage.startAddFile('file1', len(data))
        newfile2 = self.storage.startAddFile('file2', len(data))
        newfile1.append(data)
        newfile2.append(data)
        id1, alias1 = newfile1.store()
        id2, alias2 = newfile2.store()

        # Make sure we actually got an id
        self.assertNotEqual(None, id1)
        self.assertNotEqual(None, id2)

        # But they are two different ids, because we leave duplicate handling
        # to the garbage collector
        self.assertNotEqual(id1, id2)

    def test_badDigest(self):
        data = 'data ' * 50
        digest = 'crud'
        newfile = self.storage.startAddFile('file', len(data))
        newfile.srcDigest = digest
        newfile.append(data)
        self.assertRaises(DigestMismatchError, newfile.store)

    def test_alias(self):
        # Add a file (and so also add an alias)
        data = 'data ' * 50
        newfile = self.storage.startAddFile('file1', len(data))
        newfile.mimetype = 'text/unknown'
        newfile.append(data)
        fileid, aliasid = newfile.store()

        # Check that its alias has the right mimetype
        fa = self.storage.getFileAlias(aliasid, None, '/')
        self.assertEqual('text/unknown', fa.mimetype)

        # Re-add the same file, with the same name and mimetype...
        newfile2 = self.storage.startAddFile('file1', len(data))
        newfile2.mimetype = 'text/unknown'
        newfile2.append(data)
        fileid2, aliasid2 = newfile2.store()

        # Verify that we didn't get back the same alias ID
        self.assertNotEqual(fa.id,
            self.storage.getFileAlias(aliasid2, None, '/').id)

    def test_clientProvidedDuplicateIDs(self):
        # This test checks the new behaviour specified by LibrarianTransactions
        # spec: don't create IDs in DB, but do check they don't exist.

        # Create a new file
        newfile = LibraryFileUpload(self.storage, 'filename', 0)

        # Set a content ID on the file (same as would happen with a
        # client-generated ID) and store it
        newfile.contentID = 666
        newfile.store()

        newfile = LibraryFileUpload(self.storage, 'filename', 0)
        newfile.contentID = 666
        self.assertRaises(DuplicateFileIDError, newfile.store)

    def test_clientProvidedDuplicateContent(self):
        # Check the new behaviour specified by LibrarianTransactions
        # spec: allow duplicate content with distinct IDs.

        content = 'some content'

        # Store a file with id 6661
        newfile1 = LibraryFileUpload(self.storage, 'filename', 0)
        newfile1.contentID = 6661
        newfile1.append(content)
        fileid1, aliasid1 = newfile1.store()

        # Store second file identical to the first, with id 6662
        newfile2 = LibraryFileUpload(self.storage, 'filename', 0)
        newfile2.contentID = 6662
        newfile2.append(content)
        fileid2, aliasid2 = newfile2.store()

        # Create rows in the database for these files.
        LibraryFileContent(
            filesize=0, sha1='foo', md5='xx', sha256='xx', id=6661)
        LibraryFileContent(
            filesize=0, sha1='foo', md5='xx', sha256='xx', id=6662)

        flush_database_updates()
        # And no errors should have been raised!


class LibrarianStorageSwiftTests(TestCase):

    layer = LaunchpadZopelessLayer
    run_tests_with = AsynchronousDeferredRunTest.make_factory(timeout=10)

    def setUp(self):
        super(LibrarianStorageSwiftTests, self).setUp()
        switch_dbuser('librarian')
        self.swift_fixture = self.useFixture(SwiftFixture())
        self.useFixture(FeatureFixture({'librarian.swift.enabled': True}))
        self.directory = self.useFixture(TempDir()).path
        self.pushConfig('librarian_server', root=self.directory)
        self.storage = LibrarianStorage(self.directory, db.Library())
        transaction.commit()
        self.addCleanup(swift.connection_pool.clear)

    def moveToSwift(self, lfc_id):
        # Move a file to Swift so that we know it can't accidentally be
        # retrieved from the local file system.  We set its modification
        # time far enough in the past that it isn't considered potentially
        # in progress.
        path = swift.filesystem_path(lfc_id)
        mtime = time.time() - 25 * 60 * 60
        os.utime(path, (mtime, mtime))
        self.assertTrue(os.path.exists(path))
        swift.to_swift(DevNullLogger(), remove_func=os.unlink)
        self.assertFalse(os.path.exists(path))

    @defer.inlineCallbacks
    def test_completed_fetch_reuses_connection(self):
        # A completed fetch returns the expected data and reuses the Swift
        # connection.
        data = b'x' * (self.storage.CHUNK_SIZE * 4 + 1)
        newfile = self.storage.startAddFile('file', len(data))
        newfile.mimetype = 'text/plain'
        newfile.append(data)
        lfc_id, _ = newfile.store()
        self.moveToSwift(lfc_id)
        stream = yield self.storage.open(lfc_id)
        self.assertIsNotNone(stream)
        chunks = []
        while True:
            chunk = yield stream.read(self.storage.CHUNK_SIZE)
            if not chunk:
                break
            chunks.append(chunk)
        self.assertEqual(b''.join(chunks), data)
        self.assertEqual(1, len(swift.connection_pool._pool))

    @defer.inlineCallbacks
    def test_partial_fetch_does_not_reuse_connection(self):
        # If only part of a file is fetched, the Swift connection is not
        # reused.
        data = b'x' * self.storage.CHUNK_SIZE * 4
        newfile = self.storage.startAddFile('file', len(data))
        newfile.mimetype = 'text/plain'
        newfile.append(data)
        lfc_id, _ = newfile.store()
        self.moveToSwift(lfc_id)
        stream = yield self.storage.open(lfc_id)
        self.assertIsNotNone(stream)
        chunk = yield stream.read(self.storage.CHUNK_SIZE)
        self.assertEqual(b'x' * self.storage.CHUNK_SIZE, chunk)
        stream.close()
        with ExpectedException(ValueError, 'I/O operation on closed file'):
            yield stream.read(self.storage.CHUNK_SIZE)
        self.assertEqual(0, len(swift.connection_pool._pool))

    @defer.inlineCallbacks
    def test_fetch_with_close_at_end_does_not_reuse_connection(self):
        num_chunks = 4
        data = b'x' * self.storage.CHUNK_SIZE * num_chunks
        newfile = self.storage.startAddFile('file', len(data))
        newfile.mimetype = 'text/plain'
        newfile.append(data)
        lfc_id, _ = newfile.store()
        self.moveToSwift(lfc_id)
        stream = yield self.storage.open(lfc_id)
        self.assertIsNotNone(stream)
        # Read exactly the number of chunks we expect to make up the file.
        for _ in range(num_chunks):
            chunk = yield stream.read(self.storage.CHUNK_SIZE)
            self.assertEqual(b'x' * self.storage.CHUNK_SIZE, chunk)
        # Start the read that should return an empty byte string (indicating
        # EOF), but close the stream before finishing it.  This exercises
        # the connection-reuse path in TxSwiftStream.read.
        d = stream.read(self.storage.CHUNK_SIZE)
        stream.close()
        chunk = yield d
        self.assertEqual(b'', chunk)
        # In principle we might be able to reuse the connection here, but
        # SwiftStream.close doesn't know that.
        self.assertEqual(0, len(swift.connection_pool._pool))
