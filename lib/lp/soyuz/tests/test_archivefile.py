# Copyright 2016-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""ArchiveFile tests."""

import os
from datetime import timedelta

import transaction
from storm.store import Store
from testtools.matchers import AfterPreprocessing, Equals, Is, MatchesStructure
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.services.database.sqlbase import (
    flush_database_caches,
    get_transaction_timestamp,
)
from lp.services.osutils import open_for_writing
from lp.soyuz.interfaces.archivefile import IArchiveFileSet
from lp.testing import TestCaseWithFactory
from lp.testing.layers import LaunchpadZopelessLayer


def read_library_file(library_file):
    library_file.open()
    try:
        return library_file.read()
    finally:
        library_file.close()


class TestArchiveFile(TestCaseWithFactory):

    layer = LaunchpadZopelessLayer

    def test_new(self):
        archive = self.factory.makeArchive()
        library_file = self.factory.makeLibraryFileAlias()
        archive_file = getUtility(IArchiveFileSet).new(
            archive, "foo", "dists/foo", library_file
        )
        self.assertThat(
            archive_file,
            MatchesStructure(
                archive=Equals(archive),
                container=Equals("foo"),
                path=Equals("dists/foo"),
                library_file=Equals(library_file),
                date_created=Equals(
                    get_transaction_timestamp(Store.of(archive_file))
                ),
                date_superseded=Is(None),
                scheduled_deletion_date=Is(None),
            ),
        )

    def test_newFromFile(self):
        root = self.makeTemporaryDirectory()
        with open_for_writing(os.path.join(root, "dists/foo"), "w") as f:
            f.write("abc\n")
        archive = self.factory.makeArchive()
        with open(os.path.join(root, "dists/foo"), "rb") as f:
            archive_file = getUtility(IArchiveFileSet).newFromFile(
                archive, "foo", "dists/foo", f, 4, "text/plain"
            )
        now = get_transaction_timestamp(Store.of(archive_file))
        transaction.commit()
        self.assertThat(
            archive_file,
            MatchesStructure(
                archive=Equals(archive),
                container=Equals("foo"),
                path=Equals("dists/foo"),
                library_file=AfterPreprocessing(
                    read_library_file, Equals(b"abc\n")
                ),
                date_created=Equals(now),
                date_superseded=Is(None),
                scheduled_deletion_date=Is(None),
            ),
        )

    def test_getByArchive(self):
        archives = [self.factory.makeArchive(), self.factory.makeArchive()]
        archive_files = []
        now = get_transaction_timestamp(Store.of(archives[0]))
        for archive in archives:
            archive_files.append(
                self.factory.makeArchiveFile(
                    archive=archive, scheduled_deletion_date=now
                )
            )
            archive_files.append(
                self.factory.makeArchiveFile(archive=archive, container="foo")
            )
        archive_file_set = getUtility(IArchiveFileSet)
        self.assertContentEqual(
            archive_files[:2], archive_file_set.getByArchive(archives[0])
        )
        self.assertContentEqual(
            [archive_files[1]],
            archive_file_set.getByArchive(archives[0], container="foo"),
        )
        self.assertContentEqual(
            [], archive_file_set.getByArchive(archives[0], container="bar")
        )
        self.assertContentEqual(
            [archive_files[1]],
            archive_file_set.getByArchive(
                archives[0], path=archive_files[1].path
            ),
        )
        self.assertContentEqual(
            [], archive_file_set.getByArchive(archives[0], path="other")
        )
        self.assertContentEqual(
            [archive_files[0]],
            archive_file_set.getByArchive(archives[0], condemned=True),
        )
        self.assertContentEqual(
            [archive_files[1]],
            archive_file_set.getByArchive(archives[0], condemned=False),
        )
        self.assertContentEqual(
            archive_files[2:], archive_file_set.getByArchive(archives[1])
        )
        self.assertContentEqual(
            [archive_files[3]],
            archive_file_set.getByArchive(archives[1], container="foo"),
        )
        self.assertContentEqual(
            [], archive_file_set.getByArchive(archives[1], container="bar")
        )
        self.assertContentEqual(
            [archive_files[3]],
            archive_file_set.getByArchive(
                archives[1], path=archive_files[3].path
            ),
        )
        self.assertContentEqual(
            [], archive_file_set.getByArchive(archives[1], path="other")
        )
        self.assertContentEqual(
            [archive_files[2]],
            archive_file_set.getByArchive(archives[1], condemned=True),
        )
        self.assertContentEqual(
            [archive_files[3]],
            archive_file_set.getByArchive(archives[1], condemned=False),
        )
        self.assertContentEqual(
            [archive_files[0]],
            archive_file_set.getByArchive(
                archives[0],
                sha256=archive_files[0].library_file.content.sha256,
            ),
        )
        self.assertContentEqual(
            [], archive_file_set.getByArchive(archives[0], sha256="nonsense")
        )

    def test_getByArchive_path_parent(self):
        archive = self.factory.makeArchive()
        archive_files = [
            self.factory.makeArchiveFile(archive=archive, path=path)
            for path in (
                "dists/jammy/InRelease",
                "dists/jammy/Release",
                "dists/jammy/main/binary-amd64/Release",
            )
        ]
        archive_file_set = getUtility(IArchiveFileSet)
        self.assertContentEqual(
            archive_files[:2],
            archive_file_set.getByArchive(archive, path_parent="dists/jammy"),
        )
        self.assertContentEqual(
            [archive_files[2]],
            archive_file_set.getByArchive(
                archive, path_parent="dists/jammy/main/binary-amd64"
            ),
        )
        self.assertContentEqual(
            [],
            archive_file_set.getByArchive(archive, path_parent="dists/xenial"),
        )

    def test_scheduleDeletion(self):
        archive_files = [self.factory.makeArchiveFile() for _ in range(3)]
        getUtility(IArchiveFileSet).scheduleDeletion(
            archive_files[:2], timedelta(days=1)
        )
        flush_database_caches()
        now = get_transaction_timestamp(Store.of(archive_files[0]))
        tomorrow = now + timedelta(days=1)
        self.assertEqual(now, archive_files[0].date_superseded)
        self.assertEqual(tomorrow, archive_files[0].scheduled_deletion_date)
        self.assertEqual(now, archive_files[1].date_superseded)
        self.assertEqual(tomorrow, archive_files[1].scheduled_deletion_date)
        self.assertIsNone(archive_files[2].date_superseded)
        self.assertIsNone(archive_files[2].scheduled_deletion_date)

    def test_getContainersToReap(self):
        archive = self.factory.makeArchive()
        archive_files = []
        for container in ("release:foo", "other:bar", "baz"):
            for _ in range(2):
                archive_files.append(
                    self.factory.makeArchiveFile(
                        archive=archive, container=container
                    )
                )
        other_archive = self.factory.makeArchive()
        archive_files.append(
            self.factory.makeArchiveFile(
                archive=other_archive, container="baz"
            )
        )
        now = get_transaction_timestamp(Store.of(archive_files[0]))
        removeSecurityProxy(
            archive_files[0]
        ).scheduled_deletion_date = now - timedelta(days=1)
        removeSecurityProxy(
            archive_files[1]
        ).scheduled_deletion_date = now - timedelta(days=1)
        removeSecurityProxy(
            archive_files[2]
        ).scheduled_deletion_date = now + timedelta(days=1)
        removeSecurityProxy(
            archive_files[6]
        ).scheduled_deletion_date = now - timedelta(days=1)
        archive_file_set = getUtility(IArchiveFileSet)
        self.assertContentEqual(
            ["release:foo"], archive_file_set.getContainersToReap(archive)
        )
        self.assertContentEqual(
            ["baz"], archive_file_set.getContainersToReap(other_archive)
        )
        removeSecurityProxy(
            archive_files[3]
        ).scheduled_deletion_date = now - timedelta(days=1)
        self.assertContentEqual(
            ["release:foo", "other:bar"],
            archive_file_set.getContainersToReap(archive),
        )
        self.assertContentEqual(
            ["release:foo"],
            archive_file_set.getContainersToReap(
                archive, container_prefix="release:"
            ),
        )

    def test_delete(self):
        archive = self.factory.makeArchive()
        archive_files = [
            self.factory.makeArchiveFile(archive=archive) for _ in range(4)
        ]
        expected_rows = [
            (
                archive_file.container,
                archive_file.path,
                archive_file.library_file.content.sha256,
            )
            for archive_file in archive_files[:2]
        ]
        archive_file_set = getUtility(IArchiveFileSet)
        rows = archive_file_set.delete(archive_files[:2])
        self.assertContentEqual(expected_rows, rows)
        self.assertContentEqual(
            archive_files[2:], archive_file_set.getByArchive(archive)
        )
