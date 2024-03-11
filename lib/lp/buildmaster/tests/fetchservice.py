# Copyright 2015-2024 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Fixtures for dealing with the build time Fetch Service http proxy."""

import json
import uuid
from textwrap import dedent
from urllib.parse import urlsplit

import fixtures
from testtools.matchers import Equals, HasLength, MatchesStructure
from twisted.internet import defer, endpoints, reactor
from twisted.python.compat import nativeString
from twisted.web import resource, server

from lp.services.config import config


class FetchServiceAuthAPITokensResource(resource.Resource):
    """A test session resource for the fetch service authentication API."""

    isLeaf = True

    def __init__(self):
        resource.Resource.__init__(self)
        self.requests = []

    def render_POST(self, request):
        content = json.loads(request.content.read().decode("UTF-8"))
        self.requests.append(
            {
                "method": request.method,
                "uri": request.uri,
                "headers": dict(request.requestHeaders.getAllRawHeaders()),
                "json": content,
            }
        )
        return json.dumps(
            {
                "id": "1",
                "token": uuid.uuid4().hex,
            }
        ).encode("UTF-8")


class InProcessFetchServiceAuthAPIFixture(fixtures.Fixture):
    """A fixture that mocks the Fetch Service authentication API.

    Users of this fixture must call the `start` method, which returns a
    `Deferred`, and arrange for that to get back to the reactor.  This is
    necessary because the basic fixture API does not allow `setUp` to return
    anything.  For example:

        class TestSomething(TestCase):

            run_tests_with = AsynchronousDeferredRunTest.make_factory(
                timeout=30)

            @defer.inlineCallbacks
            def setUp(self):
                super().setUp()
                yield self.useFixture(
                    InProcessFetchServiceAuthAPIFixture()
                ).start()
    """

    @defer.inlineCallbacks
    def start(self):
        root = resource.Resource()
        self.sessions = FetchServiceAuthAPITokensResource()
        root.putChild(b"sessions", self.sessions)
        endpoint = endpoints.serverFromString(reactor, nativeString("tcp:0"))
        site = server.Site(self.sessions)
        self.addCleanup(site.stopFactory)
        port = yield endpoint.listen(site)
        self.addCleanup(port.stopListening)
        config.push(
            "in-process-fetch-service-api-fixture",
            dedent(
                """
                [builddmaster]
                fetch_service_control_admin_secret: admin-secret
                fetch_service_control_admin_username: admin-launchpad.test
                fetch_service_control_endpoint: http://{host}:{port}/session
                fetch_service_host: {host}
                fetch_service_port: {port}
                """
            ).format(host=port.getHost().host, port=port.getHost().port),
        )
        self.addCleanup(config.pop, "in-process-fetch-service-api-fixture")


# This class is not used yet but it could be
# useful for future tests
class FetchServiceURLMatcher(MatchesStructure):
    """Check that a string is a valid url for fetch service."""

    def __init__(self):
        super().__init__(
            scheme=Equals("http"),
            id=Equals(1),
            token=HasLength(32),
            hostname=Equals(config.builddmaster.fetch_service_host),
            port=Equals(config.builddmaster.fetch_service_port),
            path=Equals(""),
        )

    def match(self, matchee):
        super().match(urlsplit(matchee))


class RevocationEndpointMatcher(Equals):
    """Check that a string is a valid endpoint for fetch
    service session revocation.
    """

    def __init__(self, session_id):
        super().__init__(
            "{endpoint}/session/{session_id}".format(
                endpoint=config.builddmaster.fetch_service_control_endpoint,
                session_id=session_id,
            )
        )
