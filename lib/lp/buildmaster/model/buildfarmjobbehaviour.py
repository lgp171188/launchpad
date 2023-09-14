# Copyright 2009-2022 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Base and idle BuildFarmJobBehaviour classes."""

__all__ = [
    "BuildFarmJobBehaviourBase",
]

import gzip
import logging
import os
import tempfile
from collections import OrderedDict
from datetime import datetime

import transaction
from twisted.internet import defer
from twisted.web import xmlrpc
from zope.component import getUtility
from zope.security.proxy import removeSecurityProxy

from lp.buildmaster.enums import (
    BuildBaseImageType,
    BuildFarmJobType,
    BuildStatus,
)
from lp.buildmaster.interfaces.builder import BuildDaemonError, CannotBuild
from lp.buildmaster.interfaces.buildfarmjobbehaviour import BuildArgs
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.config import config
from lp.services.helpers import filenameToContentType
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.librarian.utils import copy_and_close
from lp.services.propertycache import cachedproperty
from lp.services.statsd.interfaces.statsd_client import IStatsdClient
from lp.services.utils import sanitise_urls
from lp.services.webapp import canonical_url

WORKER_LOG_FILENAME = "buildlog"


class BuildFarmJobBehaviourBase:
    """Ensures that all behaviours inherit the same initialization.

    All build-farm job behaviours should inherit from this.
    """

    image_types = [BuildBaseImageType.CHROOT]

    def __init__(self, build):
        """Store a reference to the job_type with which we were created."""
        self.build = build
        self._builder = None

    @cachedproperty
    def _authserver(self):
        return xmlrpc.Proxy(
            config.builddmaster.authentication_endpoint.encode("UTF-8"),
            connectTimeout=config.builddmaster.authentication_timeout,
        )

    @property
    def archive(self):
        if self.build is not None:
            return self.build.archive
        else:
            return None

    @property
    def distro_arch_series(self):
        if self.build is not None:
            return self.build.distro_arch_series
        else:
            return None

    @property
    def pocket(self):
        if self.build is not None:
            return self.build.pocket
        else:
            return PackagePublishingPocket.RELEASE

    def setBuilder(self, builder, worker):
        """The builder should be set once and not changed."""
        self._builder = builder
        self._worker = worker

    def determineFilesToSend(self):
        """The default behaviour is to send no files."""
        return {}

    def issueMacaroon(self):
        raise NotImplementedError(
            "This build type does not support accessing private resources."
        )

    def extraBuildArgs(self, logger=None) -> BuildArgs:
        """The default behaviour is to send only common extra arguments."""
        return {
            "arch_tag": self.distro_arch_series.architecturetag,
            "archive_private": self.archive.private,
            "build_url": canonical_url(self.build),
            "builder_constraints": removeSecurityProxy(
                self.build.builder_constraints or []
            ),
            "fast_cleanup": self._builder.virtualized,
            "series": self.distro_arch_series.distroseries.name,
        }

    @defer.inlineCallbacks
    def composeBuildRequest(self, logger):
        args = yield self.extraBuildArgs(logger=logger)
        filemap = yield self.determineFilesToSend()
        return (
            self.builder_type,
            self.distro_arch_series,
            self.pocket,
            filemap,
            args,
        )

    def verifyBuildRequest(self, logger):
        """The default behaviour is a no-op."""
        pass

    def redactXmlrpcArguments(self, args):
        # we do not want to have secrets in logs
        return sanitise_urls(repr(args))

    @defer.inlineCallbacks
    def dispatchBuildToWorker(self, logger):
        """See `IBuildFarmJobBehaviour`."""
        cookie = self.build.build_cookie
        logger.info(
            "Preparing job %s (%s) on %s."
            % (cookie, self.build.title, self._builder.url)
        )

        builder_type, das, pocket, files, args = yield (
            self.composeBuildRequest(logger)
        )

        # First cache the chroot and any other files that the job needs.
        pocket_chroot = None
        for image_type in self.image_types:
            pocket_chroot = das.getPocketChroot(
                pocket=pocket, image_type=image_type
            )
            if pocket_chroot is not None:
                break
        if pocket_chroot is None:
            raise CannotBuild(
                "Unable to find a chroot for %s" % das.displayname
            )
        chroot = pocket_chroot.chroot
        args["image_type"] = pocket_chroot.image_type.name.lower()

        filename_to_sha1 = OrderedDict()
        dl = []
        dl.append(
            self._worker.sendFileToWorker(
                logger=logger, url=chroot.http_url, sha1=chroot.content.sha1
            )
        )
        for filename, params in files.items():
            filename_to_sha1[filename] = params["sha1"]
            dl.append(self._worker.sendFileToWorker(logger=logger, **params))
        yield defer.gatherResults(dl)

        combined_args = {
            "builder_type": builder_type,
            "chroot_sha1": chroot.content.sha1,
            "filemap": filename_to_sha1,
            "args": args,
        }
        logger.info(
            "Dispatching job %s (%s) to %s:\n%s"
            % (
                cookie,
                self.build.title,
                self._builder.url,
                self.redactXmlrpcArguments(combined_args),
            )
        )

        (status, info) = yield self._worker.build(
            cookie, builder_type, chroot.content.sha1, filename_to_sha1, args
        )

        # Update stats
        job_type = getattr(self.build, "job_type", None)
        job_type_name = job_type.name if job_type else "UNKNOWN"
        statsd_client = getUtility(IStatsdClient)
        statsd_client.incr(
            "build.count",
            labels={
                "job_type": job_type_name,
                "builder_name": self._builder.name,
                "region": self._builder.region,
            },
        )

        logger.info(
            "Job %s (%s) started on %s: %s %s"
            % (cookie, self.build.title, self._builder.url, status, info)
        )

    def getUploadDirLeaf(self, build_cookie, now=None):
        """See `IPackageBuild`."""
        if now is None:
            now = datetime.now()
        timestamp = now.strftime("%Y%m%d-%H%M%S")
        return "%s-%s" % (timestamp, build_cookie)

    def transferWorkerFileToLibrarian(self, file_sha1, filename, private):
        """Transfer a file from the worker to the librarian.

        :param file_sha1: The file's sha1, which is how the file is addressed
            in the worker XMLRPC protocol. Specially, the file_sha1 'buildlog'
            will cause the build log to be retrieved and gzipped.
        :param filename: The name of the file to be given to the librarian
            file alias.
        :param private: True if the build is for a private archive.
        :return: A Deferred that calls back with a librarian file alias.
        """
        out_file_fd, out_file_name = tempfile.mkstemp(suffix=".buildlog")
        os.close(out_file_fd)

        def got_file(ignored, filename, out_file_name):
            try:
                # If the requested file is the 'buildlog' compress it
                # using gzip before storing in Librarian.
                if file_sha1 == "buildlog":
                    out_file = open(out_file_name, "rb")
                    filename += ".gz"
                    out_file_name += ".gz"
                    gz_file = gzip.GzipFile(out_file_name, mode="wb")
                    copy_and_close(out_file, gz_file)
                    os.remove(out_file_name.replace(".gz", ""))

                # Open the file, seek to its end position, count and seek to
                # beginning, ready for adding to the Librarian.
                out_file = open(out_file_name, "rb")
                out_file.seek(0, 2)
                bytes_written = out_file.tell()
                out_file.seek(0)

                library_file = getUtility(ILibraryFileAliasSet).create(
                    filename,
                    bytes_written,
                    out_file,
                    contentType=filenameToContentType(filename),
                    restricted=private,
                )
            finally:
                # Remove the temporary file.
                os.remove(out_file_name)

            return library_file.id

        d = self._worker.getFile(file_sha1, out_file_name)
        d.addCallback(got_file, filename, out_file_name)
        return d

    def getLogFileName(self):
        """Return the preferred file name for this job's log."""
        return "buildlog.txt"

    def getLogFromWorker(self, queue_item):
        """Return a Deferred which fires when the log is in the librarian."""
        d = self.transferWorkerFileToLibrarian(
            WORKER_LOG_FILENAME, self.getLogFileName(), self.build.is_private
        )
        return d

    @defer.inlineCallbacks
    def storeLogFromWorker(self, worker_status):
        """See `IBuildFarmJob`."""
        lfa_id = yield self.getLogFromWorker(self.build.buildqueue_record)
        self.build.setLog(lfa_id)
        transaction.commit()

    def verifySuccessfulBuild(self):
        """See `IBuildFarmJobBehaviour`."""
        build = self.build

        # Explode before collecting a binary that is denied in this
        # distroseries/pocket/archive
        assert build.archive.canModifySuite(
            build.distro_series, build.pocket
        ), "%s (%s) can not be built for pocket %s in %s: illegal status" % (
            build.title,
            build.id,
            build.pocket.name,
            build.archive,
        )

    @staticmethod
    def extractBuildStatus(worker_status):
        """Read build status name.

        :param worker_status: build status dict from BuilderWorker.status.
        :return: the unqualified status name, e.g. "OK".
        """
        status_string = worker_status["build_status"]
        lead_string = "BuildStatus."
        assert status_string.startswith(lead_string), (
            "Malformed status string: '%s'" % status_string
        )
        return status_string[len(lead_string) :]

    # The list of build status values for which email notifications are
    # allowed to be sent. It is up to each callback as to whether it will
    # consider sending a notification but it won't do so if the status is not
    # in this list.
    ALLOWED_STATUS_NOTIFICATIONS = ["PACKAGEFAIL", "CHROOTFAIL"]

    @defer.inlineCallbacks
    def handleStatus(self, bq, worker_status):
        """See `IBuildFarmJobBehaviour`."""
        if bq != self.build.buildqueue_record:
            raise AssertionError(
                "%r != %r" % (bq, self.build.buildqueue_record)
            )
        from lp.buildmaster.manager import BUILDD_MANAGER_LOG_NAME

        logger = logging.getLogger(BUILDD_MANAGER_LOG_NAME)
        builder_status = worker_status["builder_status"]

        if builder_status == "BuilderStatus.WAITING":
            # Build has finished.
            status = self.extractBuildStatus(worker_status)
            notify = status in self.ALLOWED_STATUS_NOTIFICATIONS
            fail_status_map = {
                "PACKAGEFAIL": BuildStatus.FAILEDTOBUILD,
                "DEPFAIL": BuildStatus.MANUALDEPWAIT,
                "CHROOTFAIL": BuildStatus.CHROOTWAIT,
            }
            if self.build.status == BuildStatus.CANCELLING:
                fail_status_map["ABORTED"] = BuildStatus.CANCELLED

            logger.info(
                "Processing finished job %s (%s) from builder %s: %s"
                % (
                    self.build.build_cookie,
                    self.build.title,
                    self.build.buildqueue_record.builder.name,
                    status,
                )
            )
            build_status = None
            if status == "OK":
                yield self.storeLogFromWorker(worker_status)
                # handleSuccess will sometimes perform write operations
                # outside the database transaction, so a failure between
                # here and the commit can cause duplicated results. For
                # example, a BinaryPackageBuild will end up in the upload
                # queue twice if notify() crashes.
                build_status = yield self.handleSuccess(worker_status, logger)
            elif status in fail_status_map:
                yield self.storeLogFromWorker(worker_status)
                build_status = fail_status_map[status]
            else:
                raise BuildDaemonError(
                    "Build returned unexpected status: %r" % status
                )
        else:
            # The build status remains unchanged.
            build_status = bq.specific_build.status

        # Set the status and (if the build has finished) dequeue the build
        # atomically.  Setting the status to UPLOADING constitutes handoff to
        # process-upload, so doing that before we've removed the BuildQueue
        # causes races.
        self.build.updateStatus(
            build_status, builder=bq.builder, worker_status=worker_status
        )

        if builder_status == "BuilderStatus.WAITING":
            if notify:
                self.build.notify()
            self.build.buildqueue_record.destroySelf()

        transaction.commit()

    @defer.inlineCallbacks
    def _downloadFiles(self, worker_status, upload_path, logger):
        filemap = worker_status["filemap"]
        filenames_to_download = []
        for filename, sha1 in filemap.items():
            logger.info(
                "Grabbing file: %s (%s)"
                % (filename, self._worker.getURL(sha1))
            )
            out_file_name = os.path.join(upload_path, filename)
            # If the evaluated output file name is not within our
            # upload path, then we don't try to copy this or any
            # subsequent files.
            if not os.path.realpath(out_file_name).startswith(upload_path):
                raise BuildDaemonError(
                    "Build returned a file named '%s'." % filename
                )
            filenames_to_download.append((sha1, out_file_name))
        yield self._worker.getFiles(filenames_to_download, logger=logger)

    @defer.inlineCallbacks
    def handleSuccess(self, worker_status, logger):
        """Handle a package that built successfully.

        Once built successfully, we pull the files, store them in a
        directory, store build information and push them through the
        uploader.
        """
        build = self.build

        # If this is a binary package build, discard it if its source is
        # no longer published.
        if build.job_type == BuildFarmJobType.PACKAGEBUILD:
            build = build.buildqueue_record.specific_build
            if not build.current_source_publication:
                return BuildStatus.SUPERSEDED

        self.verifySuccessfulBuild()

        # Ensure we have the correct build root as:
        # <BUILDMASTER_ROOT>/incoming/<UPLOAD_LEAF>/<TARGET_PATH>/[FILES]
        root = os.path.abspath(config.builddmaster.root)

        # Create a single directory to store build result files.
        upload_leaf = self.getUploadDirLeaf(self.build.build_cookie)
        grab_dir = os.path.join(root, "grabbing", upload_leaf)
        logger.debug("Storing build result at '%s'" % grab_dir)

        # Build the right UPLOAD_PATH so the distribution and archive
        # can be correctly found during the upload:
        #       <archive_id>/distribution_name
        # for all destination archive types.
        upload_path = os.path.join(
            grab_dir, str(build.archive.id), build.distribution.name
        )
        os.makedirs(upload_path)

        # Indicate that downloads are in progress.
        build.updateStatus(BuildStatus.GATHERING, worker_status=worker_status)
        transaction.commit()

        yield self._downloadFiles(worker_status, upload_path, logger)

        transaction.commit()

        # Move the directory used to grab the binaries into incoming
        # atomically, so other bits don't have to deal with incomplete
        # uploads.
        logger.info(
            "Gathered %s completely. Moving %s to uploader queue."
            % (build.build_cookie, upload_leaf)
        )
        target_dir = os.path.join(root, "incoming")
        if not os.path.exists(target_dir):
            os.mkdir(target_dir)
        os.rename(grab_dir, os.path.join(target_dir, upload_leaf))

        return BuildStatus.UPLOADING
