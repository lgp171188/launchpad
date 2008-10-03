# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Browser file for LibraryFileAlias."""

__metaclass__ = type

__all__ = [
    'LibraryFileAliasView',
    'LibraryFileAliasMD5View',
    'FileNavigationMixin',
    'StreamOrRedirectLibraryFileAliasView',
    ]

import os
import tempfile
import urllib2

from zope.interface import implements
from zope.publisher.interfaces import NotFound
from zope.publisher.interfaces.browser import IBrowserPublisher
from zope.security.interfaces import Unauthorized

from canonical.launchpad.interfaces import ILibraryFileAlias
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.publisher import (
    LaunchpadView, RedirectionView, stepthrough)
from canonical.librarian.utils import filechunks


class LibraryFileAliasView(LaunchpadView):
    """View to handle redirection for downloading files by URL.

    Rather than reference downloadable files via the obscure Librarian
    URL, downloadable files can be referenced via the Product Release URL, e.g.
    http://launchpad.net/firefox/1.0./1.0.0/+download/firefox-1.0.0.tgz.
    """

    __used_for__ = ILibraryFileAlias

    def initialize(self):
        """Redirect the request to the URL of the file in the Librarian."""
        # Redirect based on the scheme of the request, as set by Apache in the
        # 'X-SCHEME' environment variable, which is mapped to 'HTTP_X_SCHEME.
        # Note that only some requests for librarian files are allowed to come
        # in via http as most are forced to https via Apache redirection.
        request_scheme = self.request.get('HTTP_X_SCHEME')
        if request_scheme == 'http':
            redirect_to = self.context.http_url
        else:
            redirect_to = self.context.getURL()
        self.request.response.redirect(redirect_to)


class LibraryFileAliasMD5View(LaunchpadView):
    """View to show the MD5 digest for a librarian file."""

    __used_for__ = ILibraryFileAlias

    def render(self):
        """Return the plain text MD5 signature"""
        self.request.response.setHeader('Content-type', 'text/plain')
        return self.context.content.md5


class StreamOrRedirectLibraryFileAliasView(LaunchpadView):
    """Stream or redirects to `ILibraryFileAlias`.

    It streams the contents of restricted library files or redirects
    to public ones.
    """
    implements(IBrowserPublisher)

    __used_for__ = ILibraryFileAlias

    def __call__(self):
        """Streams the contents of the context `ILibraryFileAlias`.

        The file content is downloaded in chunks directly to a
        `tempfile.TemporaryFile` avoiding using large amount of memory.

        The temporary file is returned to the zope publishing machinery as
        documented in lib/zope/publisher/httpresults.txt, after adjusting
        the response 'Content-Type' appropriately.

        This method explicit ignores the local 'http_proxy' settings.
        """
        # Reset system proxy setting if it exists. The urllib2 default
        # opener is cached that's why it has to be re-installed after
        # the shell environment changes. Download the library file
        # content into a local temporary file. Finally, restore original
        # proxy-settings and refresh the urllib2 opener.
        original_proxy = os.getenv('http_proxy')
        try:
            if original_proxy is not None:
                del os.environ['http_proxy']
                urllib2.install_opener(urllib2.build_opener())
            tmp_file = tempfile.TemporaryFile()
            self.context.open()
            for chunk in filechunks(self.context):
                tmp_file.write(chunk)
            self.context.close()
        finally:
            if original_proxy is not None:
                os.environ['http_proxy'] = original_proxy
                urllib2.install_opener(urllib2.build_opener())

        self.request.response.setHeader(
            'Content-Type', self.context.mimetype)

        return tmp_file

    def browserDefault(self, request):
        """Decides whether to redirect or stream the file content.

        Only restricted file contents are streamed, finishing the traversal
        chain with this view. If the context file is public return the
        appropriate `RedirectionView` for its HTTP url.
        """
        if self.context.restricted:
            return self, ()

        return RedirectionView(self.context.http_url, self.request), ()

    def publishTraverse(self, request, name):
        """See `IBrowserPublisher`."""
        raise NotFound(name, self.context)


class FileNavigationMixin:
    """Navigate to `LibraryFileAlias` hosted in a context.

    The navigation goes through +files/<filename> where file reference is
    provided by context `getFileByName(filename)`.

    The requested file is proxied via `StreamOrRedirectLibraryFileAliasView`,
    making it possible to serve both, public and restricted, files.

    This navigation approach only supports domains with unique filenames,
    which is the case of IArchive and IBuild. It will probably have to be
    extended in order to allow traversing to multiple files potentially
    with the same filename (product files or bug attachments).
    """
    @stepthrough('+files')
    def traverse_files(self, filename):
        """Traverse on filename in the archive domain."""
        if not check_permission('launchpad.View', self.context):
            raise Unauthorized()
        library_file  = self.context.getFileByName(filename)
        return StreamOrRedirectLibraryFileAliasView(
            library_file, self.request)
