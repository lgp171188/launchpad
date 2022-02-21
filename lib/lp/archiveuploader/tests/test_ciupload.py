# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test uploads of CIBuilds."""

import json
import os

from storm.store import Store
from zope.component import getUtility

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


class TestCIUBuildUploads(TestUploadProcessorBase):
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
        """If no jobs run, no `jobs.json` will be created.

        This results in an `UploadError` / rejected upload."""
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

    def test_requires_log_file(self):
        # create "jobs.json"
        path = os.path.join(self.incoming_folder, "test", "jobs.json")
        content = {
            'build:0':
                {
                    'result': 'SUCCEEDED',
                }
        }
        write_file(path, json.dumps(content).encode("utf-8"))

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

    def test_triggers_store_upload_for_completed_ci_builds(self):
        # create "jobs.json"
        path = os.path.join(self.incoming_folder, "test", "jobs.json")
        content = {
            'build:0':
                {
                    'log': 'test_file_hash',
                    'result': 'SUCCEEDED',
                }
        }
        write_file(path, json.dumps(content).encode("utf-8"))

        # create log file
        path = os.path.join(self.incoming_folder, "test", "build:0.log")
        content = "some log content"
        write_file(path, content.encode("utf-8"))

        # create artifact
        path = os.path.join(
            self.incoming_folder, "test", "build:0", "ci.whl")
        content = b"abc"
        write_file(path, content)

        # create artifact in a sub-directory
        path = os.path.join(
            self.incoming_folder, "test", "build:0", "sub", "test.whl")
        content = b"abc"
        write_file(path, content)

        revision_status_report = self.factory.makeRevisionStatusReport(
            title="build:0",
            ci_build=self.build,
        )
        Store.of(revision_status_report).flush()

        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        self.assertEqual(UploadStatusEnum.ACCEPTED, result)
        self.assertEqual(BuildStatus.FULLYBUILT, self.build.status)

        artifact_urls = getUtility(
            IRevisionStatusReportSet
        ).getByCIBuildAndTitle(self.build, "build:0").getArtifactURLs(
            RevisionStatusArtifactType.BINARY
        )
        self.assertEqual(
            {"ci.whl", "test.whl"},
            {url.rsplit("/")[-1] for url in artifact_urls}
        )

    def test_requires_valid_result_status(self):
        # create "jobs.json"
        path = os.path.join(self.incoming_folder, "test", "jobs.json")
        content = {
            'build:0':
                {
                    'result': 'MADE_UP_STATUS',  # this is an invalid result
                }
        }
        write_file(path, json.dumps(content).encode("utf-8"))

        # create log file
        path = os.path.join(self.incoming_folder, "test", "build:0.log")
        content = "some log content"
        write_file(path, content.encode("utf-8"))

        # create artifact
        path = os.path.join(
            self.incoming_folder, "test", "build:0", "ci.whl")
        content = b"abc"
        write_file(path, content)

        # create artifact in a sub-directory
        path = os.path.join(
            self.incoming_folder, "test", "build:0", "sub", "test.whl")
        content = b"abc"
        write_file(path, content)

        revision_status_report = self.factory.makeRevisionStatusReport(
            title="build:0",
            ci_build=self.build,
        )
        Store.of(revision_status_report).flush()

        handler = UploadHandler.forProcessor(
            self.uploadprocessor,
            self.incoming_folder,
            "test",
            self.build,
        )

        result = handler.processCIResult(self.log)

        # we explicitly provided an invalid result status
        # which causes a rejected upload
        self.assertEqual(
            UploadStatusEnum.REJECTED, result
        )

    def test_creates_revision_status_report_if_not_present(self):
        # create "jobs.json"
        path = os.path.join(self.incoming_folder, "test", "jobs.json")
        content = {
            'build:0':
                {
                    'log': 'test_file_hash',
                    'result': 'SUCCEEDED',
                }
        }
        write_file(path, json.dumps(content).encode("utf-8"))

        # create log file
        path = os.path.join(self.incoming_folder, "test", "build:0.log")
        content = "some log content"
        write_file(path, content.encode("utf-8"))

        # create artifact
        path = os.path.join(
            self.incoming_folder, "test", "build:0", "ci.whl")
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
