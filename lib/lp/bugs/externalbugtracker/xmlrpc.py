# Copyright 2009-2013 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""An XMLRPC transport which uses urllib2."""

__metaclass__ = type
__all__ = [
    'UrlLib2Transport',
    'XMLRPCRedirectHandler',
    ]


from cookielib import Cookie
from cStringIO import StringIO
from urllib2 import (
    build_opener,
    HTTPCookieProcessor,
    HTTPError,
    HTTPRedirectHandler,
    Request,
    )
from urlparse import (
    urlparse,
    urlunparse,
    )
from xmlrpclib import (
    ProtocolError,
    Transport,
    )

from lp.services.config import config
from lp.services.utils import traceback_info


class XMLRPCRedirectHandler(HTTPRedirectHandler):
    """A handler for HTTP redirections of XML-RPC requests."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """Return a Request or None in response to a redirect.

        See `urllib2.HTTPRedirectHandler`.

        If the original request is a POST request, the request's payload
        will be preserved in the redirect and the returned request will
        also be a POST request.
        """
        # If we can't handle this redirect,
        # HTTPRedirectHandler.redirect_request() will raise an
        # HTTPError. We call the superclass here in the old fashion
        # since HTTPRedirectHandler isn't a new-style class.
        new_request = HTTPRedirectHandler.redirect_request(
            self, req, fp, code, msg, headers, newurl)

        # If the old request is a POST request, the payload will be
        # preserved. Note that we don't need to test for the POST-ness
        # of the old request; if its data attribute - its payload - is
        # not None it's a POST request, if it's None it's a GET request.
        # We can therefore just copy the data from the old request to
        # the new without worrying about breaking things.
        new_request.data = req.data
        new_request.timeout = req.timeout
        return new_request


class UrlLib2Transport(Transport):
    """An XMLRPC transport which uses urllib2.

    This XMLRPC transport uses the Python urllib2 module to make the request,
    with proxying handled by that module's semantics (though underdocumented).
    It also handles cookies correctly, and in addition allows specifying the
    cookie explicitly by setting `self.auth_cookie`.

    Note: this transport isn't fit for general XMLRPC use. It is just good
    enough for some of our external bug tracker implementations.

    :param endpoint: The URL of the XMLRPC server.
    """

    verbose = False

    def __init__(self, endpoint, cookie_jar=None):
        Transport.__init__(self, use_datetime=True)
        self.scheme, self.host = urlparse(endpoint)[:2]
        assert self.scheme in ('http', 'https'), (
            "Unsupported URL scheme: %s" % self.scheme)
        self.cookie_processor = HTTPCookieProcessor(cookie_jar)
        self.redirect_handler = XMLRPCRedirectHandler()
        self.opener = build_opener(
            self.cookie_processor, self.redirect_handler)
        self.timeout = config.checkwatches.default_socket_timeout

    def setCookie(self, cookie_str):
        """Set a cookie for the transport to use in future connections."""
        name, value = cookie_str.split('=')
        cookie = Cookie(
            version=0, name=name, value=value,
            port=None, port_specified=False,
            domain=self.host, domain_specified=True,
            domain_initial_dot=None,
            path='', path_specified=False,
            secure=False, expires=False, discard=None,
            comment=None, comment_url=None, rest=None)
        self.cookie_processor.cookiejar.set_cookie(cookie)

    def request(self, host, handler, request_body, verbose=0):
        """Make an XMLRPC request.

        Uses the configured proxy server to make the connection.
        """
        url = urlunparse((self.scheme, host, handler, '', '', ''))
        # httplib can raise a UnicodeDecodeError when using a Unicode
        # URL, a non-ASCII body and a proxy. http://bugs.python.org/issue12398
        if isinstance(url, unicode):
            url = url.encode('utf-8')
        headers = {'Content-type': 'text/xml'}
        request = Request(url, request_body, headers)
        try:
            response = self.opener.open(request, timeout=self.timeout).read()
        except HTTPError as he:
            raise ProtocolError(
                request.get_full_url(), he.code, he.msg, he.hdrs)
        else:
            traceback_info(response)
            return self.parse_response(StringIO(response))
