# Copyright 2009-2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Librarian garbage collection tests"""

import calendar
import hashlib
import io
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from subprocess import PIPE, STDOUT, Popen
from urllib.parse import urljoin

import requests
import transaction
from fixtures import MockPatchObject
from storm.store import Store
from swiftclient import client as swiftclient
from testtools.matchers import AnyMatch, Equals, MatchesListwise, MatchesRegex

from lp.services.config import config
from lp.services.database.interfaces import IPrimaryStore
from lp.services.database.sqlbase import (
    ISOLATION_LEVEL_AUTOCOMMIT,
    connect,
    cursor,
)
from lp.services.database.sqlobject import SQLObjectNotFound
from lp.services.features.testing import FeatureFixture
from lp.services.librarian.client import LibrarianClient
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.librarianserver import librariangc, swift
from lp.services.log.logger import BufferLogger
from lp.services.utils import utc_now
from lp.testing import TestCase, monkey_patch
from lp.testing.dbuser import switch_dbuser
from lp.testing.layers import LaunchpadZopelessLayer
from lp.testing.swift.fixture import SwiftFixture


class TestLibrarianGarbageCollectionBase:
    """Test garbage collection code that operates differently with
    Swift enabled. These tests need to be run under both environments.
    """

    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        self.client = LibrarianClient()
        self.patch(librariangc, "log", BufferLogger())

        # A value we use in a number of tests. This represents the
        # stay of execution hard coded into the garbage collector.
        # We don't destroy any data unless it has been waiting to be
        # destroyed for longer than this period. We pick a value
        # that is close enough to the stay of execution so that
        # forgetting timezone information will break things, but
        # far enough so that how long it takes the test to run
        # is not an issue. 'stay_of_excution - 1 hour' fits these
        # criteria.
        self.recent_past = utc_now() - timedelta(days=6, hours=23)
        # A time beyond the stay of execution.
        self.ancient_past = utc_now() - timedelta(days=30)

        self.f1_id, self.f2_id = self._makeDupes()

        switch_dbuser(config.librarian_gc.dbuser)
        self.ztm = self.layer.txn

        # Make sure that every file the database knows about exists on disk.
        # We manually remove them for tests that need to cope with missing
        # library items.
        store = IPrimaryStore(LibraryFileContent)
        for content in store.find(LibraryFileContent):
            path = librariangc.get_file_path(content.id)
            if not os.path.exists(path):
                if not os.path.exists(os.path.dirname(path)):
                    os.makedirs(os.path.dirname(path))
                content_bytes = "{} content".format(content.id).encode("UTF-8")
                with open(path, "wb") as f:
                    f.write(content_bytes)
                os.utime(path, (0, 0))  # Ancient past, never considered new.
                content.md5 = hashlib.md5(content_bytes).hexdigest()
                content.sha1 = hashlib.sha1(content_bytes).hexdigest()
                content.sha256 = hashlib.sha256(content_bytes).hexdigest()
                content.filesize = len(content_bytes)
        transaction.commit()

        self.con = connect(
            user=config.librarian_gc.dbuser,
            isolation=ISOLATION_LEVEL_AUTOCOMMIT,
        )

    def tearDown(self):
        self.con.rollback()
        self.con.close()
        del self.con
        super().tearDown()

    def _makeDupes(self):
        """Create two duplicate LibraryFileContent entries with one
        LibraryFileAlias each. Return the two LibraryFileAlias ids as a
        tuple.
        """
        # Connect to the database as a user with file upload privileges,
        # in this case the PostgreSQL default user who happens to be an
        # administrator on launchpad development boxes.
        switch_dbuser("testadmin")
        ztm = self.layer.txn

        ztm.begin()
        # Add some duplicate files
        content = b"This is some content"
        f1_id = self.client.addFile(
            "foo.txt",
            len(content),
            io.BytesIO(content),
            "text/plain",
        )
        f1 = LibraryFileAlias.get(f1_id)
        f2_id = self.client.addFile(
            "foo.txt",
            len(content),
            io.BytesIO(content),
            "text/plain",
        )
        f2 = LibraryFileAlias.get(f2_id)

        # Make sure the duplicates really are distinct
        self.assertNotEqual(f1_id, f2_id)
        self.assertNotEqual(f1.contentID, f2.contentID)

        f1.date_created = self.ancient_past
        f2.date_created = self.ancient_past
        f1.content.datecreated = self.ancient_past
        f2.content.datecreated = self.ancient_past

        # Set the time on disk to match the database timestamp.
        utime = calendar.timegm(self.ancient_past.utctimetuple())
        os.utime(librariangc.get_file_path(f1.contentID), (utime, utime))
        os.utime(librariangc.get_file_path(f2.contentID), (utime, utime))

        del f1, f2

        ztm.commit()

        return f1_id, f2_id

    def test_files_exist(self):
        # Confirm the files we expect created by the test harness
        # actually exist.
        self.assertTrue(self.file_exists(self.f1_id))

    def test_MergeDuplicates(self):
        # Merge the duplicates
        librariangc.merge_duplicates(self.con)

        # merge_duplicates should have committed
        self.ztm.begin()
        self.ztm.abort()

        # Confirm that the duplicates have been merged
        self.ztm.begin()
        f1 = LibraryFileAlias.get(self.f1_id)
        f2 = LibraryFileAlias.get(self.f2_id)
        self.assertEqual(f1.contentID, f2.contentID)

    def test_DeleteUnreferencedAliases(self):
        self.ztm.begin()

        # Confirm that our sample files are there.
        f1 = LibraryFileAlias.get(self.f1_id)
        f2 = LibraryFileAlias.get(self.f2_id)
        # Grab the content IDs related to these
        # unreferenced LibraryFileAliases
        c1_id = f1.contentID
        c2_id = f2.contentID
        del f1, f2
        self.ztm.abort()

        # Delete unreferenced aliases
        librariangc.delete_unreferenced_aliases(self.con)

        # This should have committed
        self.ztm.begin()

        # Confirm that the LibaryFileContents are still there.
        LibraryFileContent.get(c1_id)
        LibraryFileContent.get(c2_id)

        # But the LibraryFileAliases should be gone
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f1_id)
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f2_id)

    def test_DeleteUnreferencedAliases2(self):
        # Don't delete LibraryFileAliases accessed recently

        # Merge the duplicates. Both our aliases now point to the same
        # LibraryFileContent
        librariangc.merge_duplicates(self.con)

        # We now have two aliases sharing the same content.
        self.ztm.begin()
        f1 = LibraryFileAlias.get(self.f1_id)
        f2 = LibraryFileAlias.get(self.f2_id)
        self.assertEqual(f1.content, f2.content)

        # Flag one of our LibraryFileAliases as being recently created
        f1.date_created = self.recent_past

        del f1
        del f2
        self.ztm.commit()

        # Delete unreferenced LibraryFileAliases. This should remove
        # the alias with the ID self.f2_id, but the other should stay,
        # as it was accessed recently.
        librariangc.delete_unreferenced_aliases(self.con)

        self.ztm.begin()
        LibraryFileAlias.get(self.f1_id)
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f2_id)

    def test_DeleteUnreferencedAndWellExpiredAliases(self):
        # LibraryFileAliases can be removed after they have expired

        # Merge the duplicates. Both our aliases now point to the same
        # LibraryFileContent
        librariangc.merge_duplicates(self.con)

        # Flag one of our LibraryFileAliases with an expiry date in the past
        self.ztm.begin()
        f1 = LibraryFileAlias.get(self.f1_id)
        f1.expires = self.ancient_past
        del f1
        self.ztm.commit()

        # Delete unreferenced LibraryFileAliases. This should remove our
        # example aliases, as one is unreferenced with a NULL expiry and
        # the other is unreferenced with an expiry in the past.
        librariangc.delete_unreferenced_aliases(self.con)

        # Make sure both our example files are gone
        self.ztm.begin()
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f1_id)
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f2_id)

    def test_DoneDeleteUnreferencedButNotExpiredAliases(self):
        # LibraryFileAliases can be removed only after they have expired.
        # If an explicit expiry is set and in recent past (currently up to
        # one week ago), the files hang around.

        # Merge the duplicates. Both our aliases now point to the same
        # LibraryFileContent
        librariangc.merge_duplicates(self.con)

        # Flag one of our LibraryFileAliases with an expiry date in the
        # recent past.
        self.ztm.begin()
        f1 = LibraryFileAlias.get(self.f1_id)
        f1.expires = self.recent_past
        del f1
        self.ztm.commit()

        # Delete unreferenced LibraryFileAliases. This should not remove our
        # example aliases, as one is unreferenced with a NULL expiry and
        # the other is unreferenced with an expiry in the recent past.
        librariangc.delete_unreferenced_aliases(self.con)

        # Make sure both our example files are still there
        self.ztm.begin()
        # Our recently expired LibraryFileAlias is still available.
        LibraryFileAlias.get(self.f1_id)

    def test_deleteWellExpiredAliases(self):
        # LibraryFileAlias records that are expired are unlinked from their
        # content.

        # Flag one of our LibraryFileAliases with an expiry date in the past
        self.ztm.begin()
        f1 = LibraryFileAlias.get(self.f1_id)
        f1.expires = self.ancient_past
        del f1
        self.ztm.commit()

        # Unlink expired LibraryFileAliases.
        librariangc.expire_aliases(self.con)

        self.ztm.begin()
        # Make sure the well expired f1 is still there, but has no content.
        f1 = LibraryFileAlias.get(self.f1_id)
        self.assertIsNone(f1.content)
        # f2 should still have content, as it isn't flagged for expiry.
        f2 = LibraryFileAlias.get(self.f2_id)
        self.assertIsNotNone(f2.content)

    def test_ignoreRecentlyExpiredAliases(self):
        # LibraryFileAlias records that have expired recently are not
        # garbage collected.

        # Flag one of our LibraryFileAliases with an expiry date in the
        # recent past.
        self.ztm.begin()
        f1 = LibraryFileAlias.get(self.f1_id)
        f1.expires = self.recent_past  # Within stay of execution.
        del f1
        self.ztm.commit()

        # Unlink expired LibraryFileAliases.
        librariangc.expire_aliases(self.con)

        self.ztm.begin()
        # Make sure f1 is still there and has content. This ensures that
        # our stay of execution is still working.
        f1 = LibraryFileAlias.get(self.f1_id)
        self.assertIsNotNone(f1.content)
        # f2 should still have content, as it isn't flagged for expiry.
        f2 = LibraryFileAlias.get(self.f2_id)
        self.assertIsNotNone(f2.content)

    def test_DeleteUnreferencedContent(self):
        # Merge the duplicates. This creates an
        # unreferenced LibraryFileContent
        librariangc.merge_duplicates(self.con)

        self.ztm.begin()

        # Locate the unreferenced LibraryFileContent
        cur = cursor()
        cur.execute(
            """
            SELECT LibraryFileContent.id
            FROM LibraryFileContent
            LEFT OUTER JOIN LibraryFileAlias
                ON LibraryFileContent.id = LibraryFileAlias.content
            WHERE LibraryFileAlias.id IS NULL
                AND LibraryFileContent.id IN (%d, %d)
            """
            % (self.f1_id, self.f2_id)
        )
        results = cur.fetchall()
        self.assertEqual(len(results), 1)
        unreferenced_id = results[0][0]

        self.ztm.abort()

        # Make sure the file exists on disk
        self.assertTrue(self.file_exists(unreferenced_id))

        # Delete unreferenced content
        librariangc.delete_unreferenced_content(self.con)

        # Make sure the file is gone
        self.assertFalse(self.file_exists(unreferenced_id))

        # delete_unreferenced_content should have committed
        self.ztm.begin()

        # Make sure the unreferenced entries have all gone
        cur = cursor()
        cur.execute(
            """
            SELECT LibraryFileContent.id
            FROM LibraryFileContent
            LEFT OUTER JOIN LibraryFileAlias
                ON LibraryFileContent.id = LibraryFileAlias.content
            WHERE LibraryFileAlias.id IS NULL
            """
        )
        results = list(cur.fetchall())
        self.assertEqual(len(results), 0, "Too many results %r" % (results,))

    def test_DeleteUnreferencedContent2(self):
        # Like testDeleteUnreferencedContent, except that the file is
        # removed from disk before attempting to remove the unreferenced
        # LibraryFileContent.
        #
        # Because the garbage collector will remove an unreferenced file from
        # disk before it commits the database changes, it is possible that the
        # db removal will fail (eg. an exception was raised on COMMIT) leaving
        # the rows untouched in the database but no file on disk.
        # This is fine, as the next gc run will attempt it again and
        # nothing can use unreferenced files anyway. This test ensures
        # that this all works.

        # Merge the duplicates. This creates an
        # unreferenced LibraryFileContent
        librariangc.merge_duplicates(self.con)

        self.ztm.begin()

        # Locate the unreferenced LibraryFileContent
        cur = cursor()
        cur.execute(
            """
            SELECT LibraryFileContent.id
            FROM LibraryFileContent
            LEFT OUTER JOIN LibraryFileAlias
                ON LibraryFileContent.id = LibraryFileAlias.content
            WHERE LibraryFileAlias.id IS NULL
                AND LibraryFileContent.id IN (%d, %d)
            """
            % (self.f1_id, self.f2_id)
        )
        results = cur.fetchall()
        self.assertEqual(len(results), 1)
        unreferenced_id = results[0][0]

        self.ztm.abort()

        # Make sure the file exists on disk
        self.assertTrue(self.file_exists(unreferenced_id))

        # Remove the file from disk
        self.remove_file(unreferenced_id)
        self.assertFalse(self.file_exists(unreferenced_id))

        # Delete unreferenced content
        librariangc.delete_unreferenced_content(self.con)

        # Make sure the file is gone
        self.assertFalse(self.file_exists(unreferenced_id))

        # delete_unreferenced_content should have committed
        self.ztm.begin()

        # Make sure the unreferenced entries have all gone
        cur = cursor()
        cur.execute(
            """
            SELECT LibraryFileContent.id
            FROM LibraryFileContent
            LEFT OUTER JOIN LibraryFileAlias
                ON LibraryFileContent.id = LibraryFileAlias.content
            WHERE LibraryFileAlias.id IS NULL
            """
        )
        results = list(cur.fetchall())
        self.assertEqual(len(results), 0, "Too many results %r" % (results,))

    @contextmanager
    def librariangc_thinking_it_is_tomorrow(self):
        org_time = librariangc.time
        org_utcnow = librariangc._utcnow

        def tomorrow_time():
            return org_time() + 24 * 60 * 60 + 1

        def tomorrow_utcnow():
            return datetime.now(timezone.utc) + timedelta(days=1, seconds=1)

        try:
            librariangc.time = tomorrow_time
            librariangc._utcnow = tomorrow_utcnow
            yield
        finally:
            librariangc.time = org_time
            librariangc._utcnow = org_utcnow

    def test_deleteUnwantedFiles(self):
        self.ztm.begin()
        cur = cursor()

        # We may find files in the LibraryFileContent repository
        # that do not have an corresponding LibraryFileContent row.

        # Find a content_id we can easily delete and do so. This row is
        # removed from the database, leaving an orphaned file on the
        # filesystem that should be removed.
        cur.execute(
            """
            SELECT LibraryFileContent.id
            FROM LibraryFileContent
            LEFT OUTER JOIN LibraryFileAlias
                ON LibraryFileContent.id = content
            WHERE LibraryFileAlias.id IS NULL
            LIMIT 1
            """
        )
        content_id = cur.fetchone()[0]
        cur.execute(
            """
                DELETE FROM LibraryFileContent WHERE id=%s
                """,
            (content_id,),
        )
        self.ztm.commit()

        self.assertTrue(self.file_exists(content_id))

        # Ensure delete_unreferenced_files does not remove the file, because
        # it will have just been created (has a recent date_created). There
        # is a window between file creation and the garbage collector
        # bothering to remove the file to avoid the race condition where the
        # garbage collector is run whilst a file is being uploaded.
        librariangc.delete_unwanted_files(self.con)
        self.assertTrue(self.file_exists(content_id))

        # To test removal does occur when we want it to, we need to trick
        # the garbage collector into thinking it is tomorrow.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)

        self.assertFalse(self.file_exists(content_id))

        # Make sure nothing else has been removed from disk
        self.ztm.begin()
        cur = cursor()
        cur.execute(
            """
                SELECT id FROM LibraryFileContent
                """
        )
        for content_id in (row[0] for row in cur.fetchall()):
            self.assertTrue(self.file_exists(content_id))

    def test_delete_unwanted_files_bug437084(self):
        # There was a bug where delete_unwanted_files() would die
        # if the last file found on disk was unwanted.
        switch_dbuser("testadmin")
        content = b"foo"
        self.client.addFile(
            "foo.txt", len(content), io.BytesIO(content), "text/plain"
        )
        # Roll back the database changes, leaving the file on disk.
        transaction.abort()

        switch_dbuser(config.librarian_gc.dbuser)

        # This should cope.
        librariangc.delete_unwanted_files(self.con)

    def test_delete_unwanted_files_follows_symlinks(self):
        # In production, our tree has symlinks in it now.  We need to be able
        # to cope.
        # First, let's make sure we have some trash.
        switch_dbuser("testadmin")
        content = b"foo"
        self.client.addFile(
            "foo.txt", len(content), io.BytesIO(content), "text/plain"
        )
        # Roll back the database changes, leaving the file on disk.
        transaction.abort()

        switch_dbuser(config.librarian_gc.dbuser)

        # Now, we will move the directory containing the trash somewhere else
        # and make a symlink to it.
        original = os.path.join(config.librarian_server.root, "00", "00")
        newdir = tempfile.mkdtemp()
        alt = os.path.join(newdir, "00")
        shutil.move(original, alt)
        os.symlink(alt, original)

        # Now we will do our thing.  This is the actual test.  It used to
        # fail.
        librariangc.delete_unwanted_files(self.con)

        # Clean up.
        os.remove(original)
        shutil.move(alt, original)
        shutil.rmtree(newdir)

    def test_cronscript(self):
        script_path = os.path.join(
            config.root, "cronscripts", "librarian-gc.py"
        )
        cmd = [script_path, "-q"]
        process = Popen(
            cmd,
            stdout=PIPE,
            stderr=STDOUT,
            stdin=PIPE,
            universal_newlines=True,
        )
        (script_output, _empty) = process.communicate()
        self.assertEqual(process.returncode, 0, "Error: %s" % script_output)
        self.assertEqual(script_output, "")

        # Make sure that our example files have been garbage collected
        self.ztm.begin()
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f1_id)
        self.assertRaises(SQLObjectNotFound, LibraryFileAlias.get, self.f2_id)

        # And make sure stuff that *is* referenced remains
        LibraryFileAlias.get(2)
        cur = cursor()
        cur.execute("SELECT count(*) FROM LibraryFileAlias")
        count = cur.fetchone()[0]
        self.assertNotEqual(count, 0)
        cur.execute("SELECT count(*) FROM LibraryFileContent")
        count = cur.fetchone()[0]
        self.assertNotEqual(count, 0)

    def test_confirm_no_clock_skew(self):
        # There should not be any clock skew when running the test suite.
        librariangc.confirm_no_clock_skew(self.con)

        # To test this function raises an excption when it should,
        # fool the garbage collector into thinking it is tomorrow.
        with self.librariangc_thinking_it_is_tomorrow():
            self.assertRaises(
                Exception, librariangc.confirm_no_clock_skew, (self.con,)
            )


class TestDiskLibrarianGarbageCollection(
    TestLibrarianGarbageCollectionBase, TestCase
):
    def file_exists(self, content_id):
        path = librariangc.get_file_path(content_id)
        return os.path.exists(path)

    def remove_file(self, content_id):
        path = librariangc.get_file_path(content_id)
        os.unlink(path)

    def test_delete_unwanted_files_handles_migrated(self):
        # Files that have been uploaded to Swift have ".migrated"
        # appended to their names. These are treated just like the
        # original file, ignoring the extension.
        switch_dbuser("testadmin")
        content = b"foo"
        lfa = LibraryFileAlias.get(
            self.client.addFile(
                "foo.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        id_aborted = lfa.contentID
        # Roll back the database changes, leaving the file on disk.
        transaction.abort()

        lfa = LibraryFileAlias.get(
            self.client.addFile(
                "bar.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        transaction.commit()
        id_committed = lfa.contentID

        switch_dbuser(config.librarian_gc.dbuser)

        # Now rename the file to pretend that librarian-feed-swift has
        # dealt with it.
        path_aborted = librariangc.get_file_path(id_aborted)
        os.rename(path_aborted, path_aborted + ".migrated")

        path_committed = librariangc.get_file_path(id_committed)
        os.rename(path_committed, path_committed + ".migrated")

        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)

        self.assertFalse(os.path.exists(path_aborted + ".migrated"))
        self.assertTrue(os.path.exists(path_committed + ".migrated"))

    def test_deleteUnwantedFilesIgnoresNoise(self):
        # Directories with invalid names in the storage area are
        # ignored. They are reported as warnings though.

        # Not a hexadecimal number.
        noisedir1_path = os.path.join(config.librarian_server.root, "zz")

        # Too long
        noisedir2_path = os.path.join(config.librarian_server.root, "111")

        # Long non-hexadecimal number
        noisedir3_path = os.path.join(config.librarian_server.root, "11.bak")

        # A file with the ".migrated" suffix has migrated to Swift but
        # may still be removed from disk as unwanted by the GC. Other
        # suffixes are unknown and stay around.
        migrated_path = librariangc.get_file_path(8769786) + ".noise"

        try:
            os.mkdir(noisedir1_path)
            os.mkdir(noisedir2_path)
            os.mkdir(noisedir3_path)
            os.makedirs(os.path.dirname(migrated_path))

            # Files in the noise directories.
            noisefile1_path = os.path.join(noisedir1_path, "abc")
            noisefile2_path = os.path.join(noisedir2_path, "def")
            noisefile3_path = os.path.join(noisedir2_path, "ghi")
            with open(noisefile1_path, "w") as noisefile1:
                noisefile1.write("hello")
            with open(noisefile2_path, "w") as noisefile2:
                noisefile2.write("there")
            with open(noisefile3_path, "w") as noisefile3:
                noisefile3.write("testsuite")
            with open(migrated_path, "w") as migrated:
                migrated.write("migrant")

            # Pretend it is tomorrow to ensure the files don't count as
            # recently created, and run the delete_unwanted_files process.
            with self.librariangc_thinking_it_is_tomorrow():
                librariangc.delete_unwanted_files(self.con)

            # None of the rubbish we created has been touched.
            self.assertTrue(os.path.isdir(noisedir1_path))
            self.assertTrue(os.path.isdir(noisedir2_path))
            self.assertTrue(os.path.isdir(noisedir3_path))
            self.assertTrue(os.path.exists(noisefile1_path))
            self.assertTrue(os.path.exists(noisefile2_path))
            self.assertTrue(os.path.exists(noisefile3_path))
            self.assertTrue(os.path.exists(migrated_path))
        finally:
            # We need to clean this up ourselves, as the standard librarian
            # cleanup only removes files it knows where valid to avoid
            # accidents.
            shutil.rmtree(noisedir1_path)
            shutil.rmtree(noisedir2_path)
            shutil.rmtree(noisedir3_path)
            shutil.rmtree(os.path.dirname(migrated_path))

        # Can't check the ordering, so we'll just check that one of the
        # warnings are there.
        self.assertIn(
            "WARNING Ignoring invalid directory zz",
            librariangc.log.getLogBuffer(),
        )
        # No warning about the .migrated file.
        self.assertNotIn(".migrated", librariangc.log.getLogBuffer())


class TestSwiftLibrarianGarbageCollection(
    TestLibrarianGarbageCollectionBase, TestCase
):
    """Swift specific garbage collection tests."""

    def setUp(self):
        # Once we switch entirely to Swift, we can move this setup into
        # the lp.testing.layers code and save the per-test overhead.

        self.swift_fixture = self.useFixture(SwiftFixture())

        self.useFixture(FeatureFixture({"librarian.swift.enabled": True}))

        super().setUp()

        # Move files into Swift.
        path = librariangc.get_file_path(self.f1_id)
        assert os.path.exists(path), "Librarian uploads failed"
        swift.to_swift(BufferLogger(), remove_func=os.unlink)
        assert not os.path.exists(path), "to_swift failed to move files"

    def file_exists(self, content_id, suffix=None, pool_index=None):
        container, name = swift.swift_location(content_id)
        if suffix:
            name += suffix
        connection_pools = (
            [swift.connection_pools[pool_index]]
            if pool_index is not None
            else swift.connection_pools
        )
        for connection_pool in connection_pools:
            with swift.connection(connection_pool) as swift_connection:
                try:
                    swift.quiet_swiftclient(
                        swift_connection.head_object, container, name
                    )
                    return True
                except swiftclient.ClientException as x:
                    if x.http_status != 404:
                        raise
        return False

    def remove_file(self, content_id):
        container, name = swift.swift_location(content_id)
        for connection_pool in swift.connection_pools:
            with swift.connection(connection_pool) as swift_connection:
                try:
                    swift.quiet_swiftclient(
                        swift_connection.delete_object, container, name
                    )
                except swiftclient.ClientException as x:
                    if x.http_status != 404:
                        raise

    def test_DeleteUnreferencedContent_handles_timeout(self):
        # If delete_unreferenced_content times out trying to delete a file
        # from Swift, it logs an error and moves on.

        # Merge the duplicates. This creates an
        # unreferenced LibraryFileContent.
        librariangc.merge_duplicates(self.con)

        # Force a timeout from the Swift fixture.
        self.pushConfig(
            "librarian_server", os_username="timeout", swift_timeout=0.1
        )
        swift.reconfigure_connection_pools()

        # Delete unreferenced content.
        librariangc.delete_unreferenced_content(self.con)

        # We logged an error message.
        self.assertThat(
            librariangc.log.getLogBuffer().splitlines(),
            AnyMatch(
                MatchesRegex(r"^ERROR Failed to delete .* from Swift .*")
            ),
        )

    def test_delete_unwanted_files_handles_segments(self):
        # Large files are handled by Swift as multiple segments joined
        # by a manifest. GC treats the segments like the original file.
        switch_dbuser("testadmin")
        content = b"uploading to swift bigly"
        big1_lfa = LibraryFileAlias.get(
            self.client.addFile(
                "foo.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        big1_id = big1_lfa.contentID

        big2_lfa = LibraryFileAlias.get(
            self.client.addFile(
                "bar.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        big2_id = big2_lfa.contentID
        transaction.commit()

        for lfc_id in (big1_id, big2_id):
            # Make the files old so they don't look in-progress.
            os.utime(swift.filesystem_path(lfc_id), (0, 0))

        switch_dbuser(config.librarian_gc.dbuser)

        # Force the files to be segmented as if they were large.
        with monkey_patch(swift, MAX_SWIFT_OBJECT_SIZE=4):
            swift.to_swift(BufferLogger(), remove_func=os.unlink)

        def segment_existence(lfc_id):
            return [
                self.file_exists(lfc_id, suffix=suffix)
                for suffix in (None, "/0000", "/0001")
            ]

        # Both files and their segments exist in Swift.
        self.assertEqual([True, True, True], segment_existence(big1_id))
        self.assertEqual([True, True, True], segment_existence(big2_id))

        # All the segments survive the first purge.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)
        self.assertEqual([True, True, True], segment_existence(big1_id))
        self.assertEqual([True, True, True], segment_existence(big2_id))

        # Remove the first file from the DB.
        content = big1_lfa.content
        Store.of(big1_lfa).remove(big1_lfa)
        Store.of(content).remove(content)
        transaction.commit()

        # The first file and its segments are removed, but the second is
        # intact.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)
        self.assertEqual([False, False, False], segment_existence(big1_id))
        self.assertEqual([True, True, True], segment_existence(big2_id))

    def test_delete_unwanted_files_handles_duplicates(self):
        # GC tolerates swift_connection.get_container returning duplicate
        # names (perhaps across multiple batches).  It's not clear whether
        # this happens in practice, but some strange deletion failures
        # suggest that it might happen.
        switch_dbuser("testadmin")
        content = b"uploading to swift"
        f1_lfa = LibraryFileAlias.get(
            self.client.addFile(
                "foo.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        f1_id = f1_lfa.contentID

        f2_lfa = LibraryFileAlias.get(
            self.client.addFile(
                "bar.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        f2_id = f2_lfa.contentID
        transaction.commit()

        for lfc_id in (f1_id, f2_id):
            # Make the files old so they don't look in-progress.
            os.utime(swift.filesystem_path(lfc_id), (0, 0))

        switch_dbuser(config.librarian_gc.dbuser)

        # Force swift_connection.get_container to return duplicate results.
        orig_get_container = swiftclient.get_container

        def duplicating_get_container(*args, **kwargs):
            rv = orig_get_container(*args, **kwargs)
            if not kwargs.get("full_listing", False):
                rv = (rv[0], rv[1] * 2)
            return rv

        self.useFixture(
            MockPatchObject(
                swiftclient, "get_container", duplicating_get_container
            )
        )

        swift.to_swift(BufferLogger(), remove_func=os.unlink)

        # Both files exist in Swift.
        self.assertTrue(self.file_exists(f1_id))
        self.assertTrue(self.file_exists(f2_id))

        # Both files survive the first purge.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)
        self.assertTrue(self.file_exists(f1_id))
        self.assertTrue(self.file_exists(f2_id))

        # Remove the first file from the DB.
        content = f1_lfa.content
        Store.of(f1_lfa).remove(f1_lfa)
        Store.of(content).remove(content)
        transaction.commit()

        # The first file is removed, but the second is intact.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)
        self.assertFalse(self.file_exists(f1_id))
        self.assertTrue(self.file_exists(f2_id))

    def test_delete_unwanted_files_handles_missing(self):
        # GC tolerates a file being already missing from Swift when it tries
        # to delete it.  It's not clear why this happens in practice.
        switch_dbuser("testadmin")
        content = b"uploading to swift"
        f1_lfa = LibraryFileAlias.get(
            self.client.addFile(
                "foo.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        f1_id = f1_lfa.contentID

        f2_lfa = LibraryFileAlias.get(
            self.client.addFile(
                "bar.txt", len(content), io.BytesIO(content), "text/plain"
            )
        )
        f2_id = f2_lfa.contentID
        transaction.commit()

        for lfc_id in (f1_id, f2_id):
            # Make the files old so they don't look in-progress.
            os.utime(swift.filesystem_path(lfc_id), (0, 0))

        switch_dbuser(config.librarian_gc.dbuser)

        swift.to_swift(BufferLogger(), remove_func=os.unlink)

        # Both files exist in Swift.
        self.assertTrue(self.file_exists(f1_id))
        self.assertTrue(self.file_exists(f2_id))

        # Remove the first file from the DB.
        content = f1_lfa.content
        Store.of(f1_lfa).remove(f1_lfa)
        Store.of(content).remove(content)
        transaction.commit()

        # In production, we see a sequence of DELETE 401 / authenticate /
        # DELETE 404.  Since it isn't clear why this happens, we don't know
        # exactly how to simulate it here, but do our best by deleting the
        # object and forcibly expiring the client's token just before the
        # first expected DELETE.
        real_delete_object = swiftclient.Connection.delete_object

        def fake_delete_object(connection, *args, **kwargs):
            real_delete_object(connection, *args, **kwargs)
            self.assertIsNotNone(connection.token)
            requests.delete(
                urljoin(
                    config.librarian_server.os_auth_url,
                    "tokens/%s" % connection.token,
                )
            )
            return real_delete_object(connection, *args, **kwargs)

        self.patch(swiftclient.Connection, "delete_object", fake_delete_object)

        # delete_unwanted_files completes successfully, and the second file
        # is intact.
        with self.librariangc_thinking_it_is_tomorrow():
            swift.quiet_swiftclient(
                librariangc.delete_unwanted_files, self.con
            )
        self.assertFalse(self.file_exists(f1_id))
        self.assertTrue(self.file_exists(f2_id))


class TestTwoSwiftsLibrarianGarbageCollection(
    TestSwiftLibrarianGarbageCollection
):
    """Garbage-collection tests with two Swift instances."""

    def setUp(self):
        self.old_swift_fixture = self.useFixture(
            SwiftFixture(old_instance=True)
        )
        super().setUp()

    def test_swift_files_multiple_instances(self):
        # swift_files yields files in the correct order across multiple
        # Swift instances.
        switch_dbuser("testadmin")
        content = b"foo"
        lfas = [
            LibraryFileAlias.get(
                self.client.addFile(
                    "foo.txt", len(content), io.BytesIO(content), "text/plain"
                )
            )
            for _ in range(12)
        ]
        lfc_ids = [lfa.contentID for lfa in lfas]
        transaction.commit()

        # Simulate a migration in progress.  Some files are only in the old
        # Swift instance and have not been copied over yet; some are in both
        # instances; some were created after the migration started and so
        # are only in the new instance.
        old_lfc_ids = [
            lfc_id
            for i, lfc_id in enumerate(lfc_ids)
            if i in {0, 1, 3, 4, 6, 7, 8, 9}
        ]
        for lfc_id in old_lfc_ids:
            with swift.connection(
                swift.connection_pools[0]
            ) as swift_connection:
                swift._to_swift_file(
                    BufferLogger(),
                    swift_connection,
                    lfc_id,
                    swift.filesystem_path(lfc_id),
                )
        new_lfc_ids = [
            lfc_id
            for i, lfc_id in enumerate(lfc_ids)
            if i in {1, 2, 3, 8, 9, 10}
        ]
        for lfc_id in new_lfc_ids:
            with swift.connection() as swift_connection:
                swift._to_swift_file(
                    BufferLogger(),
                    swift_connection,
                    lfc_id,
                    swift.filesystem_path(lfc_id),
                )

        self.assertThat(
            [
                (pool, container, int(obj["name"]))
                for pool, container, obj in librariangc.swift_files(
                    lfc_ids[-1]
                )
                if int(obj["name"]) >= lfc_ids[0]
            ],
            MatchesListwise(
                [
                    Equals(
                        (
                            swift.connection_pools[pool_index],
                            container,
                            lfc_ids[i],
                        )
                    )
                    for pool_index, container, i in (
                        (0, "librarian_0", 0),
                        (0, "librarian_0", 1),
                        (1, "librarian_0", 1),
                        (1, "librarian_0", 2),
                        (0, "librarian_0", 3),
                        (1, "librarian_0", 3),
                        (0, "librarian_0", 4),
                        (0, "librarian_0", 6),
                        (0, "librarian_0", 7),
                        (0, "librarian_0", 8),
                        (1, "librarian_0", 8),
                        (0, "librarian_0", 9),
                        (1, "librarian_0", 9),
                        (1, "librarian_0", 10),
                    )
                ]
            ),
        )

    def test_delete_unwanted_files_handles_multiple_instances(self):
        # GC handles cases where files only exist in one or the other Swift
        # instance.
        switch_dbuser("testadmin")
        content = b"foo"
        lfas = [
            LibraryFileAlias.get(
                self.client.addFile(
                    "foo.txt", len(content), io.BytesIO(content), "text/plain"
                )
            )
            for _ in range(12)
        ]
        lfc_ids = [lfa.contentID for lfa in lfas]
        transaction.commit()

        for lfc_id in lfc_ids:
            # Make the files old so they don't look in-progress.
            os.utime(swift.filesystem_path(lfc_id), (0, 0))

        # Simulate a migration in progress.  Some files are only in the old
        # Swift instance and have not been copied over yet; some are in both
        # instances; some were created after the migration started and so
        # are only in the new instance.
        old_lfc_ids = [
            lfc_id
            for i, lfc_id in enumerate(lfc_ids)
            if i in {0, 1, 3, 4, 6, 7, 8}
        ]
        for lfc_id in old_lfc_ids:
            with swift.connection(
                swift.connection_pools[0]
            ) as swift_connection:
                swift._to_swift_file(
                    BufferLogger(),
                    swift_connection,
                    lfc_id,
                    swift.filesystem_path(lfc_id),
                )
        new_lfc_ids = [
            lfc_id
            for i, lfc_id in enumerate(lfc_ids)
            if i in {1, 2, 3, 8, 9, 10}
        ]
        for lfc_id in new_lfc_ids:
            with swift.connection() as swift_connection:
                swift._to_swift_file(
                    BufferLogger(),
                    swift_connection,
                    lfc_id,
                    swift.filesystem_path(lfc_id),
                )

        # All the files survive the first run.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)
        for lfc_id in lfc_ids:
            self.assertEqual(
                lfc_id in old_lfc_ids, self.file_exists(lfc_id, pool_index=0)
            )
            self.assertEqual(
                lfc_id in new_lfc_ids, self.file_exists(lfc_id, pool_index=1)
            )

        # Remove one file that is only in the old instance, one that is in
        # both instances, and one that is only in the new instance.
        for i in (0, 3, 9):
            content = lfas[i].content
            Store.of(lfas[i]).remove(lfas[i])
            Store.of(content).remove(content)
        transaction.commit()

        # The now-unreferenced files are removed, but the others are intact.
        with self.librariangc_thinking_it_is_tomorrow():
            librariangc.delete_unwanted_files(self.con)
        old_lfc_ids = [
            lfc_id for i, lfc_id in enumerate(lfc_ids) if i in {1, 4, 6, 7, 8}
        ]
        new_lfc_ids = [
            lfc_id for i, lfc_id in enumerate(lfc_ids) if i in {1, 2, 8, 10}
        ]
        for lfc_id in lfc_ids:
            self.assertEqual(
                lfc_id in old_lfc_ids, self.file_exists(lfc_id, pool_index=0)
            )
            self.assertEqual(
                lfc_id in new_lfc_ids, self.file_exists(lfc_id, pool_index=1)
            )


class TestBlobCollection(TestCase):
    layer = LaunchpadZopelessLayer

    def setUp(self):
        super().setUp()
        # Add in some sample data
        cur = cursor()

        # First a blob that has been unclaimed and expired.
        cur.execute(
            """
            INSERT INTO LibraryFileContent (filesize, sha1, md5, sha256)
            VALUES (666, 'whatever', 'whatever', 'whatever')
            """
        )
        cur.execute("""SELECT currval('libraryfilecontent_id_seq')""")
        self.expired_lfc_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO LibraryFileAlias (
                content, filename, mimetype, expires)
            VALUES (
                %s, 'whatever', 'whatever',
                CURRENT_TIMESTAMP - '1 day'::interval
                )
            """,
            (self.expired_lfc_id,),
        )
        cur.execute("""SELECT currval('libraryfilealias_id_seq')""")
        self.expired_lfa_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO TemporaryBlobStorage (uuid, file_alias)
            VALUES ('uuid', %s)
            """,
            (self.expired_lfa_id,),
        )
        cur.execute("""SELECT currval('temporaryblobstorage_id_seq')""")
        self.expired_blob_id = cur.fetchone()[0]

        # Add ApportJob and Job entries - these need to be removed
        # too.
        cur.execute(
            """
            INSERT INTO Job (status, date_finished)
            VALUES (0, CURRENT_TIMESTAMP - interval '2 days') RETURNING id
            """
        )
        self.expired_job_id = cur.fetchone()[0]
        cur.execute(
            """
            INSERT INTO ApportJob (job, blob, job_type)
            VALUES (%s, %s, 0) RETURNING id
            """,
            (self.expired_job_id, self.expired_blob_id),
        )
        self.expired_apportjob_id = cur.fetchone()[0]

        # Next a blob that has expired, but claimed and now linked to
        # elsewhere in the database
        cur.execute(
            """
            INSERT INTO LibraryFileContent (filesize, sha1, md5, sha256)
            VALUES (666, 'whatever', 'whatever', 'whatever')
            """
        )
        cur.execute("""SELECT currval('libraryfilecontent_id_seq')""")
        self.expired2_lfc_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO LibraryFileAlias (
                content, filename, mimetype, expires)
            VALUES (
                %s, 'whatever', 'whatever',
                CURRENT_TIMESTAMP - '1 day'::interval
                )
            """,
            (self.expired2_lfc_id,),
        )
        cur.execute("""SELECT currval('libraryfilealias_id_seq')""")
        self.expired2_lfa_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO TemporaryBlobStorage (uuid, file_alias)
            VALUES ('uuid2', %s)
            """,
            (self.expired2_lfa_id,),
        )
        cur.execute("""SELECT currval('temporaryblobstorage_id_seq')""")
        self.expired2_blob_id = cur.fetchone()[0]

        # Link it somewhere else, unexpired
        cur.execute(
            """
            INSERT INTO LibraryFileAlias (content, filename, mimetype)
            VALUES (%s, 'whatever', 'whatever')
            """,
            (self.expired2_lfc_id,),
        )
        cur.execute(
            """
            UPDATE Person SET mugshot=currval('libraryfilealias_id_seq')
            WHERE name='stub'
            """
        )

        # And a non expired blob
        cur.execute(
            """
            INSERT INTO LibraryFileContent (filesize, sha1, md5, sha256)
            VALUES (666, 'whatever', 'whatever', 'whatever')
            """
        )
        cur.execute("""SELECT currval('libraryfilecontent_id_seq')""")
        self.unexpired_lfc_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO LibraryFileAlias (
                content, filename, mimetype, expires)
            VALUES (
                %s, 'whatever', 'whatever',
                CURRENT_TIMESTAMP + '1 day'::interval
                )
            """,
            (self.unexpired_lfc_id,),
        )
        cur.execute("""SELECT currval('libraryfilealias_id_seq')""")
        self.unexpired_lfa_id = cur.fetchone()[0]

        cur.execute(
            """
            INSERT INTO TemporaryBlobStorage (uuid, file_alias)
            VALUES ('uuid3', %s)
            """,
            (self.unexpired_lfa_id,),
        )
        cur.execute("""SELECT currval('temporaryblobstorage_id_seq')""")
        self.unexpired_blob_id = cur.fetchone()[0]
        self.layer.txn.commit()

        # Make sure all the librarian files actually exist on disk with
        # hashes matching the DB. We use the hash as the new file
        # content, to preserve existing duplicate relationships.
        switch_dbuser("testadmin")
        cur = cursor()
        cur.execute("SELECT id, sha1 FROM LibraryFileContent")
        for content_id, sha1 in cur.fetchall():
            path = librariangc.get_file_path(content_id)
            if not os.path.exists(path):
                if not os.path.exists(os.path.dirname(path)):
                    os.makedirs(os.path.dirname(path))
                data = sha1.encode("UTF-8")
                with open(path, "wb") as f:
                    f.write(data)
                cur.execute(
                    "UPDATE LibraryFileContent "
                    "SET md5 = %s, sha1 = %s, sha256 = %s, filesize = %s "
                    "WHERE id = %s",
                    (
                        hashlib.md5(data).hexdigest(),
                        hashlib.sha1(data).hexdigest(),
                        hashlib.sha256(data).hexdigest(),
                        len(data),
                        content_id,
                    ),
                )
        self.layer.txn.commit()

        switch_dbuser(config.librarian_gc.dbuser)

        # Open a connection for our test
        self.con = connect(
            user=config.librarian_gc.dbuser,
            isolation=ISOLATION_LEVEL_AUTOCOMMIT,
        )

        self.patch(librariangc, "log", BufferLogger())

    def tearDown(self):
        self.con.rollback()
        self.con.close()
        super().tearDown()

    def test_DeleteExpiredBlobs(self):
        # Delete expired blobs from the TemporaryBlobStorage table
        librariangc.delete_expired_blobs(self.con)

        cur = self.con.cursor()

        # Our expired blob should be gone
        cur.execute(
            """
            SELECT * FROM TemporaryBlobStorage WHERE id=%s
            """,
            (self.expired_blob_id,),
        )
        self.assertIsNone(cur.fetchone())

        # As should our expired blob linked elsewhere.
        cur.execute(
            """
            SELECT * FROM TemporaryBlobStorage WHERE id=%s
            """,
            (self.expired2_blob_id,),
        )
        self.assertIsNone(cur.fetchone())

        # But our unexpired blob is still hanging around.
        cur.execute(
            """
            SELECT * FROM TemporaryBlobStorage WHERE id=%s
            """,
            (self.unexpired_blob_id,),
        )
        self.assertIsNotNone(cur.fetchone())

        # Now delete our unreferenced aliases and unreferenced content
        cur.execute(
            "SELECT id FROM LibraryFileAlias WHERE id IN (%s, %s, %s)",
            (self.expired_lfa_id, self.expired2_lfa_id, self.unexpired_lfa_id),
        )
        librariangc.delete_unreferenced_aliases(self.con)
        librariangc.delete_unreferenced_content(self.con)
        cur.execute(
            "SELECT id FROM LibraryFileAlias WHERE id IN (%s, %s, %s)",
            (self.expired_lfa_id, self.expired2_lfa_id, self.unexpired_lfa_id),
        )

        # The first expired blob should now be entirely gone
        cur.execute(
            """
            SELECT * FROM LibraryFileAlias WHERE id=%s
            """,
            (self.expired_lfa_id,),
        )
        self.assertIsNone(cur.fetchone())
        cur.execute(
            """
            SELECT * FROM LibraryFileContent WHERE id=%s
            """,
            (self.expired_lfc_id,),
        )
        self.assertIsNone(cur.fetchone())

        # The second expired blob will has lost its LibraryFileAlias,
        # but the content is still hanging around because something else
        # linked to it.
        cur.execute(
            """
            SELECT * FROM LibraryFileAlias WHERE id=%s
            """,
            (self.expired2_lfa_id,),
        )
        self.assertIsNone(cur.fetchone())
        cur.execute(
            """
            SELECT * FROM LibraryFileContent WHERE id=%s
            """,
            (self.expired2_lfc_id,),
        )
        self.assertIsNotNone(cur.fetchone())

        # The unexpired blob should be unaffected
        cur.execute(
            """
            SELECT * FROM LibraryFileAlias WHERE id=%s
            """,
            (self.unexpired_lfa_id,),
        )
        self.assertIsNotNone(cur.fetchone())
        cur.execute(
            """
            SELECT * FROM LibraryFileContent WHERE id=%s
            """,
            (self.unexpired_lfc_id,),
        )
        self.assertIsNotNone(cur.fetchone())

    def test_cronscript(self):
        # Run the cronscript
        script_path = os.path.join(
            config.root, "cronscripts", "librarian-gc.py"
        )
        cmd = [script_path, "-q"]
        process = Popen(
            cmd,
            stdout=PIPE,
            stderr=STDOUT,
            stdin=PIPE,
            universal_newlines=True,
        )
        (script_output, _empty) = process.communicate()
        self.assertEqual(process.returncode, 0, "Error: %s" % script_output)
        self.assertEqual(script_output, "")

        cur = self.con.cursor()

        # Make sure that our blobs have been garbage collectd
        cur.execute("SELECT count(*) FROM TemporaryBlobStorage")
        count = cur.fetchone()[0]
        self.assertEqual(count, 1)

        cur.execute(
            """
            SELECT count(*) FROM LibraryFileAlias
            WHERE id IN (%s, %s, %s)
            """,
            (self.expired_lfa_id, self.expired2_lfa_id, self.unexpired_lfa_id),
        )
        count = cur.fetchone()[0]
        self.assertEqual(count, 1)

        cur.execute(
            """
            SELECT count(*) FROM LibraryFileContent
            WHERE id IN (%s, %s, %s)
            """,
            (self.expired_lfc_id, self.expired2_lfc_id, self.unexpired_lfc_id),
        )
        count = cur.fetchone()[0]
        self.assertNotEqual(count, 2)
