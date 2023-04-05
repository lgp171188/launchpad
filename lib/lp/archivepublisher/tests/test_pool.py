# Copyright 2009-2018 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for pool.py."""

import hashlib
from pathlib import Path, PurePath
from unittest import mock

from lazr.enum import EnumeratedType, Item
from zope.interface import alsoProvides, implementer

from lp.archivepublisher.diskpool import (
    DiskPool,
    _diskpool_atomicfile,
    poolify,
    unpoolify,
)
from lp.registry.interfaces.sourcepackage import SourcePackageFileType
from lp.services.log.logger import BufferLogger
from lp.soyuz.enums import ArchiveRepositoryFormat, BinaryPackageFileType
from lp.soyuz.interfaces.files import (
    IBinaryPackageFile,
    IPackageReleaseFile,
    ISourcePackageReleaseFile,
)
from lp.testing import TestCase


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
        self.user_defined_fields = user_defined_fields or []
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
        filetype=None,
        user_defined_fields=None,
        ci_build=None,
    ):
        self.libraryfile = FakeLibraryFileAlias(contents, filename)
        if release_type == FakeReleaseType.SOURCE:
            self.filetype = filetype or SourcePackageFileType.DSC
            self.sourcepackagerelease_id = release_id
            self.sourcepackagerelease = FakePackageRelease(
                release_id,
                user_defined_fields=user_defined_fields,
                ci_build=ci_build,
            )
            alsoProvides(self, ISourcePackageReleaseFile)
        elif release_type == FakeReleaseType.BINARY:
            self.filetype = filetype or BinaryPackageFileType.DEB
            self.binarypackagerelease_id = release_id
            self.binarypackagerelease = FakePackageRelease(
                release_id, user_defined_fields=user_defined_fields
            )
            alsoProvides(self, IBinaryPackageFile)


class SpecificTestException(Exception):
    pass


class PoolTestingFile:
    def __init__(
        self,
        pool,
        source_name,
        source_version,
        filename,
        release_type=FakeReleaseType.BINARY,
        release_id=1,
        filetype=None,
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
            filetype=filetype,
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


class TestPoolification(TestCase):
    def test_poolify_ok(self):
        """poolify should poolify properly"""
        cases = (
            ("foo", "main", Path("main/f/foo")),
            ("foo", "universe", Path("universe/f/foo")),
            ("libfoo", "main", Path("main/libf/libfoo")),
        )
        for case in cases:
            self.assertEqual(case[2], poolify(case[0], case[1]))

    def test_unpoolify_ok(self):
        cases = (
            (PurePath("main/f/foo"), "main", "foo", None),
            (PurePath("main/f/foo/foo_1.0.dsc"), "main", "foo", "foo_1.0.dsc"),
            (PurePath("universe/f/foo"), "universe", "foo", None),
            (PurePath("main/libf/libfoo"), "main", "libfoo", None),
        )
        for path, component, source, filename in cases:
            self.assertEqual((component, source, filename), unpoolify(path))

    def test_unpoolify_too_short(self):
        self.assertRaisesWithContent(
            ValueError,
            "Path 'main' is not in a valid pool form",
            unpoolify,
            PurePath("main"),
        )

    def test_unpoolify_too_long(self):
        self.assertRaisesWithContent(
            ValueError,
            "Path 'main/f/foo/bar/baz' is not in a valid pool form",
            unpoolify,
            PurePath("main/f/foo/bar/baz"),
        )

    def test_unpoolify_prefix_mismatch(self):
        self.assertRaisesWithContent(
            ValueError,
            "Source prefix 'a' does not match source 'foo'",
            unpoolify,
            PurePath("main/a/foo"),
        )


class TestPool(TestCase):
    def setUp(self):
        super().setUp()
        self.pool_path = self.makeTemporaryDirectory()
        self.temp_path = self.makeTemporaryDirectory()
        self.pool = DiskPool(
            FakeArchive(), self.pool_path, self.temp_path, BufferLogger()
        )

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

    def test_raise_deletes_temporary_file(self):
        """If ccopying fails, cleanup is called and same error is raised"""
        foo = PoolTestingFile(
            pool=self.pool,
            source_name="foo",
            source_version="1.0",
            filename="foo-1.0.deb",
        )

        with mock.patch(
            "lp.archivepublisher.diskpool.copy_and_close",
            side_effect=SpecificTestException,
        ), mock.patch.object(
            _diskpool_atomicfile, "cleanup_temporary_path"
        ) as mock_cleanup:
            self.assertRaises(SpecificTestException, foo.addToPool, "universe")

        self.assertEqual(mock_cleanup.call_count, 1)
        self.assertFalse(foo.checkIsFile("universe"))

    def test_diskpool_atomicfile(self):
        """Temporary files are properly removed"""
        target_path = Path(self.makeTemporaryDirectory() + "/temp.file")
        foo = _diskpool_atomicfile(target_path, "wb")

        self.assertTrue(foo.tempname.exists())
        foo.cleanup_temporary_path()
        self.assertFalse(foo.tempname.exists())
