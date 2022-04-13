# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a CI upload."""

__all__ = [
    "CIUpload",
    ]

import os

from lp.archiveuploader.utils import UploadError
from lp.buildmaster.enums import BuildStatus


class CIUpload:
    """An upload from a pipeline of CI jobs."""

    def __init__(self, upload_path, logger):
        """Create a `CIUpload`.

        :param upload_path: A directory containing files to upload.
        :param logger: The logger to be used.
        """
        self.upload_path = upload_path
        self.logger = logger

    def process(self, build):
        """Process this upload, loading it into the database."""
        self.logger.debug("Beginning processing.")

        if not build.results:
            raise UploadError("Build did not run any jobs.")

        # collect all artifacts
        artifacts = {}
        # we assume first level directories are job directories
        job_directories = [
            d.name for d in os.scandir(self.upload_path) if d.is_dir()
        ]
        for job_directory in job_directories:
            artifacts[job_directory] = []
            for dirpath, _, filenames in os.walk(os.path.join(
                self.upload_path, job_directory
            )):
                for filename in filenames:
                    artifacts[job_directory].append(os.path.join(
                        dirpath, filename
                    ))

        for job_id in build.results:
            report = build.getOrCreateRevisionStatusReport(job_id)

            # attach log file
            log_file = os.path.join(self.upload_path, job_id + ".log")
            try:
                with open(log_file, mode="rb") as f:
                    report.setLog(f.read())
            except FileNotFoundError as e:
                raise UploadError(
                    "log file `%s` for job `%s` not found" % (
                        e.filename, job_id)
                ) from e

            # attach artifacts
            for file_path in artifacts[job_id]:
                with open(file_path, mode="rb") as f:
                    report.attach(
                        name=os.path.basename(file_path), data=f.read()
                    )

        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)

        self.logger.debug("Finished upload.")
