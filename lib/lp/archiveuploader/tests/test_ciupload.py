# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test uploads of CIBuilds."""

import os
from urllib.parse import quote

from storm.store import Store
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.archiveuploader.tests.test_uploadprocessor import (
    TestUploadProcessorBase,
    )
from lp.archiveuploader.uploadprocessor import (
    UploadHandler,
    UploadStatusEnum,
    )
from lp.buildmaster.enums import BuildStatus
from lp.code.enums import RevisionStatusArtifactType
from lp.code.interfaces.revisionstatus import IRevisionStatusReportSet
from lp.services.osutils import write_file


class TestCIBuildUploads(TestUploadProcessorBase):
    """End-to-end tests of CIBuild uploads."""

    def setUp(self):
        super().setUp()
        self.switchToAdmin()
        self.build = self.factory.makeCIBuild()
        self.build.updateStatus(BuildStatus.UPLOADING)
        Store.of(self.build).flush()
        self.switchToUploader()
        self.uploadprocessor = self.getUploadProcessor(
            self.layer.txn, builds=True
        )

    def test_requires_completed_CI_job(self):
        """If no jobs run, no results will be saved.

        This results in an `UploadError` / rejected upload.
        """
        os.makedirs(os.path.join(self.incoming_folder, "test"))
        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        self.assertEqual(
            UploadStatusEnum.REJECTED, result
        )

    def test_requires_upload_path(self):
        removeSecurityProxy(self.build).results = {
            'build:0': {'result': 'SUCCEEDED'},
        }
        os.makedirs(os.path.join(self.incoming_folder, "test"))
        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        # we explicitly provided no log file, which causes a rejected upload
        self.assertEqual(
            UploadStatusEnum.REJECTED, result
        )

    def test_requires_log_file(self):
        removeSecurityProxy(self.build).results = {
            'build:0': {'result': 'SUCCEEDED'},
        }
        os.makedirs(os.path.join(self.incoming_folder, "test"))
        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )
        upload_path = os.path.join(
            self.incoming_folder, "test", str(self.build.archive.id),
            self.build.distribution.name)
        os.makedirs(upload_path)

        result = handler.processCIResult(self.log)

        # we explicitly provided no log file, which causes a rejected upload
        self.assertEqual(
            UploadStatusEnum.REJECTED, result
        )

    def test_no_artifacts(self):
        # It is possible for a job to produce no artifacts.
        removeSecurityProxy(self.build).results = {
            'build:0': {
                'log': 'test_file_hash',
                'result': 'SUCCEEDED',
            },
        }
        upload_path = os.path.join(
            self.incoming_folder, "test", str(self.build.archive.id),
            self.build.distribution.name)
        write_file(os.path.join(upload_path, "build:0.log"), b"log content")
        report = self.build.getOrCreateRevisionStatusReport("build:0")
        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        self.assertEqual(UploadStatusEnum.ACCEPTED, result)
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
        log_urls = report.getArtifactURLs(RevisionStatusArtifactType.LOG)
        self.assertEqual(
            {quote("build:0-%s.txt" % self.build.commit_sha1)},
            {url.rsplit("/")[-1] for url in log_urls}
        )
        self.assertEqual(
            [], report.getArtifactURLs(RevisionStatusArtifactType.BINARY)
        )

    def test_triggers_store_upload_for_completed_ci_builds(self):
        removeSecurityProxy(self.build).results = {
            'build:0': {
                'log': 'test_file_hash',
                'result': 'SUCCEEDED',
            },
        }
        upload_path = os.path.join(
            self.incoming_folder, "test", str(self.build.archive.id),
            self.build.distribution.name)

        # create log file
        path = os.path.join(upload_path, "build:0.log")
        content = "some log content"
        write_file(path, content.encode("utf-8"))

        # create artifact
        path = os.path.join(upload_path, "build:0", "ci.whl")
        content = b"abc"
        write_file(path, content)

        # create artifact in a sub-directory
        path = os.path.join(upload_path, "build:0", "sub", "test.whl")
        content = b"abc"
        write_file(path, content)

        report = self.build.getOrCreateRevisionStatusReport("build:0")

        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        self.assertEqual(UploadStatusEnum.ACCEPTED, result)
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)

        log_urls = report.getArtifactURLs(RevisionStatusArtifactType.LOG)
        self.assertEqual(
            {quote("build:0-%s.txt" % self.build.commit_sha1)},
            {url.rsplit("/")[-1] for url in log_urls}
        )
        artifact_urls = report.getArtifactURLs(
            RevisionStatusArtifactType.BINARY
        )
        self.assertEqual(
            {"ci.whl", "test.whl"},
            {url.rsplit("/")[-1] for url in artifact_urls}
        )

    def test_creates_revision_status_report_if_not_present(self):
        removeSecurityProxy(self.build).results = {
            'build:0': {
                'log': 'test_file_hash',
                'result': 'SUCCEEDED',
            },
        }
        upload_path = os.path.join(
            self.incoming_folder, "test", str(self.build.archive.id),
            self.build.distribution.name)

        # create log file
        path = os.path.join(upload_path, "build:0.log")
        content = "some log content"
        write_file(path, content.encode("utf-8"))

        # create artifact
        path = os.path.join(upload_path, "build:0", "ci.whl")
        content = b"abc"
        write_file(path, content)

        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        self.assertEqual(
            self.build,
            getUtility(
                IRevisionStatusReportSet
            ).getByCIBuildAndTitle(self.build, "build:0").ci_build
        )
        self.assertEqual(UploadStatusEnum.ACCEPTED, result)
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)
