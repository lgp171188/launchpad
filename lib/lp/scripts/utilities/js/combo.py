# Copyright 2011-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

import os
import urlparse

from six.moves.urllib.parse import parse_qsl

from lp.scripts.utilities.js.jsbuild import (
    CSSComboFile,
    JSComboFile,
    )
from lp.services.encoding import wsgi_native_string


def parse_url(url):
    """Parse a combo URL.

    Returns the list of arguments in the original order.
    """
    scheme, loc, path, query, frag = urlparse.urlsplit(url)
    return parse_qs(query)


def parse_qs(query):
    """Parse a query string.

    Returns the list of arguments in the original order.
    """
    params = parse_qsl(query, keep_blank_values=True)
    return tuple([param for param, value in params])


def combine_files(fnames, root, resource_prefix=b"",
                  minify_css=True, rewrite_urls=True):
    """Combine many files into one.

    Returns an iterator with the combined content of all the
    files. The relative path to root will be included as a comment
    between each file.
    """

    combo_by_kind = {
        ".css": CSSComboFile([], os.path.join(root, "combo.css"),
                             resource_prefix, minify_css, rewrite_urls),
        ".js": JSComboFile([], os.path.join(root, "combo.js")),
    }

    for fname in fnames:
        combo = combo_by_kind.get(os.path.splitext(fname)[-1])
        if combo is None:
            continue
        full = os.path.abspath(os.path.join(root, fname))
        yield combo.get_file_header(full)
        if not full.startswith(root) or not os.path.exists(full):
            yield combo.get_comment("[missing]")
        else:
            with open(full, "rb") as f:
                content = f.read()
            yield combo.filter_file_content(content, full)


def combo_app(root, resource_prefix=b"", minify_css=True, rewrite_urls=True):
    """A simple YUI Combo Service WSGI app.

    Serves any files under C{root}, setting an appropriate
    C{Content-Type} header.
    """
    root = os.path.abspath(root)

    def app(environ, start_response, root=root):
        fnames = parse_qs(environ["QUERY_STRING"])
        content_type = "text/plain"
        if fnames:
            if fnames[0].endswith(".js"):
                content_type = "text/javascript"
            elif fnames[0].endswith(".css"):
                content_type = "text/css"
            status = "200 OK"
            body = combine_files(
                fnames, root, resource_prefix, minify_css, rewrite_urls)
        else:
            status = "404 Not Found"
            body = (b"Not Found",)
        response_headers = [("Content-Type", wsgi_native_string(content_type))]
        start_response(wsgi_native_string(status), response_headers)
        return body

    return app
