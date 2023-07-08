# Copyright 2010-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Tests for `ExportResult`."""

import hashlib
import io
import os.path

from lp.services.librarianserver.testing.fake import FakeLibrarian
from lp.services.log.logger import DevNullLogger
from lp.testing import TestCaseWithFactory
from lp.testing.layers import ZopelessDatabaseLayer
from lp.translations.scripts.po_export_queue import ExportResult


class FakeExportedTranslationFile:
    """Fake `IExportedTranslationFile` for testing."""

    def __init__(self, path, content, content_type):
        self.path = path
        base, ext = os.path.splitext(path)
        self.file_extension = ext
        self.size = len(content)
        self.content = content
        self.file = io.BytesIO(content)
        self.content_type = content_type

    def read(self, *args, **kwargs):
        return self.file.read(*args, **kwargs)


class TestExportResult(TestCaseWithFactory):
    layer = ZopelessDatabaseLayer

    def setUp(self):
        super().setUp()
        # In development mode, the librarian is normally configured to
        # generate HTTP URLs.  Enable HTTPS URLs so that we can test that
        # ExportResult uses them.
        self.pushConfig("librarian", use_https=True)

    def makeExportResult(self):
        request = [self.factory.makePOFile()]
        requester = self.factory.makePerson()
        logger = DevNullLogger()
        return ExportResult(requester, request, logger)

    def makeExportedTranslationFile(self):
        filename = self.factory.getUniqueUnicode()
        content = self.factory.getUniqueBytes()
        mime_type = "text/plain"
        return FakeExportedTranslationFile(filename, content, mime_type)

    def test_upload_exported_file(self):
        librarian = self.useFixture(FakeLibrarian())
        export = self.makeExportedTranslationFile()
        export_result = self.makeExportResult()
        export_result.setExportFile(export)
        export_result.upload()

        self.assertStartsWith(export_result.url, "https://")
        sha256 = hashlib.sha256(export.content).hexdigest()
        self.assertEqual(
            sha256, list(librarian.aliases.values())[0].content.sha256
        )
        alias = librarian.findBySHA256(sha256)
        self.assertEqual(export.path, alias.filename)

    def test_upload_without_exported_file_does_nothing(self):
        export_result = self.makeExportResult()
        export_result.upload()
        self.assertIs(None, export_result.url)
