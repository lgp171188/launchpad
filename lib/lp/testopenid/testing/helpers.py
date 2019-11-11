# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Helpers for TestOpenID page tests."""

__metaclass__ = type
__all__ = [
    'complete_from_browser',
    'EchoView',
    'make_identifier_select_endpoint',
    'ZopeFetcher',
    ]

from StringIO import StringIO

from openid import fetchers
from openid.consumer.discover import (
    OPENID_IDP_2_0_TYPE,
    OpenIDServiceEndpoint,
    )
from six.moves.urllib.error import HTTPError
from zope.testbrowser.wsgi import Browser

from lp.services.webapp import LaunchpadView
from lp.testing.layers import wsgi_application
from lp.testopenid.interfaces.server import get_server_url


class EchoView(LaunchpadView):
    """A view which just echoes its form arguments in the response."""

    def render(self):
        out = StringIO()
        print >> out, 'Request method: %s' % self.request.method
        keys = sorted(self.request.form.keys())
        for key in keys:
            print >> out, '%s:%s' % (key, self.request.form[key])
        return out.getvalue()


class ZopeFetcher(fetchers.HTTPFetcher):
    """An `HTTPFetcher` based on zope.testbrowser."""

    def fetch(self, url, body=None, headers=None):
        browser = Browser(wsgi_app=wsgi_application)
        if headers is not None:
            for key, value in headers.items():
                browser.addHeader(key, value)
        browser.addHeader('X-Zope-Handle-Errors', 'True')
        try:
            browser.open(url, data=body)
        except HTTPError as e:
            status = e.code
        else:
            status = 200
        return fetchers.HTTPResponse(
            browser.url, status, browser.headers, browser.contents)


def complete_from_browser(consumer, browser):
    """Complete OpenID request based on output of +echo.

    :param consumer: an OpenID `Consumer` instance.
    :param browser: a Zope testbrowser `Browser` instance.

    This function parses the body of the +echo view into a set of query
    arguments representing the OpenID response.
    """
    assert browser.contents.startswith('Request method'), (
        "Browser contents does not look like it came from +echo")
    # Skip the first line.
    query = dict(line.split(':', 1)
                 for line in browser.contents.splitlines()[1:])

    response = consumer.complete(query, browser.url)
    return response


def make_identifier_select_endpoint():
    """Create an endpoint for use in OpenID identifier select mode."""
    endpoint = OpenIDServiceEndpoint()
    endpoint.server_url = get_server_url()
    endpoint.type_uris = [OPENID_IDP_2_0_TYPE]
    return endpoint
