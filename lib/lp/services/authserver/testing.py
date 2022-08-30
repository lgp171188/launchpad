# Copyright 2021 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""In-process authserver fixture."""

__all__ = [
    "InProcessAuthServerFixture",
]

from textwrap import dedent

import fixtures
from twisted.internet import reactor
from twisted.web import server, xmlrpc
from zope.component import getUtility
from zope.publisher.xmlrpc import TestRequest

from lp.services.authserver.xmlrpc import AuthServerAPIView
from lp.services.config import config
from lp.xmlrpc.interfaces import IPrivateApplication


class InProcessAuthServer(xmlrpc.XMLRPC):
    def __init__(self, *args, **kwargs):
        xmlrpc.XMLRPC.__init__(self, *args, **kwargs)
        private_root = getUtility(IPrivateApplication)
        self.authserver = AuthServerAPIView(
            private_root.authserver, TestRequest()
        )

    def __getattr__(self, name):
        if name.startswith("xmlrpc_"):
            return getattr(self.authserver, name[len("xmlrpc_") :])
        else:
            raise AttributeError("%r has no attribute '%s'" % (self, name))


class InProcessAuthServerFixture(fixtures.Fixture, xmlrpc.XMLRPC):
    """A fixture that runs an in-process authserver."""

    def _setUp(self):
        listener = reactor.listenTCP(0, server.Site(InProcessAuthServer()))
        self.addCleanup(listener.stopListening)
        config.push(
            "in-process-auth-server-fixture",
            dedent(
                """
            [builddmaster]
            authentication_endpoint: http://localhost:{port}/

            [codehosting]
            authentication_endpoint: http://localhost:{port}/

            [librarian]
            authentication_endpoint: http://localhost:{port}/
            """
            ).format(port=listener.getHost().port),
        )
        self.addCleanup(config.pop, "in-process-auth-server-fixture")
