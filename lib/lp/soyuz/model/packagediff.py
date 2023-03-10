# Copyright 2009-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "PackageDiff",
    "PackageDiffSet",
]

import gzip
import itertools
import os
import resource
import shutil
import subprocess
import tempfile
from datetime import timezone
from functools import partial

from storm.locals import DateTime, Desc, Int, Reference
from storm.store import EmptyResultSet
from zope.component import getUtility
from zope.interface import implementer

from lp.services.config import config
from lp.services.database.bulk import load
from lp.services.database.constants import DEFAULT, UTC_NOW
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.enumcol import DBEnum
from lp.services.database.interfaces import IStore
from lp.services.database.stormbase import StormBase
from lp.services.librarian.interfaces import ILibraryFileAliasSet
from lp.services.librarian.model import LibraryFileAlias, LibraryFileContent
from lp.services.librarian.utils import copy_and_close
from lp.soyuz.enums import PackageDiffStatus
from lp.soyuz.interfaces.packagediff import IPackageDiff, IPackageDiffSet
from lp.soyuz.model.files import SourcePackageReleaseFile


def limit_deb_diff(max_size):
    """Pre-exec function to apply resource limits to debdiff.

    :param max_size: Maximum output file size in bytes.
    """
    _, hard_fsize = resource.getrlimit(resource.RLIMIT_FSIZE)
    if hard_fsize != resource.RLIM_INFINITY and hard_fsize < max_size:
        max_size = hard_fsize
    resource.setrlimit(resource.RLIMIT_FSIZE, (max_size, hard_fsize))


def perform_deb_diff(tmp_dir, out_filename, from_files, to_files):
    """Perform a (deb)diff on two packages.

    A debdiff will be invoked on the files associated with the
    two packages to be diff'ed. The resulting output will be a tuple
    containing the process return code and the STDERR output.

    :param tmp_dir: The temporary directory with the package files.
    :type tmp_dir: ``str``
    :param out_filename: The name of the file that will hold the
        resulting debdiff output.
    :type tmp_dir: ``str``
    :param from_files: A list with the names of the files associated
        with the first package.
    :type from_files: ``list``
    :param to_files: A list with the names of the files associated
        with the second package.
    :type to_files: ``list``
    """
    [from_dsc] = [name for name in from_files if name.lower().endswith(".dsc")]
    [to_dsc] = [name for name in to_files if name.lower().endswith(".dsc")]
    args = [
        "timeout",
        str(config.packagediff.debdiff_timeout),
        "debdiff",
        from_dsc,
        to_dsc,
    ]
    env = os.environ.copy()
    env["TMPDIR"] = tmp_dir

    full_path = os.path.join(tmp_dir, out_filename)
    out_file = None
    try:
        out_file = open(full_path, "wb")
        process = subprocess.Popen(
            args,
            stdout=out_file,
            stderr=subprocess.PIPE,
            preexec_fn=partial(
                limit_deb_diff, config.packagediff.debdiff_max_size
            ),
            cwd=tmp_dir,
            env=env,
        )
        stdout, stderr = process.communicate()
    finally:
        if out_file is not None:
            out_file.close()

    return process.returncode, stderr


def download_file(destination_path, libraryfile):
    """Download a file from the librarian to the destination path.

    :param destination_path: Absolute destination path (where the
        file should be downloaded to).
    :type destination_path: ``str``
    :param libraryfile: The librarian file that is to be downloaded.
    :type libraryfile: ``LibraryFileAlias``
    """
    libraryfile.open()
    destination_file = open(destination_path, "wb")
    copy_and_close(libraryfile, destination_file)


@implementer(IPackageDiff)
class PackageDiff(StormBase):
    """A Package Diff request."""

    __storm_table__ = "PackageDiff"
    __storm_order__ = ["id"]

    id = Int(primary=True)

    date_requested = DateTime(
        allow_none=False, default=UTC_NOW, tzinfo=timezone.utc
    )

    requester_id = Int(name="requester", allow_none=True)
    requester = Reference(requester_id, "Person.id")

    from_source_id = Int(name="from_source", allow_none=False)
    from_source = Reference(from_source_id, "SourcePackageRelease.id")

    to_source_id = Int(name="to_source", allow_none=False)
    to_source = Reference(to_source_id, "SourcePackageRelease.id")

    date_fulfilled = DateTime(
        allow_none=True, default=None, tzinfo=timezone.utc
    )

    diff_content_id = Int(name="diff_content", allow_none=True, default=None)
    diff_content = Reference(diff_content_id, "LibraryFileAlias.id")

    status = DBEnum(
        name="status",
        allow_none=False,
        enum=PackageDiffStatus,
        default=PackageDiffStatus.PENDING,
    )

    def __init__(
        self,
        from_source,
        to_source,
        requester=None,
        date_fulfilled=None,
        diff_content=None,
        status=DEFAULT,
    ):
        super().__init__()
        self.from_source = from_source
        self.to_source = to_source
        self.requester = requester
        self.date_fulfilled = date_fulfilled
        self.diff_content = diff_content
        self.status = status

    @property
    def title(self):
        """See `IPackageDiff`."""
        ancestry_archive = self.from_source.upload_archive
        if ancestry_archive == self.to_source.upload_archive:
            ancestry_identifier = self.from_source.version
        else:
            ancestry_identifier = "%s (in %s)" % (
                self.from_source.version,
                ancestry_archive.distribution.name.capitalize(),
            )
        return "diff from %s to %s" % (
            ancestry_identifier,
            self.to_source.version,
        )

    @property
    def private(self):
        """See `IPackageDiff`."""
        to_source = self.to_source
        archives = [to_source.upload_archive] + to_source.published_archives
        return all(archive.private for archive in archives)

    def _countDeletedLFAs(self):
        """How many files associated with either source package have been
        deleted from the librarian?"""
        return (
            IStore(LibraryFileAlias)
            .find(
                LibraryFileAlias.id,
                SourcePackageReleaseFile.sourcepackagerelease_id.is_in(
                    (self.from_source_id, self.to_source_id)
                ),
                SourcePackageReleaseFile.libraryfile_id == LibraryFileAlias.id,
                LibraryFileAlias.content == None,
            )
            .count()
        )

    def performDiff(self):
        """See `IPackageDiff`.

        This involves creating a temporary directory, downloading the files
        from both SPRs involved from the librarian, running debdiff, storing
        the output in the librarian and updating the PackageDiff record.
        """
        # Make sure the files associated with the two source packages are
        # still available in the librarian.
        if self._countDeletedLFAs() > 0:
            self.status = PackageDiffStatus.FAILED
            return

        blacklist = config.packagediff.blacklist.split()
        if self.from_source.sourcepackagename.name in blacklist:
            self.status = PackageDiffStatus.FAILED
            return

        # Create the temporary directory where the files will be
        # downloaded to and where the debdiff will be performed.
        tmp_dir = tempfile.mkdtemp()

        try:
            directions = ("from", "to")

            # Keep track of the files belonging to the respective packages.
            downloaded = dict(zip(directions, ([], [])))

            # Make it easy to iterate over packages.
            packages = dict(
                zip(directions, (self.from_source, self.to_source))
            )

            # Iterate over the packages to be diff'ed.
            for direction, package in packages.items():
                # Create distinct directory locations for
                # 'from' and 'to' files.
                absolute_path = os.path.join(tmp_dir, direction)
                os.makedirs(absolute_path)

                # Download the files associated with each package in
                # their corresponding relative location.
                for file in package.files:
                    the_name = file.libraryfile.filename
                    relative_location = os.path.join(direction, the_name)
                    downloaded[direction].append(relative_location)
                    destination_path = os.path.join(absolute_path, the_name)
                    download_file(destination_path, file.libraryfile)

            # All downloads are done. Construct the name of the resulting
            # diff file.
            result_filename = "%s_%s_%s.diff" % (
                self.from_source.sourcepackagename.name,
                self.from_source.version,
                self.to_source.version,
            )

            # Perform the actual diff operation.
            return_code, stderr = perform_deb_diff(
                tmp_dir, result_filename, downloaded["from"], downloaded["to"]
            )

            # `debdiff` failed, mark the package diff request accordingly
            # and return. 0 means no differences, 1 means they differ.
            # Note that pre-Karmic debdiff will return 0 even if they differ.
            if return_code not in (0, 1):
                self.status = PackageDiffStatus.FAILED
                return

            # Compress the generated diff.
            out_file = open(os.path.join(tmp_dir, result_filename), "rb")
            gzip_result_filename = result_filename + ".gz"
            gzip_file_path = os.path.join(tmp_dir, gzip_result_filename)
            gzip_file = gzip.GzipFile(gzip_file_path, mode="wb")
            copy_and_close(out_file, gzip_file)

            # Calculate the compressed size.
            gzip_size = os.path.getsize(gzip_file_path)

            # Upload the compressed diff to librarian and update
            # the package diff request.
            gzip_file = open(gzip_file_path, "rb")
            try:
                librarian_set = getUtility(ILibraryFileAliasSet)
                self.diff_content = librarian_set.create(
                    gzip_result_filename,
                    gzip_size,
                    gzip_file,
                    "application/gzipped-patch",
                    restricted=self.private,
                )
            finally:
                gzip_file.close()

            # Last but not least, mark the diff as COMPLETED.
            self.date_fulfilled = UTC_NOW
            self.status = PackageDiffStatus.COMPLETED
        finally:
            shutil.rmtree(tmp_dir)


@implementer(IPackageDiffSet)
class PackageDiffSet:
    """This class is to deal with Distribution related stuff"""

    def __iter__(self):
        """See `IPackageDiffSet`."""
        return iter(
            IStore(PackageDiff)
            .find(PackageDiff)
            .order_by(Desc(PackageDiff.id))
        )

    def get(self, diff_id):
        """See `IPackageDiffSet`."""
        return IStore(PackageDiff).get(PackageDiff, diff_id)

    def getDiffsToReleases(self, sprs, preload_for_display=False):
        """See `IPackageDiffSet`."""
        from lp.registry.model.distribution import Distribution
        from lp.soyuz.model.archive import Archive
        from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease

        if len(sprs) == 0:
            return EmptyResultSet()
        spr_ids = [spr.id for spr in sprs]
        result = IStore(PackageDiff).find(
            PackageDiff, PackageDiff.to_source_id.is_in(spr_ids)
        )
        result.order_by(
            PackageDiff.to_source_id, Desc(PackageDiff.date_requested)
        )

        def preload_hook(rows):
            lfas = load(LibraryFileAlias, (pd.diff_content_id for pd in rows))
            load(LibraryFileContent, (lfa.contentID for lfa in lfas))
            sprs = load(
                SourcePackageRelease,
                itertools.chain.from_iterable(
                    (pd.from_source_id, pd.to_source_id) for pd in rows
                ),
            )
            archives = load(Archive, (spr.upload_archiveID for spr in sprs))
            load(Distribution, (a.distributionID for a in archives))

        if preload_for_display:
            return DecoratedResultSet(result, pre_iter_hook=preload_hook)
        else:
            return result

    def getDiffBetweenReleases(self, from_spr, to_spr):
        """See `IPackageDiffSet`."""
        return (
            IStore(PackageDiff)
            .find(PackageDiff, from_source=from_spr, to_source=to_spr)
            .first()
        )
