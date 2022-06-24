# Copyright 2010-2015 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import io
import json
import logging
import os.path
import tarfile
import tempfile
import zipfile

from lazr.delegates import delegate_to
from pkginfo import Wheel
from storm.expr import And
from storm.locals import (
    Int,
    JSON,
    Reference,
    )
from wheel_filename import parse_wheel_filename
from zope.component import getUtility
from zope.interface import (
    implementer,
    provider,
    )
import zstandard

from lp.code.enums import RevisionStatusArtifactType
from lp.code.interfaces.cibuild import ICIBuildSet
from lp.code.interfaces.revisionstatus import IRevisionStatusArtifactSet
from lp.registry.interfaces.distroseries import IDistroSeriesSet
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.services.config import config
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IMasterStore
from lp.services.database.stormbase import StormBase
from lp.services.job.model.job import (
    EnumeratedSubclass,
    Job,
    )
from lp.services.job.runner import BaseRunnableJob
from lp.services.librarian.interfaces.client import LibrarianServerError
from lp.services.librarian.utils import copy_and_close
from lp.services.mail.sendmail import format_address_for_person
from lp.soyuz.enums import (
    ArchiveJobType,
    ArchiveRepositoryFormat,
    BinaryPackageFileType,
    BinaryPackageFormat,
    PackageUploadStatus,
    )
from lp.soyuz.interfaces.archivejob import (
    IArchiveJob,
    IArchiveJobSource,
    ICIBuildUploadJob,
    ICIBuildUploadJobSource,
    IPackageUploadNotificationJob,
    IPackageUploadNotificationJobSource,
    )
from lp.soyuz.interfaces.binarypackagename import IBinaryPackageNameSet
from lp.soyuz.interfaces.publishing import IPublishingSet
from lp.soyuz.interfaces.queue import IPackageUploadSet
from lp.soyuz.model.archive import Archive


@implementer(IArchiveJob)
class ArchiveJob(StormBase):
    """Base class for jobs related to Archives."""

    __storm_table__ = 'ArchiveJob'

    id = Int(primary=True)

    job_id = Int(name='job')
    job = Reference(job_id, Job.id)

    archive_id = Int(name='archive')
    archive = Reference(archive_id, Archive.id)

    job_type = DBEnum(enum=ArchiveJobType, allow_none=False)

    metadata = JSON('json_data')

    def __init__(self, archive, job_type, metadata):
        """Create an ArchiveJob.

        :param archive: the `IArchive` this job relates to.
        :param job_type: the `ArchiveJobType` of this job.
        :param metadata: the type-specific variables, as a json-compatible
            dict.
        """
        super().__init__()
        self.job = Job()
        self.archive = archive
        self.job_type = job_type
        self.metadata = metadata

    def makeDerived(self):
        return ArchiveJobDerived.makeSubclass(self)


@delegate_to(IArchiveJob)
@provider(IArchiveJobSource)
class ArchiveJobDerived(BaseRunnableJob, metaclass=EnumeratedSubclass):
    """Intermediate class for deriving from ArchiveJob."""

    def __init__(self, job):
        self.context = job

    @classmethod
    def create(cls, archive, metadata=None):
        """See `IArchiveJob`."""
        if metadata is None:
            metadata = {}
        job = ArchiveJob(archive, cls.class_job_type, metadata)
        derived = cls(job)
        derived.celeryRunOnCommit()
        return derived

    @classmethod
    def iterReady(cls):
        """Iterate through all ready ArchiveJobs."""
        store = IMasterStore(ArchiveJob)
        jobs = store.find(
            ArchiveJob,
            And(ArchiveJob.job_type == cls.class_job_type,
                ArchiveJob.job_id.is_in(Job.ready_jobs)))
        return (cls(job) for job in jobs)

    def getOopsVars(self):
        """See `IRunnableJob`."""
        vars = super().getOopsVars()
        vars.extend([
            ('archive_id', self.context.archive.id),
            ('archive_job_id', self.context.id),
            ('archive_job_type', self.context.job_type.title),
            ])
        return vars


@implementer(IPackageUploadNotificationJob)
@provider(IPackageUploadNotificationJobSource)
class PackageUploadNotificationJob(ArchiveJobDerived):

    class_job_type = ArchiveJobType.PACKAGE_UPLOAD_NOTIFICATION

    config = config.IPackageUploadNotificationJobSource

    @classmethod
    def create(cls, packageupload, summary_text=None):
        """See `IPackageUploadNotificationJobSource`."""
        metadata = {
            'packageupload_id': packageupload.id,
            'packageupload_status': packageupload.status.title,
            'summary_text': summary_text,
            }
        return super().create(packageupload.archive, metadata)

    def getOopsVars(self):
        """See `ArchiveJobDerived`."""
        vars = super().getOopsVars()
        vars.extend([
            ('packageupload_id', self.metadata['packageupload_id']),
            ('packageupload_status', self.metadata['packageupload_status']),
            ('summary_text', self.metadata['summary_text']),
            ])
        return vars

    @property
    def packageupload(self):
        return getUtility(IPackageUploadSet).get(
            self.metadata['packageupload_id'])

    @property
    def packageupload_status(self):
        return PackageUploadStatus.getTermByToken(
            self.metadata['packageupload_status']).value

    @property
    def summary_text(self):
        return self.metadata['summary_text']

    def run(self):
        """See `IRunnableJob`."""
        packageupload = self.packageupload
        if packageupload.changesfile is None:
            changes_file_object = None
        else:
            changes_file_object = io.BytesIO(packageupload.changesfile.read())
        logger = logging.getLogger()
        packageupload.notify(
            status=self.packageupload_status, summary_text=self.summary_text,
            changes_file_object=changes_file_object, logger=logger)


class ScanException(Exception):
    """A CI build upload job failed to scan a file."""


@implementer(ICIBuildUploadJob)
@provider(ICIBuildUploadJobSource)
class CIBuildUploadJob(ArchiveJobDerived):

    class_job_type = ArchiveJobType.CI_BUILD_UPLOAD

    user_error_types = (ScanException,)
    retry_error_types = (LibrarianServerError,)
    max_retries = 3

    config = config.ICIBuildUploadJobSource

    # XXX cjwatson 2022-06-10: There doesn't seem to be a very clear
    # conceptual distinction between BinaryPackageFormat and
    # BinaryPackageFileType, but we end up having to add entries to both for
    # each new package type because they're used in different database
    # columns.  Try to minimize the hassle involved in this by maintaining a
    # mapping here of all the formats we're interested in.
    filetype_by_format = {
        BinaryPackageFormat.WHL: BinaryPackageFileType.WHL,
        BinaryPackageFormat.CONDA_V1: BinaryPackageFileType.CONDA_V1,
        BinaryPackageFormat.CONDA_V2: BinaryPackageFileType.CONDA_V2,
        }

    # We're only interested in uploading certain kinds of packages to
    # certain kinds of archives.
    binary_format_by_repository_format = {
        ArchiveRepositoryFormat.DEBIAN: {
            BinaryPackageFormat.DEB,
            BinaryPackageFormat.UDEB,
            BinaryPackageFormat.DDEB,
            },
        ArchiveRepositoryFormat.PYTHON: {BinaryPackageFormat.WHL},
        ArchiveRepositoryFormat.CONDA: {
            BinaryPackageFormat.CONDA_V1,
            BinaryPackageFormat.CONDA_V2,
            },
        }

    @classmethod
    def create(cls, ci_build, requester, target_archive, target_distroseries,
               target_pocket, target_channel=None):
        """See `ICIBuildUploadJobSource`."""
        metadata = {
            "ci_build_id": ci_build.id,
            "target_distroseries_id": target_distroseries.id,
            "target_pocket": target_pocket.title,
            "target_channel": target_channel,
            }
        derived = super().create(target_archive, metadata)
        derived.job.requester = requester
        return derived

    def __repr__(self):
        """Returns an informative representation of the job."""
        parts = [
            "%s to upload %r to %s %s" % (
                self.__class__.__name__,
                self.ci_build,
                self.archive.reference,
                self.target_distroseries.getSuite(self.target_pocket),
                ),
            ]
        if self.target_channel is not None:
            parts.append(" {%s}" % self.target_channel)
        return "<%s>" % "".join(parts)

    def getOopsVars(self):
        vars = super().getOopsVars()
        vars.extend([
            (key, self.metadata[key])
            for key in (
                "ci_build_id",
                "target_distroseries_id",
                "target_pocket",
                "target_channel",
                )])
        return vars

    def getOperationDescription(self):
        """See `IRunnableJob`."""
        return "uploading %s to %s" % (
            self.ci_build.title, self.archive.reference)

    def getErrorRecipients(self):
        return [format_address_for_person(self.requester)]

    @property
    def ci_build(self):
        return getUtility(ICIBuildSet).getByID(self.metadata["ci_build_id"])

    @property
    def target_distroseries(self):
        return getUtility(IDistroSeriesSet).get(
            self.metadata["target_distroseries_id"])

    @property
    def target_pocket(self):
        return PackagePublishingPocket.getTermByToken(
            self.metadata["target_pocket"]).value

    @property
    def target_channel(self):
        return self.metadata["target_channel"]

    def _scanCondaMetadata(self, index, about):
        return {
            "name": index["name"],
            "version": index["version"],
            "summary": about.get("summary", ""),
            "description": about.get("description", ""),
            "architecturespecific": index["platform"] is not None,
            "homepage": about.get("home", ""),
            # We should perhaps model this explicitly since it's used by the
            # publisher, but this gives us an easy way to pass this through
            # without needing to add a column to a large table that's only
            # relevant to a tiny minority of rows.
            "user_defined_fields": [("subdir", index["subdir"])],
            }

    def _scanFile(self, path):
        # XXX cjwatson 2022-06-10: We should probably start splitting this
        # up some more.
        name = os.path.basename(path)
        if path.endswith(".whl"):
            try:
                parsed_path = parse_wheel_filename(path)
                wheel = Wheel(path)
            except Exception as e:
                raise ScanException("Failed to scan %s" % name) from e
            return {
                "name": wheel.name,
                "version": wheel.version,
                "summary": wheel.summary or "",
                "description": wheel.description,
                "binpackageformat": BinaryPackageFormat.WHL,
                "architecturespecific": "any" not in parsed_path.platform_tags,
                "homepage": wheel.home_page or "",
                }
        elif path.endswith(".tar.bz2"):
            try:
                with tarfile.open(path) as tar:
                    index = json.loads(
                        tar.extractfile("info/index.json").read().decode())
                    about = json.loads(
                        tar.extractfile("info/about.json").read().decode())
            except Exception as e:
                raise ScanException("Failed to scan %s" % name) from e
            scanned = {"binpackageformat": BinaryPackageFormat.CONDA_V1}
            scanned.update(self._scanCondaMetadata(index, about))
            return scanned
        elif path.endswith(".conda"):
            try:
                with zipfile.ZipFile(path) as zipf:
                    base_name = os.path.basename(path)[:-len(".conda")]
                    info = io.BytesIO()
                    with zipf.open("info-%s.tar.zst" % base_name) as raw_info:
                        zstandard.ZstdDecompressor().copy_stream(
                            raw_info, info)
                    info.seek(0)
                    with tarfile.open(fileobj=info) as tar:
                        index = json.loads(
                            tar.extractfile("info/index.json").read().decode())
                        about = json.loads(
                            tar.extractfile("info/about.json").read().decode())
            except Exception as e:
                raise ScanException("Failed to scan %s" % name) from e
            scanned = {"binpackageformat": BinaryPackageFormat.CONDA_V2}
            scanned.update(self._scanCondaMetadata(index, about))
            return scanned
        else:
            return None

    def run(self):
        """See `IRunnableJob`."""
        logger = logging.getLogger()
        with tempfile.TemporaryDirectory(prefix="ci-build-copy-job") as tmpdir:
            releases = {
                (release.binarypackagename, release.binpackageformat): release
                for release in self.ci_build.binarypackages}
            allowed_binary_formats = (
                self.binary_format_by_repository_format.get(
                    self.archive.repository_format, set()))
            binaries = {}
            for artifact in getUtility(
                    IRevisionStatusArtifactSet).findByCIBuild(self.ci_build):
                if artifact.artifact_type == RevisionStatusArtifactType.LOG:
                    continue
                name = artifact.library_file.filename
                contents = os.path.join(tmpdir, name)
                artifact.library_file.open()
                copy_and_close(artifact.library_file, open(contents, "wb"))
                metadata = self._scanFile(contents)
                if metadata is None:
                    logger.info("No upload handler for %s" % name)
                    continue
                binpackageformat = metadata["binpackageformat"]
                if binpackageformat not in allowed_binary_formats:
                    logger.info(
                        "Skipping %s (not relevant to %s archives)" % (
                            name, self.archive.repository_format))
                    continue
                logger.info(
                    "Uploading %s to %s %s (%s)" % (
                        name, self.archive.reference,
                        self.target_distroseries.getSuite(self.target_pocket),
                        self.target_channel))
                metadata["binarypackagename"] = bpn = (
                    getUtility(IBinaryPackageNameSet).ensure(metadata["name"]))
                del metadata["name"]
                filetype = self.filetype_by_format[binpackageformat]
                bpr = releases.get((bpn, binpackageformat))
                if bpr is None:
                    bpr = self.ci_build.createBinaryPackageRelease(**metadata)
                for bpf in bpr.files:
                    if (bpf.libraryfile == artifact.library_file and
                            bpf.filetype == filetype):
                        break
                else:
                    bpr.addFile(artifact.library_file, filetype=filetype)
                # The publishBinaries interface was designed for .debs,
                # which need extra per-binary "override" information
                # (component, etc.).  None of this is relevant here.
                binaries[bpr] = (None, None, None, None)
            if binaries:
                getUtility(IPublishingSet).publishBinaries(
                    self.archive, self.target_distroseries, self.target_pocket,
                    binaries, channel=self.target_channel)
