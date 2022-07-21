# Copyright 2004-2020 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Path handling.

This module supplies useful functions for dealing with paths and
extracting useful information out of them.  It was extracted from cscvs, and
cut down to only what Launchpad's product release finder needs.
"""

import os
import re
import stat

# Regular expressions make things easy
patched_ext = re.compile(
    r"([._+-](orig|old|new|patch|patched)|~)$", re.IGNORECASE
)
version_ext = re.compile(
    r"[_-]v?([0-9][0-9a-z:.+]*"
    r"(?:[-_](?:pre|rc|alpha|beta|test)"
    r"(?:[0-9:.+][0-9a-z:.+]*|(?![a-z])))?)",
    re.IGNORECASE,
)


class FileFormat:
    """Known file formats.

    Constants:
      TAR       Tar file
      PATCH     Patch file
      ZIP       Zip file
    """

    TAR = "TAR"
    PATCH = "PATCH"
    ZIP = "ZIP"


class Compression:
    """Known compressions.

    Constants:
      GZIP      gzip
      BZIP2     bzip2
    """

    GZIP = "gzip"
    BZIP2 = "bzip2"
    COMPRESS = "compress"


class Extensions:
    """Extensions that map to file formats and compressions.

    Constants:
      FORMAT    Extensions that suggest a particular file format.
      COMPRESS  Extensions that suggest a particular compression.
      BOTH      Extensions that suggest both.
    """

    FORMAT = {
        ".tar": (FileFormat.TAR,),
        ".patch": (FileFormat.PATCH,),
        ".dpatch": (FileFormat.PATCH,),
        ".diff": (FileFormat.PATCH,),
        ".zip": (FileFormat.ZIP,),
        ".jar": (FileFormat.ZIP,),
    }

    COMPRESS = {
        ".gz": (Compression.GZIP,),
        ".bz2": (Compression.BZIP2,),
        ".Z": (Compression.COMPRESS,),
    }

    BOTH = {
        ".tgz": (FileFormat.TAR, Compression.GZIP),
        ".tbz": (FileFormat.TAR, Compression.BZIP2),
        ".tbz2": (FileFormat.TAR, Compression.BZIP2),
    }


class Filenames:
    """File names that may be special.

    Constants:
      IGNORE    Filenames that suggest we ignore the path.
    """

    IGNORE = [".arch-inventory", ".cvsignore", ".bzrignore"]


class Directories:
    """Directory names that suggest formats for their contents.

    Constants:
      FORMAT    Directory names that suggest a particular file format.
      IGNORE    Directory names that suggest we ignore the path.
    """

    FORMAT = {
        "tarballs": FileFormat.TAR,
        "tarfiles": FileFormat.TAR,
        "patches": FileFormat.PATCH,
    }

    IGNORE = ["{arch}", ".arch-ids", "CVS", "RCS", ".svn", "_darcs", ".bzr"]


class PathBase:
    """Cache path information.

    This class provides functionality for representing a path on a
    filesystem.  It can be combined with any sub-class of the built-in str
    type.

    Properties are available which hold cached information about the file,
    to reduce stat calls and improve performance.  They are properties
    rather than functions to indicate their cached status.

    You almost certainly want to use Path rather than PathBase unless you
    are sub-classing from multiple str-derived base-classes.  PathBase
    _must_ be mixed with a class that derives from str.
    """

    def __new__(cls, path=".", *args, **kwds):
        if path.__class__ == cls:
            # Identical class means we behave like a singleton
            return path
        elif isinstance(path, PathBase):
            # Otherwise instance of PathBase or sub-class means we avoid
            # repeated calls of canon()
            return str.__new__(cls, path)
        else:
            return str.__new__(cls, canon(path))

    def __repr__(self):
        """Return a debugging representation of the manifest."""
        text = "<%s %r>" % (type(self).__name__, str(self))
        return text

    def __eq__(self, other):
        """Compare to another Path or string."""
        return as_file(str(self)) == as_file(str(other))

    @property
    def basename(self):
        """Cache and return filename portion of path."""
        try:
            return self._basename
        except AttributeError:
            basename = os.path.basename(as_file(self))
            if self.isdir:
                self._basename = as_dir(basename)
            else:
                self._basename = basename
            return self._basename

    @property
    def dirname(self):
        """Cache and return directory portion of path."""
        try:
            return self._dirname
        except AttributeError:
            path = as_file(self)
            if path != "":
                self._dirname = CanonPath(os.path.dirname(path))
            else:
                self._dirname = None
            return self._dirname

    def stat(self):
        """Cache and return stat results for path.

        If the path does not exist, None is returned.
        """
        try:
            return self._stat
        except AttributeError:
            try:
                self._stat = os.lstat(self)
            except OSError:
                self._stat = None
            return self._stat

    def _del_stat(self):
        """Clear the cached stat results."""
        try:
            del self._stat
        except AttributeError:
            pass

    stat = property(stat, fdel=_del_stat)

    @property
    def exists(self):
        """Return whether path exists.

        Symbolic links are not followed.
        """
        return self.stat is not None

    @property
    def isdir(self):
        """Return whether path exists and is a directory."""
        try:
            return stat.S_ISDIR(self.stat.st_mode)
        except AttributeError:
            return False

    @property
    def isfile(self):
        """Return whether path exists and is an ordinary file."""
        try:
            return stat.S_ISREG(self.stat.st_mode)
        except AttributeError:
            return False

    @property
    def islink(self):
        """Return whether path exists and is a symbolic link."""
        try:
            return stat.S_ISLNK(self.stat.st_mode)
        except AttributeError:
            return False

    @property
    def size(self):
        """Return size of file."""
        try:
            if self.isfile:
                return self.stat.st_size
            else:
                return None
        except AttributeError:
            return None

    @property
    def mode(self):
        """Return permissions of path."""
        try:
            return stat.S_IMODE(self.stat.st_mode)
        except AttributeError:
            return None

    @property
    def mtime(self):
        """Return modification time of path."""
        try:
            return self.stat.st_mtime
        except AttributeError:
            return None

    def join(self, *args):
        """Join path elements."""
        return Path(os.path.join(self, *args))

    def splitpath(self):
        """Return dirname and basename together."""
        return (self.dirname, self.basename)

    def parents(self):
        """Iterate over the parents of the path.

        Generator that yields (dirname, basename) for each directory
        above the path.
        """
        (dirname, basename) = self.splitpath()
        while dirname is not None:
            yield (dirname, basename)

            basename = os.path.join(dirname.basename, basename)
            dirname = dirname.dirname


class Path(PathBase, str):
    """Path with cached information.

    This object represents a path on the filesystem.  The class
    is derived from the built-in str type to allow it to be used
    naturally.

    Additional properties are available which hold cached information
    about the file, to reduce stat calls and improve performance.  They
    are properties rather than functions to indicate their cached status.
    """


class CanonPath(Path):
    """Canonical path with cached information.

    This object is identical to Path except that it performs no
    canonicalisation of the path given to it, assuming (and requiring) that
    you have already done so.
    """

    def __new__(cls, path=".", *args, **kwds):
        if path.__class__ == cls:
            # Identical class means we behave like a singleton
            return path
        else:
            return str.__new__(cls, path)


def ignored_part(path):
    """Return whether the path contains an ignored part."""
    path_parts = parts(path)
    for part in path_parts:
        # Rely on anything calling us filtering out ,, and ++ directories
        # because we use those ourselves quite a lot.  walk() for example
        # never descends into them if caught by the block further below.
        if part in Directories.IGNORE:
            return True
    else:
        # path may end in /, we don't want to test the bit before that
        # against Filenames.IGNORE but _do_ want to test it against
        # ,, and ++ so this is why the following code is different.
        if os.path.basename(path) in Filenames.IGNORE:
            return True
        elif path_parts[-1].startswith(",,"):
            return True
        elif path_parts[-1].startswith("++"):
            return True
        else:
            return False


def format_part(path):
    """Return whether the path contains a part that suggests a format."""
    for part in reversed(parts(path)):
        if part in Directories.FORMAT:
            return Directories.FORMAT[part]
    else:
        return None


def match_ext(name, extensions):
    """Match a filename against the list of extensions.

    If a match is found it returns a tuple of the name with the matching
    extension stripped, the matching extension and information about the
    extension appended.

    If no match is found it returns None.
    """
    for ext in sorted(extensions, key=len, reverse=True):
        if name.endswith(ext):
            return (name[: -len(ext)], ext) + extensions[ext]
    else:
        return None


def split_path(path):
    """Split path into pieces and extract information from it.

    Returns a tuple of (dirname, name, ext, format, compress).
    """
    dirname = os.path.dirname(path)
    name = os.path.basename(path)
    path_ext = ""
    path_format = None
    path_compress = None

    # Check for version-control leaking
    if ignored_part(dirname):
        return (dirname, name, path_ext, path_format, path_compress)

    # Check combined extensions
    info = match_ext(name, Extensions.BOTH)
    if info is not None:
        (name, ext, path_format, path_compress) = info
        path_ext = ext + path_ext

    # Check compression extensions
    if path_compress is None:
        info = match_ext(name, Extensions.COMPRESS)
        if info is not None:
            (name, ext, path_compress) = info
            path_ext = ext + path_ext

    # Check format extensions
    if path_format is None:
        info = match_ext(name, Extensions.FORMAT)
        if info is not None:
            (name, ext, path_format) = info
            path_ext = ext + path_ext

    # Check format directory names
    if path_format is None:
        path_format = format_part(dirname)

    return (dirname, name, path_ext, path_format, path_compress)


def name(path):
    """Return the name prefix extracted from the path."""
    return split_path(path)[1]


def split_version(name):
    """Extract the version from the filename.

    Returns a tuple of (name, version), where version is None if not found.
    """
    match = version_ext.search(name)
    if match is not None:
        split = match.start()
        return (name[:split], name[split + 1 :])
    else:
        return (name, None)


def as_dir(path):
    """Return the path with a trailing slash."""
    if path.endswith("/"):
        return path
    elif len(path):
        return path + "/"
    else:
        return ""


def as_file(path):
    """Return the path without a trailing slash."""
    while path[-1:] == "/":
        path = path[:-1]
    return path


def relative(path):
    """Return the path without a leading slash."""
    while path[:1] == "/":
        path = path[1:]
    return path


def parts(path):
    """Return the parts of the path."""
    return relative(as_file(path)).split("/")


def under(root, path):
    """Return whether a path is underneath a given root."""
    if as_dir(root) == as_dir(path):
        return True
    elif path.startswith(as_dir(root)):
        return True
    else:
        return False


def subdir(root, path):
    """Return path relative to root."""
    if not under(root, path):
        raise ValueError("path must start with root")

    return relative(path[len(root) :])


def canon(path):
    """Canonicalise the path.

    The return path is normalised, absolute and has any symlinks within
    it expanded.
    """
    (path, base) = os.path.split(os.path.abspath(path))
    while path != "/":
        if os.path.islink(path):
            path = os.path.normpath(
                os.path.join(os.path.dirname(path), os.readlink(path))
            )
        else:
            base = os.path.join(os.path.basename(path), base)
            path = os.path.dirname(path)

    path = os.path.join(path, base)
    if os.path.isdir(path) and not os.path.islink(path):
        return as_dir(path)
    else:
        return path
