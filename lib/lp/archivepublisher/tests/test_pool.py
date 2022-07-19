# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for pool.py."""

import hashlib
import shutil
import unittest
from pathlib import Path
from tempfile import mkdtemp

from lazr.enum import EnumeratedType, Item
from zope.interface import alsoProvides, implementer

from lp.archivepublisher.diskpool import DiskPool, poolify
from lp.services.log.logger import BufferLogger
from lp.soyuz.enums import ArchiveRepositoryFormat
from lp.soyuz.interfaces.files import (
    IBinaryPackageFile,
    IPackageReleaseFile,
    ISourcePackageReleaseFile,
)


class FakeArchive:
    def __init__(self, repository_format=ArchiveRepositoryFormat.DEBIAN):
        self.repository_format = repository_format


class FakeLibraryFileContent:
    def __init__(self, contents):
        self.sha1 = hashlib.sha1(contents).hexdigest()


class FakeLibraryFileAlias:
    def __init__(self, contents, filename):
        self.contents = contents
        self.filename = filename

    @property
    def content(self):
        return FakeLibraryFileContent(self.contents)

    def open(self):
        self.loc = 0

    def read(self, chunksize):
        end_chunk = self.loc + chunksize
        chunk = self.contents[self.loc : end_chunk]
        self.loc = end_chunk
        return chunk

    def close(self):
        pass


class FakePackageRelease:
    def __init__(self, release_id, user_defined_fields=None, ci_build=None):
        self.id = release_id
        self.user_defined_fields = user_defined_fields
        self.ci_build = ci_build

    def getUserDefinedField(self, name):
        for k, v in self.user_defined_fields:
            if k.lower() == name.lower():
                return v


class FakeReleaseType(EnumeratedType):

    SOURCE = Item("Source")
    BINARY = Item("Binary")


@implementer(IPackageReleaseFile)
class FakePackageReleaseFile:
    def __init__(
        self,
        contents,
        filename,
        release_type=FakeReleaseType.BINARY,
        release_id=1,
        user_defined_fields=None,
        ci_build=None,
    ):
        self.libraryfile = FakeLibraryFileAlias(contents, filename)
        if release_type == FakeReleaseType.SOURCE:
            self.sourcepackagereleaseID = release_id
            self.sourcepackagerelease = FakePackageRelease(
                release_id,
                user_defined_fields=user_defined_fields,
                ci_build=ci_build,
            )
            alsoProvides(self, ISourcePackageReleaseFile)
        elif release_type == FakeReleaseType.BINARY:
            self.binarypackagereleaseID = release_id
            self.binarypackagerelease = FakePackageRelease(
                release_id, user_defined_fields=user_defined_fields
            )
            alsoProvides(self, IBinaryPackageFile)


class PoolTestingFile:
    def __init__(
        self,
        pool,
        source_name,
        source_version,
        filename,
        release_type=FakeReleaseType.BINARY,
        release_id=1,
        user_defined_fields=None,
    ):
        self.pool = pool
        self.source_name = source_name
        self.source_version = source_version
        self.pub_file = FakePackageReleaseFile(
            source_name.encode(),
            filename,
            release_type=release_type,
            release_id=release_id,
            user_defined_fields=user_defined_fields,
        )

    def addToPool(self, component: str):
        return self.pool.addFile(
            component, self.source_name, self.source_version, self.pub_file
        )

    def removeFromPool(self, component: str) -> int:
        return self.pool.removeFile(
            component, self.source_name, self.source_version, self.pub_file
        )

    def checkExists(self, component: str) -> bool:
        path = self.pool.pathFor(
            component, self.source_name, self.source_version, self.pub_file
        )
        return path.exists()

    def checkIsLink(self, component: str) -> bool:
        path = self.pool.pathFor(
            component, self.source_name, self.source_version, self.pub_file
        )
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
        self.pool = DiskPool(
            FakeArchive(), self.pool_path, self.temp_path, BufferLogger()
        )

    def tearDown(self):
        shutil.rmtree(self.pool_path)
        shutil.rmtree(self.temp_path)

    def testSimpleAdd(self):
        """Adding a new file should work."""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )
        result = foo.addToPool("main")
        self.assertEqual(self.pool.results.FILE_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))

    def testSimpleSymlink(self):
        """Adding a file twice should result in a symlink."""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )
        foo.addToPool("main")
        result = foo.addToPool("universe")
        self.assertEqual(self.pool.results.SYMLINK_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        self.assertTrue(foo.checkIsLink("universe"))

    def testSymlinkShuffleOnAdd(self):
        """If the second add is a more preferred component, links shuffle."""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )
        foo.addToPool("universe")
        result = foo.addToPool("main")
        self.assertEqual(self.pool.results.SYMLINK_ADDED, result)
        self.assertTrue(foo.checkIsFile("main"))
        self.assertTrue(foo.checkIsLink("universe"))

    def testRemoveSymlink(self):
        """Remove file should just remove a symlink"""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )
        foo.addToPool("main")
        foo.addToPool("universe")

        size = foo.removeFromPool("universe")
        self.assertFalse(foo.checkExists("universe"))
        self.assertEqual(31, size)

    def testRemoveLoneFile(self):
        """Removing a file with no symlinks removes it."""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )
        foo.addToPool("main")

        size = foo.removeFromPool("main")
        self.assertFalse(foo.checkExists("universe"))
        self.assertEqual(3, size)

    def testSymlinkShuffleOnRemove(self):
        """Removing a file with a symlink shuffles links."""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )
        foo.addToPool("universe")
        foo.addToPool("main")

        foo.removeFromPool("main")
        self.assertFalse(foo.checkExists("main"))
        self.assertTrue(foo.checkIsFile("universe"))
