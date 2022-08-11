Launchpad helper to write tar files
===================================

LaunchpadWriteTarFile is a helper class to make .tar.gz generation
easy.

    >>> import io
    >>> import tarfile
    >>> from lp.services.tarfile_helpers import LaunchpadWriteTarFile

First, we are going to define a function we are going to use to validate the
output we will get.

    >>> def examine_tarfile(tar):
    ...     members = tar.getmembers()
    ...     # Calculate the length of the longest name.
    ...     max_length = max(len(member.name) for member in members)
    ...     # Use this length to generate an appropriate format string.
    ...     format = '%%-%ds | %%s' % max_length
    ...
    ...     for member in members:
    ...         if member.type == tarfile.REGTYPE:
    ...             file = tar.extractfile(member)
    ...
    ...             if file is not None:
    ...                 print(format % (
    ...                     member.name, six.ensure_text(file.read())))
    ...             else:
    ...                 print(format % (member.name, ''))
    ...         elif member.type == tarfile.SYMTYPE:
    ...             print(format % (
    ...                 member.name, "<link to %s>" % member.linkname))
    ...         elif member.type == tarfile.DIRTYPE:
    ...             print(format % (member.name, "<directory>"))

    # Start off by creating a blank archive.
    # We'll need a filehandle to store it in.
    >>> buffer = io.BytesIO()
    >>> archive = LaunchpadWriteTarFile(buffer)

We can add files individually. First argument is the file name, second
argument is the file content.

    >>> archive.add_file('foo', b'1')

Or add many files simultaneously using a dictionary that use the key as
the file name and the value the file content.

    >>> archive.add_files({'bar': b'2', 'baz': b'3'})

We can add symbolic links.

    >>> archive.add_symlink('link', 'foo')

We can add directories.

    >>> archive.add_directory('dir')

Once we are done adding files, the archive needs to be closed.

    >>> archive.close()

And now we can inspect the produced file.

    >>> _ = buffer.seek(0)
    >>> archive = tarfile.open('', 'r', buffer)
    >>> examine_tarfile(archive)
    foo  | 1
    bar  | 2
    baz  | 3
    link | <link to foo>
    dir  | <directory>

There are also some convenience methods for getting directly from several
files, represented with a dictionary, which have the file name as key and
file content as the value, to a stream...

If we have several files to import...

    >>> files = {
    ...     'eins': b'zwei',
    ...     'drei': b'vier',
    ... }

...then we can easily turn it into a tarfile file object with
files_to_tarfile...

    >>> archive = LaunchpadWriteTarFile.files_to_tarfile(files)
    >>> examine_tarfile(archive)
    drei | vier
    eins | zwei

...or a tarfile stream with files_to_stream...

    >>> stream = LaunchpadWriteTarFile.files_to_stream(files)
    >>> archive = tarfile.open('', 'r', stream)
    >>> examine_tarfile(archive)
    drei | vier
    eins | zwei

...or a byte string.

    >>> data = LaunchpadWriteTarFile.files_to_bytes(files)
    >>> archive = tarfile.open('', 'r', io.BytesIO(data))
    >>> examine_tarfile(archive)
    drei | vier
    eins | zwei

If a filename contains slashes, containing directories are automatically
created.

    >>> archive = LaunchpadWriteTarFile.files_to_tarfile({
    ...     'uno/dos/tres/cuatro': b'blah',
    ...     })
    >>> examine_tarfile(archive)
    uno                 | <directory>
    uno/dos             | <directory>
    uno/dos/tres        | <directory>
    uno/dos/tres/cuatro | blah
