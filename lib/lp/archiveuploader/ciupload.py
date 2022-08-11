# Copyright 2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Process a CI upload."""

__all__ = [
    "CIUpload",
]

import json
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
        # The upload path is structured as
        # .../incoming/<BUILD_COOKIE>/<ARCHIVE_ID>/<DISTRIBUTION_NAME>.
        # This is historical and doesn't necessarily make a lot of sense for
        # CI builds, but we need to fit into how the rest of the build farm
        # works.
        upload_path = os.path.join(
            self.upload_path, str(build.archive.id), build.distribution.name
        )
        # we assume first level directories are job directories
        if os.path.isdir(upload_path):
            job_directories = [
                d.name for d in os.scandir(upload_path) if d.is_dir()
            ]
        else:
            job_directories = []
        for job_directory in job_directories:
            artifacts[job_directory] = []
            for dirpath, _, filenames in os.walk(
                os.path.join(upload_path, job_directory)
            ):
                for filename in filenames:
                    artifacts[job_directory].append(
                        os.path.join(dirpath, filename)
                    )

        for job_id in build.results:
            report = build.getOrCreateRevisionStatusReport(job_id)

            # attach log file
            log_file = os.path.join(upload_path, job_id + ".log")
            try:
                with open(log_file, mode="rb") as f:
                    report.setLog(f.read())
            except FileNotFoundError as e:
                raise UploadError(
                    "log file `%s` for job `%s` not found"
                    % (e.filename, job_id)
                ) from e

            # attach properties, if available
            properties_file = os.path.join(upload_path, job_id + ".properties")
            try:
                with open(properties_file) as f:
                    report.update(properties=json.load(f))
            except FileNotFoundError:
                pass

            # attach artifacts
            for file_path in artifacts.get(job_id, []):
                with open(file_path, mode="rb") as f:
                    report.attach(
                        name=os.path.basename(file_path), data=f.read()
                    )

        self.logger.debug("Updating %s" % build.title)
        build.updateStatus(BuildStatus.FULLYBUILT)

        self.logger.debug("Finished upload.")
