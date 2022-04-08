# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for pool.py."""

import hashlib
from pathlib import Path
import shutil
from tempfile import mkdtemp
import unittest

from lp.archivepublisher.diskpool import (
    DiskPool,
    poolify,
    )
from lp.services.log.logger import BufferLogger


class FakeLibraryFileContent:

    def __init__(self, contents):
        self.sha1 = hashlib.sha1(contents).hexdigest()


class FakeLibraryFileAlias:

    def __init__(self, contents):
        self.content = FakeLibraryFileContent(contents)
        self.contents = contents

    def open(self):
        self.loc = 0

    def read(self, chunksize):
        end_chunk = self.loc + chunksize
        chunk = self.contents[self.loc:end_chunk]
        self.loc = end_chunk
        return chunk

    def close(self):
        pass


class FakePackageReleaseFile:

    def __init__(self, contents):
        self.libraryfile = FakeLibraryFileAlias(contents)


class PoolTestingFile:

    def __init__(self, pool, sourcename, filename):
        self.pool = pool
        self.sourcename = sourcename
        self.filename = filename
        self.contents = sourcename.encode("UTF-8")

    def addToPool(self, component: str):
        return self.pool.addFile(
            component, self.sourcename, self.filename,
            FakePackageReleaseFile(self.contents))

    def removeFromPool(self, component: str) -> int:
        return self.pool.removeFile(component, self.sourcename, self.filename)

    def checkExists(self, component: str) -> bool:
        path = self.pool.pathFor(component, self.sourcename, self.filename)
        return path.exists()

    def checkIsLink(self, component: str) -> bool:
        path = self.pool.pathFor(component, self.sourcename, self.filename)
        return path.is_symlink()

    def checkIsFile(self, component: str) -> bool:
        return self.checkExists(component) and not self.checkIsLink(component)


class TestPoolification(unittest.TestCase):

    def testPoolificationOkay(self):
        """poolify should poolify properly"""
        cases = (
            ("foo", "main", Path("main/f/foo")),
            ("foo", "universe", Path("universe/f/foo")),
            ("libfoo", "main", Path("main/libf/libfoo")),
            )
        for case in cases:
            self.assertEqual(case[2], poolify(case[0], case[1]))


class TestPool(unittest.TestCase):

    def setUp(self):
        self.pool_path = mkdtemp()
        self.temp_path = mkdtemp()
        self.pool = DiskPool(self.pool_path, self.temp_path, BufferLogger())

    def tearDown(self):
        shutil.rmtree(self.pool_path)
        shutil.rmtree(self.temp_path)

    def testSimpleAdd(self):
        """Adding a new file should work."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        result = foo.addToPool("main")
        self.assertEqual(self.pool.results.FILE_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))

    def testSimpleSymlink(self):
        """Adding a file twice should result in a symlink."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("main")
        result = foo.addToPool("universe")
        self.assertEqual(self.pool.results.SYMLINK_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        self.assertTrue(foo.checkIsLink("universe"))

    def testSymlinkShuffleOnAdd(self):
        """If the second add is a more preferred component, links shuffle."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("universe")
        result = foo.addToPool("main")
        self.assertEqual(self.pool.results.SYMLINK_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        self.assertTrue(foo.checkIsLink("universe"))

    def testRemoveSymlink(self):
        """Remove file should just remove a symlink"""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("main")
        foo.addToPool("universe")

        size = foo.removeFromPool("universe")
        self.assertFalse(foo.checkExists("universe"))
        self.assertEqual(31, size)

    def testRemoveLoneFile(self):
        """Removing a file with no symlinks removes it."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("main")

        size = foo.removeFromPool("main")
        self.assertFalse(foo.checkExists("universe"))
        self.assertEqual(3, size)

    def testSymlinkShuffleOnRemove(self):
        """Removing a file with a symlink shuffles links."""
        foo = PoolTestingFile(self.pool, "foo", "foo-1.0.deb")
        foo.addToPool("universe")
        foo.addToPool("main")

        foo.removeFromPool("main")
        self.assertFalse(foo.checkExists("main"))
        self.assertTrue(foo.checkIsFile("universe"))
