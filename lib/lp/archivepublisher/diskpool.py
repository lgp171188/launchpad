# Copyright 2009-2016 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__all__ = [
    "DiskPool",
    "DiskPoolEntry",
    "FileAddActionEnum",
    "poolify",
    "unpoolify",
]

import logging
import os
import tempfile
from pathlib import Path, PurePath
from typing import TYPE_CHECKING, Optional, Tuple, Union

from lp.archivepublisher import HARDCODED_COMPONENT_ORDER
from lp.services.librarian.utils import copy_and_close, sha1_from_path
from lp.services.propertycache import cachedproperty
from lp.soyuz.interfaces.archive import IArchive
from lp.soyuz.interfaces.files import IPackageReleaseFile
from lp.soyuz.interfaces.publishing import (
    MissingSymlinkInPool,
    NotInPool,
    PoolFileOverwriteError,
)


def get_source_prefix(source: str) -> str:
    """Get the prefix for a pooled source package name.

    In the Debian repository format, packages are published to directories
    of the form `pool/<component>/<source prefix>/<source name>/`, perhaps
    best described here::

        https://lists.debian.org/debian-devel/2000/10/msg01340.html

    The directory here called `<source prefix>` (there doesn't seem to be a
    canonical term for this) is formed by taking the first character of the
    source name, except when the source name starts with "lib" in which case
    it's formed by taking the first four characters of the source name.
    This was originally in order to behave reasonably on file systems such
    as ext2, but is now entrenched and expected.
    """
    if source.startswith("lib"):
        return source[:4]
    else:
        return source[:1]


def poolify(source: str, component: Optional[str] = None) -> Path:
    """Poolify a given source and component name."""
    path = Path(get_source_prefix(source)) / source
    if component is not None:
        path = Path(component) / path
    return path


def unpoolify(path: PurePath) -> Tuple[str, str, Optional[str]]:
    """Take a path and unpoolify it.

    Return a tuple of component, source, filename.
    """
    p = path.parts
    if len(p) < 3 or len(p) > 4:
        raise ValueError(
            "Path '%s' is not in a valid pool form" % path.as_posix()
        )
    component, source_prefix, source = p[:3]
    if source_prefix != get_source_prefix(source):
        raise ValueError(
            "Source prefix '%s' does not match source '%s'"
            % (source_prefix, source)
        )
    if len(p) == 4:
        return component, source, p[3]
    return component, source, None


def relative_symlink(src_path: Path, dst_path: Path) -> None:
    """Path.symlink_to replacement that creates relative symbolic links."""
    src_path = Path(os.path.normpath(str(src_path)))
    dst_path = Path(os.path.normpath(str(dst_path)))
    common_prefix = Path(os.path.commonpath([str(src_path), str(dst_path)]))
    backward_elems = [os.path.pardir] * (
        len(dst_path.parts) - len(common_prefix.parts) - 1
    )
    forward_elems = src_path.parts[len(common_prefix.parts) :]
    src_path = Path(*backward_elems, *forward_elems)
    dst_path.symlink_to(src_path)


class FileAddActionEnum:
    """Possible actions taken when adding a file.

    FILE_ADDED: we added the actual file to the disk
    SYMLINK_ADDED: we created a symlink to another copy of the same file
    NONE: no action was necessary or taken.
    """

    FILE_ADDED = "file_added"
    SYMLINK_ADDED = "symlink_added"
    NONE = "none"


class _diskpool_atomicfile:
    """Simple file-like object used by the pool to atomically move into place
    a file after downloading from the librarian.

    This class is designed to solve a very specific problem encountered in
    the publisher. Namely that should the publisher crash during the process
    of publishing a file to the pool, an empty or incomplete file would be
    present in the pool. Its mere presence would fool the publisher into
    believing it had already downloaded that file to the pool, resulting
    in failures in the apt-ftparchive stage.

    By performing a rename() when the file is guaranteed to have been
    fully written to disk (after the fd.close()) we can be sure that if
    the filename is present in the pool, it is definitely complete.
    """

    def __init__(
        self,
        targetfilename: Path,
        mode: str,
        rootpath: Union[str, Path] = "/tmp",
    ) -> None:
        # atomicfile implements the file object interface, but it is only
        # really used (or useful) for writing binary files, which is why we
        # keep the mode constructor argument but assert it's sane below.
        if mode == "w":
            mode = "wb"
        assert mode == "wb"

        assert not targetfilename.exists()

        self.targetfilename = targetfilename
        fd, name = tempfile.mkstemp(prefix="temp-download.", dir=str(rootpath))
        self.fd = os.fdopen(fd, mode)
        self.tempname = Path(name)
        self.write = self.fd.write

    def close(self) -> None:
        """Make the atomic move into place having closed the temp file."""
        self.fd.close()
        self.tempname.chmod(0o644)
        # Note that this will fail if the target and the temp dirs are on
        # different filesystems.
        self.tempname.rename(self.targetfilename)

    def cleanup_temporary_path(self) -> None:
        """Removes temporary path created on __init__"""
        if self.tempname.exists():
            self.tempname.unlink()


class DiskPoolEntry:
    """Represents a single file in the pool, across all components.

    Creating a DiskPoolEntry performs disk reads, so don't create an
    instance of this class unless you need to know what's already on
    the disk for this file.

    'tempath' must be in the same filesystem as 'rootpath', it will be
    used to store the installation candidate while it is being downloaded
    from the Librarian.

    Remaining files in the 'temppath' indicated installation failures and
    require manual removal after further investigation.
    """

    def __init__(
        self,
        archive: IArchive,
        rootpath: Path,
        temppath: Path,
        source_name: str,
        source_version: str,
        pub_file: IPackageReleaseFile,
        logger: logging.Logger,
    ) -> None:
        self.archive = archive
        self.rootpath = rootpath
        self.temppath = temppath
        self.source_name = source_name
        self.source_version = source_version
        self.pub_file = pub_file
        self.logger = logger

        self.file_component = None
        self.symlink_components = set()

        for component in HARDCODED_COMPONENT_ORDER:
            path = self.pathFor(component)
            if path.is_symlink():
                self.symlink_components.add(component)
            elif path.is_file():
                assert not self.file_component
                self.file_component = component
        if self.symlink_components:
            assert self.file_component

    def debug(self, *args, **kwargs) -> None:
        self.logger.debug(*args, **kwargs)

    def pathFor(self, component: str) -> Path:
        """Return the path for this file in the given component."""
        return (
            self.rootpath
            / poolify(self.source_name, component)
            / self.pub_file.libraryfile.filename
        )

    def preferredComponent(
        self, add: Optional[str] = None, remove: Optional[str] = None
    ) -> Optional[str]:
        """Return the appropriate component for the real file.

        If add is passed, add it to the list before calculating.
        If remove is passed, remove it before calculating.
        Thus, we can calculate which component should contain the main file
        after the addition or removal we are working on.
        """
        components = set()
        if self.file_component:
            components.add(self.file_component)
        components = components.union(self.symlink_components)
        if add is not None:
            components.add(add)
        if remove is not None and remove in components:
            components.remove(remove)

        for component in HARDCODED_COMPONENT_ORDER:
            if component in components:
                return component

        # https://github.com/python/mypy/issues/7511
        return None

    @cachedproperty
    def file_hash(self) -> str:
        """Return the SHA1 sum of this file."""
        if TYPE_CHECKING:
            assert self.file_component is not None
        targetpath = self.pathFor(self.file_component)
        return sha1_from_path(str(targetpath))

    def addFile(self, component: str):
        """See DiskPool.addFile."""
        assert component in HARDCODED_COMPONENT_ORDER

        targetpath = self.pathFor(component)
        targetpath.parent.mkdir(parents=True, exist_ok=True)
        lfa = self.pub_file.libraryfile

        if self.file_component:
            # There's something on disk. Check hash.
            sha1 = lfa.content.sha1
            if sha1 != self.file_hash:
                raise PoolFileOverwriteError(
                    "%s != %s for %s"
                    % (sha1, self.file_hash, self.pathFor(self.file_component))
                )

            if (
                component == self.file_component
                or component in self.symlink_components
            ):
                # The file is already here
                return FileAddActionEnum.NONE
            else:
                # The file is present in a different component,
                # make a symlink.
                relative_symlink(self.pathFor(self.file_component), targetpath)
                self.symlink_components.add(component)
                # Then fix to ensure the right component is linked.
                self._sanitiseLinks()

                return FileAddActionEnum.SYMLINK_ADDED

        # If we get to here, we want to write the file.
        assert not targetpath.exists()

        self.debug(
            "Making new file in %s for %s/%s"
            % (component, self.source_name, lfa.filename)
        )

        file_to_write = _diskpool_atomicfile(
            targetpath, "wb", rootpath=self.temppath
        )
        try:
            lfa.open()
            copy_and_close(lfa, file_to_write)
        except Exception:
            # Prevent ending up with a stray temporary file lying around if
            # anything goes wrong whily copying the file. Still raises error
            self.debug("Cleaning up temp path %s" % file_to_write.tempname)
            file_to_write.cleanup_temporary_path()
            raise

        self.file_component = component
        return FileAddActionEnum.FILE_ADDED

    def removeFile(self, component: str) -> int:
        """Remove a file from a given component; return bytes freed.

        This method handles three situations:

        1) Remove a symlink

        2) Remove the main file and there are no symlinks left.

        3) Remove the main file and there are symlinks left.
        """
        filename = self.pub_file.libraryfile.filename
        if not self.file_component:
            raise NotInPool(
                "File for removing %s %s/%s is not in pool, skipping."
                % (component, self.source_name, filename)
            )

        # Okay, it's there, if it's a symlink then we need to remove
        # it simply.
        if component in self.symlink_components:
            self.debug(
                "Removing %s %s/%s as it is a symlink"
                % (component, self.source_name, filename)
            )
            # ensure we are removing a symbolic link and
            # it is published in one or more components
            link_path = self.pathFor(component)
            assert link_path.is_symlink()
            return self._reallyRemove(component)

        if component != self.file_component:
            raise MissingSymlinkInPool(
                "Symlink for %s/%s in %s is missing, skipping."
                % (self.source_name, filename, component)
            )

        # It's not a symlink, this means we need to check whether we
        # have symlinks or not.
        if len(self.symlink_components) == 0:
            self.debug(
                "Removing %s/%s from %s"
                % (self.source_name, filename, component)
            )
        else:
            # The target for removal is the real file, and there are symlinks
            # pointing to it. In order to avoid breakage, we need to first
            # shuffle the symlinks, so that the one we want to delete will
            # just be one of the links, and becomes safe.
            targetcomponent = self.preferredComponent(remove=component)
            if TYPE_CHECKING:
                assert targetcomponent is not None
            self._shufflesymlinks(targetcomponent)

        return self._reallyRemove(component)

    def _reallyRemove(self, component: str) -> int:
        """Remove file and return file size.

        Remove the file from the filesystem and from our data
        structures.
        """
        fullpath = self.pathFor(component)
        assert fullpath.exists()

        if component == self.file_component:
            # Deleting the master file is only allowed if there
            # are no symlinks left.
            assert not self.symlink_components
            self.file_component = None
        elif component in self.symlink_components:
            self.symlink_components.remove(component)

        size = fullpath.lstat().st_size
        fullpath.unlink()
        return size

    def _shufflesymlinks(self, targetcomponent: str) -> None:
        """Shuffle the symlinks for filename so that targetcomponent contains
        the real file and the rest are symlinks to the right place..."""
        if TYPE_CHECKING:
            assert self.file_component is not None

        if targetcomponent == self.file_component:
            # We're already in the right place.
            return

        filename = self.pub_file.libraryfile.filename
        if targetcomponent not in self.symlink_components:
            raise ValueError(
                "Target component '%s' is not a symlink for %s"
                % (targetcomponent, filename)
            )

        self.debug(
            "Shuffling symlinks so primary for %s is in %s"
            % (filename, targetcomponent)
        )

        # Okay, so first up, we unlink the targetcomponent symlink.
        targetpath = self.pathFor(targetcomponent)
        targetpath.unlink()

        # Now we rename the source file into the target component.
        sourcepath = self.pathFor(self.file_component)

        # XXX cprov 2006-05-26: if it fails the symlinks are severely broken
        # or maybe we are writing them wrong. It needs manual fix !
        # Nonetheless, we carry on checking other candidates.
        # Use 'find -L . -type l' on pool to find out broken symlinks
        # Normally they only can be fixed by remove the broken links and
        # run a careful (-C) publication.

        # ensure targetpath doesn't exists and  the sourcepath exists
        # before rename them.
        assert not targetpath.exists()
        assert sourcepath.exists()
        sourcepath.rename(targetpath)

        # XXX cprov 2006-06-12: it may cause problems to the database, since
        # ZTM isn't handled properly in scripts/publish-distro.py. Things are
        # committed mid-procedure & bare exception is caught.

        # Update the data structures.
        self.symlink_components.add(self.file_component)
        self.symlink_components.remove(targetcomponent)
        self.file_component = targetcomponent

        # Now we make the symlinks on the filesystem.
        for comp in self.symlink_components:
            newpath = self.pathFor(comp)
            try:
                newpath.unlink()
            except OSError:
                # Do nothing because it's almost certainly a not found.
                pass
            relative_symlink(targetpath, newpath)

    def _sanitiseLinks(self) -> None:
        """Ensure the real file is in the most preferred component.

        If this file is in more than one component, ensure the real
        file is in the most preferred component and the other components
        use symlinks.

        It's important that the real file be in the most preferred
        component because partial mirrors may only take a subset of
        components, and these partial mirrors must not have broken
        symlinks where they should have working files.
        """
        component = self.preferredComponent()
        if not self.file_component == component:
            if TYPE_CHECKING:
                assert component is not None
            self._shufflesymlinks(component)


class DiskPool:
    """Scan a pool on the filesystem and record information about it.

    Its constructor receives 'rootpath', which is the pool path where the
    files will be installed, and the 'temppath', which is a temporary
    directory used to store the installation candidate from librarian.

    'rootpath' and 'temppath' must be in the same filesystem, see
    DiskPoolEntry for further information.
    """

    results = FileAddActionEnum

    def __init__(
        self, archive: IArchive, rootpath, temppath, logger: logging.Logger
    ) -> None:
        self.archive = archive
        self.rootpath = Path(rootpath)
        self.temppath = Path(temppath) if temppath is not None else None
        self.logger = logger

    def _getEntry(
        self,
        source_name: str,
        source_version: str,
        pub_file: IPackageReleaseFile,
    ) -> DiskPoolEntry:
        """Return a new DiskPoolEntry for the given source and file."""
        if TYPE_CHECKING:
            assert self.temppath is not None
        return DiskPoolEntry(
            self.archive,
            self.rootpath,
            self.temppath,
            source_name,
            source_version,
            pub_file,
            self.logger,
        )

    def pathFor(
        self,
        comp: str,
        source_name: str,
        source_version: str,
        pub_file: Optional[IPackageReleaseFile] = None,
        file: Optional[str] = None,
    ) -> Path:
        """Return the path for the given pool file."""
        if file is None:
            if TYPE_CHECKING:
                assert pub_file is not None
            file = pub_file.libraryfile.filename
        if file is None:
            raise AssertionError("Must pass either pub_file or file")
        return self.rootpath / poolify(source_name, comp) / file

    def addFile(
        self,
        component: str,
        source_name: str,
        source_version: str,
        pub_file: IPackageReleaseFile,
    ):
        """Add a file with the given contents to the pool.

        `component`, `source_name`, `source_version`, and `pub_file` are
        used to calculate the on-disk location.

        pub_file is an `IPackageReleaseFile` providing the file's contents
        and SHA-1 hash.  The SHA-1 hash is used to compare the given file
        with an existing file, if one exists for any component.

        There are four possible outcomes:
        - If the file doesn't exist in the pool for any component, it will
        be written from the given contents and results.ADDED_FILE will be
        returned.

        - If the file already exists in the pool, in this or any other
        component, the hash of the file on disk will be calculated and
        compared with the hash provided. If they fail to match,
        PoolFileOverwriteError will be raised.

        - If the file already exists but not in this component, and the
        hash test above passes, a symlink will be added, and
        results.SYMLINK_ADDED will be returned. Also, the symlinks will be
        checked and sanitised, to ensure the real copy of the file is in the
        most preferred component, according to HARDCODED_COMPONENT_ORDER.

        - If the file already exists and is already in this component,
        either as a file or a symlink, and the hash check passes,
        results.NONE will be returned and nothing will be done.
        """
        entry = self._getEntry(source_name, source_version, pub_file)
        return entry.addFile(component)

    def removeFile(
        self,
        component: str,
        source_name: str,
        source_version: str,
        pub_file: IPackageReleaseFile,
    ) -> int:
        """Remove the specified file from the pool.

        There are three possible outcomes:
        - If the specified file does not exist, NotInPool will be raised.

        - If the specified file exists and is a symlink, or is the only
        copy of the file in the pool, it will simply be deleted, and its
        size will be returned.

        - If the specified file is a real file and there are symlinks
        referencing it, the symlink in the next most preferred component
        will be deleted, and the file will be moved to replace it. The
        size of the deleted symlink will be returned.
        """
        entry = self._getEntry(source_name, source_version, pub_file)
        return entry.removeFile(component)
