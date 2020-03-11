# Copyright 2015-2019 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Fixtures for dealing with the build time 'snap' HTTP proxy."""

from __future__ import absolute_import, print_function, unicode_literals

__metaclass__ = type

from datetime import datetime
import json
from textwrap import dedent
import uuid

import fixtures
from six.moves.urllib_parse import urlsplit
from testtools.matchers import (
    Equals,
    HasLength,
    MatchesStructure,
    )
from twisted.internet import (
    defer,
    endpoints,
    reactor,
    )
from twisted.python.compat import nativeString
from twisted.web import (
    resource,
    server,
    )

from lp.services.config import config


class ProxyAuthAPITokensResource(resource.Resource):
    """A test tokens resource for the proxy authentication API."""

    isLeaf = True

    def __init__(self):
        resource.Resource.__init__(self)
        self.requests = []

    def render_POST(self, request):
        content = request.content.read()
        self.requests.append({
            "method": request.method,
            "uri": request.uri,
            "headers": dict(request.requestHeaders.getAllRawHeaders()),
            "content": content,
            })
        username = json.loads(content)["username"]
        return json.dumps({
            "username": username,
            "secret": uuid.uuid4().hex,
            "timestamp": datetime.utcnow().isoformat(),
            })


class InProcessProxyAuthAPIFixture(fixtures.Fixture):
    """A fixture that pretends to be the proxy authentication API.

    Users of this fixture must call the `start` method, which returns a
    `Deferred`, and arrange for that to get back to the reactor.  This is
    necessary because the basic fixture API does not allow `setUp` to return
    anything.  For example:

        class TestSomething(TestCase):

            run_tests_with = AsynchronousDeferredRunTest.make_factory(
                timeout=10)

            @defer.inlineCallbacks
            def setUp(self):
                super(TestSomething, self).setUp()
                yield self.useFixture(InProcessProxyAuthAPIFixture()).start()
    """

    @defer.inlineCallbacks
    def start(self):
        root = resource.Resource()
        self.tokens = ProxyAuthAPITokensResource()
        root.putChild("tokens", self.tokens)
        endpoint = endpoints.serverFromString(reactor, nativeString("tcp:0"))
        site = server.Site(self.tokens)
        self.addCleanup(site.stopFactory)
        port = yield endpoint.listen(site)
        self.addCleanup(port.stopListening)
        config.push("in-process-proxy-auth-api-fixture", dedent("""
            [snappy]
            builder_proxy_auth_api_admin_secret: admin-secret
            builder_proxy_auth_api_endpoint: http://%s:%s/tokens
            """) %
            (port.getHost().host, port.getHost().port))
        self.addCleanup(config.pop, "in-process-proxy-auth-api-fixture")


class ProxyURLMatcher(MatchesStructure):
    """Check that a string is a valid url for a snap build proxy."""

    def __init__(self, job, now):
        super(ProxyURLMatcher, self).__init__(
            scheme=Equals("http"),
            username=Equals("{}-{}".format(
                job.build.build_cookie, int(now))),
            password=HasLength(32),
            hostname=Equals(config.snappy.builder_proxy_host),
            port=Equals(config.snappy.builder_proxy_port),
            path=Equals(""))

    def match(self, matchee):
        super(ProxyURLMatcher, self).match(urlsplit(matchee))


class RevocationEndpointMatcher(Equals):
    """Check that a string is a valid endpoint for proxy token revocation."""

    def __init__(self, job, now):
        super(RevocationEndpointMatcher, self).__init__(
            "{}/{}-{}".format(
                config.snappy.builder_proxy_auth_api_endpoint,
                job.build.build_cookie, int(now)))